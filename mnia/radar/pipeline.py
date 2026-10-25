"""Radar de notícias em tempo real.

Ciclo (a cada MNIA_RADAR_INTERVALO_MIN minutos):
  1. coleta todas as fontes ativas + caixa de entrada (redes)
  2. grava só o que é novo (deduplicação por hash)
  3. classifica com o Claude em lotes
  4. compara com a concorrência por assunto
  5. alerta urgentes na hora
Resumo de hora em hora: pautas e itens a acompanhar.
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..config import config, fontes
from ..coletores import ItemColetado, caixa_entrada, coletar_fonte
from ..db import Execucao, Item, agora, gerar_hash, item_existe, sessao
from ..telegram import alerta_tecnico, enviar
from . import mensagens
from ..llm import ErroLLM
from .classificador import classificar, normalizar_analise

log = logging.getLogger("mnia.radar")
LOTE = 10


def _utc_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ------------------------------------------------------------------ 1-2 coleta

def gravar_itens(coletados: list[ItemColetado], origem: str) -> int:
    novos = 0
    with sessao() as s:
        for c in coletados:
            h = gerar_hash(c.fonte_id, c.titulo, c.url)
            if item_existe(s, h):
                continue
            s.add(Item(
                hash=h, origem=origem, fonte_id=c.fonte_id, fonte_nome=c.fonte_nome,
                fonte_tipo=c.fonte_tipo, url=c.url, titulo=c.titulo, texto=c.texto,
                publicado_em=_utc_naive(c.publicado_em),
                analise_extra={"peso": c.peso},
            ))
            s.flush()
            novos += 1
    return novos


def coletar_tudo(lista_fontes: list[dict] | None = None) -> tuple[list[ItemColetado], list[str]]:
    coletados, erros = [], []
    for f in lista_fontes if lista_fontes is not None else fontes():
        try:
            coletados += coletar_fonte(f)
        except Exception as e:
            erros.append(f"{f.get('id')}: {type(e).__name__}: {e}")
            log.warning("Fonte %s falhou: %s", f.get("id"), e)
    try:
        coletados += caixa_entrada.coletar()
    except Exception as e:
        erros.append(f"caixa_entrada: {e}")
    return coletados, erros


# ------------------------------------------------------------------ 3 análise

def assuntos_recentes(horas: int = 24, limite: int = 80) -> list[str]:
    corte = agora() - timedelta(hours=horas)
    with sessao() as s:
        linhas = s.execute(
            select(Item.assunto_chave).where(Item.coletado_em >= corte, Item.assunto_chave.is_not(None),
                                             Item.relevancia >= 4)
            .order_by(Item.coletado_em.desc()).limit(limite * 3)
        ).scalars().all()
    vistos: list[str] = []
    for a in linhas:
        if a not in vistos:
            vistos.append(a)
    return vistos[:limite]


def analisar_pendentes(origem: str = "radar", limite: int | None = None) -> int:
    limite = limite or config().max_itens_por_rodada
    with sessao() as s:
        pendentes = s.execute(
            select(Item).where(Item.origem == origem, Item.analisado.is_(False))
            .order_by(Item.coletado_em.desc()).limit(limite)
        ).scalars().all()
        dados = [{"id": i.id, "titulo": i.titulo, "texto": (i.texto or "")[:800],
                  "fonte": i.fonte_nome, "tipo_fonte": i.fonte_tipo,
                  "peso": (i.analise_extra or {}).get("peso", 1)} for i in pendentes]

    total = 0
    fila = [dados[i:i + LOTE] for i in range(0, len(dados), LOTE)]
    while fila:
        lote = fila.pop(0)
        try:
            analises = classificar(lote, assuntos_recentes(), modulo=origem)
        except ErroLLM as e:
            # Um lote problemático não derruba a rodada: divide em dois e tenta de novo;
            # um item isolado que ainda falha fica para a próxima rodada.
            if len(lote) > 1:
                meio = len(lote) // 2
                fila[:0] = [lote[:meio], lote[meio:]]
                log.warning("Lote de %d itens falhou; dividindo. (%s)", len(lote), e)
            else:
                log.warning("Item %s não analisado nesta rodada: %s", lote[0]["id"], e)
            continue
        por_id = {int(a["id"]): normalizar_analise(a) for a in analises if str(a.get("id")).isdigit()}
        with sessao() as s:
            for d in lote:
                item = s.get(Item, d["id"])
                a = por_id.get(d["id"])
                if a is None:
                    continue  # IA não devolveu: tenta na próxima rodada
                for campo, valor in a.items():
                    setattr(item, campo, valor)
                item.analisado = True
                total += 1
    # Itens que sobraram além do limite e são antigos (>6h) viram descartados para não acumular
    corte = agora() - timedelta(hours=6)
    with sessao() as s:
        velhos = s.execute(select(Item).where(Item.origem == origem, Item.analisado.is_(False),
                                              Item.coletado_em < corte)).scalars().all()
        for v in velhos:
            v.analisado, v.prioridade, v.relevancia = True, "descartar", 0
    return total


# ------------------------------------------------------------------ 4 concorrência

def marcar_concorrencia(horas: int = 24) -> None:
    corte = agora() - timedelta(hours=horas)
    with sessao() as s:
        itens = s.execute(select(Item).where(
            Item.coletado_em >= corte, Item.assunto_chave.is_not(None), Item.analisado.is_(True)
        )).scalars().all()
        grupos: dict[str, list[Item]] = {}
        for i in itens:
            grupos.setdefault(i.assunto_chave, []).append(i)
        for grupo in grupos.values():
            proprios = [i for i in grupo if i.fonte_tipo == "proprio"]
            concorr = [i for i in grupo if i.fonte_tipo == "concorrente"]
            if not concorr and not proprios:
                continue
            if concorr and not proprios:
                sit = "mn_nao_deu"
            elif proprios and concorr and min(p.coletado_em for p in proprios) < min(c.coletado_em for c in concorr):
                sit = "mn_deu_primeiro"
            elif proprios:
                sit = "mn_ja_deu"
            else:
                continue
            veiculos = sorted({c.fonte_nome for c in concorr})
            for i in grupo:
                extra = dict(i.analise_extra or {})
                extra.update({"concorrencia": sit, "veiculos": veiculos})
                i.analise_extra = extra


# ------------------------------------------------------------------ 5 alertas

def _ja_alertado_assunto(s, chave: str | None, horas: int = 12) -> bool:
    if not chave:
        return False
    corte = agora() - timedelta(hours=horas)
    return s.scalar(select(Item.id).where(Item.assunto_chave == chave, Item.alertado.is_(True),
                                          Item.coletado_em >= corte).limit(1)) is not None


def alertar_urgentes() -> int:
    cfg = config()
    fila: list[tuple[int, str]] = []
    with sessao() as s:
        urgentes = s.execute(select(Item).where(
            Item.origem == "radar", Item.prioridade == "urgente", Item.alertado.is_(False),
            Item.fonte_tipo != "proprio",
        ).order_by(Item.relevancia.desc())).scalars().all()
        for item in urgentes:
            if _ja_alertado_assunto(s, item.assunto_chave):
                item.alertado = True   # mesmo fato já avisado: não repete
                continue
            fila.append((item.id, mensagens.msg_urgente(item)))
            item.alertado = True
            s.flush()
    # envio fora da transação (não segura o banco enquanto fala com o Telegram)
    for item_id, texto in fila:
        enviar(cfg.chat_radar, texto, tipo="urgente", item_id=item_id)
    return len(fila)


def enviar_resumo(minutos: int = 60) -> int:
    cfg = config()
    fim = agora()
    inicio = fim - timedelta(minutes=minutos)
    with sessao() as s:
        itens = s.execute(select(Item).where(
            Item.origem == "radar", Item.analisado.is_(True), Item.alertado.is_(False),
            Item.prioridade.in_(["pauta", "acompanhar"]), Item.fonte_tipo != "proprio",
            Item.relevancia >= cfg.relevancia_minima_alerta - 2,
        ).order_by(Item.relevancia.desc())).scalars().all()
        # um item por assunto (o de maior relevância)
        escolhidos, chaves = [], set()
        for i in itens:
            if i.assunto_chave and (i.assunto_chave in chaves or _ja_alertado_assunto(s, i.assunto_chave)):
                i.alertado = True
                continue
            chaves.add(i.assunto_chave)
            escolhidos.append(i)
        if not escolhidos:
            return 0
        texto = mensagens.msg_resumo(escolhidos, inicio, fim)
        for i in escolhidos:
            i.alertado = True
    enviar(cfg.chat_radar, texto, tipo="resumo_hora")
    return len(escolhidos)


# ------------------------------------------------------------------ orquestração

def _primeira_rodada() -> bool:
    with sessao() as s:
        return s.scalar(select(Execucao.id).where(Execucao.modulo == "radar",
                                                  Execucao.sucesso.is_(True)).limit(1)) is None


def rodar_radar(lista_fontes: list[dict] | None = None) -> Execucao:
    """Uma rodada completa. Na primeira rodada forma a linha de base sem alertar."""
    linha_de_base = _primeira_rodada()
    with sessao() as s:
        exe = Execucao(modulo="radar")
        s.add(exe)
        s.flush()
        exe_id = exe.id
    erros: list[str] = []
    novos = analisados = alertas = 0
    sucesso = True
    try:
        coletados, erros = coletar_tudo(lista_fontes)
        novos = gravar_itens(coletados, "radar")
        analisados = analisar_pendentes("radar")
        marcar_concorrencia()
        if linha_de_base:
            with sessao() as s:
                for i in s.execute(select(Item).where(Item.origem == "radar")).scalars():
                    i.alertado = True
            log.info("Primeira rodada: linha de base formada (%d itens), sem alertas.", novos)
            # relatório de fontes no grupo técnico (substitui o `testar-fontes` quando não há terminal)
            from ..telegram import enviar as _enviar, esc as _esc
            falhas = "\n".join(f"❌ {_esc(e[:120])}" for e in erros[:15]) or "Todas as fontes responderam."
            _enviar(config().chat_tecnico,
                    f"📡 <b>Radar: linha de base formada</b>\n{novos} manchetes registradas.\n"
                    f"Fontes com falha: {len(erros)}\n{falhas}", tipo="tecnico")
        else:
            alertas = alertar_urgentes()
    except Exception as e:
        sucesso = False
        erros.append(traceback.format_exc(limit=3))
        alerta_tecnico("radar", f"{type(e).__name__}: {e}")
        log.exception("Radar falhou")
    with sessao() as s:
        exe = s.get(Execucao, exe_id)
        exe.fim, exe.itens_novos, exe.itens_analisados = agora(), novos, analisados
        exe.alertas, exe.erros, exe.sucesso = alertas, erros or None, sucesso
    # Muitas fontes falhando = problema técnico
    if lista_fontes is None and len(erros) > max(3, len(fontes()) // 2):
        alerta_tecnico("radar", f"{len(erros)} fontes falharam:\n" + "\n".join(erros[:8]))
    log.info("Radar: %d novos, %d analisados, %d alertas, %d erros", novos, analisados, alertas, len(erros))
    return exe
