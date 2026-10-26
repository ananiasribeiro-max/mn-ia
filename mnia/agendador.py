"""Agendador: mantém todos os módulos rodando no servidor.

  radar     -> a cada MNIA_RADAR_INTERVALO_MIN minutos
  resumo    -> de hora em hora (minuto 2), das 6h às 23h
  clipping  -> todo dia em MNIA_CLIPPING_HORARIO
  triagem   -> a cada MNIA_TRIAGEM_INTERVALO_MIN minutos
  saude     -> todo dia 7h: relatório técnico (execuções, falhas, custo)
  laudas    -> de hora em hora (minuto 10), das 6h às 22h, para as pautas fortes do radar
  youtube   -> a cada MNIA_YOUTUBE_INTERVALO_MIN: vídeos novos → matéria, títulos, post, cortes
"""
from __future__ import annotations

import logging
from datetime import timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import Integer, case, func, select

from .clipping.matinal import rodar_clipping
from .config import config
from .db import Custo, Execucao, agora, init_db, sessao
from .radar.pipeline import enviar_resumo, rodar_radar
from .telegram import enviar
from .lauda.gerar import rodar_laudas
from .triagem.email_pauta import rodar_triagem
from .youtube.pipeline import rodar_youtube

log = logging.getLogger("mnia.agendador")


def relatorio_saude() -> str:
    desde = agora() - timedelta(hours=24)
    with sessao() as s:
        linhas = s.execute(
            select(Execucao.modulo, func.count(), func.sum(case((Execucao.sucesso.is_(True), 1), else_=0)),
                   func.sum(Execucao.itens_novos), func.sum(Execucao.alertas))
            .where(Execucao.inicio >= desde).group_by(Execucao.modulo)
        ).all()
        custo = s.scalar(select(func.coalesce(func.sum(Custo.custo_usd), 0)).where(Custo.em >= desde))
    partes = ["🩺 <b>MN-IA — saúde das últimas 24h</b>"]
    for modulo, total, ok, novos, alertas in linhas:
        falhas = total - (ok or 0)
        icone = "✅" if falhas == 0 else "⚠️"
        partes.append(f"{icone} <b>{modulo}</b>: {total} rodadas, {falhas} falhas, "
                      f"{novos or 0} itens novos, {alertas or 0} alertas")
    partes.append(f"💲 Custo estimado de IA: US$ {float(custo):.2f}")
    return "\n".join(partes)


def _seguro(nome, func_):
    def rodar():
        try:
            func_()
        except Exception:
            log.exception("Job %s falhou", nome)
    rodar.__name__ = nome
    return rodar


def iniciar() -> None:
    cfg = config()
    init_db()
    from .config import operacao_pausada
    if operacao_pausada():
        # Operação pausada pela direção: não chama o Claude, não coleta, não envia nada.
        # Fica de pé só para a atualização automática trazer a versão que religa.
        import time
        log.warning("MN-IA PAUSADO (config/operacao.yaml). Nada será executado.")
        while True:
            time.sleep(3600)
    hh, mm = (int(x) for x in cfg.clipping_horario.split(":"))
    ag = BlockingScheduler(timezone=cfg.fuso)
    ag.add_job(_seguro("radar", rodar_radar), "interval", minutes=cfg.radar_intervalo_min,
               max_instances=1, coalesce=True)
    if cfg.radar_resumo_horario and cfg.radar_modo != "individual":
        ag.add_job(_seguro("resumo", enviar_resumo), "cron", hour="6-23", minute=2,
                   max_instances=1, coalesce=True)
    ag.add_job(_seguro("clipping", rodar_clipping), "cron", hour=hh, minute=mm, max_instances=1)
    ag.add_job(_seguro("triagem", rodar_triagem), "interval", minutes=cfg.triagem_intervalo_min,
               max_instances=1, coalesce=True)
    ag.add_job(_seguro("laudas", rodar_laudas), "cron", hour="6-22", minute=10,
               max_instances=1, coalesce=True)
    ag.add_job(_seguro("youtube", rodar_youtube), "interval", minutes=cfg.youtube_intervalo_min,
               max_instances=1, coalesce=True)
    ag.add_job(_seguro("saude", lambda: enviar(cfg.chat_tecnico, relatorio_saude(), tipo="tecnico")),
               "cron", hour=7, minute=0)
    log.info("MN-IA iniciado. Radar a cada %d min, clipping às %s, triagem a cada %d min.",
             cfg.radar_intervalo_min, cfg.clipping_horario, cfg.triagem_intervalo_min)
    # Aviso de partida no grupo técnico (útil quando não há terminal, ex.: Docker Manager)
    modo = "SIMULADO (sem chave da Anthropic)" if cfg.modo_simulado else "Claude ativo"
    enviar(cfg.chat_tecnico,
           f"🟢 <b>MN-IA ligado</b>\nModo: {modo}\nRadar a cada {cfg.radar_intervalo_min} min · "
           f"clipping às {cfg.clipping_horario} · triagem {'ligada' if cfg.imap_host else 'desligada'}\n"
           "Cortes pelo Telegram: mande /ajuda",
           tipo="tecnico")
    try:  # situação das fontes no grupo técnico a cada partida (mostra fonte nova que não responde)
        from .coletores import coletar_fonte
        from .config import fontes as _fontes
        ruins = []
        for f in _fontes():
            try:
                if not coletar_fonte(f):
                    ruins.append(f"⚠️ {f['nome']}: sem itens")
            except Exception as e:
                ruins.append(f"❌ {f['nome']}: {type(e).__name__}")
        total = len(_fontes())
        enviar(cfg.chat_tecnico, f"📡 <b>Fontes do radar:</b> {total - len(ruins)}/{total} respondendo"
               + ("\n" + "\n".join(ruins) if ruins else ""), tipo="tecnico")
    except Exception as e:
        log.warning("Teste de fontes na partida falhou: %s", e)
    from .bot import iniciar_em_segundo_plano
    iniciar_em_segundo_plano()  # comandos /corte pelo Telegram + pré-carga dos modelos de transcrição
    rodar_radar()  # primeira rodada imediata
    ag.start()
