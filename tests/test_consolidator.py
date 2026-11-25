from unittest.mock import Mock
import pytest

from wiki_memoria.config import AppConfig
from wiki_memoria.files import now
from wiki_memoria.indexer.embedder import LocalEmbedder
from wiki_memoria.indexer.fts_store import FtsStore
from wiki_memoria.project_resolver import ProjectResolver
from wiki_memoria.worker.consolidator import WikiConsolidator
from wiki_memoria.worker.scheduler import FlushScheduler
from wiki_memoria.worker.spool import SpoolQueue


def test_flush_and_retry(tmp_path):
    config = AppConfig(data_root=tmp_path / "vault")
    config.embeddings.enabled = False
    project = ProjectResolver(config).resolve(str(tmp_path))
    router = Mock()
    scheduler = FlushScheduler(config, WikiConsolidator(config, router, LocalEmbedder(config.embeddings)))
    queue = SpoolQueue(project.directory)
    for folder in ("wiki/hindsight", "wiki/recuerdos", "raw/sources/hindsight", "backup"):
        p = project.directory/folder/"orig.md"
        p.parent.mkdir(parents=True)
        p.write_text("privado")
    entry = dict(id="1", turn_count=1, timestamp=now(), workspace=str(tmp_path), harness="claude",
                 source="raw/sources/sessions/claude/test.md", turns=[{"role":"user","text":"nueva regla"}])
    queue.append(entry)
    assert not scheduler.run(project)
    router.run_structured.side_effect = RuntimeError()
    with pytest.raises(RuntimeError):
        scheduler.run(project, True)
    assert queue.snapshot() == [entry]
    router.run_structured.side_effect = None
    router.run_structured.return_value = dict(session_summary="cambio",durable_worth_saving=True,
        page_updates=[dict(slug="plan",title="Plan",mode="create_page",markdown_delta="Regla ghp_secreto",
                           tracks=[],citations=[entry["source"]])],
        initiatives=[dict(slug="uno", title="Uno",status="activa",summary="nuevo",next_step="revisar")],
        corrections=[dict(topic="Regla",previous_claim="antes",verified_truth="ahora",evidence="test")])
    assert scheduler.run(project, True)
    assert not queue.snapshot()
    assert len(FtsStore(project.directory).list_recent()) == 3
    assert all(p.read_text() == "privado" for p in project.directory.rglob("orig.md"))
    assert "ghp_secreto" not in (project.directory/"wiki/paginas/plan.md").read_text()
    queue.append(entry | {"id":"old","timestamp":"2020-01-01T00:00:00Z"})
    router.reset_mock()
    assert scheduler.run(project) and not queue.snapshot()
    router.run_structured.assert_not_called()
