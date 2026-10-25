"""Rodada do canal: vídeo novo → transcrição → matéria + títulos + post → cortes verticais.

Cada vídeo vira um Item (origem="youtube"). Estado em analise_extra:
  processado (bool), tentativas (int), ultimo_erro (str), materias (int), cortes (int)
"""
from __future__ import annotations

import logging
from datetime import timedelta, timezone

from sqlalchemy import select

from ..config import config
from ..db import Execucao, Item, agora, gerar_hash, item_existe, sessao
from ..digital import materia as dig
from ..llm import ErroLLM
from ..telegram import alerta_tecnico, enviar, enviar_video, esc
from ..video import cortes as vc
from . import canal, legendas

log = logging.getLogger("mnia.youtube")
MAX_TENTATIVAS = 8          # legenda automática pode levar horas para sair
_bloqueio_avisado = {"feito": False}


def _utc_naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt and dt.tzinfo else dt


def registrar_novos(videos: list[canal.Video]) -> int:
    """Grava vídeos novos. Na primeira vez, só o mais recente fica pendente (linha de base)."""
    with sessao() as s:
        primeira = s.scalar(select(Item.id).where(Item.origem == "youtube").limit(1)) is None
        novos = 0
        # a lista já vem dos mais novos para os mais antigos; com datas, reordena por elas
        if all(v.publicado_em for v in videos):
            videos = sorted(videos, key=lambda v: v.publicado_em, reverse=True)
        for pos, v in enumerate(videos):
            h = gerar_hash("youtube", v.video_id, v.url)
            if item_existe(s, h):
                continue
            pendente = (not primeira) or pos == 0
            s.add(Item(hash=h, origem="youtube", fonte_id="youtube", fonte_nome="Meio Norte+ (YouTube)",
                       fonte_tipo="proprio", url=v.url, titulo=v.titulo, texto=v.descricao,
                       publicado_em=_utc_naive(v.publicado_em) or agora(), analisado=not pendente,
                       analise_extra={"video_id": v.video_id, "processado": not pendente, "tentativas": 0}))
            novos += 1
    return novos


def pendentes(limite: int) -> list[int]:
    with sessao() as s:
        itens = s.execute(select(Item).where(Item.origem == "youtube", Item.analisado.is_(False))
                          .order_by(Item.publicado_em.desc())).scalars().all()
        return [i.id for i in itens if (i.analise_extra or {}).get("tentativas", 0) < MAX_TENTATIVAS][:limite]


def _marcar(item_id: int, **campos) -> None:
    with sessao() as s:
        item = s.get(Item, item_id)
        extra = dict(item.analise_extra or {})
        extra.update({k: v for k, v in campos.items() if k != "analisado"})
        item.analise_extra = extra
        if "analisado" in campos:
            item.analisado = campos["analisado"]


def _enviar_cortes(item_id: int, vid: str, url: str, titulo: str, cortes: list, trechos) -> tuple[int, list]:
    cfg = config()
    feitos, falhas = 0, []
    for n, c in enumerate(cortes, 1):
        try:
            arq = vc.gerar_corte(vid, url, c, trechos, n)
            leg = (f"🎬 <b>CORTE {n}</b> — {esc(c.get('titulo', ''))}\n"
                   f"{esc(c.get('inicio', ''))}–{esc(c.get('fim', ''))} de <a href=\"{esc(url)}\">{esc(titulo)}</a>\n\n"
                   f"<b>Legenda sugerida:</b> {esc(c.get('legenda', ''))}\n"
                   f"<i>Por que: {esc(c.get('motivo', ''))}</i>\n"
                   f"<i>1080x1920 (9:16), pronto para Reels e Shorts. Aprovar antes de publicar.</i>")
            enviar_video(cfg.chat_cortes, arq, leg, item_id=item_id,
                         duracao=vc.duracao(arq), capa=vc.gerar_capa(arq))
            feitos += 1
        except Exception as e:
            falhas.append(f"corte {n}: {type(e).__name__}: {str(e)[:200]}")
            log.warning("Corte %s de %s falhou: %s", n, vid, e)
    return feitos, falhas


def refazer_cortes(item_id: int) -> dict:
    """Gera e envia de novo só os cortes de um vídeo já processado."""
    with sessao() as s:
        it = s.get(Item, item_id)
        vid, url, titulo, descricao = it.analise_extra["video_id"], it.url, it.titulo, it.texto or ""
        cortes = (it.analise_extra or {}).get("cortes_def")
    trechos, info = legendas.obter(url)
    if not cortes:
        duracao = float(info.get("duration") or trechos[-1].fim)
        cortes = dig.gerar(titulo, descricao, legendas.transcricao_compacta(trechos), duracao).get("cortes", [])
    feitos, falhas = _enviar_cortes(item_id, vid, url, titulo, cortes, trechos)
    _marcar(item_id, cortes=feitos, cortes_def=cortes, falhas_cortes=falhas or None)
    return {"cortes": feitos, "falhas": falhas}


def corte_indicado(item_id: int, inicio: float, quadro: str = "", fotos: list | None = None,
                   credito: str = "") -> dict:
    """Um corte a partir do ponto que a redação indicou (ex.: 14:01), com enquadramento opcional."""
    with sessao() as s:
        it = s.get(Item, item_id)
        vid, url, titulo = it.analise_extra["video_id"], it.url, it.titulo
    trechos, info = legendas.obter(url)
    if info.get("title") and titulo.startswith("Vídeo "):
        titulo = info["title"]
    c = dig.corte_indicado(titulo, trechos, inicio)
    if quadro:
        c["quadro"] = quadro
    if fotos:
        c["fotos"], c["credito"] = fotos, credito
    feitos, falhas = _enviar_cortes(item_id, vid, url, titulo, [c], trechos)
    return {"cortes": feitos, "falhas": falhas, "inicio": c["inicio"], "fim": c["fim"], "titulo": c.get("titulo")}


def enviar_modelos(item_id: int) -> dict:
    """Envia o 1º corte de um vídeo nos três modelos visuais, para comparação."""
    from ..video.layouts import MODELOS
    cfg = config()
    with sessao() as s:
        it = s.get(Item, item_id)
        vid, url, titulo, descricao = it.analise_extra["video_id"], it.url, it.titulo, it.texto or ""
        cortes = (it.analise_extra or {}).get("cortes_def")
    trechos, info = legendas.obter(url)
    if not cortes:
        duracao = float(info.get("duration") or trechos[-1].fim)
        cortes = dig.gerar(titulo, descricao, legendas.transcricao_compacta(trechos), duracao).get("cortes", [])
        _marcar(item_id, cortes_def=cortes)
    if not cortes:
        return {"enviados": 0}
    enviados = 0
    for modelo, arq in vc.comparar_modelos(vid, url, cortes[0], trechos):
        leg = (f"🎨 <b>MODELO: {esc(modelo.upper())}</b>\n{esc(MODELOS[modelo])}\n\n"
               f"Para adotar: MNIA_CORTE_MODELO={esc(modelo)}")
        enviar_video(cfg.chat_cortes, arq, leg, item_id=item_id, duracao=vc.duracao(arq),
                     capa=vc.gerar_capa(arq))
        enviados += 1
    return {"enviados": enviados}


def processar_video(item_id: int) -> dict:
    cfg = config()
    with sessao() as s:
        it = s.get(Item, item_id)
        vid, url, titulo, descricao = it.analise_extra["video_id"], it.url, it.titulo, it.texto or ""
        tentativas = (it.analise_extra or {}).get("tentativas", 0)

    try:
        trechos, info = legendas.obter(url)
    except legendas.SemLegenda as e:
        _marcar(item_id, tentativas=tentativas + 1, ultimo_erro=str(e))
        return {"status": "sem_legenda"}
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        return {"status": "ao_vivo"}  # tenta de novo quando a transmissão acabar
    if not trechos:
        _marcar(item_id, tentativas=tentativas + 1, ultimo_erro="legenda vazia")
        return {"status": "sem_legenda"}

    if info.get("title") and titulo.startswith("Vídeo "):
        titulo = info["title"]
        with sessao() as s:
            s.get(Item, item_id).titulo = titulo
    duracao = float(info.get("duration") or trechos[-1].fim)
    transcricao = legendas.transcricao_compacta(trechos)
    resultado = dig.gerar(titulo, descricao, transcricao, duracao)

    materias = resultado.get("materias", [])
    for n, m in enumerate(materias, 1):
        enviar(cfg.chat_digital, dig.formatar_materia(m, titulo, url, n, len(materias)), tipo="materia",
               item_id=item_id)
    if resultado.get("post_redes"):
        enviar(cfg.chat_digital, dig.formatar_post(resultado["post_redes"], titulo, url), tipo="post",
               item_id=item_id)

    feitos, falhas = (_enviar_cortes(item_id, vid, url, titulo, resultado.get("cortes", []), trechos)
                      if cfg.cortes_ligados else (0, []))

    _marcar(item_id, analisado=True, processado=True, materias=len(materias), cortes=feitos,
            falhas_cortes=falhas or None, duracao=duracao,
            cortes_def=resultado.get("cortes", []))
    return {"status": "ok", "materias": len(materias), "cortes": feitos, "falhas": falhas}


def rodar_youtube() -> Execucao:
    cfg = config()
    with sessao() as s:
        exe = Execucao(modulo="youtube")
        s.add(exe)
        s.flush()
        exe_id = exe.id
    novos = feitos = 0
    erros: list[str] = []
    try:
        novos = registrar_novos(canal.listar_videos(cfg.youtube_canal))
        for item_id in pendentes(cfg.youtube_max_videos):
            try:
                r = processar_video(item_id)
                if r["status"] == "ok":
                    feitos += 1
                    erros += r.get("falhas", [])
            except legendas.Bloqueado as e:
                erros.append(f"bloqueado: {e}")
                if not _bloqueio_avisado["feito"]:
                    alerta_tecnico("youtube", "O YouTube pediu verificação para este servidor e bloqueou a "
                                   "leitura das legendas. Ver no passo a passo como usar cookies de uma conta.")
                    _bloqueio_avisado["feito"] = True
                break
            except ErroLLM as e:
                erros.append(f"video {item_id}: {e}")
            except Exception as e:
                erros.append(f"video {item_id}: {type(e).__name__}: {str(e)[:200]}")
                log.exception("Vídeo %s falhou", item_id)
                with sessao() as s:
                    t = (s.get(Item, item_id).analise_extra or {}).get("tentativas", 0)
                _marcar(item_id, tentativas=t + 1, ultimo_erro=str(e)[:300])
        vc.limpar_antigos()
    except Exception as e:
        erros.append(f"{type(e).__name__}: {e}")
        alerta_tecnico("youtube", erros[-1])
        log.exception("Rodada do YouTube falhou")
    with sessao() as s:
        exe = s.get(Execucao, exe_id)
        exe.fim, exe.itens_novos, exe.itens_analisados = agora(), novos, feitos
        exe.erros, exe.sucesso = erros or None, not any(e.startswith(("bloqueado", "Runtime")) for e in erros)
    log.info("YouTube: %d vídeos novos, %d processados, %d erros", novos, feitos, len(erros))
    return exe
