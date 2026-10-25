"""Envio de mensagens para os grupos do Telegram.

Sem token configurado, ou em modo simulado, as mensagens são impressas
no console e gravadas em dados/telegram_simulado.log.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime
from pathlib import Path

import httpx

from .config import RAIZ, config
from .db import Alerta, sessao

log = logging.getLogger("mnia.telegram")
LIMITE = 4000  # Telegram aceita 4096; margem para tags


def esc(texto: str | None) -> str:
    """Escapa texto para o modo HTML do Telegram."""
    return html.escape(texto or "", quote=False)


def _partes(texto: str) -> list[str]:
    if len(texto) <= LIMITE:
        return [texto]
    partes, atual = [], ""
    for bloco in texto.split("\n\n"):
        if len(atual) + len(bloco) + 2 > LIMITE and atual:
            partes.append(atual)
            atual = ""
        atual += ("\n\n" if atual else "") + bloco
    if atual:
        partes.append(atual)
    return partes


def _simular(canal: str, texto: str) -> None:
    arq = RAIZ / "dados" / "telegram_simulado.log"
    arq.parent.mkdir(parents=True, exist_ok=True)
    with arq.open("a", encoding="utf-8") as f:
        f.write(f"\n===== [{datetime.now():%Y-%m-%d %H:%M:%S}] canal={canal} =====\n{texto}\n")
    print(f"\n----- TELEGRAM ({canal}) -----\n{texto}\n")


def enviar(canal: str, texto: str, *, tipo: str, item_id: int | None = None) -> bool:
    """Envia texto (HTML do Telegram) para um chat. Retorna True se entregue."""
    cfg = config()
    sucesso = True
    if not cfg.telegram_token or not canal or cfg.simulado:
        _simular(canal or "sem-canal", texto)
    else:
        url = f"https://api.telegram.org/bot{cfg.telegram_token}/sendMessage"
        for parte in _partes(texto):
            try:
                r = httpx.post(url, json={
                    "chat_id": canal, "text": parte, "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }, timeout=20)
                if r.status_code != 200:
                    sucesso = False
                    log.error("Telegram %s no chat %s: %s", r.status_code, canal, r.text[:300])
            except httpx.HTTPError as e:
                sucesso = False
                # a mensagem de erro do httpx pode conter a URL com o token: não registrar
                log.error("Telegram falhou no chat %s: %s", canal, type(e).__name__)
    try:
        with sessao() as s:
            s.add(Alerta(item_id=item_id, tipo=tipo, canal=canal or "simulado",
                         texto=texto[:10000], sucesso=sucesso))
    except Exception as e:
        log.warning("Falha ao registrar alerta: %s", e)
    return sucesso


def alerta_tecnico(modulo: str, erro: str) -> None:
    cfg = config()
    enviar(cfg.chat_tecnico, f"⚠️ <b>MN-IA — erro em {esc(modulo)}</b>\n<code>{esc(erro[:1500])}</code>",
           tipo="tecnico")


LIMITE_VIDEO = 49 * 1024 * 1024  # bots do Telegram enviam até 50 MB


def enviar_video(canal: str, caminho: Path, legenda: str, *, item_id: int | None = None) -> bool:
    """Envia um vídeo (corte) para aprovação. Acima de 50 MB, avisa e não envia."""
    cfg = config()
    tamanho = caminho.stat().st_size
    if not cfg.telegram_token or not canal or cfg.simulado:
        _simular(canal or "sem-canal", f"[VÍDEO {caminho.name} {tamanho // 1024} KB]\n{legenda}")
        return True
    if tamanho > LIMITE_VIDEO:
        return enviar(canal, legenda + f"\n\n⚠️ Corte com {tamanho // (1024 * 1024)} MB: acima do limite do "
                      "Telegram. Arquivo guardado no servidor: " + esc(caminho.name), tipo="corte", item_id=item_id)
    url = f"https://api.telegram.org/bot{cfg.telegram_token}/sendVideo"
    sucesso = True
    try:
        with caminho.open("rb") as f:
            r = httpx.post(url, data={"chat_id": canal, "caption": legenda[:1024], "parse_mode": "HTML",
                                      "supports_streaming": "true"},
                           files={"video": (caminho.name, f, "video/mp4")}, timeout=180)
        if r.status_code != 200:
            sucesso = False
            log.error("Telegram vídeo %s no chat %s: %s", r.status_code, canal, r.text[:300])
    except httpx.HTTPError as e:
        sucesso = False
        log.error("Telegram vídeo falhou no chat %s: %s", canal, type(e).__name__)
    try:
        with sessao() as s:
            s.add(Alerta(item_id=item_id, tipo="corte", canal=canal, texto=legenda[:2000], sucesso=sucesso))
    except Exception as e:
        log.warning("Falha ao registrar alerta: %s", e)
    return sucesso
