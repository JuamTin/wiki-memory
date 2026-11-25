import json
from pathlib import Path

from ..files import append_text, atomic_write, file_lock, safe_path


class SpoolQueue:
    def __init__(self, root: Path) -> None:
        self.path = safe_path(root, ".state/spool.jsonl")
        self.lock = safe_path(root, ".state/spool.lock")

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line]

    def snapshot(self) -> list[dict]:
        with file_lock(self.lock):
            return self._read()

    def append(self, entry: dict) -> int:
        with file_lock(self.lock):
            entries = self._read()
            if not any(row["id"] == entry["id"] for row in entries):
                append_text(self.path, json.dumps(entry, ensure_ascii=False) + "\n")
                entries.append(entry)
            return sum(row["turn_count"] for row in entries)

    def acknowledge(self, ids: set[str]) -> None:
        with file_lock(self.lock):
            remaining = (json.dumps(r, ensure_ascii=False) + "\n" for r in self._read() if r["id"] not in ids)
            atomic_write(self.path, "".join(remaining))
