from time import perf_counter

from wiki_memoria.config import Embeddings
from wiki_memoria.indexer.embedder import LocalEmbedder
from wiki_memoria.indexer.fts_store import FtsStore
from wiki_memoria.indexer.hybrid_search import HybridSearcher


def build(tmp_path, enabled):
    store = FtsStore(tmp_path)
    for folder, name, text in [("correcciones", "cor", "regla vigente"), ("paginas", "new", "regla vigente"),
                               ("paginas", "old", "---\nstatus: superseded\n---\nregla vigente"),
                               ("notas", "sleep", "El gato duerme en el sofá de la casa."),
                               ("notas", "fruit", "Cosecha de frutas tropicales en el campo.")]:
        rel = f"wiki/{folder}/{name}.md"
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        store.index_file(rel)
    return HybridSearcher(store, LocalEmbedder(Embeddings(enabled=enabled)))


def test_degradation_and_order(tmp_path):
    s = build(tmp_path, False)
    assert s.index_missing() == 0
    assert [h["title"] for h in s.search("regla")] == ["cor", "new"]
    assert [h["title"] for h in s.search("regla", incluir_obsoletos=True)] == ["cor", "new", "old"]


def test_real_cross_language(tmp_path):
    s = build(tmp_path, True)
    s.embedder.wait()
    assert s.index_missing() == 5
    assert s.index_missing() == 0
    query = "The cat is sleeping on the couch"
    assert not s.store.search_fts(query)
    s.search(query)
    start = perf_counter()
    assert s.search(query, tipos=["nota"])[0]["title"] == "sleep"
    assert perf_counter() - start < .150
