import json
import pytest
from wiki_memoria.harnesses.claude import ClaudeAdapter
from wiki_memoria.harnesses.codex import CodexAdapter
from wiki_memoria.harnesses.antigravity import AntigravityAdapter


@pytest.mark.parametrize("adapter,valid,noise", [
    (ClaudeAdapter(), {"type":"user","message":{"content":"Hola"}}, {"type":"user","message":{"content":"skip"},"isMeta":True}),
    (CodexAdapter(), {"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Hola"}]}},
     {"type":"event_msg","payload":{"message":"skip"}}),
    (AntigravityAdapter(), {"type":"USER_INPUT","content":"Hola","created_at":"2026-11-24T12:30:00Z"},
     {"type":"PLANNER_RESPONSE","tool_calls":[]}),
])
def test_delta(tmp_path, adapter, valid, noise):
    path = tmp_path / "log.jsonl"
    encoded = json.dumps(valid).encode()
    path.write_bytes(json.dumps(noise).encode() + b"\n" + encoded + b"\n" + encoded[:5])
    first, cursor = adapter.read_transcript_delta(path, 0)
    assert len(first) == 1 and first[0].text == "Hola"
    with path.open("ab") as stream:
        stream.write(encoded[5:] + b"\n")
    second, cursor = adapter.read_transcript_delta(path, cursor)
    assert second == first
    assert adapter.read_transcript_delta(path, cursor) == ([], cursor)
    assert adapter.strip_injected_memory("a" + adapter.mark("privado") + "b") == "ab"
