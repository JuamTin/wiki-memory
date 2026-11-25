import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate

from ..config import Consolidation
from ..harnesses.cleanup import ConversationCleanup


class HeadlessLlmRouter:
    def __init__(self, config: Consolidation) -> None:
        self.config = config

    def command(self, harness: str, prompt: str, schema: str, directory: Path) -> list[str]:
        model = self.config.harnesses[harness]
        if harness == "claude":
            return ["claude", "-p", prompt, "--model", model.model, "--effort", model.effort or "high",
                    "--output-format", "json", "--json-schema", schema, "--no-session-persistence",
                    "--disable-slash-commands", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                    "--setting-sources", "", "--tools", ""]
        if harness == "codex":
            path = directory / "output-schema.json"
            path.write_text(schema)
            return ["codex", "exec", "-m", model.model, "-c", f'model_reasoning_effort="{model.reasoning_effort}"',
                    "-c", "features.hooks=false", "--ephemeral", "--skip-git-repo-check", "-s", "read-only",
                    "--output-schema", str(path), prompt]
        return ["agy", "-p", prompt, "--model", model.model, "--output-format", "json", "--json-schema", schema,
                "--disable-slash-commands", "--print-timeout", f"{self.config.timeout_seconds}s"]

    def run_structured(self, prompt: str, schema: dict, active_harness: str) -> dict[str, Any]:
        active = "agy" if active_harness == "antigravity" else active_harness
        order = dict.fromkeys(active if h == "active" else h for h in self.config.fallback_order)
        env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY") and k != "HINDSIGHT_API_TOKEN"}
        env.update(WIKI_MEMORIA_INTERNAL="1", HINDSIGHT_DISABLE_HOOKS="1")
        failures = []
        with tempfile.TemporaryDirectory(prefix="wiki-memoria-") as tmp:
            for harness in order:
                if harness not in self.config.harnesses:
                    continue
                args = self.command(harness, prompt, json.dumps(schema), Path(tmp))
                try:
                    proc = subprocess.run(args, capture_output=True, text=True, cwd=tmp, env=env,
                                          timeout=self.config.timeout_seconds + 2, stdin=subprocess.DEVNULL)
                    try:
                        data = json.loads(proc.stdout)
                    except ValueError:
                        data = {}
                    if harness == "agy" and isinstance(data, dict) and data.get("conversation_id"):
                        ConversationCleanup().run(data["conversation_id"])
                    result = data.get("structured_output", data) if isinstance(data, dict) else data
                    errors = proc.stderr + (str(data.get("error", "")) if isinstance(data, dict) else "")
                    if proc.returncode or re.search(r"\b(?:429|rate.limit|quota.exceeded|overloaded)\b", errors, re.I):
                        raise ValueError("fallo del proveedor")
                    validate(result, schema)
                    return result
                except (OSError, subprocess.TimeoutExpired, ValueError, ValidationError) as exc:
                    failures.append(f"{harness}: {type(exc).__name__}")
        raise RuntimeError("Sin respuesta válida de los proveedores: " + ", ".join(failures))
