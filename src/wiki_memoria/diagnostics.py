import json
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

from .config import AppConfig
from .indexer.hybrid_search import load_vector_extension


class Doctor:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def report(self) -> dict:
        import os
        home = Path.home()
        config = Path(os.environ.get("WIKI_MEMORIA_CONFIG", home / ".wiki-memoria/config.json"))
        checks = {"config": config.is_file(), "permisos": self.config.data_root.is_dir()
                  and self.config.data_root.stat().st_mode & 0o777 == 0o700}
        configs = {"claude": (".claude/settings.json", ".claude.json"), "codex": (".codex/hooks.json", ".codex/config.toml"),
                   "antigravity": (".gemini/config/hooks.json", ".gemini/config/mcp_config.json")}
        hindsight = False
        for harness, (hooks, mcp) in configs.items():
            paths = [home / hooks, home / mcp]
            try:
                hook_data = json.loads(paths[0].read_text())
                raw = paths[1].read_text()
                parsed = tomllib.loads(raw) if paths[1].suffix == ".toml" else json.loads(raw)
                servers = parsed.get("mcp_servers", parsed.get("mcpServers", {}))
                flat = harness == "antigravity"
                groups = hook_data.get("coding-agents" if flat else "hooks", {})
                events = {"PreInvocation": "prompt", "Stop": "stop"} if flat else {
                    "SessionStart": "start", "UserPromptSubmit": "prompt", "Stop": "stop"}
                binary = Path(sys.executable).with_name("wiki-memoria")
                hook = str(binary.with_name("wiki-memoria-hook"))
                complete = True
                for event, short in events.items():
                    entries = groups.get(event, [])
                    specs = entries if flat else [s for group in entries for s in group.get("hooks", [])]
                    commands = [shlex.split(s.get("command", "")) for s in specs]
                    complete &= [hook, "--harness", harness, "--event", short] in commands
                server = servers.get("wiki-memoria", {})
                checks[harness] = complete and server.get("command") == str(binary) and server.get("args") == ["mcp"]
                hindsight |= "hindsight" in json.dumps(groups).lower() or any("hindsight" in s.lower() for s in servers)
            except (OSError, ValueError):
                checks[harness] = False
            checks[f"cli_{harness}"] = shutil.which("agy" if harness == "antigravity" else harness) is not None
        checks["hindsight_hooks_disabled"] = not hindsight
        checks["systemd_timer"] = bool(shutil.which("systemctl")) and subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", "wiki-memoria-flush.timer"], capture_output=True).returncode == 0
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE VIRTUAL TABLE f USING fts5(t)")
            checks["sqlite_fts5"] = True
            load_vector_extension(db)
            checks["sqlite_vec"] = bool(db.execute("SELECT vec_version()").fetchone())
        checks["onnx_model"] = any(self.config.embeddings.cache_dir.rglob("*.onnx"))
        return checks
