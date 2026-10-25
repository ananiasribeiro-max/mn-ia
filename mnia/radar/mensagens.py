"""Formatação das mensagens do radar para o Telegram (HTML)."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..config import config
from ..db import Item
from ..telegram import esc

ICONE_RISCO = {"verde": "🟢", "amarelo": "🟡", "vermelho": "🔴"}
ICONE_PRIO = {"urgente": "🚨", "pauta": "📌", "acompanhar": "👀", "descartar": "·"}
NOME_PLAT = {"tv": "TV", "radio": "Rádio", "portal": "Portal", "redes": "Redes"}


def hora_local(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(config().fuso)).strftime("%H:%M")


def situacao_concorrencia(item: Item) -> str:
    extra = item.analise_extra or {}
    sit = extra.get("concorrencia")
    if sit == "mn_nao_deu":
        outros = ", ".join(extra.get("veiculos", [])[:3])
        return f"⚔️ <b>Concorrência já deu</b> ({esc(outros)}) — MN ainda não"
    if sit == "mn_deu_primeiro":
        return "🏁 <b>MN deu primeiro</b>"
    if sit == "mn_ja_deu":
        return "✔️ MN já deu"
    return ""


NOME_UF = {"PI": "Piauí", "MA": "Maranhão", "CE": "Ceará", "PA": "Pará", "AM": "Amazonas", "AC": "Acre",
           "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo", "DF": "Distrito Federal"}


def lugar(item: Item) -> str:
    """Cidade e estado por extenso (ex.: "São Luís, Maranhão"); "Brasil" no nacional sem lugar."""
    extra = item.analise_extra or {}
    abr, local, uf = extra.get("abrangencia"), (extra.get("local") or "").strip(), extra.get("uf_fonte", "")
    if abr == "internacional":
        return local or "Internacional"
    cidade, estado = "", ""
    if local:
        partes = [p.strip() for p in local.replace(" - ", "-").replace(",", "-").split("-") if p.strip()]
        if partes and partes[-1].upper() in NOME_UF or (partes and partes[-1] in NOME_UF.values()):
            estado = NOME_UF.get(partes[-1].upper(), partes[-1])
            cidade = "-".join(partes[:-1])
        elif partes:
            cidade = local
    if not estado and abr != "nacional":
        estado = NOME_UF.get(uf, "") if uf and uf != "BR" else ""
    if cidade and estado and cidade != estado:
        return f"{cidade}, {estado}"
    return estado or cidade or ("Brasil" if abr == "nacional" or uf == "BR" else "")


def linha_local(item: Item) -> str:
    texto = lugar(item)
    if not texto:
        return ""
    liga = " · 🔗 ligação com o Piauí" if (item.analise_extra or {}).get("liga_piaui") \
        and (item.analise_extra or {}).get("abrangencia") != "piaui" else ""
    return f"📍 {esc(texto)}{liga}"


def bloco_item(item: Item, detalhado: bool = True) -> str:
    plats = " · ".join(NOME_PLAT.get(p, p) for p in (item.plataformas or []))
    linhas = [
        f"{ICONE_PRIO.get(item.prioridade, '')} {ICONE_RISCO.get(item.risco, '')} "
        f"<b>{esc(item.resumo or item.titulo)}</b>",
    ]
    loc = linha_local(item)
    if loc:
        linhas.append(loc)
    if detalhado and item.porque_importa:
        linhas.append(f"↳ {esc(item.porque_importa)}")
    meta = f"{esc(item.fonte_nome)} · relevância {item.relevancia}/10"
    if item.editoria:
        meta += f" · {esc(item.editoria)}"
    if plats:
        meta += f" · indicado: {plats}"
    linhas.append(f"<i>{meta}</i>")
    conc = situacao_concorrencia(item)
    if conc:
        linhas.append(conc)
    if item.risco == "vermelho":
        linhas.append("⛔ <b>Não usar sem confirmação de fonte primária</b>")
    elif item.risco == "amarelo":
        linhas.append("⚠️ Checar antes de usar")
    if item.url:
        linhas.append(f'<a href="{esc(item.url)}">abrir</a>')
    return "\n".join(linhas)


def msg_urgente(item: Item) -> str:
    return "🚨 <b>RADAR MN — URGENTE</b>\n\n" + bloco_item(item)


def msg_topico(item: Item) -> str:
    nome = {"pauta": "PAUTA", "acompanhar": "ACOMPANHAR"}.get(item.prioridade, "RADAR")
    return f"📡 <b>RADAR MN · {nome}</b>\n\n" + bloco_item(item)


def msg_resumo(itens: list[Item], inicio: datetime, fim: datetime) -> str:
    cab = f"📡 <b>RADAR MN — {hora_local(inicio)} às {hora_local(fim)}</b>"
    if not itens:
        return cab + "\n\nNada relevante novo no período."
    pautas = [i for i in itens if i.prioridade == "pauta"]
    acomp = [i for i in itens if i.prioridade == "acompanhar"]
    partes = [cab]
    if pautas:
        partes.append(f"<b>📌 PAUTA ({len(pautas)})</b>")
        partes += [bloco_item(i) for i in pautas]
    if acomp:
        partes.append(f"<b>👀 ACOMPANHAR ({len(acomp)})</b>")
        partes += [bloco_item(i, detalhado=False) for i in acomp[:10]]
        if len(acomp) > 10:
            partes.append(f"<i>+ {len(acomp) - 10} itens no painel</i>")
    nao_deu = [i for i in itens if (i.analise_extra or {}).get("concorrencia") == "mn_nao_deu"]
    if nao_deu:
        partes.append(f"⚔️ <b>{len(nao_deu)} assunto(s) que a concorrência deu e o MN ainda não.</b>")
    return "\n\n".join(partes)
