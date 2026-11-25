import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..files import is_memory_document, now, private_dirs, safe_path
from ..redactor import SecretRedactor
from .chunker import MarkdownChunker

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
 id INTEGER PRIMARY KEY, rel_path TEXT UNIQUE NOT NULL, scope TEXT NOT NULL, kind TEXT NOT NULL,
 title TEXT NOT NULL, origin TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', superseded_by TEXT,
 verified_commit TEXT, tracks_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 mtime_ns INTEGER NOT NULL, sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunks (
 id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 section_heading TEXT NOT NULL, section_index INTEGER NOT NULL, content TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_document ON chunks(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(content,section_heading,
 content='chunks',content_rowid='id',tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS chunks_insert AFTER INSERT ON chunks BEGIN
 INSERT INTO chunks_fts(rowid,content,section_heading) VALUES(new.id,new.content,new.section_heading); END;
CREATE TRIGGER IF NOT EXISTS chunks_delete AFTER DELETE ON chunks BEGIN
 INSERT INTO chunks_fts(chunks_fts,rowid,content,section_heading) VALUES('delete',old.id,old.content,old.section_heading); END;
CREATE TABLE IF NOT EXISTS transcript_cursors (
 harness TEXT NOT NULL,session_id TEXT NOT NULL,transcript_path TEXT NOT NULL,byte_offset INTEGER NOT NULL DEFAULT 0,
 turn_count INTEGER NOT NULL DEFAULT 0,last_seen_at TEXT NOT NULL,PRIMARY KEY(harness,session_id));
CREATE TABLE IF NOT EXISTS sync_state(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL);
"""

HIT_COLUMNS = "c.id AS chunk_id,c.section_heading,c.content,d.*"


class FtsStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.database = safe_path(root, ".state/index.sqlite")
        private_dirs(self.database.parent)
        os.close(os.open(self.database, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600))
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.database, timeout=5)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("PRAGMA foreign_keys=ON")
            yield db

    def index_file(self, relative: str) -> bool:
        path = safe_path(self.root, relative)
        rel = Path(relative)
        if not is_memory_document(rel):
            raise ValueError("Documento fuera de la wiki")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            stamp = path.stat()
            old = db.execute("SELECT * FROM documents WHERE rel_path=?", (relative,)).fetchone()
            if old and old["mtime_ns"] == stamp.st_mtime_ns:
                return False
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if old and old["sha256"] == digest:
                db.execute("UPDATE documents SET mtime_ns=? WHERE id=?", (stamp.st_mtime_ns, old["id"]))
                return False
            text = SecretRedactor.redact(raw.decode("utf-8"))
            meta, body = {}, text
            if text.startswith("---\n"):
                from ..markdown_store import split_frontmatter
                meta, body = split_frontmatter(raw.decode("utf-8"))
                body = SecretRedactor.redact(body)
                for key in ("title", "superseded_by", "verified_commit"):
                    if isinstance(meta.get(key), str):
                        meta[key] = SecretRedactor.redact(meta[key])
                if isinstance(meta.get("tracks"), list):
                    meta["tracks"] = [SecretRedactor.redact(str(t)) for t in meta["tracks"]]
            folder = str(rel.parent)
            kinds = {"wiki/hindsight": "hindsight_page", "wiki/recuerdos": "hindsight_memory", "wiki/notas": "nota",
                     "wiki/iniciativas": "iniciativa", "wiki/correcciones": "correccion", "wiki/paginas": "pagina"}
            kind = kinds.get(folder, "raw")
            if relative.startswith("raw/sources/sessions/"):
                kind = "session"
            if relative == "raw/sources/git/commits.md":
                kind = "git"
            migrated = relative.startswith(("wiki/hindsight/", "wiki/recuerdos/", "raw/sources/hindsight/"))
            date = datetime.fromtimestamp(stamp.st_mtime, UTC).isoformat()
            if old:
                db.execute("DELETE FROM documents WHERE id=?", (old["id"],))
            doc = db.execute("""INSERT INTO documents(rel_path,scope,kind,title,origin,status,superseded_by,
                verified_commit,tracks_json,created_at,updated_at,mtime_ns,sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (relative, "global" if self.root.name == "global" else "proyecto", kind, str(meta.get("title", path.stem)),
                 "hindsight_migrated" if migrated else "wiki_v2", meta.get("status", "active"), meta.get("superseded_by"),
                 meta.get("verified_commit"), json.dumps(meta.get("tracks", [])), str(meta.get("created_at", date)),
                 str(meta.get("updated_at", date)), stamp.st_mtime_ns, digest))
            db.executemany("INSERT INTO chunks(doc_id,section_heading,section_index,content) VALUES(?,?,?,?)",
                           ((doc.lastrowid, *chunk) for chunk in MarkdownChunker().chunk(body)))
        return True

    def search_fts(self, query: str, limit: int = 30, include_obsolete: bool = False) -> list[dict[str, Any]]:
        terms = re.findall(r"\w+", query)
        if not terms:
            return []
        expr = " OR ".join(f'"{t}"' for t in terms)
        with self.connection() as db:
            rows = db.execute(f"""SELECT {HIT_COLUMNS} FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid
                JOIN documents d ON d.id=c.doc_id WHERE chunks_fts MATCH ? AND (? OR d.status!='superseded')
                ORDER BY rank LIMIT ?""", (expr, include_obsolete, limit))
            return list(map(dict, rows))

    def list_recent(self, limit: int = 15) -> list[dict[str, Any]]:
        with self.connection() as db:
            return list(map(dict, db.execute("SELECT * FROM documents ORDER BY updated_at DESC LIMIT ?", (limit,))))

    def cursor(self, harness: str, session: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM transcript_cursors WHERE harness=? AND session_id=?", (harness, session)).fetchone()
            return dict(row) if row else {"byte_offset": 0, "turn_count": 0}

    def set_cursor(self, harness: str, session: str, path: str, offset: int, count: int) -> None:
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO transcript_cursors VALUES(?,?,?,?,?,?)",
                       (harness, session, path, offset, count, now()))

    def state(self, key: str) -> str | None:
        with self.connection() as db:
            row = db.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
            return row[0] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO sync_state VALUES(?,?,?)", (key, value, now()))
