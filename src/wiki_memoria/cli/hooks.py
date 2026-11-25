import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from ..files import append_text, file_lock, now, safe_path
from ..harnesses.antigravity import AntigravityAdapter
from ..harnesses.base import HarnessAdapter, HookInput
from ..harnesses.claude import ClaudeAdapter
from ..harnesses.codex import CodexAdapter
from ..manifest import update_manifest
from ..indexer.fts_store import FtsStore
from ..worker.spool import SpoolQueue
from ..workspace import WorkspaceResolver


class HookService:
    def __init__(self) -> None:
        config = Path(os.environ.get("WIKI_MEMORIA_CONFIG", "~/.wiki-memoria/config.json")).expanduser()
        self.config = json.loads(config.read_text()) if config.exists() else {}
        data = self.config
        self.resolver = WorkspaceResolver(SimpleNamespace(
            data_root=Path(os.environ.get("WIKI_MEMORIA_ROOT", data.get("data_root", "~/wiki-memoria"))).expanduser().resolve(),
            disabled_paths=list(map(Path, data.get("disabled_paths", ["/home/juamtin/Documentos/trabajo"]))),
            opt_in_only=data.get("opt_in_only", False), opt_in_paths=list(map(Path, data.get("opt_in_paths", []))),
            map_path_to_bank={Path(k): v for k, v in data.get("map_path_to_bank", {}).items()}))

    def handle(self, harness: str, event: str, payload: dict) -> dict:
        adapter = {"claude": ClaudeAdapter, "codex": CodexAdapter, "antigravity": AntigravityAdapter}[harness]()
        info = adapter.parse_hook_input(payload)
        project = self.resolver.resolve(info.workspace)
        if not re.fullmatch(r"[\w-]{1,160}", info.session_id):
            raise ValueError("Sesión inválida")
        if harness == "antigravity":
            from ..harnesses.cleanup import ConversationCleanup
            cleanup = ConversationCleanup()
            if cleanup.path.exists() and info.session_id in json.loads(cleanup.path.read_text()):
                return {}
            if event != "stop":
                cleanup.run()
        with file_lock(safe_path(project.directory, ".state/hook.lock")):
            store = FtsStore(project.directory)
            if event == "stop":
                self.capture(harness, adapter, info, project, store)
                return {}
            count = store.cursor(harness, info.session_id)["turn_count"]
            key = f"injection/{harness}/{info.session_id}"
            if count % 10 or store.state(key) == str(count):
                return {}
            text = self.context(store, project)
            store.set_state(key, str(count))
            return adapter.format_context_output(event, text) if text else {}

    def context(self, store: FtsStore, project: SimpleNamespace) -> str:
        from ..staleness import StalenessDetector
        detector = StalenessDetector(store)
        activity = detector.scan_uncommitted_activity(project.workspace) if project.common_dir else []
        with store.connection() as db:
            pages = db.execute("SELECT * FROM documents WHERE kind IN ('pagina','iniciativa','hindsight_page') AND status='active' ORDER BY updated_at DESC LIMIT 8")
            lines = []
            for page in pages:
                fresh = detector.evaluate_page_freshness(dict(page), project.workspace, activity)
                lines.append(f"{fresh['frescura']}: {page['title']} ({page['rel_path']})")
        events = [(row["updated_at"], row["rel_path"]) for row in store.list_recent(3)]
        events.extend((row["updated_at"], row["archivo"]) for row in activity)
        lines.extend("Actividad: " + p for _, p in sorted(events, reverse=True)[:3])
        budget = min(600, self.config.get("hooks", {}).get("max_inject_tokens", 600))
        return "\n".join(lines).encode()[:max(0, budget - 65)].decode(errors="ignore")

    def capture(self, harness: str, adapter: HarnessAdapter, info: HookInput, project: SimpleNamespace,
                store: FtsStore) -> None:
        if not info.transcript:
            return
        path = Path(info.transcript).expanduser().resolve(strict=True)
        self.resolver.check_workspace(path)
        if path.suffix != ".jsonl":
            raise ValueError("Transcripción inválida")
        prior = store.cursor(harness, info.session_id)
        offset = prior["byte_offset"] if prior.get("transcript_path") == str(path) else 0
        turns, end = adapter.read_transcript_delta(path, offset)
        count = prior["turn_count"]
        if turns:
            update_manifest(project.data_root, project.directory, project.bank_id, project.common_dir or project.workspace)
            stamp = now()
            event_id = hashlib.sha256(f"{harness}/{info.session_id}/{path}/{offset}/{end}".encode()).hexdigest()
            date = datetime.fromtimestamp(path.stat().st_mtime, UTC).date()
            rel = f"raw/sources/sessions/{harness}/{date}-{info.session_id}.md"
            target = safe_path(project.directory, rel)
            marker = f"<!-- delta:{event_id} -->"
            body = "\n".join(f"### {t.role} {t.timestamp}\n{t.text}" for t in turns)
            if not target.exists() or marker not in target.read_text():
                append_text(target, f"\n{marker}\n{body}\n")
            store.index_file(rel)
            added = max(1, sum(t.role == "user" for t in turns))
            count += added
            entry = dict(id=event_id, timestamp=stamp, harness=harness, workspace=str(project.workspace),
                         source=rel, turn_count=added, turns=[t._asdict() for t in turns])
            pending = SpoolQueue(project.directory).append(entry)
        store.set_cursor(harness, info.session_id, str(path), end, count)
        if turns and pending >= self.config.get("consolidation", {}).get("turn_threshold", 4):
            binary = Path(sys.executable).with_name("wiki-memoria")
            subprocess.Popen([binary, "worker", "--project", project.directory], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
