"""Legendas do YouTube (manuais ou automáticas) como transcrição com tempo.

Usa yt-dlp só para buscar a legenda: o vídeo não é baixado aqui.
"""
from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("mnia.legendas")

IDIOMAS = ["pt-BR", "pt", "pt-orig", "pt-PT"]
TS = re.compile(r"(\d{1,2}:)?(\d{2}):(\d{2})[.,](\d{3})")


@dataclass
class Trecho:
    inicio: float
    fim: float
    texto: str


def opcoes_base() -> dict:
    """Opções comuns do yt-dlp: runtime JavaScript e cookies opcionais (dados/cookies.txt)."""
    from ..config import RAIZ
    op = {"js_runtimes": {"deno": {}, "node": {}}, "quiet": True, "no_warnings": True}
    cookies = RAIZ / "dados" / "cookies.txt"
    if cookies.exists():
        op["cookiefile"] = str(cookies)
    return op


class SemLegenda(RuntimeError):
    pass


class Bloqueado(RuntimeError):
    """YouTube pediu verificação ("confirme que não é um robô") para o servidor."""


def _seg(ts: str) -> float:
    m = TS.match(ts.strip())
    if not m:
        return 0.0
    h = int(m.group(1)[:-1]) if m.group(1) else 0
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000


def interpretar_vtt(vtt: str) -> list[Trecho]:
    """Converte VTT em trechos, limpando tags e as repetições típicas da legenda automática."""
    trechos: list[Trecho] = []
    blocos = re.split(r"\n\s*\n", vtt.replace("\r", ""))
    for b in blocos:
        linhas = [l for l in b.strip().split("\n") if l.strip()]
        idx = next((i for i, l in enumerate(linhas) if "-->" in l), None)
        if idx is None:
            continue
        ini, fim = [p.strip().split(" ")[0] for p in linhas[idx].split("-->")]
        texto = " ".join(linhas[idx + 1:])
        texto = re.sub(r"<[^>]+>", "", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        if not texto:
            continue
        trechos.append(Trecho(_seg(ini), _seg(fim), texto))

    # Legenda automática repete a linha anterior no começo da próxima: remove o eco.
    limpos: list[Trecho] = []
    for t in trechos:
        if limpos:
            ant = limpos[-1].texto
            if t.texto == ant:
                limpos[-1].fim = t.fim
                continue
            if t.texto.startswith(ant):
                t = Trecho(t.inicio, t.fim, t.texto[len(ant):].strip())
                if not t.texto:
                    continue
        limpos.append(t)
    return limpos


def transcricao_compacta(trechos: list[Trecho], limite_chars: int = 60000) -> str:
    """Texto com marcas de tempo a cada ~20 s, para o Claude localizar trechos."""
    linhas, atual, marca = [], [], None
    for t in trechos:
        if marca is None:
            marca = t.inicio
        atual.append(t.texto)
        if t.fim - marca >= 20:
            linhas.append(f"[{int(marca // 60):02d}:{int(marca % 60):02d}] " + " ".join(atual))
            atual, marca = [], None
    if atual and marca is not None:
        linhas.append(f"[{int(marca // 60):02d}:{int(marca % 60):02d}] " + " ".join(atual))
    texto = "\n".join(linhas)
    return texto[:limite_chars]


def obter(video_url: str) -> tuple[list[Trecho], dict]:
    """Devolve (trechos, info). info tem duration, is_live, live_status, title."""
    import yt_dlp

    with tempfile.TemporaryDirectory() as tmp:
        opcoes = {
            **opcoes_base(),
            "skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
            "subtitleslangs": IDIOMAS, "subtitlesformat": "vtt",
            "outtmpl": str(Path(tmp) / "%(id)s.%(ext)s"),
        }
        try:
            with yt_dlp.YoutubeDL(opcoes) as ydl:
                info = ydl.extract_info(video_url, download=True)
        except Exception as e:
            msg = str(e)
            if "confirm you" in msg.lower() or "not a bot" in msg.lower() or "sign in" in msg.lower():
                raise Bloqueado(msg[:300]) from e
            raise
        resumo = {k: info.get(k) for k in ("id", "title", "duration", "is_live", "live_status", "upload_date")}
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            return [], resumo
        arquivos = sorted(Path(tmp).glob("*.vtt"))
        # prefere legenda manual (sem "orig") e português do Brasil
        arquivos.sort(key=lambda p: (("orig" in p.name), ("pt-BR" not in p.name)))
        if not arquivos:
            raise SemLegenda("vídeo sem legenda em português (ainda)")
        return interpretar_vtt(arquivos[0].read_text(encoding="utf-8", errors="replace")), resumo
