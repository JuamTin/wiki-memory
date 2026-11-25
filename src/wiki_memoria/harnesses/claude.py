from .base import HarnessAdapter, TranscriptTurn


class ClaudeAdapter(HarnessAdapter):
    def parse_turn(self, row: dict) -> TranscriptTurn | None:
        role = row.get("type")
        if role not in {"user", "assistant"} or any(row.get(k) for k in ("isMeta", "isSidechain", "isCompactSummary")):
            return None
        content = self.text_blocks(row.get("message", {}).get("content"))
        return TranscriptTurn(role, content, row.get("timestamp", ""))
