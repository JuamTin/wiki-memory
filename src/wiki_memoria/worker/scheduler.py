from datetime import UTC, datetime

from ..config import AppConfig
from ..domain import ProjectContext
from ..files import file_lock, safe_path
from .consolidator import WikiConsolidator
from .spool import SpoolQueue


class FlushScheduler:
    def __init__(self, config: AppConfig, consolidator: WikiConsolidator) -> None:
        self.config = config
        self.consolidator = consolidator

    def run(self, project: ProjectContext, force: bool = False) -> bool:
        try:
            with file_lock(safe_path(project.directory, ".state/worker.lock"), blocking=False):
                entries = SpoolQueue(project.directory).snapshot()
                if not entries:
                    return False
                last = max(datetime.fromisoformat(e["timestamp"]) for e in entries)
                idle = (datetime.now(UTC) - last).total_seconds()
                turns = sum(e["turn_count"] for e in entries)
                if (force or turns >= self.config.consolidation.turn_threshold
                        or idle >= self.config.consolidation.idle_flush_minutes * 60):
                    self.consolidator.flush(project, entries)
                    return True
                return False
        except BlockingIOError:
            return False
