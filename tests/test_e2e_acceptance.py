"""Pruebas de aceptación. La prueba RBI usa una copia del índice de la bóveda."""
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from time import perf_counter, sleep

import pytest

from wiki_memoria.config import AppConfig
from wiki_memoria.indexer.fts_store import FtsStore
from wiki_memoria.mcp.server import WikiMemoriaMcpServer


@pytest.fixture(autouse=True)
def subscription_environment(monkeypatch):
    for key in tuple(os.environ):
        if key.endswith("_API_KEY") or key == "HINDSIGHT_API_TOKEN":
            monkeypatch.delenv(key)


def test_real_rbi(tmp_path):
    source = Path.home() / "wiki-memoria"
    workspace = Path.home() / "Documentos/juamtin/RBI"
    if not workspace.is_dir() or not (source / "manifest.json").exists():
        pytest.skip("La aceptación de RBI requiere la bóveda migrada y su checkout local")
    manifest = (source / "manifest.json").read_text()
    root = tmp_path / "vault"
    root.mkdir()
    (root / "manifest.json").write_text(manifest)
    bank = next(b for b in json.loads(manifest)["banks"] if b["bank_id"] == "coding-agent::RBI")
    for relative in [bank["path"], "global"]:
        index = Path(relative) / ".state/index.sqlite"
        (root/index).parent.mkdir(parents=True)
        with closing(sqlite3.connect(f"file:{source/index}?mode=ro", uri=True)) as real, closing(sqlite3.connect(root/index)) as dest:
            real.backup(dest)
        commits = Path(relative) / "raw/sources/git/commits.md"
        if (source / commits).is_file():
            (root / commits).parent.mkdir(parents=True)
            (root / commits).write_bytes((source / commits).read_bytes())
    from wiki_memoria.indexer.hybrid_search import load_vector_extension
    server = WikiMemoriaMcpServer(AppConfig(data_root=root))
    server.embedder.wait()
    args = {"workspace":str(workspace)}
    search = args | {"consulta":"estrategia de régimen"}
    server.dispatch("memoria_buscar", search)
    # A live bank may contain fresh lexical-only Stop captures. Warm the copy through MCP.
    deadline = perf_counter() + 120
    store = FtsStore(root / bank["path"])
    while True:
        with store.connection() as db:
            load_vector_extension(db)
            chunks = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
            vectors = db.execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
        if chunks == vectors and chunks > 0:
            break
        assert perf_counter() < deadline, (chunks, vectors)
        sleep(.1)
    durations = []
    for _ in range(20):
        start = perf_counter()
        assert server.dispatch("memoria_buscar", search)["resultados"]
        durations.append(perf_counter() - start)
    latency = sorted(durations)[18]
    print(f"RBI búsqueda híbrida p95 {latency * 1000:.1f} ms")
    assert latency < .15
    # RBI is a live checkout. The strategy originally appeared as untracked and
    # subsequently landed in Git. Assert the evidence supplied by its current state.
    activity = server.dispatch("memoria_reciente", args | {"limite":200, "dias":365})["actividad"]
    status = subprocess.check_output(["git", "-C", workspace, "status", "--porcelain", "--", "Strategies/VWAP_DMI"])
    if status:
        assert any(row["tipo"] == "sin_commit" and "Strategies/VWAP_DMI" in row["archivo"] for row in activity)
    else:
        assert any(row["tipo"] == "git" and "Strategies/VWAP_DMI/" in row["resumen"] for row in activity)
    assert server.dispatch("memoria_paginas", args)["paginas"]


@pytest.mark.parametrize("harness", ["claude", "codex", "antigravity"])
def test_capture(tmp_path, harness):
    root = tmp_path / "vault"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"data_root":str(root), "consolidation":{"turn_threshold":1000}}))
    env = os.environ | {"WIKI_MEMORIA_CONFIG":str(config), "WIKI_MEMORIA_ROOT":str(root), "WIKI_MEMORIA_INTERNAL":"0"}
    secret = "sk-synthetic-secret"
    path = tmp_path / "transcript.jsonl"
    content = "capturado " + secret
    rows = {"claude":{"type":"user","message":{"content":content}},
            "codex":{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":content}]}},
            "antigravity":{"type":"USER_INPUT","content":content}}
    path.write_text(json.dumps(rows[harness]) + "\n")
    payload = ({"workspacePaths":[str(tmp_path)], "conversationId":"test", "transcriptPath":str(path)} if harness=="antigravity"
               else {"cwd":str(tmp_path),"session_id":"test","transcript_path":str(path)})
    command = [Path(sys.executable).with_name("wiki-memoria-hook"), "--harness", harness, "--event"]
    for event in ("start", "prompt", "stop"):
        times = []
        for _ in range(20):
            start = perf_counter()
            result = subprocess.run(command+[event], input=json.dumps(payload), text=True, env=env, capture_output=True,check=True)
            times.append(perf_counter()-start)
            assert isinstance(json.loads(result.stdout), dict)
        assert sorted(times)[18] < .3
    bank, = (root/"proyectos").iterdir()
    assert FtsStore(bank).search_fts("capturado")
    assert not any(secret.encode() in f.read_bytes() for f in root.rglob("*") if f.is_file())
    server = WikiMemoriaMcpServer(AppConfig(data_root=root))
    with pytest.raises(PermissionError):
        server.dispatch("memoria_reciente", {"workspace":"/home/juamtin/Documentos/trabajo/sub"})

def test_untracked_strategy_in_timeline(tmp_path):
    workspace = tmp_path / "RBI"
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    strategies = workspace / "Strategies"
    strategies.mkdir()
    (strategies / "README.md").touch()
    subprocess.run(["git", "-C", workspace, "add", "Strategies/README.md"], check=True)
    (strategies / "VWAP_DMI").mkdir()
    (strategies / "VWAP_DMI/strategy.py").touch()
    server = WikiMemoriaMcpServer(AppConfig(data_root=tmp_path / "vault"))
    rows = server.dispatch("memoria_reciente", {"workspace":str(workspace)})["actividad"]
    assert any(r["tipo"] == "sin_commit" and r["archivo"] == "Strategies/VWAP_DMI/" for r in rows)
