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


def _formatos_live(url: str) -> tuple[dict, float]:
    """URLs dos fragmentos DASH (áudio 140, vídeo 137/136) e duração de cada fragmento."""
    import urllib.request
    import yt_dlp
    with yt_dlp.YoutubeDL({**opcoes_base(), "live_from_start": True, "skip_download": True}) as ydl:
        i = ydl.extract_info(url, download=False)
    urls = {}
    for f in i.get("formats", []):
        fid = str(f.get("format_id", "")).split("-")[0]
        if fid in ("140", "137", "136", "135") and f.get("url") and fid not in urls:
            urls[fid] = f["url"]
    if "140" not in urls:
        raise RuntimeError("transmissão sem áudio 140 em DASH")
    r = urllib.request.urlopen(urls["140"] + "&sq=0", timeout=30)
    head_seq = int(r.headers.get("X-Head-Seqnum") or 0)
    head_t = float(r.headers.get("X-Head-Time-Sec") or 0)
    dur = head_t / head_seq if head_seq and head_t else 5.0
    return urls, dur


def _baixar_fragmentos(base: str, sq0: int, sq1: int, destino: Path) -> Path:
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    def pega(sq: int) -> bytes:
        for tentativa in range(4):
            try:
                return urllib.request.urlopen(f"{base}&sq={sq}", timeout=30).read()
            except Exception:
                time.sleep(1 + tentativa)
        raise RuntimeError(f"fragmento {sq} falhou")

    with ThreadPoolExecutor(8) as ex:
        partes = list(ex.map(pega, range(sq0, sq1 + 1)))
    destino.write_bytes(b"".join(partes))
    return destino


def baixar(url: str, ini: float, fim: float, destino: Path, *, so_audio: bool, ao_vivo: bool) -> Path:
    import subprocess
    destino.parent.mkdir(parents=True, exist_ok=True)
    ini = max(0.0, ini)
    if ao_vivo:
        # transmissão em andamento: busca os fragmentos DASH pelo número de sequência (DVR)
        urls, dur = _formatos_live(url)
        sq0, sq1 = int(ini // dur), int(fim // dur)
        desloc = ini - sq0 * dur
        tmp = destino.parent / (destino.stem + "_frag")
        tmp.mkdir(exist_ok=True)
        a = _baixar_fragmentos(urls["140"], sq0, sq1, tmp / "a.mp4")
        entradas = ["-i", str(a)]
        if not so_audio:
            vid = next(urls[k] for k in ("137", "136", "135") if k in urls)
            v = _baixar_fragmentos(vid, sq0, sq1, tmp / "v.mp4")
            entradas = ["-i", str(v), "-i", str(a)]
        saida = destino.with_suffix(".m4a" if so_audio else ".mp4")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", *entradas, "-ss", f"{desloc:.2f}", "-t", f"{fim - ini:.2f}"]
        cmd += (["-vn", "-c:a", "aac", "-b:a", "128k"] if so_audio else
                ["-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-c:a", "aac", "-b:a", "160k"])
        subprocess.run(cmd + [str(saida)], check=True, capture_output=True, timeout=900)
        for f in tmp.iterdir():
            f.unlink()
        tmp.rmdir()
        return saida
    import yt_dlp
    from yt_dlp.utils import download_range_func
    base = destino.with_suffix("")
    op = {
        **opcoes_base(),
        "format": "ba/b" if so_audio else "bv*[height<=1080]+ba/b[height<=1080]/b",
        "download_ranges": download_range_func(None, [(ini, fim)]),
        "outtmpl": str(base) + ".%(ext)s",
        "noplaylist": True,
    }
    if not so_audio:
        op["merge_output_format"] = "mp4"
        op["force_keyframes_at_cuts"] = True
    with yt_dlp.YoutubeDL(op) as ydl:
        ydl.download([url])
    arqs = [a for a in sorted(base.parent.glob(base.name + ".*")) if a.suffix not in (".part", ".ytdl")]
    if not arqs:
        raise RuntimeError("download não gerou arquivo")
    return arqs[0]


def _pcm16k(arquivo: Path):
    """Áudio em float32 mono 16 kHz via ffmpeg (evita depender da versão do PyAV)."""
    import subprocess
    import numpy as np
    bruto = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(arquivo), "-f", "s16le",
                            "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True, timeout=600).stdout
    return np.frombuffer(bruto, np.int16).astype(np.float32) / 32768.0


def transcrever(arquivo: Path, deslocamento: float, modelo: str = "base") -> tuple[list[Trecho], list[tuple[float, float, str]]]:
    """Devolve (trechos por frase, palavras com tempo), já no relógio da transmissão."""
    segs, _ = _modelo(modelo).transcribe(_pcm16k(arquivo), language="pt", vad_filter=True, word_timestamps=True,
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


def segundo_da_hora(i: dict, hora: str, fuso: str = "America/Fortaleza") -> float | None:
    """Converte a hora do relógio (ex.: 02:16) em segundos desde o início da transmissão."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    ini = i.get("release_timestamp") or i.get("timestamp")
    if not ini or not hora:
        return None
    t0 = datetime.fromtimestamp(float(ini), ZoneInfo(fuso))
    hh, mm = (int(x) for x in hora.split(":")[:2])
    alvo = t0.replace(hour=hh, minute=mm, second=0)
    if alvo < t0 - timedelta(hours=1):
        alvo += timedelta(days=1)
    return max(0.0, (alvo - t0).total_seconds())


def achar_frase(url: str, frase: str, janela: int = 600, max_janelas: int = 18,
                hora: str = "") -> tuple[float, dict]:
    """Procura a frase (perto da hora indicada, ou da borda ao vivo para trás)."""
    i = info(url)
    ao_vivo = bool(i.get("is_live") or i.get("live_status") == "is_live")
    fim = duracao_atual(i)
    if fim <= 0:
        raise RuntimeError("não consegui saber a duração da transmissão")
    perto = segundo_da_hora(i, hora)
    if perto is not None:
        janelas = [(perto - 240, perto + 360), (perto - 840, perto - 220), (perto + 340, perto + 940)]
    else:
        janelas = [(fim - (k + 1) * janela - 20, fim - k * janela) for k in range(max_janelas)]
    with tempfile.TemporaryDirectory() as tmp:
        for k, (a, b) in enumerate(janelas):
            a, b = max(0.0, a), min(fim, b)
            if b <= a:
                continue
            log.info("Procurando a frase entre %.0f s e %.0f s", a, b)
            audio = baixar(url, a, b, Path(tmp) / f"a{k}.m4a", so_audio=True, ao_vivo=ao_vivo)
            _, palavras = transcrever(audio, a, "base")
            achou = procurar(palavras, frase)
            if achou is not None:
                return achou, i
            audio.unlink(missing_ok=True)
    raise RuntimeError("não encontrei a frase nas últimas horas da transmissão")
