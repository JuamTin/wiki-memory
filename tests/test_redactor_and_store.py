import json
from pathlib import Path

import pytest
from wiki_memoria.config import AppConfig
from wiki_memoria.project_resolver import ProjectResolver
from wiki_memoria.markdown_store import MarkdownStore, split_frontmatter


@pytest.fixture
def store(tmp_path):
    cfg = AppConfig(data_root=tmp_path / "vault")
    return MarkdownStore(ProjectResolver(cfg).resolve(str(tmp_path)))


def test_disk_redaction(store):
    secrets = ["sk-private", "ghp_abcdef", "github_pat_dontstore", "Bearer abcdef",
               "eyJabcdef.abcdef.abcdef", 'MY_API_KEY="with spaces"',
               "-----BEGIN PRIVATE KEY-----\nhidden\n-----END PRIVATE KEY-----"]
    body = "\n".join(secrets)
    rel = store.write_note("sk-title", body, tracks=["ghp_track"])
    raw = store.append_raw_session("codex", "id", body, "2026-11-24")
    for path in (rel, raw):
        s = store.read_markdown(path)
        assert all(item not in s for item in secrets + ["sk-title", "ghp_track", "hidden"])
        assert s.count("[REDACTED:") >= 7
        assert (store.root / path).stat().st_mode & 0o777 == 0o600
    assert Path(rel).name in store.read_markdown("wiki/index.md")
    assert rel in store.read_markdown("wiki/log.md")
    assert len(json.loads((store.project.data_root / "manifest.json").read_text())["banks"]) == 1


def test_correction_and_sections(store):
    old = store.write_page("plan", "Plan", "## Uno\nabc\n## Dos\nbcd")
    assert store.read_markdown(old, "Uno") == "abc"
    assert store.read_markdown(old, start=1, end=1) == "---\n"
    new = store.write_correction("tema", "antes", "ahora", "fuente", old)
    meta, _ = split_frontmatter(store.read_markdown(old))
    assert (meta["status"], meta["superseded_by"]) == ("superseded", new)
    initiative = store.write_initiative("meta", "Meta", "uno")
    assert store.write_initiative("meta", "Meta", "dos") == initiative


def test_paths(store, tmp_path):
    store.write_note("sano", "contenido")
    (store.root / "wiki/link.md").symlink_to(tmp_path / "privado")
    for path in ["wiki/link.md", "../wiki/index.md", "/tmp/example.md", ".state/index.sqlite"]:
        with pytest.raises(ValueError):
            store.read_markdown(path)
    for rel in ["wiki/hindsight/orig.md", "wiki/recuerdos/orig.md", "raw/sources/hindsight/orig.md", "backup/orig.md"]:
        with pytest.raises(ValueError):
            store.write_correction("tema", "antes", "ahora", "fuente", rel)
