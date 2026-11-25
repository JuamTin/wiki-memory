from .base import HarnessAdapter, TranscriptTurn


class CodexAdapter(HarnessAdapter):
    def parse_turn(self, row: dict) -> TranscriptTurn | None:
        if row.get("type") != "response_item":
            return None
        payload = row.get("payload", {})
        role = payload.get("role")
        if payload.get("type") == "function_call":
            return TranscriptTurn("assistant", "Herramienta: " + str(payload.get("name", "")), row.get("timestamp", ""))
        if role not in {"assistant", "user"} or payload.get("type") != "message":
            return None
        text = self.text_blocks(payload.get("content"))
        if text.startswith(("<environment_context>", "<permissions instructions>", "# AGENTS.md instructions")):
            return None
        return TranscriptTurn(role, text, row.get("timestamp", ""))
