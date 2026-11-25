import fcntl
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def safe_path(root: Path, relative: str | Path) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError("Ruta relativa inválida")
    path = root / rel
    if path.resolve() != path:
        raise ValueError("No se admiten enlaces simbólicos")
    return path


def is_memory_document(relative: Path) -> bool:
    return relative.suffix == ".md" and (relative.parts[:1] == ("wiki",) or
            relative.parts[:2] == ("raw", "sources") or relative.as_posix() in {"purpose.md", "schema.md"})


def private_dirs(path: Path) -> None:
    if not path.exists():
        private_dirs(path.parent)
        path.mkdir(mode=0o700, exist_ok=True)


def atomic_write(path: Path, text: str) -> None:
    private_dirs(path.parent)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as tmp:
        try:
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
            os.replace(tmp.name, path)
        finally:
            Path(tmp.name).unlink(missing_ok=True)


@contextmanager
def file_lock(path: Path, blocking: bool = True) -> Iterator[None]:
    private_dirs(path.parent)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as stream:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.flock(stream, flags)
        yield


def append_text(path: Path, text: str) -> None:
    private_dirs(path.parent)
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
