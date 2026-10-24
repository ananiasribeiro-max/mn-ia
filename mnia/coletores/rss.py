"""Coletor de feeds RSS/Atom."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import feedparser

from . import ItemColetado
from .http import baixar


def _limpar(html_txt: str | None) -> str | None:
    if not html_txt:
        return None
    txt = re.sub(r"<[^>]+>", " ", html_txt)
    return re.sub(r"\s+", " ", txt).strip()[:2000] or None


def interpretar(fonte: dict, conteudo: str) -> list[ItemColetado]:
    feed = feedparser.parse(conteudo)
    itens = []
    for e in feed.entries[:50]:
        titulo = (e.get("title") or "").strip()
        if not titulo:
            continue
        pub = None
        if e.get("published_parsed"):
            pub = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
        itens.append(ItemColetado(
            fonte_id=fonte["id"], fonte_nome=fonte["nome"], fonte_tipo=fonte["tipo"],
            titulo=titulo, url=e.get("link"),
            texto=_limpar(e.get("summary") or e.get("description")),
            publicado_em=pub, peso=int(fonte.get("peso", 1)),
        ))
    return itens


def coletar(fonte: dict) -> list[ItemColetado]:
    return interpretar(fonte, baixar(fonte["url"]))
