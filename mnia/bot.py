"""Comandos da redação pelo Telegram (sem terminal, sem intermediário).

  /corte <link> 14:01                          corte a partir de um minuto do vídeo
  /corte <link> "começo da fala"               corte a partir de uma frase (serve para AO VIVO)
  /corte <link> "começo da fala" 02:16         idem, com a hora do relógio da tela (busca mais rápida)
  /ajuda                                       lista os comandos

Só os grupos/canais configurados no .env podem dar comandos. Os pedidos entram numa
fila e são feitos um de cada vez; o resultado vai para o canal de cortes.
"""
from __future__ import annotations

import logging
import queue
import re
import shlex
import threading
import time

import httpx

from .config import RAIZ, config
from .telegram import enviar, esc

log = logging.getLogger("mnia.bot")
OFFSET = RAIZ / "dados" / "telegram_offset.txt"
_fila: "queue.Queue[tuple[str, dict]]" = queue.Queue()

AJUDA = (
    "🤖 <b>Comandos do MN-IA</b>\n\n"
    "<b>/corte</b> <i>link</i> <i>14:01</i>\n"
    "  corte a partir de um minuto do vídeo\n\n"
    "<b>/corte</b> <i>link</i> \"<i>começo da fala</i>\" <i>02:16</i>\n"
    "  corte a partir de uma frase; serve para transmissão AO VIVO.\n"
    "  A hora (relógio da tela) é opcional, mas deixa a busca bem mais rápida.\n\n"
    "O corte chega no canal de cortes em 1 a 3 minutos."
)


def chats_autorizados() -> set[str]:
    cfg = config()
    return {str(c) for c in (cfg.chat_cortes, cfg.chat_radar, cfg.chat_tecnico, cfg.chat_digital,
                             cfg.chat_producao, cfg.chat_clipping, cfg.chat_triagem) if c}


def interpretar(texto: str) -> dict | None:
    """'/corte link 14:01' ou '/corte link "frase" 02:16' -> pedido; None se não for comando de corte."""
    texto = texto.strip().replace("“", '"').replace("”", '"')
    if not re.match(r"^/corte(@\w+)?\b", texto):
        return None
    try:
        partes = shlex.split(texto)
    except ValueError:
        partes = texto.split()
    partes = partes[1:]
    url = next((p for p in partes if "youtu" in p), "")
    resto = [p for p in partes if p != url]
    horas = [p for p in resto if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", p)]
    palavras = [p for p in resto if p not in horas]
    frase = " ".join(palavras).strip().strip('"').strip()
    pedido = {"url": url, "frase": frase, "inicio": "", "hora": ""}
    if frase:
        pedido["hora"] = horas[0] if horas else ""
    elif horas:
        pedido["inicio"] = horas[0]
    return pedido


def _executar(chat: str, p: dict) -> None:
    from .digital.materia import mmss
    from .youtube.pipeline import corte_indicado, corte_por_frase, item_para_url
    t0 = time.time()
    try:
        item_id = item_para_url(p["url"])
        if p["frase"]:
            r = corte_por_frase(item_id, p["frase"], hora=p["hora"])
        else:
            r = corte_indicado(item_id, mmss(p["inicio"]))
        seg = int(time.time() - t0)
        if r.get("cortes"):
            enviar(chat, f"✅ Corte pronto em {seg}s ({esc(r['inicio'])}–{esc(r['fim'])}): "
                         f"<b>{esc(r.get('titulo') or '')}</b>\nEnviado ao canal de cortes.", tipo="bot")
        else:
            enviar(chat, f"⚠️ Não consegui montar o corte: {esc('; '.join(r.get('falhas') or []) or 'sem detalhes')}",
                   tipo="bot")
    except Exception as e:
        log.exception("Pedido de corte falhou")
        enviar(chat, f"⚠️ Não consegui fazer o corte: {esc(str(e)[:300])}", tipo="bot")


def _trabalhador() -> None:
    while True:
        chat, pedido = _fila.get()
        try:
            _executar(chat, pedido)
        finally:
            _fila.task_done()


def _responder(chat: str, texto: str) -> None:
    if texto.strip().startswith(("/ajuda", "/start", "/help")):
        enviar(chat, AJUDA, tipo="bot")
        return
    p = interpretar(texto)
    if p is None:
        return
    if not p["url"] or not (p["frase"] or p["inicio"]):
        enviar(chat, "Formato: <code>/corte link 14:01</code> ou "
                     "<code>/corte link \"começo da fala\" 02:16</code>", tipo="bot")
        return
    na_frente = _fila.qsize()
    _fila.put((chat, p))
    onde = f"frase “{esc(p['frase'][:60])}”" + (f" perto de {esc(p['hora'])}" if p["hora"] else "") \
        if p["frase"] else f"minuto {esc(p['inicio'])}"
    enviar(chat, f"⏳ Pedido recebido: corte a partir da {onde}."
                 + (f" {na_frente} pedido(s) na frente." if na_frente else ""), tipo="bot")


def escutar() -> None:
    """Long polling do getUpdates; roda numa thread do agendador."""
    cfg = config()
    if not cfg.telegram_token:
        log.info("Bot sem token: comandos desligados")
        return
    autorizados = chats_autorizados()
    url = f"https://api.telegram.org/bot{cfg.telegram_token}/getUpdates"
    try:
        offset = int(OFFSET.read_text().strip()) if OFFSET.exists() else 0
    except ValueError:
        offset = 0
    log.info("Bot de comandos ativo (%d chats autorizados)", len(autorizados))
    while True:
        try:
            r = httpx.get(url, params={"timeout": 50, "offset": offset,
                                       "allowed_updates": '["message","channel_post"]'}, timeout=60)
            if r.status_code != 200:
                log.warning("getUpdates %s", r.status_code)
                time.sleep(10)
                continue
            for up in r.json().get("result", []):
                offset = up["update_id"] + 1
                msg = up.get("message") or up.get("channel_post") or {}
                chat = str((msg.get("chat") or {}).get("id", ""))
                texto = msg.get("text") or ""
                if not texto.startswith("/"):
                    continue
                if chat not in autorizados:
                    log.warning("Comando ignorado de chat não autorizado %s", chat)
                    continue
                _responder(chat, texto)
            OFFSET.parent.mkdir(parents=True, exist_ok=True)
            OFFSET.write_text(str(offset))
        except httpx.HTTPError as e:
            log.warning("getUpdates falhou: %s", type(e).__name__)  # sem URL (tem o token)
            time.sleep(5)
        except Exception:
            log.exception("Erro no bot de comandos")
            time.sleep(5)


def iniciar_em_segundo_plano() -> None:
    threading.Thread(target=_trabalhador, name="bot-fila", daemon=True).start()
    threading.Thread(target=escutar, name="bot-escuta", daemon=True).start()

    def _pre() -> None:
        try:
            from .youtube.aovivo import precarregar
            precarregar()
        except Exception as e:
            log.warning("Pré-carga dos modelos falhou: %s", e)
    threading.Thread(target=_pre, name="pre-modelos", daemon=True).start()
