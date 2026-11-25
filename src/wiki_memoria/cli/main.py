import argparse
import asyncio
import json
import os
from pathlib import Path

from ..config import AppConfig, ConfigLoader
from ..files import safe_path
from ..indexer.embedder import LocalEmbedder
from ..indexer.fts_store import FtsStore
from ..indexer.hybrid_search import HybridSearcher
from ..project_resolver import ProjectResolver, bank_directory
from ..worker.consolidator import WikiConsolidator
from ..worker.runner import HeadlessLlmRouter
from ..worker.scheduler import FlushScheduler
from ..worker.spool import SpoolQueue


def registered(config: AppConfig) -> list[Path]:
    path = safe_path(config.data_root, "manifest.json")
    banks = json.loads(path.read_text())["banks"] if path.exists() else []
    return [bank_directory(config.data_root, b["path"]) for b in banks] + [safe_path(config.data_root, "global")]


def reindex(directory: Path, embedder: LocalEmbedder) -> dict:
    store = FtsStore(directory)
    files = set()
    for rel in ("purpose.md", "schema.md"):
        if safe_path(directory, rel).is_file():
            store.index_file(rel)
            files.add(rel)
    for sub in ["wiki", "raw/sources"]:
        for path in sorted(safe_path(directory, sub).rglob("*.md")):
            rel = path.relative_to(directory).as_posix()
            store.index_file(rel)
            files.add(rel)
    with store.connection() as db:
        indexed = {r[0] for r in db.execute("SELECT rel_path FROM documents")}
        db.executemany("DELETE FROM documents WHERE rel_path=?", ((p,) for p in indexed - files))
    embedder.wait()
    vectors = HybridSearcher(store, embedder).index_missing()
    return {"banco": directory.name, "archivos": len(files), "vectores_nuevos": vectors}


def main() -> None:
    parser = argparse.ArgumentParser(prog="wiki-memoria")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("mcp")
    worker = sub.add_parser("worker").add_mutually_exclusive_group(required=True)
    worker.add_argument("--project", type=Path)
    worker.add_argument("--idle-flush", action="store_true")
    sub.add_parser("consolidate").add_argument("--workspace", default=os.getcwd())
    index = sub.add_parser("reindex").add_mutually_exclusive_group(required=True)
    index.add_argument("--workspace")
    index.add_argument("--all", action="store_true")
    for name in ("install", "uninstall"):
        command = sub.add_parser(name)
        command.add_argument("harnesses", nargs="*")
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--disable-hindsight", action="store_true")
    sub.add_parser("doctor")
    args = parser.parse_args()
    config = ConfigLoader.load()
    if args.cmd in {"install", "uninstall", "doctor"}:
        from ..harnesses.installer import Doctor, HarnessInstaller
        if args.cmd == "doctor":
            checks = Doctor(config).report()
            print(json.dumps(checks, indent=2))
            raise SystemExit(0 if all(checks.values()) else 1)
        harnesses = args.harnesses or list(HarnessInstaller.paths)
        if set(harnesses) - HarnessInstaller.paths.keys():
            parser.error("Harness no reconocido")
        for line in HarnessInstaller(config).apply(harnesses, dry_run=args.dry_run, uninstall=args.cmd == "uninstall",
                                                   disable_hindsight=args.disable_hindsight):
            print(line)
        return
    resolver = ProjectResolver(config)
    embedder = LocalEmbedder(config.embeddings)
    if args.cmd == "mcp":
        from ..mcp.server import WikiMemoriaMcpServer
        asyncio.run(WikiMemoriaMcpServer(config).run())
        return
    if args.cmd == "reindex":
        directories = registered(config) if args.all else [resolver.resolve(args.workspace).directory]
        for directory in directories:
            print(json.dumps(reindex(directory, embedder)), flush=True)
        return
    scheduler = FlushScheduler(config, WikiConsolidator(config, HeadlessLlmRouter(config.consolidation), embedder))
    if args.cmd == "consolidate":
        print(json.dumps({"consolidado": scheduler.run(resolver.resolve(args.workspace), force=True)}))
        return
    projects = (safe_path(config.data_root, "proyectos").glob("*") if args.idle_flush else [args.project])
    errors = []
    for directory in projects:
        relative = directory.absolute().relative_to(config.data_root).as_posix()
        bank_directory(config.data_root, relative)
        if not safe_path(directory, ".state/spool.jsonl").exists():
            continue
        entries = SpoolQueue(directory).snapshot()
        if entries:
            try:
                project = resolver.resolve(entries[-1]["workspace"])
                if project.directory != directory:
                    raise ValueError("El banco no corresponde al workspace")
                scheduler.run(project)
            except (ValueError, OSError, RuntimeError) as exc:
                if not args.idle_flush:
                    raise
                errors.append(f"{directory.name}: {exc}")
    if errors:
        raise SystemExit("\n".join(errors))
