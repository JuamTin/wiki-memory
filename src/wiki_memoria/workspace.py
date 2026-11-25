import hashlib
import json
import re
import subprocess
from pathlib import Path

from types import SimpleNamespace
from typing import Any


def bank_directory(root: Path, relative: str) -> Path:
    parts = Path(relative).parts
    if len(parts) != 2 or parts[0] != "proyectos" or parts[1] in {".", ".."}:
        raise ValueError("Ruta de banco inválida")
    directory = root.joinpath(*parts)
    if directory.resolve() != directory:
        raise ValueError("Enlace en ruta del banco")
    return directory


class WorkspaceResolver:
    context_type = SimpleNamespace

    def __init__(self, config: Any) -> None:
        self.config = config

    def check_workspace(self, path: Path) -> None:
        if any(path.is_relative_to(p.expanduser().resolve()) for p in self.config.disabled_paths):
            raise PermissionError("Memoria deshabilitada en este directorio")

    def resolve(self, workspace: str) -> Any:
        path = Path(workspace).expanduser().resolve()
        self.check_workspace(path)
        if not path.is_dir():
            raise NotADirectoryError(path)
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir", "--show-toplevel"],
            capture_output=True, text=True, check=False,
        )
        common = None
        if result.returncode == 0:
            git_directory, worktree = result.stdout.rstrip("\n").splitlines()
            common = Path(git_directory).resolve()
            path = Path(worktree).resolve()
            self.check_workspace(common)
            self.check_workspace(path)
        identity = common.parent if common and common.name == ".git" else common or path
        requested = Path(workspace).resolve()
        mappings = [(len(p.parts), name) for p, name in self.config.map_path_to_bank.items()
                    if any(w.is_relative_to(p.expanduser().resolve()) for w in (requested, identity))]
        if self.config.opt_in_only and not mappings and not any(
            requested.is_relative_to(p.expanduser().resolve()) for p in self.config.opt_in_paths
        ):
            raise PermissionError("Proyecto fuera de opt_in_paths")
        root = self.config.data_root
        manifest = root / "manifest.json"
        banks = json.loads(manifest.read_text())["banks"] if manifest.exists() else []
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", identity.name).strip(".-")[:60] or "sin-nombre"
        digest = hashlib.sha256(str(identity).encode()).hexdigest()[:12]
        name = max(mappings)[1] if mappings else f"coding-agent::{identity.name}"
        for bank in banks:
            if bank["bank_id"] == name or (mappings and bank["path"] == name):
                if not mappings and bank.get("workspace", str(identity)) != str(identity):
                    continue
                return self.context_type(workspace=path, common_dir=common, bank_id=bank["bank_id"],
                                      data_root=root, directory=bank_directory(root, bank["path"]))
        if mappings:
            # Explicit mappings must name a known bank. A typo must never fork its memory.
            raise ValueError(f"Banco sin registrar: {name}")
        return self.context_type(workspace=path, common_dir=common, bank_id=f"{name}::{digest}",
                              data_root=root, directory=bank_directory(root, f"proyectos/{slug}--{digest}"))
