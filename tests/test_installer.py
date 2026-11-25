import json
import tomllib
from wiki_memoria.config import AppConfig
from wiki_memoria.harnesses.installer import HarnessInstaller


def test_install_uninstall(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("WIKI_MEMORIA_CONFIG", raising=False)
    api = HarnessInstaller(AppConfig(data_root=tmp_path/"vault"), tmp_path)
    codex = tmp_path/".codex/config.toml"
    codex.parent.mkdir(parents=True)
    original = '# conservar\n[mcp_servers.otro]\ncommand="otro"\n[mcp_servers.wiki-memoria]\ncommand="node"\n'
    codex.write_text(original)
    hooks = tmp_path/".claude/settings.json"
    hooks.parent.mkdir()
    hooks.write_text(json.dumps({"hooks":{"Stop":[{"matcher":"X","hooks":[
        {"command":"otro"},{"command":"node /home/u/.hindsight/coding-agents/dist/stop.js"}]}]}}))
    options = dict(manage_timer=False, disable_hindsight=True)
    api.apply(list(api.paths), dry_run=True, **options)
    assert not codex.with_name("config.toml.bak").exists()
    api.apply(list(api.paths), **options)
    first = {p:p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    api.apply(list(api.paths), **options)
    assert first == {p:p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert tomllib.loads(codex.read_text())["mcp_servers"]["otro"]["command"] == "otro"
    assert "conservar" in codex.read_text() and "hindsight" not in hooks.read_text()
    assert codex.with_name("config.toml.bak").read_text() == original
    api.apply(list(api.paths), uninstall=True, **options)
    assert "wiki-memoria-hook" not in hooks.read_text() and "otro" in hooks.read_text()
    assert tomllib.loads(codex.read_text()) == tomllib.loads(original)
    assert not (tmp_path/".config/systemd/user/wiki-memoria-flush.timer").exists()


def test_codex_reviewed_hook_keeps_group_index_at_cutover(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKI_MEMORIA_CONFIG", str(tmp_path / "config.json"))
    installer = HarnessInstaller(AppConfig(data_root=tmp_path / "vault"), tmp_path)
    path = tmp_path / ".codex/hooks.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"hooks": {"Stop": [
        {"hooks": [{"command": "node /home/example/.hindsight/coding-agents/dist/stop.js"}]}
    ]}}))
    installer.apply(["codex"], manage_timer=False)
    original = json.loads(path.read_text())["hooks"]["Stop"][1]
    installer.apply(["codex"], disable_hindsight=True, manage_timer=False)
    result = json.loads(path.read_text())["hooks"]["Stop"]
    assert result == [{"hooks": []}, original]
