"""Construye evaluacion/casos_propios.jsonl a partir de evaluacion/casos_propios_fuente.json.

Cada caso fuente trae el mensaje y su INTERPRETACIÓN según politicas.md (operaciones y pendientes).
La respuesta esperada se calcula con el motor de reglas determinista (verificado contra los 84 casos
publicados) y luego se revisa a mano / con verificadores independientes.

    uv run python evaluacion/construir_casos_propios.py
"""

import json
from datetime import datetime
from pathlib import Path

from novapedidos.config import get_settings
from novapedidos.dominio import Catalogo, Operacion, Pendiente, construir_pedido

AQUI = Path(__file__).resolve().parent


def main() -> None:
    catalogo = Catalogo.desde_directorio(get_settings().data_dir)
    fuente = json.loads((AQUI / "casos_propios_fuente.json").read_text(encoding="utf-8"))
    salida = []
    for caso in fuente:
        i = caso["interpretacion"]
        pedido = construir_pedido(
            catalogo,
            caso["cliente_id"],
            datetime.fromisoformat(caso["fecha_hora"]),
            es_pedido=i["es_pedido"],
            pide_lo_de_siempre=i["pide_lo_de_siempre"],
            operaciones=[Operacion(texto=o["sku"], **o) for o in i["operaciones"]],
            pendientes_resolucion=[Pendiente(**p) for p in i["pendientes"]],
        )
        esperado = pedido.model_dump(mode="json", exclude={"cliente_id"})
        entrada = {k: caso[k] for k in ("cliente_id", "fecha_hora", "mensajes")}
        salida.append({"id": caso["id"], "tipo": caso["tipo"], "entrada": entrada, "esperado": esperado})
    destino = AQUI / "casos_propios.jsonl"
    destino.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in salida) + "\n", encoding="utf-8")
    print(f"{len(salida)} casos -> {destino}")


if __name__ == "__main__":
    main()
