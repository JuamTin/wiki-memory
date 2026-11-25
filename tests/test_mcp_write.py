import json
from wiki_memoria.config import AppConfig
from wiki_memoria.mcp.server import WikiMemoriaMcpServer


def test_tools_and_writes(tmp_path):
    api = WikiMemoriaMcpServer(AppConfig(data_root=tmp_path / "vault"))
    assert len(api.models) == 11
    def call(name, **args):
        return api.dispatch("memoria_" + name, {"workspace": str(tmp_path), **args})
    note = call("guardar", titulo="Regla", contenido="regla vieja ghp_example")["guardado"]
    assert "ghp_example" not in json.dumps(call("leer", archivo=note))
    new = call("corregir", tema="Regla", afirmacion_anterior="regla vieja", verdad_actual="regla actual",
               evidencia="fuente", reemplaza_archivo=note)["guardado"]
    assert call("buscar", consulta="regla")["resultados"][0]["archivo"] == new
    first = call("iniciativa", titulo="Motor", resumen="regla", estado="activa")
    assert call("iniciativa", titulo="Motor", resumen="regla", estado="pausada") == first
    assert call("reflexionar", pregunta="regla")["evidencia"]
    assert call("estado")["chunks"] > 0
    assert call("diagnosticar")["checks"]["sqlite_fts5"]
