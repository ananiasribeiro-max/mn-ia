"""Coletores: um por tipo de fonte. Todos devolvem lista de ItemColetado."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger("mnia.coletores")


@dataclass
class ItemColetado:
    fonte_id: str
    fonte_nome: str
    fonte_tipo: str
    titulo: str
    url: str | None = None
    texto: str | None = None
    publicado_em: datetime | None = None
    peso: int = 1


def coletar_fonte(fonte: dict) -> list[ItemColetado]:
    from . import html_home, rss
    formato = fonte.get("formato", "rss")
    if formato == "rss":
        return rss.coletar(fonte)
    if formato == "html":
        return html_home.coletar(fonte)
    log.warning("Formato desconhecido na fonte %s: %s", fonte.get("id"), formato)
    return []
