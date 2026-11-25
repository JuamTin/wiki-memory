import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter

from wiki_memoria.indexer.fts_store import FtsStore


def test_fastpath_and_concurrency(tmp_path):
    path = tmp_path / "transcript.jsonl"
    path.write_text(json.dumps({"type":"user","message":{"content":"secreto ghp_abcdef"}}) + "\n")
    env = os.environ | {"WIKI_MEMORIA_CONFIG":str(tmp_path/"config"), "WIKI_MEMORIA_ROOT":str(tmp_path/"vault")}
    payload = json.dumps(dict(cwd=str(tmp_path), session_id="one", transcript_path=str(path)))
    binary = Path(sys.executable).with_name("wiki-memoria-hook")
    def run(event, internal=False):
        start = perf_counter()
        result = subprocess.run([binary, "--harness", "claude", "--event", event], input=payload,
                                text=True, env=env | {"WIKI_MEMORIA_INTERNAL":str(int(internal))}, capture_output=True, check=True)
        assert isinstance(json.loads(result.stdout), dict)
        return perf_counter() - start
    assert sorted(run("prompt") for _ in range(20))[18] < .3
    assert sorted(run("start", True) for _ in range(20))[18] < .025
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(run, ["stop", "stop"]))
    root, = (tmp_path/"vault/proyectos").iterdir()
    assert FtsStore(root).cursor("claude","one")["turn_count"] == 1
    assert len((root/".state/spool.jsonl").read_text().splitlines()) == 1
    assert all(b"ghp_abcdef" not in p.read_bytes() for p in root.rglob("*") if p.is_file())
    code = """import sys
from wiki_memoria.cli.hooks import HookService
HookService().handle("claude","prompt",__import__("json").loads(sys.argv[1]))
assert not set(sys.modules).intersection({"fastembed","onnxruntime","sqlite_vec","mcp","pydantic","yaml"})
"""
    subprocess.run([sys.executable, "-c", code, payload], check=True, env=env)
