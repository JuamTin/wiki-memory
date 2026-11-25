import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, NamedTuple

from ..redactor import SecretRedactor


class HookInput(NamedTuple):
    workspace: str
    session_id: str
    transcript: str | None


class TranscriptTurn(NamedTuple):
    role: str
    text: str
    timestamp: str


class HarnessAdapter(ABC):
    def parse_hook_input(self, payload: dict) -> HookInput:
        return HookInput(payload["cwd"], payload["session_id"], payload.get("transcript_path"))

    def format_context_output(self, event: str, text: str) -> dict:
        name = {"start": "SessionStart", "prompt": "UserPromptSubmit"}[event]
        return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": self.mark(text)}}

    @staticmethod
    def mark(text: str) -> str:
        return f"<!-- wiki-memoria:context -->\n{text}\n<!-- /wiki-memoria:context -->"

    @staticmethod
    def strip_injected_memory(text: str) -> str:
        return re.sub(r"<!-- wiki-memoria:context -->.*?(?:<!-- (?:/wiki-memoria:context|wiki-memoria:end|wiki-memoria:context) -->|\Z)",
                      "", text, flags=re.S).strip()

    @staticmethod
    def text_blocks(content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        return "\n".join(b["text"] for b in content if isinstance(b, dict) and b.get("type") in
                         {"text", "input_text", "output_text"} and isinstance(b.get("text"), str))

    @abstractmethod
    def parse_turn(self, row: dict) -> TranscriptTurn | None: ...

    def read_transcript_delta(self, path: Path, byte_offset: int) -> tuple[list[TranscriptTurn], int]:
        result = []
        with path.open("rb") as stream:
            stream.seek(byte_offset if path.stat().st_size >= byte_offset else 0)
            offset = stream.tell()
            for line in stream:
                if not line.endswith(b"\n"):
                    break
                row = json.loads(line)
                turn = self.parse_turn(row)
                if turn:
                    text = self.strip_injected_memory(turn.text)
                    if text:
                        result.append(turn._replace(text=SecretRedactor.redact(text)))
                offset = stream.tell()
        return result, offset
