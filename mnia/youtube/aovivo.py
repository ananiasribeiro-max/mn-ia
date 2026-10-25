"""Cortes em transmissões AO VIVO (sem legenda do YouTube) e cortes a partir de uma frase.

1. Baixa só o áudio, em janelas de 10 min, da borda ao vivo para trás.
2. Transcreve no próprio servidor (faster-whisper, CPU) e procura a frase indicada.
3. Achou: baixa o trecho de vídeo desde o início da transmissão (live_from_start),
   transcreve com mais precisão para a legenda e segue o fluxo normal do corte.

Tempos são sempre em segundos desde o início da transmissão (o mesmo relógio do
player do YouTube depois que a live termina).
"""
from __future__ import annotations

import difflib
import logging
import re
import tempfile
import time
import unicodedata
from pathlib import Path

from ..config import RAIZ
from .legendas import Trecho, opcoes_base

log = logging.getLogger("mnia.aovivo")
MODELOS_DIR = RAIZ / "dados" / "modelos"
_modelos: dict = {}


def _modelo(nome: str):
    from faster_whisper import WhisperModel
    if nome not in _modelos:
        MODELOS_DIR.mkdir(parents=True, exist_ok=True)
        _modelos[nome] = WhisperModel(nome, device="cpu", compute_type="int8", download_root=str(MODELOS_DIR))
    return _modelos[nome]


def info(url: str) -> dict:
    import yt_dlp
    with yt_dlp.YoutubeDL({**opcoes_base(), "skip_download": True, "ignore_no_formats_error": True}) as ydl:
        return ydl.extract_info(url, download=False) or {}


def duracao_atual(i: dict) -> float:
    """Segundos de transmissão até agora (ao vivo) ou duração total (gravado)."""
    if i.get("is_live") or i.get("live_status") == "is_live":
        ini = i.get("release_timestamp") or i.get("timestamp")
        if ini:
            return max(0.0, time.time() - float(ini))
    return float(i.get("duration") or 0)


def baixar(url: str, ini: float, fim: float, destino: Path, *, so_audio: bool, ao_vivo: bool) -> Path:
    import yt_dlp
    from yt_dlp.utils import download_range_func
    destino.parent.mkdir(parents=True, exist_ok=True)
    base = destino.with_suffix("")
    op = {
        **opcoes_base(),
        "format": "ba/b" if so_audio else "bv*[height<=1080]+ba/b[height<=1080]/b",
        "download_ranges": download_range_func(None, [(max(0.0, ini), fim)]),
        "outtmpl": str(base) + ".%(ext)s",
        "noplaylist": True,
    }
    if not so_audio:
        op["merge_output_format"] = "mp4"
        op["force_keyframes_at_cuts"] = True
    if ao_vivo:
        op["live_from_start"] = True
    with yt_dlp.YoutubeDL(op) as ydl:
        ydl.download([url])
    arqs = [a for a in sorted(base.parent.glob(base.name + ".*")) if a.suffix not in (".part", ".ytdl")]
    if not arqs:
        raise RuntimeError("download não gerou arquivo")
    return arqs[0]


def transcrever(arquivo: Path, deslocamento: float, modelo: str = "base") -> tuple[list[Trecho], list[tuple[float, float, str]]]:
    """Devolve (trechos por frase, palavras com tempo), já no relógio da transmissão."""
    segs, _ = _modelo(modelo).transcribe(str(arquivo), language="pt", vad_filter=True, word_timestamps=True,
                                         beam_size=1 if modelo in ("tiny", "base") else 5)
    trechos, palavras = [], []
    for s in segs:
        trechos.append(Trecho(s.start + deslocamento, s.end + deslocamento, s.text.strip()))
        for w in (s.words or []):
            palavras.append((w.start + deslocamento, w.end + deslocamento, w.word.strip()))
    return trechos, palavras


def _limpa(t: str) -> list[str]:
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", t).split()


def procurar(palavras: list[tuple[float, float, str]], frase: str, minimo: float = 0.72) -> float | None:
    """Início (s) da frase nas palavras transcritas, com tolerância a erros de transcrição."""
    alvo = _limpa(frase)[:10]
    if not alvo:
        return None
    toks = [(_limpa(w)[0] if _limpa(w) else "", ini) for ini, _, w in palavras]
    toks = [(w, ini) for w, ini in toks if w]
    n = len(alvo)
    melhor, quando = 0.0, None
    for i in range(0, max(1, len(toks) - n + 1)):
        janela = " ".join(w for w, _ in toks[i:i + n])
        r = difflib.SequenceMatcher(None, " ".join(alvo), janela).ratio()
        if r > melhor:
            melhor, quando = r, toks[i][1]
    log.info("Melhor semelhança com a frase: %.2f", melhor)
    return quando if melhor >= minimo else None


def achar_frase(url: str, frase: str, janela: int = 600, max_janelas: int = 18) -> tuple[float, dict]:
    """Procura a frase da borda ao vivo para trás. Devolve (segundo de início, info)."""
    i = info(url)
    ao_vivo = bool(i.get("is_live") or i.get("live_status") == "is_live")
    fim = duracao_atual(i)
    if fim <= 0:
        raise RuntimeError("não consegui saber a duração da transmissão")
    with tempfile.TemporaryDirectory() as tmp:
        for k in range(max_janelas):
            b = fim - k * janela
            a = max(0.0, b - janela - 20)
            log.info("Procurando a frase entre %.0f s e %.0f s", a, b)
            audio = baixar(url, a, b, Path(tmp) / f"a{k}.m4a", so_audio=True, ao_vivo=ao_vivo)
            _, palavras = transcrever(audio, a, "base")
            achou = procurar(palavras, frase)
            if achou is not None:
                return achou, i
            audio.unlink(missing_ok=True)
            if a <= 0:
                break
    raise RuntimeError("não encontrei a frase nas últimas horas da transmissão")
