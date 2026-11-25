import asyncio
import inspect
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, get_type_hints
from urllib.parse import unquote, urlparse

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import ConfigDict, create_model

from ..config import AppConfig, ConfigLoader
from ..worker.spool import SpoolQueue
from ..diagnostics import Doctor
from ..redactor import SecretRedactor
from ..domain import ProjectContext
from ..files import safe_path
from ..indexer.embedder import LocalEmbedder
from ..indexer.fts_store import FtsStore
from ..indexer.hybrid_search import HybridSearcher, VectorBackfill, load_vector_extension
from ..markdown_store import MarkdownStore, slugify
from ..project_resolver import ProjectResolver, bank_directory
from ..staleness import StalenessDetector


class MemoryTools:
    def __init__(self, config: AppConfig, embedder: LocalEmbedder) -> None:
        self.config = config
        from ..worker.runner import HeadlessLlmRouter
        self.router = HeadlessLlmRouter(config.consolidation)
        self.embedder = embedder
        self.backfill = VectorBackfill(embedder)

    def scopes(self, project: ProjectContext, ambito: str) -> list[ProjectContext]:
        glob = project.model_copy(update={"bank_id": "global", "directory": safe_path(project.data_root, "global")})
        return {"proyecto": [project], "global": [glob], "ambos": [project, glob]}[ambito]

    @staticmethod
    def counts(directory: Path) -> dict[str, int]:
        counts = dict(paginas=0, sesiones=0, notas=0, chunks=0)
        if safe_path(directory, ".state/index.sqlite").exists():
            with FtsStore(directory).connection() as db:
                for kind, label in [("pagina", "paginas"), ("hindsight_page", "paginas"), ("session", "sesiones"), ("nota", "notas")]:
                    counts[label] += db.execute("SELECT count(*) FROM documents WHERE kind=?", (kind,)).fetchone()[0]
                counts["chunks"] = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
        return counts

    def memoria_proyectos(self, project: ProjectContext) -> dict:
        """Lista bancos registrados y conteos del índice local."""
        path = safe_path(project.data_root, "manifest.json")
        banks = json.loads(path.read_text())["banks"] if path.exists() else []
        return {"proyectos": [{"banco": b["bank_id"], **self.counts(bank_directory(project.data_root, b["path"]))}
                              for b in banks], "global": self.counts(safe_path(project.data_root, "global"))}

    def memoria_buscar(self, project: ProjectContext, consulta: str, limite: int = 10,
                       ambito: Literal["ambos", "proyecto", "global"] = "ambos", tipos: list[str] | None = None,
                       desde: str | None = None, hasta: str | None = None,
                       orden: Literal["relevancia", "reciente"] = "relevancia", incluir_obsoletos: bool = False) -> dict:
        """Busca fragmentos relevantes en los índices léxico y vectorial."""
        hits = []
        for scope in self.scopes(project, ambito):
            store = FtsStore(scope.directory)
            self.backfill.schedule(store)
            search = HybridSearcher(store, self.embedder)
            for row in search.search(consulta, limite, orden=orden, tipos=tipos, desde=desde, hasta=hasta,
                                     incluir_obsoletos=incluir_obsoletos):
                hit = dict(archivo=str((scope.directory / row["rel_path"]).relative_to(project.data_root)),
                           tipo=row["kind"], updated_at=row["updated_at"], score=row["score"], fragmento=row["content"])
                if row["tracks_json"] != "[]" and scope.bank_id != "global":
                    freshness = StalenessDetector(store).evaluate_page_freshness(row, project.workspace)
                    if freshness["frescura"] == "desactualizada":
                        hit["stale_warning"] = freshness
                hits.append(hit)
        return {"resultados": sorted(hits, key=lambda h: h["updated_at" if orden == "reciente" else "score"], reverse=True)[:limite]}

    def memoria_reciente(self, project: ProjectContext, dias: int = 7, limite: int = 15,
                         incluir_git: bool = True, incluir_sin_commit: bool = True) -> dict:
        """Devuelve actividad reciente, incluidos commits y cambios locales."""
        store = FtsStore(project.directory)
        detector = StalenessDetector(store, self.config.hooks.git_commits_limit)
        events = []
        if incluir_git:
            detector.sync_git_commits(project)
            path = safe_path(project.directory, "raw/sources/git/commits.md")
            if path.exists():
                for block in path.read_text().split("\n## ")[1:]:
                    header, _, message = block.partition("\n")
                    sha, stamp = header.split(" ", 1)
                    events.append(dict(tipo="git", commit=sha, updated_at=stamp, resumen=message.strip()))
        with store.connection() as db:
            rows = db.execute("""SELECT kind,rel_path,updated_at FROM documents
                WHERE kind IN ('session','pagina','nota','iniciativa','correccion','hindsight_page')
                ORDER BY updated_at DESC LIMIT ?""", (limite,))
            events.extend(dict(tipo=row["kind"], archivo=row["rel_path"], updated_at=row["updated_at"]) for row in rows)
        if incluir_sin_commit and project.common_dir:
            events.extend(dict(tipo="sin_commit", **r) for r in detector.scan_uncommitted_activity(project.workspace, limite))
        cutoff = (datetime.now(UTC) - timedelta(days=dias)).timestamp()
        def timestamp(event: dict) -> float:
            return datetime.fromisoformat(event["updated_at"]).timestamp()
        return {"actividad": sorted((e for e in events if timestamp(e) >= cutoff), key=timestamp, reverse=True)[:limite]}

    def memoria_paginas(self, project: ProjectContext, ambito: Literal["ambos", "proyecto", "global"] = "proyecto") -> dict:
        """Lista páginas e iniciativas y su frescura frente a Git."""
        pages = []
        for scope in self.scopes(project, ambito):
            store = FtsStore(scope.directory)
            detector = StalenessDetector(store)
            with store.connection() as db:
                rows = db.execute("SELECT * FROM documents WHERE kind IN ('pagina','iniciativa','hindsight_page') ORDER BY updated_at DESC")
                activity = detector.scan_uncommitted_activity(project.workspace) if project.common_dir else []
                for row in map(dict, rows):
                    pages.append(dict(archivo=str((scope.directory / row["rel_path"]).relative_to(project.data_root)),
                                      titulo=row["title"], updated_at=row["updated_at"], verified_commit=row["verified_commit"],
                                      **detector.evaluate_page_freshness(row, project.workspace, activity)))
        return {"paginas": pages}

    def memoria_leer(self, project: ProjectContext, archivo: str, seccion: str | None = None,
                     linea_inicio: int | None = None, linea_fin: int | None = None) -> dict:
        """Lee un documento por ruta y opcionalmente sección o líneas."""
        rel = Path(archivo)
        for scope in self.scopes(project, "ambos"):
            prefix = scope.directory.relative_to(project.data_root)
            if rel.is_relative_to(prefix):
                return {"archivo": archivo, "contenido": MarkdownStore(scope).read_markdown(
                    str(rel.relative_to(prefix)), seccion, linea_inicio, linea_fin)}
        return {"archivo": archivo, "contenido": MarkdownStore(project).read_markdown(archivo, seccion, linea_inicio, linea_fin)}


    def _index_changed(self, project: ProjectContext, *rels: str) -> None:
        store = FtsStore(project.directory)
        for rel in dict.fromkeys(rels):
            if rel:
                store.index_file(rel)
        HybridSearcher(store, self.embedder).index_missing()

    def memoria_guardar(self, project: ProjectContext, titulo: str, contenido: str,
                        ambito: Literal["proyecto", "global"] = "proyecto", etiquetas: list[str] | None = None,
                        tracks: list[str] | None = None) -> dict:
        """Guarda e indexa una nota manual redactada."""
        scope = self.scopes(project, ambito)[0]
        rel = MarkdownStore(scope).write_note(titulo, contenido, etiquetas=etiquetas or [], tracks=tracks or [])
        self._index_changed(scope, rel)
        return {"guardado": str((scope.directory / rel).relative_to(project.data_root))}

    def memoria_corregir(self, project: ProjectContext, tema: str, afirmacion_anterior: str, verdad_actual: str,
                         evidencia: str, reemplaza_archivo: str | None = None) -> dict:
        """Documenta una corrección y enlaza el documento sustituido."""
        old = Path(reemplaza_archivo).relative_to(project.directory.relative_to(project.data_root)).as_posix() if (
            reemplaza_archivo and Path(reemplaza_archivo).is_relative_to(project.directory.relative_to(project.data_root))) else reemplaza_archivo
        rel = MarkdownStore(project).write_correction(tema, afirmacion_anterior, verdad_actual, evidencia, old)
        self._index_changed(project, rel, old or "")
        return {"guardado": str((project.directory / rel).relative_to(project.data_root))}

    def memoria_iniciativa(self, project: ProjectContext, titulo: str, resumen: str,
                           estado: Literal["activa", "pausada", "completada", "archivada"], siguiente_paso: str = "",
                           slug: str | None = None) -> dict:
        """Actualiza una iniciativa por slug."""
        rel = MarkdownStore(project).write_initiative(slug or slugify(SecretRedactor.redact(titulo)), titulo, resumen,
                                                      estado=estado, siguiente_paso=siguiente_paso)
        self._index_changed(project, rel)
        return {"guardado": str((project.directory / rel).relative_to(project.data_root))}

    def memoria_reflexionar(self, project: ProjectContext, pregunta: str, profundidad: str = "normal",
                            usar_llm: bool = False) -> dict:
        """Recupera citas literales por fuente para razonar sobre la pregunta."""
        evidence = []
        for kinds in (["pagina", "nota", "hindsight_page", "iniciativa"], ["correccion"], ["session"], ["git"]):
            results = self.memoria_buscar(project, pregunta, 6 if profundidad == "profunda" else 3,
                                          tipos=kinds)["resultados"]
            evidence.extend(dict(archivo=row["archivo"], tipo=row["tipo"], cita=row["fragmento"]) for row in results)
        bundle = {"pregunta": pregunta, "evidencia": evidence}
        if usar_llm:
            schema = {"type":"object", "properties":{"sintesis":{"type":"string"}}, "required":["sintesis"],
                      "additionalProperties":False}
            bundle.update(self.router.run_structured(json.dumps(bundle, ensure_ascii=False), schema, "codex"))
        return bundle

    def memoria_estado(self, project: ProjectContext) -> dict:
        """Describe la sincronización, la cola y la cobertura vectorial del proyecto."""
        fts = FtsStore(project.directory)
        entries = SpoolQueue(project.directory).snapshot()
        with fts.connection() as db:
            count = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
            vectors = 0
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='chunks_vec'").fetchone():
                load_vector_extension(db)
                vectors = db.execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
        return {"pending_turns": sum(entry["turn_count"] for entry in entries),
                "last_git_sha": fts.state("last_git_sha"), "ultima_consolidacion": fts.state("last_consolidation"),
                "chunks": count, "vectores": vectors, "embedder_ready": self.embedder.is_ready,
                "desactualizadas": sum(p["frescura"] == "desactualizada" for p in self.memoria_paginas(project)["paginas"])}

    def memoria_diagnosticar(self, project: ProjectContext) -> dict:
        """Verifica configuración local, hooks, temporizador, CLIs y modelo."""
        return {"checks": Doctor(self.config).report(), "embedder_ready": self.embedder.is_ready,
                "embedder_error": self.embedder.error}


class WikiMemoriaMcpServer:
    def __init__(self, config: AppConfig | None = None) -> None:
        config = config or ConfigLoader.load()
        self.resolver = ProjectResolver(config)
        self.embedder = LocalEmbedder(config.embeddings)
        self.handlers = MemoryTools(config, self.embedder)
        self.models = {}
        for name in dir(self.handlers):
            if name.startswith("memoria_"):
                method = getattr(self.handlers, name)
                hints = get_type_hints(method)
                fields = {k: (hints[k], p.default if p.default != inspect.Parameter.empty else ...)
                          for k, p in inspect.signature(method).parameters.items() if k != "project"}
                self.models[name] = create_model(name, __config__=ConfigDict(extra="forbid"),
                                                 workspace=(str | None, None), **fields)
        self.server = Server("wiki-memoria", version="2.0.0", on_list_tools=self.list_tools, on_call_tool=self.call_tool)

    async def list_tools(self, ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name=name, description=getattr(self.handlers, name).__doc__,
                                            inputSchema=model.model_json_schema()) for name, model in self.models.items()])

    def dispatch(self, name: str, args: dict[str, Any]) -> dict:
        values = self.models[name].model_validate(args).model_dump()
        project = self.resolver.resolve(values.pop("workspace") or os.getcwd())
        if "limite" in values and not 1 <= values["limite"] <= 200:
            raise ValueError("Límite fuera de 1..200")
        return getattr(self.handlers, name)(project, **values)

    async def call_tool(self, ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        try:
            args = dict(params.arguments or {})
            if not args.get("workspace") and getattr(ctx.session.client_capabilities, "roots", None) is not None:
                roots = await ctx.session.list_roots()
                if roots.roots:
                    uri = urlparse(str(roots.roots[0].uri))
                    if uri.scheme == "file" and uri.netloc in ("", "localhost"):
                        args["workspace"] = unquote(uri.path)
            result = await asyncio.to_thread(self.dispatch, params.name, args)
            return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                                        structuredContent=result)
        except (KeyError, ValueError, OSError) as exc:
            return types.CallToolResult(isError=True, content=[types.TextContent(type="text", text=str(exc))])

    async def run(self) -> None:
        self.embedder.start_background_load()
        async with stdio_server() as (reader, writer):
            await self.server.run(reader, writer, self.server.create_initialization_options())
