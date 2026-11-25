import json
from pathlib import Path

from .files import atomic_write, file_lock, now, safe_path


def update_manifest(root: Path, directory: Path, bank_id: str, identity: Path) -> None:
    if directory == root / "global":
        return
    with file_lock(safe_path(root, ".state/manifest.lock")):
        path = safe_path(root, "manifest.json")
        data = json.loads(path.read_text()) if path.exists() else {"version": 2, "global": "global", "banks": []}
        relative = directory.relative_to(root).as_posix()
        bank = next((b for b in data["banks"] if b["path"] == relative), None)
        if bank is None:
            bank = {"bank_id": bank_id, "path": relative,
                    "workspace": str(identity.parent if identity.name == ".git" else identity)}
            data["banks"].append(bank)
        bank["updated_at"] = now()
        atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
