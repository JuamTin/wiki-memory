import json
import subprocess
import pytest
from wiki_memoria.config import Consolidation
from wiki_memoria.worker.runner import HeadlessLlmRouter

SCHEMA = {"type":"object","properties":{"texto":{"type":"string"}},"required":["texto"],"additionalProperties":False}


def test_rotation(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("EXAMPLE_API_KEY", "private")
    monkeypatch.delenv("ANTIGRAVITY_LS_ADDRESS", raising=False)
    seen = []
    def run(args, **options):
        harness = args[0]
        seen.append(harness)
        assert not any(key.endswith("_API_KEY") for key in options["env"])
        assert options["env"]["WIKI_MEMORIA_INTERNAL"] == options["env"]["HINDSIGHT_DISABLE_HOOKS"] == "1"
        body = {"claude": "invalid", "agy": '{"conversation_id":"abc","structured_output":{"invalid":true}}',
                "codex": '{"texto":"ok"}'}[harness]
        return subprocess.CompletedProcess(args, 0, body, "quota exceeded" if harness == "claude" else "")
    monkeypatch.setattr(subprocess, "run", run)
    assert HeadlessLlmRouter(Consolidation()).run_structured("prompt", SCHEMA, "claude") == {"texto":"ok"}
    assert seen == ["claude","agy","codex"]
    assert json.loads((tmp_path/".wiki-memoria/internal_sessions.json").read_text()) == ["abc"]


def test_exhaustion(monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("cli", 1)
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError, match="agy.*codex.*claude"):
        HeadlessLlmRouter(Consolidation()).run_structured("x", SCHEMA, "antigravity")


def test_cleanup_scoped_to_config(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    from wiki_memoria.harnesses.cleanup import ConversationCleanup
    isolated = tmp_path / "smoke"
    monkeypatch.setenv("WIKI_MEMORIA_CONFIG", str(isolated / "config.json"))
    monkeypatch.setenv("ANTIGRAVITY_LS_ADDRESS", "127.0.0.1:12345")
    monkeypatch.setenv("ANTIGRAVITY_CSRF_TOKEN", "synthetic")
    response = MagicMock()
    response.__enter__.return_value.status = 200
    def rpc(request, timeout):
        assert json.loads(request.data) == {"conversationId": "owned-test"}
        assert request.get_header("Connect-protocol-version") == "1"
        return response
    monkeypatch.setattr("wiki_memoria.harnesses.cleanup.urlopen", rpc)
    cleanup = ConversationCleanup()
    cleanup.run("owned-test")
    assert cleanup.path == isolated / "internal_sessions.json"
    assert json.loads(cleanup.path.read_text()) == []
