import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import tomlkit

from ..config import AppConfig
from ..files import atomic_write, private_dirs
from ..diagnostics import Doctor


class HarnessInstaller:
    paths = {"claude": (".claude/settings.json", ".claude.json"),
             "codex": (".codex/hooks.json", ".codex/config.toml"),
             "antigravity": (".gemini/config/hooks.json", ".gemini/config/mcp_config.json")}

    def __init__(self, config: AppConfig, home: Path | None = None) -> None:
        self.config = config
        self.home = home or Path.home()
        self.binary = Path(sys.executable).with_name("wiki-memoria")
        self.hook = self.binary.with_name("wiki-memoria-hook")

    @staticmethod
    def _owned(command: str, disable: bool) -> bool:
        try:
            parts = shlex.split(command)
        except ValueError:
            return False
        return bool(parts) and (Path(parts[0]).name == "wiki-memoria-hook" or
                                (disable and any("/.hindsight/coding-agents/" in p for p in parts)))

    def _hooks(self, data: dict, harness: str, remove: bool, disable: bool) -> None:
        flat = harness == "antigravity"
        groups = data.setdefault("coding-agents" if flat else "hooks", {})
        events = {"PreInvocation": "prompt", "Stop": "stop"} if flat else {
            "SessionStart": "start", "UserPromptSubmit": "prompt", "Stop": "stop"}
        for event in set(groups) | set(events):
            kept = []
            for item in groups.get(event, []):
                if flat:
                    if not self._owned(item.get("command", ""), disable):
                        kept.append(item)
                elif "hooks" in item:
                    hooks = [h for h in item["hooks"] if not self._owned(h.get("command", ""), disable)]
                    # Codex identifies a reviewed hook by its group and handler indexes.
                    # Keep the vacant Hindsight slot on cutover so wiki retains its position.
                    codex_slot = harness == "codex" and not remove and (
                        not item["hooks"] or all(self._owned(h.get("command", ""), True)
                        and not self._owned(h.get("command", ""), False) for h in item["hooks"]))
                    if hooks or codex_slot:
                        kept.append(item | {"hooks": hooks})
                else:
                    kept.append(item)
            if event in events and not remove:
                cmd = shlex.join([str(self.hook), "--harness", harness, "--event", events[event]])
                spec = {"command": cmd, "timeout": 5}
                kept.append(spec if flat else {"hooks": [{"type": "command", **spec}]})
            if kept:
                groups[event] = kept
            else:
                groups.pop(event, None)

    @staticmethod
    def backup(path: Path, content: str) -> Path:
        first = path.with_name(path.name + ".bak")
        if not first.exists():
            atomic_write(first, content)
        elif first.read_text() != content:
            fingerprint = hashlib.sha256(content.encode()).hexdigest()[:12]
            later = path.with_name(f"{path.name}.{fingerprint}.bak")
            if not later.exists():
                atomic_write(later, content)
        return first

    def apply(self, harnesses: list[str], *, dry_run: bool = False, uninstall: bool = False,
              disable_hindsight: bool = False, manage_timer: bool = True) -> list[str]:
        changes: dict[Path, str | None] = {}
        for harness in harnesses:
            for i, relative in enumerate(self.paths[harness]):
                path = self.home / relative
                if path.is_symlink():
                    raise ValueError(f"Configuración enlazada: {path}")
                if uninstall and not path.exists():
                    continue
                toml = path.suffix == ".toml"
                decode = tomlkit.parse if toml else json.loads
                old = path.read_text() if path.exists() else ("" if toml else "{}")
                data = decode(old)
                if i == 0:
                    self._hooks(data, harness, uninstall, disable_hindsight)
                else:
                    key = "mcp_servers" if toml else "mcpServers"
                    servers = data.setdefault(key, {})
                    if disable_hindsight:
                        servers.pop("hindsight", None)
                    if uninstall:
                        current = servers.get("wiki-memoria", {})
                        if current.get("command") == str(self.binary):
                            servers.pop("wiki-memoria", None)
                            backup = path.with_name(path.name + ".bak")
                            if backup.exists():
                                original = decode(backup.read_text()).get(key, {}).get("wiki-memoria")
                                if original:
                                    servers["wiki-memoria"] = original
                    else:
                        servers["wiki-memoria"] = {"command": str(self.binary), "args": ["mcp"]}
                if data != decode(old):
                    changes[path] = tomlkit.dumps(data) if toml else json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        config = Path(os.getenv("WIKI_MEMORIA_CONFIG", self.home / ".wiki-memoria/config.json"))
        if not uninstall and not config.exists():
            changes[config] = self.config.model_dump_json(indent=2) + "\n"
        units = self.home / ".config/systemd/user"
        service, timer = units / "wiki-memoria-flush.service", units / "wiki-memoria-flush.timer"
        unit_data = {service: "[Unit]\nDescription=Consolidar la memoria inactiva\n[Service]\nType=oneshot\n"
                     + f'ExecStart="{self.binary}" worker --idle-flush\n',
                     timer: "[Unit]\nDescription=Revisar turnos pendientes\n[Timer]\nOnBootSec=2min\n"
                     "OnUnitActiveSec=3min\nPersistent=true\n[Install]\nWantedBy=timers.target\n"}
        for path, content in unit_data.items():
            if uninstall:
                if path.exists() and path.read_text() == content:
                    changes[path] = None
            elif not path.exists() or path.read_text() != content:
                changes[path] = content
        report = [f"{'Retirar' if v is None else 'Actualizar'} {p}" for p, v in changes.items()]
        if "codex" in harnesses:
            report.append("Codex requiere revisar y aprobar los hooks modificados en .hook-trust.")
        if dry_run:
            return report
        if uninstall and manage_timer and timer.exists():
            subprocess.run(["systemctl", "--user", "disable", "--now", timer.name], check=True)
        for path, content in changes.items():
            if path.exists():
                self.backup(path, path.read_text())
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, content)
        if not uninstall:
            private_dirs(self.config.data_root)
            self.config.data_root.chmod(0o700)
        if manage_timer:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            if not uninstall:
                subprocess.run(["systemctl", "--user", "enable", "--now", timer.name], check=True)
        return report
