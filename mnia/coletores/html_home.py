"""Coletor de manchetes a partir da página inicial de um site.

Funciona na maioria dos portais sem configuração: pega links do próprio
domínio cujo texto tem cara de manchete. Para um site específico, dá para
informar `seletor` (CSS) no fontes.yaml.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import ItemColetado
from .http import baixar

MIN_CARAC, MAX_CARAC = 35, 220
IGNORAR = re.compile(
    r"(assine|login|entrar|cadastre|politica de privacidade|termos de uso|fale conosco|"
    r"anuncie|expediente|trabalhe conosco|newsletter|whatsapp|baixe o app)", re.I)
URL_IGNORAR = re.compile(r"(/tag/|/autor/|/author/|/categoria/|/category/|/page/|#|javascript:|mailto:)", re.I)


def _dominio(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def interpretar(fonte: dict, conteudo: str) -> list[ItemColetado]:
    sopa = BeautifulSoup(conteudo, "html.parser")
    base = fonte["url"]
    dominio = _dominio(base)
    candidatos = sopa.select(fonte["seletor"]) if fonte.get("seletor") else sopa.find_all("a", href=True)

    vistos, itens = set(), []
    for a in candidatos:
        if a.name != "a":
            a = a.find("a", href=True) or a
        href = a.get("href")
        if not href:
            continue
        url = urljoin(base, href)
        if _dominio(url) != dominio or URL_IGNORAR.search(url):
            continue
        titulo = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        if not (MIN_CARAC <= len(titulo) <= MAX_CARAC) or IGNORAR.search(titulo):
            continue
        if url in vistos:
            continue
        vistos.add(url)
        itens.append(ItemColetado(
            fonte_id=fonte["id"], fonte_nome=fonte["nome"], fonte_tipo=fonte["tipo"],
            titulo=titulo, url=url, peso=int(fonte.get("peso", 1)), uf=fonte.get("uf", ""),
        ))
        if len(itens) >= 40:
            break
    return itens


def coletar(fonte: dict) -> list[ItemColetado]:
    return interpretar(fonte, baixar(fonte["url"]))
