import subprocess
from time import perf_counter

from wiki_memoria.config import AppConfig
from wiki_memoria.indexer.fts_store import FtsStore
from wiki_memoria.project_resolver import ProjectResolver
from wiki_memoria.staleness import StalenessDetector, git


def test_git_delta(tmp_path):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True)
    def commit():
        git(repo, "add", ".")
        git(repo, "-c", "user.email=a@b", "-c", "user.name=test", "commit", "-m", "prueba")
        return git(repo, "rev-parse", "HEAD").decode().strip()
    (repo / "code").write_text("one")
    original = commit()
    project = ProjectResolver(AppConfig(data_root=tmp_path / "vault")).resolve(str(repo))
    store = FtsStore(project.directory)
    detector = StalenessDetector(store)
    detector.sync_git_commits(project)
    (repo / "code").write_text("two")
    doc = {"tracks": ["code", "Strategies"], "verified_commit": original}
    assert detector.evaluate_page_freshness(doc, repo)["archivos"] == ["code"]
    current = commit()
    (repo / "Strategies/VWAP_DMI").mkdir(parents=True)
    (repo / "Strategies/VWAP_DMI/strategy.py").touch()
    start = perf_counter()
    activity = detector.scan_uncommitted_activity(repo)
    assert perf_counter() - start < .04 and activity
    assert detector.evaluate_page_freshness(doc, repo)["frescura"] == "desactualizada"
    detector.sync_git_commits(project)
    detector.sync_git_commits(project)
    body = (project.directory / "raw/sources/git/commits.md").read_text()
    assert body.count(original) == body.count(current) == 1
    assert store.search_fts("prueba")
