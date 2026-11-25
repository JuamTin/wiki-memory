# Runbook de Ejecución LLM: `wiki-memoria v2` (`WIKI-001`)

> **Instrucciones del Sistema para el Agente Ejecutor:**
> Actúas como ingeniero senior implementando **`wiki-memoria v2`** según la especificación aprobada (`2.0.0-spec`).
> - **Repositorio de código:** `/home/juamtin/Documentos/juamtin/wiki-memoria-engine` (entorno `uv` propio en `.venv/`; **nunca** mezclar con `conda algotrade`).
> - **Bóveda de datos (`WIKI_MEMORIA_ROOT`):** `/home/juamtin/wiki-memoria` (**nunca** borrar ni mutar `backup/`, `wiki/hindsight/`, `wiki/recuerdos/` ni `raw/sources/hindsight/`).
> - **Estilo obligatorio:** Python `>= 3.12`, OOP con SRP estricto (una clase = una responsabilidad, métodos cortos, inyección por constructor, type hints en todos los parámetros y retornos, SQL parametrizado `?`, context managers `with`, cero estado global mutable).
> - **Restricción crítica de latencia:** `src/wiki_memoria/cli/hook_entry.py` **no puede importar** `fastembed`, `onnxruntime`, `sqlite_vec` ni `mcp` (solo stdlib + `sqlite3`, objetivo `< 50 ms`).
> - **Protocolo de ejecución:** ejecuta las tareas estrictamente en orden (`1.1` → `5.3`). No avances a la siguiente tarea hasta que el comando **Verificación Empírica (DoD)** pase al 100 % y marques sus checkboxes `- [x]`.

---

## ETAPA 01: Cimientos del Proyecto, Configuración y Almacenamiento Markdown

#### Tarea 1.1: Inicializar repositorio Python con `uv` y estructura modular SRP
* **Prioridad:** `crítica`
* **Disciplina:** DevOps & Cloud
* **Archivos Afectados:**
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/pyproject.toml`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/.gitignore`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/__init__.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/domain.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_smoke.py`
* **Contratos:**
  - Consume: Ninguno (tarea semilla).
  - Produce: Entorno `uv` funcional (`.venv/`), scripts CLI registrados (`wiki-memoria`, `wiki-memoria-hook`) y modelos Pydantic base (`ProjectContext`, `Turn`, `MemoryDoc`, `ConsolidationPlan`).
* **Instrucciones:**
  - [x] Paso 1: Inicializar Git en `/home/juamtin/Documentos/juamtin/wiki-memoria-engine` y crear `.gitignore` (`.venv/`, `__pycache__/`, `.pytest_cache/`, `*.sqlite*`, `.cache/`).
  - [x] Paso 2: Crear `pyproject.toml` con `requires-python = ">=3.12"`, dependencias (`mcp>=1.9.0`, `pydantic>=2.10`, `sqlite-vec>=0.1.6`, `fastembed>=0.6.0`, `pyyaml>=6.0`), grupo dev (`pytest>=8.0`) y entry points `wiki-memoria = "wiki_memoria.cli.main:main"` y `wiki-memoria-hook = "wiki_memoria.cli.hook_entry:main"`.
  - [x] Paso 3: Definir los modelos de dominio tipados en `src/wiki_memoria/domain.py` incluyendo el esquema Pydantic de `ConsolidationPlan` (exacto a la sección 4.4 del Spec).
  - [x] Paso 4: Ejecutar `uv sync --dev` y crear `tests/test_smoke.py` verificando imports y serialización del JSON Schema de `ConsolidationPlan`.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/test_smoke.py -v`
  - **Resultado Esperado:** `1 passed` (o más) con `exit code 0` y entorno `.venv/` independiente de `conda`.

#### Tarea 1.2: Implementar `ConfigLoader` y `ProjectResolver` (worktree-safe y bloqueo de rutas)
* **Prioridad:** `crítica`
* **Disciplina:** Backend & Datos
* **Archivos Afectados:**
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/config.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/project_resolver.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_project_resolver.py`
* **Contratos:**
  - Consume: `domain.py` (Tarea 1.1), formato de `/home/juamtin/wiki-memoria/manifest.json`.
  - Produce: `ConfigLoader.load() -> AppConfig` (default `~/.wiki-memoria/config.json`, respeta `WIKI_MEMORIA_CONFIG` y `WIKI_MEMORIA_ROOT`) y `ProjectResolver.resolve(workspace: str) -> ProjectContext`.
* **Instrucciones:**
  - [x] Paso 1: Implementar `AppConfig` y `ConfigLoader` en `config.py` con todos los defaults de la sección 4.1 del Spec (`disabled_paths=["/home/juamtin/Documentos/trabajo"]`, `migration_watermark="2026-11-19T00:47:11Z"`, modelos `haiku/high`, `gemini-3.8-flash-low`, `gpt-6-luna/medium`, `fallback_order=["active","agy","codex","claude"]`).
  - [x] Paso 2: Implementar `ProjectResolver` usando `git rev-parse --git-common-dir` normalizado a ruta absoluta (comparte banco entre worktrees enlazados), soporte para `opt_in_only`, `disabled_paths`, `map_path_to_bank` (longest-prefix wins) y resolución retrocompatible contra los 14 bancos de `manifest.json`.
  - [x] Paso 3: Escribir pruebas unitarias cubriendo: rechazo de `/home/juamtin/Documentos/trabajo` y subdirectorios, worktree compartido, resolución de RBI a `proyectos/RBI--b2a7657555e8`, y nuevo proyecto sin colisión.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/test_project_resolver.py -v`
  - **Resultado Esperado:** Todos los tests pasan (`exit code 0`), incluyendo bloqueo estricto de `Documentos/trabajo`.

#### Tarea 1.3: Implementar `SecretRedactor` y `MarkdownStore` (append-only + índice y registro automáticos)
* **Prioridad:** `crítica`
* **Disciplina:** Backend & Datos
* **Archivos Afectados:**
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/redactor.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/markdown_store.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_redactor_and_store.py`
* **Contratos:**
  - Consume: `ProjectContext` (Tarea 1.2).
  - Produce: `SecretRedactor.redact(text: str) -> str` y `MarkdownStore` (`write_note`, `write_page`, `write_initiative`, `write_correction`, `append_raw_session`, `read_markdown`, `rebuild_index`, `append_log`, `update_manifest`).
* **Instrucciones:**
  - [x] Paso 1: Implementar `SecretRedactor` detectando y redactando con `[REDACTED:<tipo>]` claves `sk-*`, `ghp_*`/`github_pat_*`, `Bearer <token>`, JWT (`eyJ...`), asignaciones `*API_KEY=*`, `*SECRET=*`, `*TOKEN=*`, `*PASSWORD=*` y bloques de claves privadas PEM.
  - [x] Paso 2: Implementar `MarkdownStore` con permisos `0700`/`0600`, escritura atómica (`tmp` + `os.replace`), frontmatter YAML seguro vía `yaml.safe_dump`, bloqueo estricto de symlinks y *path traversal* en `read_markdown`, soporte de lectura por encabezado `##` o rango de líneas, marcado de `status: superseded` + `superseded_by`, y actualización automática de `wiki/index.md` y `wiki/log.md`.
  - [x] Paso 3: Escribir tests sobre un directorio temporal verificando redacción de 6 tipos de secretos, rechazo de symlinks y actualización consistente de `index.md` + `log.md`.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/test_redactor_and_store.py -v`
  - **Resultado Esperado:** Todos los tests pasan; ningún token sintético sobrevive en disco.

---

## ETAPA 02: Motor de Indexación Híbrido Local y Detección de Frescura

#### Tarea 2.1: Implementar `MarkdownChunker` y `FtsStore` (SQLite WAL + FTS5 + cursors)
* **Prioridad:** `crítica`
* **Disciplina:** Backend & Datos
* **Archivos Afectados:**
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/indexer/__init__.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/indexer/chunker.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/indexer/fts_store.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_fts_store.py`
* **Contratos:**
  - Consume: `MarkdownStore` (Tarea 1.3), `ProjectContext` (Tarea 1.2).
  - Produce: `MarkdownChunker.chunk(text) -> list[Chunk]` y `FtsStore` (esquema SQLite de la sección 4.2 del Spec: `documents`, `chunks`, `chunks_fts`, `transcript_cursors`, `sync_state`, `index_file`, `search_fts`, `list_recent`).
* **Instrucciones:**
  - [x] Paso 1: Implementar `MarkdownChunker` dividiendo por encabezados `#{1,3}` con sub-división máxima de `1200` caracteres y parseo de frontmatter (detectando `origin=hindsight_migrated` si la ruta cae en `wiki/hindsight/`, `wiki/recuerdos/` o `raw/sources/hindsight/`).
  - [x] Paso 2: Implementar `FtsStore` usando **solo `sqlite3` stdlib** (para poder importarlo también desde hooks rápidos) con `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, `tokenize='unicode61 remove_diacritics 2'`, re-indexado incremental por `(mtime_ns, sha256)` y consultas parametrizadas.
  - [x] Paso 3: Escribir tests de búsqueda con/sin tildes (`regimen` vs `régimen`), supersedencia, cursors incrementales y prueba de concurrencia con 2 conexiones simultáneas.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/test_fts_store.py -v`
  - **Resultado Esperado:** Todos los tests pasan sin `SQLITE_BUSY` y FTS5 indexa en `< 200 ms` sobre fixtures.

#### Tarea 2.2: Implementar `LocalEmbedder` (MiniLM-L12-v2 lazy) y `HybridSearcher` (`sqlite-vec` + RRF)
* **Prioridad:** `crítica`
* **Disciplina:** Backend & Datos
* **Archivos Afectados:**
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/indexer/embedder.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/indexer/hybrid_search.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_hybrid_search.py`
* **Contratos:**
  - Consume: `FtsStore` (Tarea 2.1), `AppConfig.embeddings` (Tarea 1.2).
  - Produce: `LocalEmbedder` (carga lazy/en hilo en segundo plano de `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`) y `HybridSearcher.search(...) -> list[SearchHit]` (RRF + pesos de la sección 4.3 del Spec + degradación automática a FTS5 si el modelo aún está cargando).
* **Instrucciones:**
  - [x] Paso 1: Implementar `LocalEmbedder` con `start_background_load()`, propiedad `is_ready`, `embed_passages(texts)` y `embed_query(text)` usando `fastembed.TextEmbedding` (con `cache_dir` persistente en `~/.cache/wiki-memoria/fastembed`).
  - [x] Paso 2: Implementar `HybridSearcher` gestionando `chunks_vec` (`vec0(chunk_id INTEGER PRIMARY KEY, embedding float[384])`), indexado vectorial incremental de chunks faltantes y fusión RRF con multiplicadores $w_{\text{kind}}$, $w_{\text{status}}$ y $w_{\text{recency}}$, además de `orden="reciente"` y filtro `incluir_obsoletos`.
  - [x] Paso 3: Escribir tests verificando degradación limpia a FTS5 con embedder apagado, búsqueda híbrida real en español/inglés con `sqlite-vec` y prioridad de `correccion` > `pagina` > `superseded`.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/test_hybrid_search.py -v`
  - **Resultado Esperado:** Todos los tests pasan; consulta híbrida en caliente `< 150 ms`.

#### Tarea 2.3: Implementar `StalenessDetector` (Git incremental + cambios sin commit)
* **Prioridad:** `alta`
* **Disciplina:** Backend & Datos
* **Archivos Afectados:**
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/staleness.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_staleness.py`
* **Contratos:**
  - Consume: `ProjectContext` (Tarea 1.2), `MarkdownStore` (Tarea 1.3), `FtsStore` (Tarea 2.1).
  - Produce: `StalenessDetector` (`sync_git_commits`, `scan_uncommitted_activity`, `evaluate_page_freshness`).
* **Instrucciones:**
  - [x] Paso 1: Implementar `sync_git_commits(project)` ingiriendo solo commits nuevos desde `last_git_sha` en `raw/sources/git/commits.md` e indexándolos en `FtsStore`.
  - [x] Paso 2: Implementar `scan_uncommitted_activity(workspace)` leyendo `git status --porcelain` y los archivos modificados/sin seguimiento más recientes por `mtime` (acotado y rápido, `< 40 ms`), para detectar trabajo no commiteado como `Strategies/VWAP_DMI/`.
  - [x] Paso 3: Implementar `evaluate_page_freshness(doc, workspace)` comparando `verified_commit` y `tracks` del frontmatter contra `git diff --name-only <verified_commit>..HEAD` + `git status --porcelain`.
  - [x] Paso 4: Escribir tests sobre un repo Git temporal con commits, archivos modificados y archivos sin seguimiento.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/test_staleness.py -v`
  - **Resultado Esperado:** Detecta commits nuevos, archivos untracked recientes y marca páginas como `desactualizada` cuando cambia un archivo bajo `tracks`.

---

## ETAPA 03: Servidor MCP v2 (10 Herramientas)

#### Tarea 3.1: Implementar `WikiMemoriaMcpServer` — herramientas de lectura, timeline y frescura
* **Prioridad:** `crítica`
* **Disciplina:** Backend & Datos
* **Archivos Afectados:**
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/mcp/__init__.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/mcp/server.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_mcp_read.py`
* **Contratos:**
  - Consume: `ConfigLoader`, `ProjectResolver`, `MarkdownStore`, `HybridSearcher`, `StalenessDetector` (Etapas 01–02).
  - Produce: Herramientas MCP `memoria_proyectos`, `memoria_buscar`, `memoria_reciente`, `memoria_paginas`, `memoria_leer` con arranque no bloqueante (embedder en hilo secundario).
* **Instrucciones:**
  - [x] Paso 1: Crear `WikiMemoriaMcpServer` sobre `mcp.server.Server` (`stdio`), iniciando `LocalEmbedder.start_background_load()` al arrancar el servidor para no retrasar el handshake.
  - [x] Paso 2: Implementar inferencia de `workspace` opcional vía MCP `roots/list` o fallback a `os.getcwd()`, manteniendo validación estricta de `disabled_paths`.
  - [x] Paso 3: Implementar los 5 handlers de lectura (`memoria_proyectos`, `memoria_buscar`, `memoria_reciente` incluyendo commits y archivos sin commit, `memoria_paginas` con bandera `vigente`/`desactualizada`, y `memoria_leer` con filtro por `seccion` o rango de líneas).
  - [x] Paso 4: Escribir pruebas de integración invocando los handlers directamente y validando salidas JSON.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/test_mcp_read.py -v`
  - **Resultado Esperado:** Las 5 herramientas de lectura responden correctamente y rechazan `Documentos/trabajo`.

#### Tarea 3.2: Completar `WikiMemoriaMcpServer` — escritura, corrección, iniciativas, reflexión y diagnóstico
* **Prioridad:** `crítica`
* **Disciplina:** Backend & Datos
* **Archivos Afectados:**
  - Modificar: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/mcp/server.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_mcp_write.py`
* **Contratos:**
  - Consume: `WikiMemoriaMcpServer` (Tarea 3.1), `SecretRedactor` (Tarea 1.3).
  - Produce: Herramientas MCP `memoria_guardar`, `memoria_corregir`, `memoria_iniciativa`, `memoria_reflexionar` (`usar_llm=false` por defecto), `memoria_estado` y `memoria_diagnosticar`.
* **Instrucciones:**
  - [x] Paso 1: Implementar `memoria_guardar` (redactando secretos, escribiendo en `wiki/notas/`, re-indexando FTS5+vec e `index.md`/`log.md`), `memoria_corregir` (marcando `superseded_by` en el archivo reemplazado) y `memoria_iniciativa` (upsert de archivo único en `wiki/iniciativas/<slug>.md`).
  - [x] Paso 2: Implementar `memoria_reflexionar` recuperando evidencia multi-fuente (páginas + correcciones + sesiones + git) con citas literales; cuando `usar_llm=false` devuelve el paquete estructurado directo, y deja el gancho inyectable para `HeadlessLlmRouter` (Etapa 04) cuando `usar_llm=true`.
  - [x] Paso 3: Implementar `memoria_estado` y `memoria_diagnosticar` (reportando config, hooks, timer, CLIs y estado del embedder).
  - [x] Paso 4: Escribir pruebas unitarias/integración cubriendo todas las escrituras, supersedencia y redacción de secretos.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/test_mcp_write.py -v`
  - **Resultado Esperado:** Las 10 herramientas MCP v2 están registradas y pasan 100 % de tests.

---

## ETAPA 04: Adaptadores Multi-Harness, Hooks Rápidos y Worker de Consolidación

#### Tarea 4.1: Implementar adaptadores y parsers incrementales para Claude Code, Codex y Antigravity
* **Prioridad:** `crítica`
* **Disciplina:** Backend & Datos
* **Archivos Afectados:**
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/harnesses/__init__.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/harnesses/base.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/harnesses/claude.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/harnesses/codex.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/harnesses/antigravity.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_harnesses_parsers.py`
* **Contratos:**
  - Consume: `Turn` (Tarea 1.1), `SecretRedactor` (Tarea 1.3).
  - Produce: `ClaudeAdapter`, `CodexAdapter`, `AntigravityAdapter` implementando parseo de payload `stdin`, formateo de salida `stdout` (`hookSpecificOutput` vs `injectSteps`), lectura incremental de transcripciones desde `byte_offset` y `strip_injected_memory`.
* **Instrucciones:**
  - [x] Paso 1: Definir `HarnessAdapter` (ABC) en `base.py` con `parse_hook_input`, `format_context_output`, `read_transcript_delta(path, byte_offset)` y `strip_injected_memory` (eliminando bloques delimitados por `<!-- wiki-memoria:context -->`).
  - [x] Paso 2: Implementar los 3 adaptadores respetando exactamente los contratos verificados en Wayfinder S2 (`workspacePaths[0]`/`conversationId`/`transcriptPath` + `injectSteps` + `created_at` en Antigravity; `response_item` en Codex; `user`/`assistant` excluyendo `isMeta`/`isSidechain`/`isCompactSummary` en Claude).
  - [x] Paso 3: Escribir tests con fixtures realistas de los 3 formatos JSONL verificando lectura incremental sin duplicados al re-invocar con el nuevo `byte_offset`.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/test_harnesses_parsers.py -v`
  - **Resultado Esperado:** Todos los parsers extraen exactamente el delta de turnos nuevos y descartan ruido/memoria inyectada.

#### Tarea 4.2: Implementar `SpoolQueue` y el entrypoint ultra-ligero `wiki-memoria-hook` (`< 50 ms`)
* **Prioridad:** `crítica`
* **Disciplina:** Backend & Datos
* **Archivos Afectados:**
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/worker/__init__.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/worker/spool.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/cli/__init__.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/cli/hook_entry.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_hooks_fastpath.py`
* **Contratos:**
  - Consume: `ProjectResolver` (versión stdlib-compatible), `FtsStore` (Tarea 2.1), `SecretRedactor` (Tarea 1.3), `harnesses/*` (Tarea 4.1).
  - Produce: Binario `wiki-memoria-hook --harness <claude|codex|antigravity> --event <start|prompt|stop>` con latencia `< 300 ms` p95 (meta `< 50 ms`).
* **Instrucciones:**
  - [x] Paso 1: Implementar `SpoolQueue` en `spool.py` usando `fcntl.flock`, append atómico a `.state/spool.jsonl` y conteo de turnos pendientes + timestamp del último turno.
  - [x] Paso 2: Implementar `hook_entry.py` garantizando **cero imports pesados** (verificado en test con `sys.modules`):
    - Si `WIKI_MEMORIA_INTERNAL=1` → `print("{}")` y `exit(0)` inmediato.
    - En `start`/`prompt`: si es primer turno (o cada 10 turnos), inyectar `<= 600` tokens con páginas vigentes, últimas 3 actividades y alertas de *staleness*; además en Antigravity drenar `~/.wiki-memoria/internal_sessions.json` llamando a `DeleteConversation` si hay IDs pendientes.
    - En `stop`: extraer delta de transcripción, redactar secretos, escribir en `raw/sources/sessions/<harness>/`, indexar en FTS5, encolar en `.state/spool.jsonl` y, si `pending_turns >= 4`, lanzar `wiki-memoria worker --project <dir>` en modo detached (`start_new_session=True`).
  - [x] Paso 3: Escribir tests midiendo tiempo real de ejecución CLI (20 corridas), verificando `< 300 ms` p95, salida en `< 25 ms` con `WIKI_MEMORIA_INTERNAL=1` y concurrencia de 2 `Stop` simultáneos.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/test_hooks_fastpath.py -v`
  - **Resultado Esperado:** Todos los tests pasan; `fastembed` y `mcp` no aparecen en `sys.modules`; p95 `< 300 ms`.

#### Tarea 4.3: Implementar `HeadlessLlmRouter` (suscripciones, fallback cruzado y limpieza Antigravity)
* **Prioridad:** `crítica`
* **Disciplina:** Backend & Datos
* **Archivos Afectados:**
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/worker/runner.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_headless_router.py`
* **Contratos:**
  - Consume: `AppConfig.consolidation` (Tarea 1.2), `ConsolidationPlan` JSON Schema (Tarea 1.1).
  - Produce: `HeadlessLlmRouter.run_structured(prompt, schema, active_harness) -> dict` con fallback cruzado `[active, agy, codex, claude]`, entorno sanitizado (sin `*_API_KEY`, con `WIKI_MEMORIA_INTERNAL=1` y `HINDSIGHT_DISABLE_HOOKS=1`) y limpieza `DeleteConversation` / `internal_sessions.json`.
* **Instrucciones:**
  - [x] Paso 1: Implementar constructores de comando exactos verificados en Wayfinder S1/S3 (Claude con `--strict-mcp-config --mcp-config '{"mcpServers":{}}' --setting-sources "" --no-session-persistence --tools ""`; Codex con `-c features.hooks=false --ephemeral --output-schema`; Antigravity con `--model gemini-3.8-flash-low --json-schema --disable-slash-commands`).
  - [x] Paso 2: Implementar detección de fallo/rate-limit (`returncode != 0`, timeout, JSON inválido, patrones `429`/`rate limit`/`quota`/`overloaded`) y rotación automática por `fallback_order`.
  - [x] Paso 3: Implementar limpieza post-ejecución de `agy`: si `ANTIGRAVITY_LS_ADDRESS` + `ANTIGRAVITY_CSRF_TOKEN` están disponibles, invocar `DeleteConversation` vía `urllib.request`; en caso contrario, registrar `conversation_id` en `~/.wiki-memoria/internal_sessions.json`.
  - [x] Paso 4: Escribir tests con subprocesos mockeados verificando sanitización de API keys, orden de fallback exacto y cola de limpieza de Antigravity.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/test_headless_router.py -v`
  - **Resultado Esperado:** Fallback cruzado, validación JSON y sanitización de variables pasan al 100 %.

#### Tarea 4.4: Implementar `WikiConsolidator`, `FlushScheduler` y CLI principal (`wiki-memoria`)
* **Prioridad:** `crítica`
* **Disciplina:** Backend & Datos
* **Archivos Afectados:**
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/worker/consolidator.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/worker/scheduler.py`
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/cli/main.py`
  - Modificar: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/mcp/server.py` (conectar `HeadlessLlmRouter` cuando `usar_llm=true` en `memoria_reflexionar`)
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_consolidator.py`
* **Contratos:**
  - Consume: `SpoolQueue` (Tarea 4.2), `HeadlessLlmRouter` (Tarea 4.3), `MarkdownStore` (Tarea 1.3), `HybridSearcher` (Tarea 2.2), `StalenessDetector` (Tarea 2.3).
  - Produce: CLI completo `wiki-memoria` (`mcp`, `worker`, `consolidate`, `reindex`) y consolidación atómica protegida por `flock` y *watermark* `2026-11-19`.
* **Instrucciones:**
  - [x] Paso 1: Implementar `WikiConsolidator` construyendo un prompt compacto (delta de spool + títulos de páginas vigentes + últimos commits), validando la respuesta JSON con Pydantic (`ConsolidationPlan`), redactando de nuevo cualquier texto devuelto, escribiendo determinísticamente en `wiki/paginas/`, `wiki/iniciativas/` y `wiki/correcciones/` (con `verified_commit` actual y `tracks`), reconstruyendo `index.md`/`log.md` e indexando FTS5 + embeddings.
  - [x] Paso 2: Implementar `FlushScheduler` con lock no bloqueante por proyecto y reglas exactas: `pending_turns >= 4`, `idle >= 15 min` (con `pending_turns >= 1`) o `--force` manual; si todos los harnesses fallan, conservar el spool intacto para reintento posterior.
  - [x] Paso 3: Conectar subcomandos `mcp`, `worker --idle-flush`, `consolidate --workspace <path>`, `reindex --workspace <path>` en `cli/main.py` y el soporte `usar_llm=true` en `memoria_reflexionar`.
  - [x] Paso 4: Escribir tests de consolidación completa verificando que nunca se tocan archivos bajo `wiki/hindsight/` ni `backup/`, que el spool se vacía solo tras éxito y que un fallo total preserva el spool.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/test_consolidator.py -v`
  - **Resultado Esperado:** Consolidación E2E (con router mockeado) crea páginas/iniciativas/correcciones, actualiza índice/log/vectores y respeta el watermark histórico.

---

## ETAPA 05: Instalador Multi-Harness, `systemd` Timer y Corte Definitivo de Hindsight

#### Tarea 5.1: Implementar `HarnessInstaller`, `Doctor` y `systemd --user` timer (15 min idle)
* **Prioridad:** `alta`
* **Disciplina:** DevOps & Cloud
* **Archivos Afectados:**
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/harnesses/installer.py`
  - Modificar: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/src/wiki_memoria/cli/main.py` (subcomandos `install`, `uninstall`, `doctor`)
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_installer.py`
* **Contratos:**
  - Consume: `AppConfig` (Tarea 1.2), entry points `wiki-memoria` y `wiki-memoria-hook` (Tareas 4.2 y 4.4).
  - Produce: Instalador idempotente con backup previo para Claude Code (`~/.claude/settings.json`, `~/.claude.json`), Codex (`~/.codex/hooks.json`, `~/.codex/config.toml` + aviso explícito de `.hook-trust`), Antigravity (`~/.gemini/config/hooks.json` + MCP) y `systemd --user` (`wiki-memoria-flush.timer` cada 3 min).
* **Instrucciones:**
  - [x] Paso 1: Implementar `HarnessInstaller` con soporte `--dry-run`, backup automático `.bak` antes de editar cualquier config de usuario, bandera `--disable-hindsight` para retirar limpiamente los hooks/MCP de Hindsight sin romper otros hooks/servidores, y generación de `wiki-memoria-flush.{service,timer}`.
  - [x] Paso 2: Implementar `Doctor` verificando: existencia de `config.json`, permisos `0700` en `~/wiki-memoria`, estado de hooks y MCP en los 3 harnesses, `systemctl --user is-active wiki-memoria-flush.timer`, binarios `claude`/`codex`/`agy` en `PATH` y disponibilidad del modelo ONNX.
  - [x] Paso 3: Escribir tests sobre un `$HOME` temporal verificando idempotencia (`install` × 2 sin duplicados), preservación de otros MCP/hooks y reversión limpia con `uninstall`.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/test_installer.py -v`
  - **Resultado Esperado:** `install`, `uninstall` y `doctor` son 100 % idempotentes y no destruyen entradas ajenas.

#### Tarea 5.2: Re-indexado inicial de `~/wiki-memoria/` y suite de aceptación global (Criterios 1–6)
* **Prioridad:** `crítica`
* **Disciplina:** QA & Release Ops
* **Archivos Afectados:**
  - Crear: `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/tests/test_e2e_acceptance.py`
* **Contratos:**
  - Consume: Sistema completo (Etapas 01–04) y bóveda real `/home/juamtin/wiki-memoria` (solo lectura en pruebas de regresión + reindexación de `.state/index.sqlite`).
  - Produce: Índices `.state/index.sqlite` construidos para los 14 bancos existentes y reporte de aceptación automatizado.
* **Instrucciones:**
  - [x] Paso 1: Ejecutar `wiki-memoria reindex --all` sobre `~/wiki-memoria/` verificando que `backup/` y los 836 `.md` migrados permanecen con el mismo SHA-256 (0 mutaciones, 0 llamadas LLM).
  - [x] Paso 2: Escribir y ejecutar `tests/test_e2e_acceptance.py` validando: (a) latencia de hooks `< 300 ms` p95, (b) búsqueda híbrida `< 150 ms` sobre RBI real, (c) detección del caso real `RBI / Strategies/VWAP_DMI/` sin commits en `memoria_reciente`, (d) bloqueo total en `/home/juamtin/Documentos/trabajo`, (e) redacción de tokens sintéticos y (f) ejecución con `*_API_KEY` eliminadas del entorno.
* **Verificación Empírica (DoD):**
  - **Comando:** `cd /home/juamtin/Documentos/juamtin/wiki-memoria-engine && uv run pytest tests/ -v`
  - **Resultado Esperado:** 100 % de tests pasan; `memoria_reciente` sobre `RBI` reporta `Strategies/VWAP_DMI/` y búsqueda híbrida responde en `< 150 ms`.

#### Tarea 5.3: Instalación real en los 3 harnesses, smoke test en vivo y apagado de Hindsight
* **Prioridad:** `alta`
* **Disciplina:** QA & Release Ops
* **Archivos Afectados:**
  - Modificar (vía `wiki-memoria install`): `~/.claude/settings.json`, `~/.claude.json`, `~/.codex/hooks.json`, `~/.codex/config.toml`, `~/.gemini/config/hooks.json`, config MCP de Antigravity, `~/.config/systemd/user/wiki-memoria-flush.{service,timer}`
* **Contratos:**
  - Consume: Suite completa en verde (Tarea 5.2).
  - Produce: `wiki-memoria v2` operativo en producción local en Claude Code, Codex y Antigravity; Hindsight desactivado limpiamente.
* **Instrucciones:**
  - [x] Paso 1: Ejecutar `wiki-memoria install claude codex antigravity --dry-run`, revisar diffs y luego aplicar instalación real + habilitar `wiki-memoria-flush.timer`.
  - [ ] Paso 2: Ejecutar 1 sesión de prueba en Claude Code, 1 en Codex (aprobando `.hook-trust`) y 1 en Antigravity; verificar captura `< 5 s`, consolidación manual `wiki-memoria consolidate`, cero recursión y `SESSIONS_DELTA == 0` (y borrado efectivo en Antigravity).
  - [ ] Paso 3: Confirmar `wiki-memoria doctor` 100 % verde y ejecutar `wiki-memoria install --disable-hindsight` para apagar los hooks de Hindsight definitivamente.
* **Verificación Empírica (DoD):**
  - **Comando:** `/home/juamtin/Documentos/juamtin/wiki-memoria-engine/.venv/bin/wiki-memoria doctor`
  - **Resultado Esperado:** Todos los checks en `OK` (`claude`, `codex`, `antigravity`, `systemd_timer`, `sqlite_fts5`, `sqlite_vec`, `onnx_model`, `hindsight_hooks=disabled`) y `exit code 0`.

### Estado de la aceptación en vivo

- [Seguro] El reindexado inicial cubrió los 836 Markdown de los 14 bancos y del espacio global, con 15.668 vectores. Coincidieron los SHA-256 de los 836 Markdown y de los 10 archivos de respaldo antes y después de esa operación.
- [Seguro] La última suite pasó 35 pruebas. La búsqueda híbrida sobre una copia del índice real de RBI tardó 38,2 ms p95 en 20 consultas. La primera ejecución mostró `Strategies/VWAP_DMI/` sin seguimiento. Durante la aceptación RBI incorporó la estrategia en el commit `e7875a2`. La suite comprueba el commit real y reproduce la detección sin seguimiento en un repositorio temporal.
- [Seguro] Los tres clientes capturaron un turno real en el banco de prueba. Codex requirió aprobar individualmente los hooks de inicio, prompt y fin de turno.
- [Seguro] La consolidación real produjo una página, indexó siete fragmentos y vació el spool. Los procesos internos de Claude y Codex tuvieron un delta de cero sesiones persistentes.
- [Seguro] El paso 5.3.2 sigue abierto. Antigravity en modo `-p` entregó los eventos `PreInvocation` y `Stop` sin `ANTIGRAVITY_LS_ADDRESS` ni `ANTIGRAVITY_CSRF_TOKEN`. La conversación de consolidación quedó en cola. La prueba con una cola aislada de un solo ID tampoco confirmó su borrado.
- [Seguro] Se instalaron los tres clientes y el timer de usuario. El corte de Hindsight queda pendiente de cerrar 5.3.2.
