import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Embeddings(BaseModel):
    enabled: bool = True
    model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    threads: int = Field(default=8, ge=1)
    cache_dir: Path = Field(default_factory=lambda: Path.home() / ".cache/wiki-memoria/fastembed")


class HarnessConfig(BaseModel):
    model: str
    effort: str | None = None
    reasoning_effort: str | None = None


def default_harnesses() -> dict[str, HarnessConfig]:
    return {
        "claude": HarnessConfig(model="haiku", effort="high"),
        "agy": HarnessConfig(model="gemini-3.8-flash-low"),
        "codex": HarnessConfig(model="gpt-6-luna", reasoning_effort="medium"),
    }


class Consolidation(BaseModel):
    turn_threshold: int = Field(default=4, ge=1)
    idle_flush_minutes: int = Field(default=15, ge=1)
    timeout_seconds: int = Field(default=60, ge=1)
    fallback_order: list[Literal["active", "agy", "codex", "claude"]] = ["active", "agy", "codex", "claude"]
    harnesses: dict[str, HarnessConfig] = Field(default_factory=default_harnesses)


class Hooks(BaseModel):
    max_inject_tokens: int = Field(default=600, ge=1, le=600)
    git_commits_limit: int = Field(default=50, ge=1)


class AppConfig(BaseModel):
    version: Literal[2] = 2
    data_root: Path = Field(default_factory=lambda: Path.home() / "wiki-memoria")
    opt_in_only: bool = False
    opt_in_paths: list[Path] = []
    disabled_paths: list[Path] = [Path("/home/juamtin/Documentos/trabajo")]
    map_path_to_bank: dict[Path, str] = {}
    migration_watermark: str = "2026-11-19T00:47:11Z"
    embeddings: Embeddings = Field(default_factory=Embeddings)
    consolidation: Consolidation = Field(default_factory=Consolidation)
    hooks: Hooks = Field(default_factory=Hooks)


class ConfigLoader:
    @staticmethod
    def load() -> AppConfig:
        path = Path(os.environ.get("WIKI_MEMORIA_CONFIG", "~/.wiki-memoria/config.json")).expanduser()
        values = json.loads(path.read_text()) if path.exists() else {}
        if "WIKI_MEMORIA_ROOT" in os.environ:
            values["data_root"] = os.environ["WIKI_MEMORIA_ROOT"]
        config = AppConfig.model_validate(values)
        config.data_root = config.data_root.expanduser().resolve()
        return config
