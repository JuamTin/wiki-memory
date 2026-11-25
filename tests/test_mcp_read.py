import asyncio

import pytest
from wiki_memoria.config import AppConfig
from wiki_memoria.indexer.fts_store import FtsStore
from wiki_memoria.markdown_store import MarkdownStore
from wiki_memoria.mcp.server import WikiMemoriaMcpServer


def test_read_tools(tmp_path):
    api = WikiMemoriaMcpServer(AppConfig(data_root=tmp_path / "vault"))
    args = {"workspace": str(tmp_path)}
    ctx = api.resolver.resolve(str(tmp_path))
    rel = MarkdownStore(ctx).write_page("ejemplo", "Ejemplo", "## Tema\nla memoria durable")
    FtsStore(ctx.directory).index_file(rel)
    names = {t.name for t in asyncio.run(api.list_tools(None, None)).tools}
    for name in names:
        with pytest.raises((PermissionError, ValueError)):
            api.dispatch(name, {"workspace": "/home/juamtin/Documentos/trabajo"})
    assert api.dispatch("memoria_proyectos", args)["proyectos"][0]["paginas"] == 1
    hit = api.dispatch("memoria_buscar", args | {"consulta": "durable"})["resultados"][0]
    assert api.dispatch("memoria_leer", args | {"archivo": hit["archivo"], "seccion": "Tema"})["contenido"] == "la memoria durable"
    assert api.dispatch("memoria_paginas", args)["paginas"][0]["frescura"] == "vigente"
    assert api.dispatch("memoria_reciente", args)["actividad"][0]["archivo"] == rel


def test_stdio_handshake(tmp_path):
    import sys
    from pathlib import Path
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    cfg = tmp_path / "config.json"
    cfg.write_text('{"embeddings":{"enabled":false}}')
    async def exchange():
        spec = StdioServerParameters(command=str(Path(sys.executable).with_name("wiki-memoria")), args=["mcp"],
                                     env={"WIKI_MEMORIA_CONFIG":str(cfg), "WIKI_MEMORIA_ROOT":str(tmp_path/"vault")})
        async with stdio_client(spec) as (reader, writer), ClientSession(reader, writer) as client:
            await client.initialize()
            assert len((await client.list_tools()).tools) == 11
            result = await client.call_tool("memoria_proyectos", {"workspace":str(tmp_path)})
            assert not result.is_error and result.structured_content["proyectos"] == []
    asyncio.run(asyncio.wait_for(exchange(), timeout=12))
