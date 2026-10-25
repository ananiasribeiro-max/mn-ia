"""Comandos da redação pelo Telegram (sem terminal, sem intermediário).

  /corte <link> 14:01                          corte a partir de um minuto do vídeo
  /corte <link> "começo da fala"               corte a partir de uma frase (serve para AO VIVO)
  /corte <link> "começo da fala" 02:16         idem, com a hora do relógio da tela (busca mais rápida)
  /central <link> ...                          mesmo pedido no modelo do programa Central Meio Norte
                                               (mande junto 1 ou 2 fotos do assunto, como álbum com legenda)
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
    "<b>/central</b> <i>link</i> <i>14:01</i>  (ou com \"frase\" e hora)\n"
    "  mesmo corte no modelo do <b>Central Meio Norte</b>: fala em cima, foto do assunto embaixo,\n"
    "  frase de destaque no meio. Mande 1 ou 2 fotos junto (álbum, com o comando na legenda).\n"
    "  Sem foto, uso as da biblioteca do servidor (ex.: lula.jpg, flavio.jpg) pelos nomes citados.\n\n"
    "O corte chega no canal de cortes em 1 a 3 minutos."
)


def chats_autorizados() -> set[str]:
    cfg = config()
    return {str(c) for c in (cfg.chat_cortes, cfg.chat_radar, cfg.chat_tecnico, cfg.chat_digital,
                             cfg.chat_producao, cfg.chat_clipping, cfg.chat_triagem) if c}


def interpretar(texto: str) -> dict | None:
    """'/corte link 14:01' ou '/corte link "frase" 02:16' -> pedido; None se não for comando de corte."""
    texto = texto.strip().replace("“", '"').replace("”", '"')
    m = re.match(r"^/(corte|central)(@\w+)?\b", texto)
    if not m:
        return None
    modelo = "central" if m.group(1) == "central" else ""
    try:
        partes = shlex.split(texto)
    except ValueError:
        partes = texto.split()
    partes = partes[1:]
    url = next((p for p in partes if "youtu" in p), "")
    resto = [p for p in partes if p != url]
    if any(p.lower() in ("central", "#central") for p in resto):
        modelo = "central"
        resto = [p for p in resto if p.lower() not in ("central", "#central")]
    horas = [p for p in resto if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", p)]
    palavras = [p for p in resto if p not in horas]
    frase = " ".join(palavras).strip().strip('"').strip()
    pedido = {"url": url, "frase": frase, "inicio": "", "hora": "", "modelo": modelo, "fotos": []}
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
        fotos = [(f, "") for f in p.get("fotos") or []]
        if p["frase"]:
            r = corte_por_frase(item_id, p["frase"], hora=p["hora"], fotos=fotos, modelo=p.get("modelo", ""))
        else:
            r = corte_indicado(item_id, mmss(p["inicio"]), fotos=fotos, modelo=p.get("modelo", ""))
        seg = int(time.time() - t0)
        if r.get("cortes"):
            extra = ""
            if p.get("modelo") == "central" and not p.get("fotos"):
                usadas = r.get("fotos_usadas") or []
                extra = ("\nFotos da biblioteca: " + esc(", ".join(usadas))) if usadas else \
                    "\n(Sem foto do assunto: usei o vídeo desfocado embaixo. Mande fotos junto no próximo.)"
            enviar(chat, f"✅ Corte pronto em {seg}s ({esc(r['inicio'])}–{esc(r['fim'])}): "
                         f"<b>{esc(r.get('titulo') or '')}</b>{extra}\nEnviado ao canal de cortes.", tipo="bot")
        else:
            enviar(chat, f"⚠️ Não consegui montar o corte: {esc('; '.join(r.get('falhas') or []) or 'sem detalhes')}",
                   tipo="bot")
    except Exception as e:
        log.exception("Pedido de corte falhou")
        enviar(chat, f"⚠️ Não consegui fazer o corte: {esc(str(e)[:300])}", tipo="bot")


_fila_gerar: "queue.Queue[tuple[str, int, str, int]]" = queue.Queue()


def _gerador() -> None:
    """Gera pauta/matéria/post/nota quando alguém toca no botão de um tópico do radar."""
    from .radar import produtos
    while True:
        chat, msg_id, alvo, item_id = _fila_gerar.get()
        try:
            r = produtos.gerar(item_id, alvo)
            enviar(chat, produtos.formatar(alvo, r), tipo=f"produto_{alvo}", item_id=item_id, responder_a=msg_id)
        except Exception as e:
            log.exception("Geração %s do item %s falhou", alvo, item_id)
            enviar(chat, f"⚠️ Não consegui gerar ({esc(alvo)}): {esc(str(e)[:200])}", tipo="bot",
                   responder_a=msg_id)
        finally:
            _fila_gerar.task_done()


def _botao(cb: dict, autorizados: set[str]) -> None:
    cfg = config()
    api = f"https://api.telegram.org/bot{cfg.telegram_token}/answerCallbackQuery"
    msg = cb.get("message") or {}
    chat = str((msg.get("chat") or {}).get("id", ""))
    m = re.fullmatch(r"g:(tv|portal|redes|radio):(\d+)", cb.get("data") or "")
    if chat not in autorizados or not m:
        httpx.post(api, json={"callback_query_id": cb["id"]}, timeout=10)
        return
    alvo, item_id = m.group(1), int(m.group(2))
    nomes = {"tv": "a pauta de TV", "portal": "a matéria do portal", "redes": "o post", "radio": "a nota de rádio"}
    httpx.post(api, json={"callback_query_id": cb["id"], "text": f"Gerando {nomes[alvo]}… chega em instantes."},
               timeout=10)
    _fila_gerar.put((chat, msg.get("message_id"), alvo, item_id))


def _trabalhador() -> None:
    while True:
        chat, pedido = _fila.get()
        try:
            _executar(chat, pedido)
        finally:
            _fila.task_done()


def _baixar_foto(file_id: str) -> str:
    """Baixa a foto enviada no Telegram para dados/fotos e devolve o caminho."""
    cfg = config()
    api = f"https://api.telegram.org/bot{cfg.telegram_token}"
    info = httpx.get(f"{api}/getFile", params={"file_id": file_id}, timeout=30).json()["result"]
    destino = RAIZ / "dados" / "fotos" / f"tg_{info['file_unique_id']}.jpg"
    destino.parent.mkdir(parents=True, exist_ok=True)
    conteudo = httpx.get(f"https://api.telegram.org/file/bot{cfg.telegram_token}/{info['file_path']}",
                         timeout=60).content
    destino.write_bytes(conteudo)
    return str(destino)


def _responder(chat: str, texto: str, fotos: list[str] | None = None) -> None:
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
    if fotos:
        try:
            p["fotos"] = [_baixar_foto(f) for f in fotos[:2]]
        except Exception as e:
            log.warning("Falha ao baixar foto do Telegram: %s", type(e).__name__)
    na_frente = _fila.qsize()
    _fila.put((chat, p))
    modelo_txt = " no modelo <b>Central Meio Norte</b>" if p.get("modelo") == "central" else ""
    fotos_txt = f" com {len(p['fotos'])} foto(s)" if p.get("fotos") else ""
    onde = f"frase “{esc(p['frase'][:60])}”" + (f" perto de {esc(p['hora'])}" if p["hora"] else "") \
        if p["frase"] else f"minuto {esc(p['inicio'])}"
    enviar(chat, f"⏳ Pedido recebido: corte{modelo_txt}{fotos_txt} a partir da {onde}."
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
    albuns: dict[str, dict] = {}   # media_group_id -> {"chat","fotos","texto","t"}
    while True:
        try:
            r = httpx.get(url, params={"timeout": 5 if albuns else 50, "offset": offset,
                                       "allowed_updates": '["message","channel_post","callback_query"]'}, timeout=60)
            if r.status_code != 200:
                log.warning("getUpdates %s", r.status_code)
                time.sleep(10)
                continue
            for up in r.json().get("result", []):
                offset = up["update_id"] + 1
                if up.get("callback_query"):
                    _botao(up["callback_query"], autorizados)
                    continue
                msg = up.get("message") or up.get("channel_post") or {}
                chat = str((msg.get("chat") or {}).get("id", ""))
                if chat not in autorizados:
                    if (msg.get("text") or msg.get("caption") or "").startswith("/"):
                        log.warning("Comando ignorado de chat não autorizado %s", chat)
                    continue
                texto = msg.get("text") or msg.get("caption") or ""
                foto = (msg.get("photo") or [{}])[-1].get("file_id")
                grupo = msg.get("media_group_id")
                if grupo:  # álbum: junta as fotos; o comando vem na legenda de uma delas
                    a = albuns.setdefault(grupo, {"chat": chat, "fotos": [], "texto": "", "t": time.time()})
                    if foto:
                        a["fotos"].append(foto)
                    if texto:
                        a["texto"] = texto
                    a["t"] = time.time()
                    continue
                if texto.startswith("/"):
                    _responder(chat, texto, [foto] if foto else None)
            for g in [g for g, a in albuns.items() if time.time() - a["t"] > 2.5]:
                a = albuns.pop(g)
                if a["texto"].startswith("/"):
                    _responder(a["chat"], a["texto"], a["fotos"])
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
    threading.Thread(target=_gerador, name="bot-gerar", daemon=True).start()
    threading.Thread(target=escutar, name="bot-escuta", daemon=True).start()

    def _pre() -> None:
        try:
            from .youtube.aovivo import precarregar
            precarregar()
        except Exception as e:
            log.warning("Pré-carga dos modelos falhou: %s", e)
    threading.Thread(target=_pre, name="pre-modelos", daemon=True).start()
