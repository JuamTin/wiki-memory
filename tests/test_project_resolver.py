import json
import subprocess
from pathlib import Path

import pytest

from wiki_memoria.config import AppConfig, ConfigLoader
from wiki_memoria.project_resolver import ProjectResolver


@pytest.fixture
def resolver(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"banks": [
        {"bank_id": "coding-agent::RBI", "path": "proyectos/RBI--b2a7657555e8"},
        {"bank_id": "other", "path": "proyectos/other"},
    ]}))
    return ProjectResolver(AppConfig(data_root=root))


@pytest.mark.parametrize("suffix", ["", "/subdir"])
def test_disabled(resolver, suffix):
    with pytest.raises(PermissionError):
        resolver.resolve("/home/juamtin/Documentos/trabajo" + suffix)


def test_manifest_and_identity(resolver, tmp_path):
    for name in ("RBI", "a/demo", "b/demo"):
        (tmp_path / name).mkdir(parents=True)
    assert resolver.resolve(str(tmp_path / "RBI")).directory.name == "RBI--b2a7657555e8"
    assert resolver.resolve(str(tmp_path / "a/demo")).directory != resolver.resolve(str(tmp_path / "b/demo")).directory


def test_mapping(resolver, tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    resolver.config.opt_in_only = True
    with pytest.raises(PermissionError):
        resolver.resolve(str(sub))
    resolver.config.map_path_to_bank = {tmp_path: "other", sub: "coding-agent::RBI"}
    assert resolver.resolve(str(sub)).bank_id == "coding-agent::RBI"


def test_worktree(resolver, tmp_path):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@test",
                    "commit", "--allow-empty", "-m", "init"], check=True)
    linked = tmp_path / "linked"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(linked)], check=True)
    assert resolver.resolve(str(repo)).directory == resolver.resolve(str(linked)).directory
    resolver.config.disabled_paths = [repo]
    with pytest.raises(PermissionError):
        resolver.resolve(str(linked))


def test_config(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text('{"opt_in_only":true}')
    monkeypatch.setenv("WIKI_MEMORIA_CONFIG", str(path))
    monkeypatch.setenv("WIKI_MEMORIA_ROOT", str(tmp_path))
    cfg = ConfigLoader.load()
    assert cfg.opt_in_only and cfg.data_root == tmp_path
    assert cfg.consolidation.harnesses["agy"].model == "gemini-3.8-flash-low"
