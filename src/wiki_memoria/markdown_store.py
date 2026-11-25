import re
import unicodedata
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from .manifest import update_manifest
from .domain import ProjectContext
from .files import append_text, atomic_write, file_lock, is_memory_document, now, safe_path
from .redactor import SecretRedactor


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = re.match(r"\A---\r?\n(.*?)^---\r?\n", text, re.S | re.M)
    if not match:
        return {}, text
    meta = yaml.safe_load(match[1]) or {}
    if not isinstance(meta, dict):
        raise ValueError("Frontmatter inválido")
    return meta, text[match.end():]


def slugify(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:90] or "nota"


class MarkdownStore:
    kinds = {"nota": "notas", "pagina": "paginas", "iniciativa": "iniciativas", "correccion": "correcciones"}

    def __init__(self, project: ProjectContext) -> None:
        self.project = project
        self.root = project.directory

    def _path(self, rel: str | Path) -> Path:
        return safe_path(self.root, rel)

    def _save(self, path: Path, meta: dict[str, Any], content: str) -> None:
        clean = self._clean_metadata(meta)
        header = yaml.safe_dump(clean, allow_unicode=True, sort_keys=False)
        atomic_write(path, f"---\n{header}---\n{SecretRedactor.redact(content)}")

    def _clean_metadata(self, meta: dict[str, Any]) -> dict[str, Any]:
        return {key: SecretRedactor.redact(value) if isinstance(value, str)
                else [SecretRedactor.redact(item) for item in value] if isinstance(value, list)
                else value for key, value in meta.items()}

    def _write(self, kind: str, slug: str, title: str, content: str, *,
               replaces: str | None = None, **fields: Any) -> str:
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            raise ValueError("Slug inválido")
        rel = f"wiki/{self.kinds[kind]}/{slug}.md"
        path = self._path(rel)
        with file_lock(self._path(".state/markdown.lock")):
            previous = None
            if replaces:
                old_path = self._path(replaces)
                if (old_path.suffix != ".md" or Path(replaces).parent.as_posix() not in
                        {f"wiki/{d}" for d in self.kinds.values()} or old_path == path):
                    raise ValueError("Solo se pueden sustituir documentos v2")
                previous = split_frontmatter(old_path.read_text())
            created = split_frontmatter(path.read_text())[0].get("created_at") if path.exists() else None
            stamp = now()
            self._save(path, dict(title=title, kind=kind, origin="wiki_v2", status="active",
                                  created_at=created or stamp, updated_at=stamp, **fields), content)
            if previous:
                meta, body = previous
                meta.update(status="superseded", superseded_by=rel, updated_at=stamp)
                self._save(old_path, meta, body)
            self.rebuild_index()
            self.append_log(rel)
            self.update_manifest()
        return rel

    def write_note(self, title: str, content: str, **fields: Any) -> str:
        return self._write("nota", uuid4().hex, title, content, **fields)

    def write_page(self, slug: str, title: str, content: str, **fields: Any) -> str:
        return self._write("pagina", slug, title, content, **fields)

    def write_initiative(self, slug: str, title: str, summary: str, **fields: Any) -> str:
        return self._write("iniciativa", slug, title, summary, **fields)

    def write_correction(self, topic: str, previous_claim: str, verified_truth: str, evidence: str,
                         replaces: str | None = None, slug: str | None = None) -> str:
        content = f"## Afirmación anterior\n{previous_claim}\n\n## Verdad verificada\n{verified_truth}\n\n## Evidencia\n{evidence}\n"
        return self._write("correccion", slug or uuid4().hex, topic, content, replaces=replaces)

    def append_raw_session(self, harness: str, session: str, content: str, date: str) -> str:
        if harness not in {"claude", "codex", "antigravity"} or not re.fullmatch(r"[\w-]+", session):
            raise ValueError("Identificador de sesión inválido")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("Fecha inválida")
        rel = f"raw/sources/sessions/{harness}/{date}-{session}.md"
        with file_lock(self._path(".state/markdown.lock")):
            append_text(self._path(rel), SecretRedactor.redact(content))
        return rel

    def read_markdown(self, relative: str, section: str | None = None, start: int | None = None,
                      end: int | None = None) -> str:
        path = self._path(relative)
        rel = Path(relative)
        if not is_memory_document(rel):
            raise ValueError("Archivo fuera de la wiki")
        text = path.read_text()
        if section:
            heading = re.search(r"(?m)^##[ \t]+" + re.escape(section) + r"[ \t]*$", text)
            if heading is None:
                raise KeyError(section)
            return re.split(r"(?m)^#{1,2}[ \t]+", text[heading.end():], maxsplit=1)[0].strip()
        if start is not None or end is not None:
            if (start or 1) < 1 or (end is not None and end < (start or 1)) or start == 0:
                raise ValueError("Rango inválido")
            return "".join(text.splitlines(keepends=True)[(start or 1)-1:end])
        return text

    def rebuild_index(self) -> None:
        wiki = self._path("wiki")
        links = [p.relative_to(wiki).as_posix() for p in sorted(wiki.glob("*/*.md"))
                 if self._path(p.relative_to(self.root)).is_file()]
        atomic_write(self._path("wiki/index.md"), "# Índice\n\n" + "".join(f"- [{p}]({p})\n" for p in links))

    def append_log(self, relative: str) -> None:
        append_text(self._path("wiki/log.md"), f"- {now()} {SecretRedactor.redact(relative)}\n")

    def update_manifest(self) -> None:
        update_manifest(self.project.data_root, self.root, self.project.bank_id,
                        self.project.common_dir or self.project.workspace)
