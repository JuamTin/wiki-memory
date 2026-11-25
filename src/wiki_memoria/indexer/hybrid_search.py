import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from .embedder import LocalEmbedder
from .fts_store import FtsStore, HIT_COLUMNS


def load_vector_extension(db: sqlite3.Connection) -> None:
    import sqlite_vec
    db.enable_load_extension(True)
    try:
        sqlite_vec.load(db)
    finally:
        db.enable_load_extension(False)


class HybridSearcher:
    def __init__(self, store: FtsStore, embedder: LocalEmbedder) -> None:
        self.store = store
        self.embedder = embedder

    def index_missing(self, batch_size: int = 64) -> int:
        if not self.embedder.is_ready:
            return 0
        indexed = 0
        with self.store.connection() as db:
            load_vector_extension(db)
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(chunk_id INTEGER PRIMARY KEY,embedding float[384])")
            db.execute("DELETE FROM chunks_vec WHERE chunk_id NOT IN (SELECT id FROM chunks)")
            db.commit()
            while rows := db.execute("""SELECT id,content FROM chunks WHERE id NOT IN
                    (SELECT chunk_id FROM chunks_vec) ORDER BY id LIMIT ?""", (batch_size,)).fetchall():
                vectors = self.embedder.embed_passages([row["content"] for row in rows])
                db.execute("BEGIN IMMEDIATE")
                for row, vec in zip(rows, vectors, strict=True):
                    present = db.execute("""SELECT id FROM chunks WHERE id=? AND NOT EXISTS
                        (SELECT 1 FROM chunks_vec WHERE chunk_id=?)""", (row["id"], row["id"])).fetchone()
                    if present:
                        db.execute("INSERT INTO chunks_vec VALUES(?,?)", (row["id"], vec))
                        indexed += 1
                db.commit()
        return indexed

    def _nearest(self, query: str, limit: int, obsolete: bool) -> list[dict[str, Any]]:
        with self.store.connection() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='chunks_vec'").fetchone():
                return []
            load_vector_extension(db)
            rows = db.execute(f"""WITH near AS MATERIALIZED (SELECT chunk_id,distance FROM chunks_vec
                  WHERE embedding MATCH ? AND k=? ORDER BY distance)
                SELECT {HIT_COLUMNS} FROM near JOIN chunks c ON c.id=near.chunk_id
                JOIN documents d ON d.id=c.doc_id WHERE (? OR d.status!='superseded') ORDER BY near.distance""",
                (self.embedder.embed_query(query), limit, obsolete))
            return list(map(dict, rows))

    def search(self, query: str, limit: int = 10, *, incluir_obsoletos: bool = False,
               orden: str = "relevancia", tipos: list[str] | None = None,
               desde: str | None = None, hasta: str | None = None) -> list[dict[str, Any]]:
        depth = min(4096, max(64, limit * 8))
        ranks = [self.store.search_fts(query, depth, incluir_obsoletos)]
        if self.embedder.is_ready:
            ranks.append(self._nearest(query, depth, incluir_obsoletos))
        scores: dict[int, float] = {}
        hits = {}
        for ranking in ranks:
            for pos, hit in enumerate(ranking, start=1):
                key = hit["chunk_id"]
                scores[key] = scores.get(key, 0) + 1 / (60 + pos)
                hits[key] = hit
        kinds = {"correccion": 1.35, "pagina": 1.25, "iniciativa": 1.20, "nota": 1.15,
                 "hindsight_page": 1, "session": .90, "git": .85, "hindsight_memory": .80, "raw": .65}
        result = []
        reference = datetime.now(UTC)
        for key, hit in hits.items():
            date = hit["updated_at"]
            if (tipos and hit["kind"] not in tipos) or (desde and date < desde) or (hasta and date[:len(hasta)] > hasta):
                continue
            try:
                updated = datetime.fromisoformat(date)
                days = max(0, (reference - updated.replace(tzinfo=updated.tzinfo or UTC)).days)
            except ValueError:
                days = 0
            weight = kinds[hit["kind"]] * {"active": 1, "archived": .5, "superseded": .15}.get(hit["status"], 1)
            hit["score"] = scores[key] * weight * (.85 + .15 * math.exp(-days / 30))
            result.append(hit)
        return sorted(result, key=lambda x: x["updated_at"] if orden == "reciente" else x["score"], reverse=True)[:limit]


class VectorBackfill:
    """Index new hook captures after model loading without delaying interactive searches."""

    def __init__(self, embedder: LocalEmbedder) -> None:
        self.embedder = embedder
        self._lock = Lock()
        self._running: set[Path] = set()

    def schedule(self, store: FtsStore) -> None:
        if not self.embedder.is_ready:
            return
        with self._lock:
            if store.database in self._running:
                return
            with store.connection() as db:
                if db.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is None:
                    return
                load_vector_extension(db)
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='chunks_vec'").fetchone()
                if exists and db.execute("""SELECT 1 FROM chunks WHERE id NOT IN
                        (SELECT chunk_id FROM chunks_vec) LIMIT 1""").fetchone() is None:
                    return
            self._running.add(store.database)
            Thread(target=self._run, args=(store,), daemon=True, name="wiki-vector-index").start()

    def _run(self, store: FtsStore) -> None:
        try:
            HybridSearcher(store, self.embedder).index_missing()
        finally:
            with self._lock:
                self._running.remove(store.database)
