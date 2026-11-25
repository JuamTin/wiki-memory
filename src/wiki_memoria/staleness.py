from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .domain import ProjectContext
from .files import atomic_write, file_lock, safe_path
from .indexer.fts_store import FtsStore
from .redactor import SecretRedactor


def git(workspace: Path, *args: str) -> bytes:
    cmd = subprocess.run(["git", "-C", str(workspace), *args], capture_output=True, check=True,
                         env=os.environ | {"GIT_OPTIONAL_LOCKS": "0"})
    return cmd.stdout


class StalenessDetector:
    def __init__(self, store: FtsStore, limit: int = 50) -> None:
        self.store = store
        self.limit = limit

    def sync_git_commits(self, project: ProjectContext) -> None:
        if project.common_dir is None:
            return
        rel = "raw/sources/git/commits.md"
        path = safe_path(project.directory, rel)
        with file_lock(safe_path(project.directory, ".state/git.lock")):
            try:
                head = git(project.workspace, "rev-parse", "--verify", "HEAD").decode().strip()
            except subprocess.CalledProcessError:
                return
            last = self.store.state("last_git_sha")
            if head == last:
                return
            args = ["log", "--format=%x1e%H%x1f%cI%x1f%s", "--name-only"]
            try:
                raw = git(project.workspace, *args, *([f"{last}..{head}"] if last else [f"-{self.limit}", head]))
            except subprocess.CalledProcessError:
                raw = git(project.workspace, *args, f"-{self.limit}", head)
            body = path.read_text() if path.exists() else ""
            seen = set(re.findall(r"(?m)^## ([a-f0-9]{40,64}) ", body))
            for entry in reversed(raw.decode(errors="replace").split("\x1e")[1:]):
                sha, stamp, message = entry.strip().split("\x1f", 2)
                if sha not in seen:
                    body += f"\n## {sha} {stamp}\n{SecretRedactor.redact(message)}\n"
            atomic_write(path, body)
            self.store.index_file(rel)
            self.store.set_state("last_git_sha", head)

    @staticmethod
    def scan_uncommitted_activity(workspace: Path, limit: int = 50) -> list[dict[str, Any]]:
        try:
            raw = git(workspace, "status", "--porcelain=v1", "-z", "--untracked-files=normal")
        except subprocess.CalledProcessError:
            return []
        entries = iter(raw.split(b"\0"))
        changes = []
        for record in entries:
            if not record:
                continue
            code, name = record[:2].decode(), os.fsdecode(record[3:])
            if "R" in code or "C" in code:
                old = os.fsdecode(next(entries, b""))
            else:
                old = None
            path = workspace / name
            try:
                mtime = path.lstat().st_mtime
            except FileNotFoundError:
                mtime = (workspace / ".git").stat().st_mtime
            changes.append(dict(archivo=name, anterior=old, estado=code,
                                updated_at=datetime.fromtimestamp(mtime, UTC).isoformat()))
        return sorted(changes, key=lambda row: row["updated_at"], reverse=True)[:limit]

    def evaluate_page_freshness(self, doc: dict[str, Any], workspace: Path,
                                activity: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        tracks = [Path(t) for t in doc.get("tracks", json.loads(doc.get("tracks_json") or "[]"))]
        changed = set()
        if tracks:
            activity = self.scan_uncommitted_activity(workspace, 2**31) if activity is None else activity
            paths = {Path(row[k]) for row in activity for k in ("archivo", "anterior") if row.get(k)}
            sha = doc.get("verified_commit")
            if sha:
                if not re.fullmatch("[0-9a-fA-F]{7,64}", sha):
                    return {"frescura": "desactualizada", "archivos": [], "motivo": "commit inválido"}
                try:
                    paths.update(Path(os.fsdecode(p)) for p in git(workspace, "diff", "--no-renames", "--name-only",
                                                                  "-z", f"{sha}..HEAD", "--").split(b"\0") if p)
                except subprocess.CalledProcessError:
                    return {"frescura": "desactualizada", "archivos": [], "motivo": "commit desconocido"}
            changed = {str(p) for p in paths if any(p.is_relative_to(t) or t.is_relative_to(p) for t in tracks)}
        return {"frescura": "desactualizada" if changed else "vigente", "archivos": sorted(changed)}
