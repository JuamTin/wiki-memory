from .base import HarnessAdapter, HookInput, TranscriptTurn


class AntigravityAdapter(HarnessAdapter):
    def parse_hook_input(self, payload: dict) -> HookInput:
        return HookInput(payload["workspacePaths"][0], payload["conversationId"], payload.get("transcriptPath"))

    def format_context_output(self, event: str, text: str) -> dict:
        return {"injectSteps": [{"ephemeralMessage": self.mark(text)}]}

    def parse_turn(self, row: dict) -> TranscriptTurn | None:
        role = {"USER_INPUT": "user", "PLANNER_RESPONSE": "assistant"}.get(row.get("type"))
        if role:
            return TranscriptTurn(role, self.text_blocks(row.get("content")), row.get("created_at") or row.get("timestamp", ""))
        return None
