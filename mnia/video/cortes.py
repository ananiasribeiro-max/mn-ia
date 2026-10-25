"""Cortes verticais (9:16) legendados a partir dos vídeos do canal.

1. Baixa SÓ o trecho escolhido (yt-dlp com intervalo), não o vídeo inteiro.
2. Monta o vertical 1080x1920: fundo desfocado + vídeo original centralizado.
3. Título do corte no alto da tela e legenda (da transcrição) embaixo.
4. Envia ao Telegram para o produtor digital aprovar antes de publicar.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

from ..config import RAIZ
from ..youtube.legendas import Trecho, opcoes_base

log = logging.getLogger("mnia.cortes")
PASTA = RAIZ / "dados" / "cortes"
FONTE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


class ErroCorte(RuntimeError):
    pass


def _ts_srt(seg: float) -> str:
    seg = max(0.0, seg)
    h, r = divmod(seg, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def srt_do_trecho(trechos: list[Trecho], ini: float, fim: float, max_chars: int = 34) -> str:
    """Legenda do intervalo [ini, fim], com tempos relativos ao começo do corte."""
    blocos, n = [], 1
    for t in trechos:
        if t.fim <= ini or t.inicio >= fim:
            continue
        a, b = max(t.inicio, ini) - ini, min(t.fim, fim) - ini
        linhas = textwrap.wrap(t.texto, max_chars)[:2]
        if not linhas or b - a < 0.3:
            continue
        blocos.append(f"{n}\n{_ts_srt(a)} --> {_ts_srt(b)}\n" + "\n".join(linhas) + "\n")
        n += 1
    return "\n".join(blocos)


def nome_seguro(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", texto.lower())[:40].strip("-") or "corte"


def baixar_trecho(video_url: str, ini: float, fim: float, destino: Path) -> Path:
    import yt_dlp
    from yt_dlp.utils import download_range_func

    destino.parent.mkdir(parents=True, exist_ok=True)
    base = destino.with_suffix("")
    opcoes = {
        **opcoes_base(),
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "download_ranges": download_range_func(None, [(ini, fim)]),
        "force_keyframes_at_cuts": True,
        "outtmpl": str(base) + ".%(ext)s",
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opcoes) as ydl:
        ydl.download([video_url])
    arquivos = sorted(base.parent.glob(base.name + ".*"))
    videos = [a for a in arquivos if a.suffix in (".mp4", ".mkv", ".webm")]
    if not videos:
        raise ErroCorte("download do trecho não gerou arquivo de vídeo")
    return videos[0]


def _escapar_drawtext(caminho: Path) -> str:
    return str(caminho).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def montar_vertical(entrada: Path, saida: Path, titulo: str, srt: str) -> Path:
    if not shutil.which("ffmpeg"):
        raise ErroCorte("ffmpeg não instalado")
    pasta = saida.parent
    pasta.mkdir(parents=True, exist_ok=True)
    arq_titulo = pasta / (saida.stem + "_titulo.txt")
    arq_titulo.write_text("\n".join(textwrap.wrap(titulo.upper(), 22)[:3]), encoding="utf-8")
    arq_srt = pasta / (saida.stem + ".srt")
    arq_srt.write_text(srt or "", encoding="utf-8")

    filtros = [
        "[0:v]split=2[a][b]",
        "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:2,eq=brightness=-0.15[fundo]",
        "[b]scale=1080:-2[frente]",
        "[fundo][frente]overlay=(W-w)/2:(H-h)/2[base]",
        (f"[base]drawtext=fontfile={FONTE}:textfile='{_escapar_drawtext(arq_titulo)}':"
         "fontcolor=white:fontsize=64:line_spacing=12:box=1:boxcolor=0xC8102E@0.92:boxborderw=24:"
         "x=(w-text_w)/2:y=270[tit]"),
    ]
    if srt.strip():
        estilo = ("FontName=DejaVu Sans,Bold=1,FontSize=9,PrimaryColour=&H00FFFFFF,"
                  "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=48")
        filtros.append(f"[tit]subtitles='{_escapar_drawtext(arq_srt)}':force_style='{estilo}',setsar=1[v]")
    else:
        filtros.append("[tit]setsar=1[v]")
    saida_video = "[v]"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(entrada),
           "-filter_complex", ";".join(filtros), "-map", saida_video, "-map", "0:a?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-level", "4.1", "-aspect", "9:16",
           "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", "-r", "30", str(saida)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise ErroCorte("ffmpeg: " + proc.stderr[-500:])
    for tmp in (arq_titulo, arq_srt):
        tmp.unlink(missing_ok=True)
    return saida


def gerar_capa(video: Path) -> Path | None:
    """Miniatura 180x320 (exigência do Telegram para mostrar o vídeo em pé)."""
    capa = video.with_suffix(".jpg")
    proc = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(video), "-frames:v", "1",
                           "-vf", "scale=180:320,setsar=1", "-q:v", "4", str(capa)], capture_output=True, timeout=60)
    return capa if proc.returncode == 0 and capa.exists() else None


def duracao(video: Path) -> int:
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                           str(video)], capture_output=True, text=True, timeout=30)
    try:
        return int(round(float(proc.stdout.strip())))
    except ValueError:
        return 0


def gerar_corte(video_id: str, video_url: str, corte: dict, trechos: list[Trecho], n: int,
                modelo: str | None = None) -> Path:
    import os
    from . import layouts
    modelo = modelo or os.getenv("MNIA_CORTE_MODELO", "mn")
    pedido = corte.get("quadro") or os.getenv("MNIA_CORTE_QUADRO", "auto")
    quadro = None if pedido == "auto" else layouts.quadro_de(pedido)
    ini, fim = float(corte["ini_s"]), float(corte["fim_s"])
    pasta = PASTA / video_id
    bruto = baixar_trecho(video_url, ini, fim, pasta / f"bruto_{n}.mp4")
    try:
        saida = pasta / f"{n:02d}-{modelo}-{nome_seguro(corte.get('titulo', 'corte'))}.mp4"
        crop = None
        if pedido == "auto":
            from . import enquadrar
            try:
                cw, ch, planos = enquadrar.planejar(bruto)
                crop = enquadrar.filtro_crop(cw, ch, planos)
                corte["planos"] = [(round(p.t0, 1), round(p.t1, 1), p.x, p.y, p.tipo) for p in planos]
                log.info("Enquadramento %s: %s", video_id, corte["planos"])
            except Exception as e:  # sem OpenCV ou vídeo estranho: segue sem recorte
                log.warning("Enquadramento automático falhou: %s", e)
        return layouts.renderizar(bruto, saida, modelo, corte.get("titulo", ""), trechos, ini, fim,
                                  destaque=corte.get("destaque", ""), quadro=quadro, crop=crop,
                                  fotos=corte.get("fotos"), credito=corte.get("credito", ""))
    finally:
        bruto.unlink(missing_ok=True)


def comparar_modelos(video_id: str, video_url: str, corte: dict, trechos: list[Trecho]) -> list[tuple[str, Path]]:
    """Mesmo trecho nos três modelos, para a equipe escolher o visual."""
    from . import layouts
    ini, fim = float(corte["ini_s"]), float(corte["fim_s"])
    pasta = PASTA / video_id
    bruto = baixar_trecho(video_url, ini, fim, pasta / "bruto_modelos.mp4")
    try:
        return [(m, layouts.renderizar(bruto, pasta / f"modelo-{m}.mp4", m, corte.get("titulo", ""),
                                       trechos, ini, fim, destaque=corte.get("destaque", "")))
                for m in layouts.MODELOS]
    finally:
        bruto.unlink(missing_ok=True)


def limpar_antigos(dias: int = 7) -> int:
    """Apaga cortes com mais de N dias para não lotar o disco."""
    import time
    if not PASTA.exists():
        return 0
    limite, n = time.time() - dias * 86400, 0
    for arq in PASTA.rglob("*.mp4"):
        if arq.stat().st_mtime < limite:
            arq.unlink(missing_ok=True)
            n += 1
    return n
