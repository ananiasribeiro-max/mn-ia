"""Caixa de entrada genérica (redes sociais e outras integrações).

Qualquer serviço externo (ferramenta de social listening, n8n, Make, um
script do desenvolvedor) pode deixar arquivos JSON em
`dados/entrada/` com este formato:

    [
      {
        "fonte_id": "instagram_governo_pi",
        "fonte_nome": "Instagram @governodopiaui",
        "fonte_tipo": "rede",
        "titulo": "Texto ou legenda do post",
        "url": "https://instagram.com/p/...",
        "texto": "conteúdo completo (opcional)",
        "engajamento": 1520,          # opcional: curtidas+comentários+compart.
        "publicado_em": "2026-10-24T14:00:00-03:00"   # opcional
      }
    ]

O radar lê, processa e move o arquivo para `dados/entrada/processados/`.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from ..config import RAIZ
from . import ItemColetado

log = logging.getLogger("mnia.caixa_entrada")
PASTA = RAIZ / "dados" / "entrada"


def coletar() -> list[ItemColetado]:
    PASTA.mkdir(parents=True, exist_ok=True)
    feitos = PASTA / "processados"
    feitos.mkdir(exist_ok=True)
    itens: list[ItemColetado] = []
    for arq in sorted(PASTA.glob("*.json")):
        try:
            dados = json.loads(arq.read_text(encoding="utf-8"))
            for d in dados if isinstance(dados, list) else [dados]:
                pub = None
                if d.get("publicado_em"):
                    try:
                        pub = datetime.fromisoformat(d["publicado_em"])
                    except ValueError:
                        pass
                texto = d.get("texto") or ""
                if d.get("engajamento"):
                    texto = f"[engajamento: {d['engajamento']}] {texto}".strip()
                itens.append(ItemColetado(
                    fonte_id=d.get("fonte_id", "entrada"),
                    fonte_nome=d.get("fonte_nome", "Entrada externa"),
                    fonte_tipo=d.get("fonte_tipo", "rede"),
                    titulo=(d.get("titulo") or "")[:500],
                    url=d.get("url"), texto=texto or None, publicado_em=pub,
                    peso=int(d.get("peso", 2)),
                ))
            arq.rename(feitos / arq.name)
        except Exception as e:
            log.error("Arquivo de entrada inválido %s: %s", arq.name, e)
            arq.rename(arq.with_suffix(".erro"))
    return [i for i in itens if i.titulo]
