from concurrent.futures import ThreadPoolExecutor
from time import monotonic

from wiki_memoria.indexer.fts_store import FtsStore
from wiki_memoria.indexer.chunker import MarkdownChunker


def test_chunking():
    chunks = MarkdownChunker().chunk("# Principal\n" + "a" * 2500 + "\n### Último\nfin")
    assert len(chunks) == 4 and max(len(c.content) for c in chunks) == 1200
    assert chunks[-1].section_heading == "Último"


def test_incremental(tmp_path):
    s = FtsStore(tmp_path)
    p = tmp_path / "wiki/hindsight/page.md"
    p.parent.mkdir(parents=True)
    p.write_text("---\ntitle: Página\n---\n## tema\nrégimen")
    rel = "wiki/hindsight/page.md"
    start = monotonic()
    assert s.index_file(rel)
    assert monotonic() - start < .2
    assert not s.index_file(rel)
    assert s.search_fts("regimen")[0]["origin"] == "hindsight_migrated"
    p.write_text("---\nstatus: superseded\n---\nObsoleto")
    s.index_file(rel)
    assert not s.search_fts("regimen", include_obsolete=True)
    assert not s.search_fts("obsoleto")
    assert s.search_fts("obsoleto", include_obsolete=True)


def test_concurrent(tmp_path):
    stores = [FtsStore(tmp_path), FtsStore(tmp_path)]
    (tmp_path / "wiki").mkdir()
    def index(i):
        rel = f"wiki/{i}.md"
        (tmp_path / rel).write_text("régimen")
        stores[i % 2].index_file(rel)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(index, range(10)))
    assert len(stores[0].list_recent()) == 10
    stores[0].set_cursor("codex", "abc", "log", 153, 2)
    assert stores[1].cursor("codex", "abc")["byte_offset"] == 153
