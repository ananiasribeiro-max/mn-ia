"""Modelo de corte do programa CENTRAL MEIO NORTE (só quando a redação pedir).

  0–960 px     fala do comentarista (vídeo enquadrado), selo "CENTRAL meionorte" no alto
  960–1920 px  foto(s) estática(s) que ilustram o assunto (1 ou 2 lado a lado)
  no meio      caixa azul com a frase do comentarista entre aspas (Oswald)
  no pé        marca "meio norte" empilhada

Sem legenda queimada: o áudio é a fala e a frase de destaque resume o que foi dito.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from ..config import RAIZ

log = logging.getLogger("mnia.central")
BASE = Path(__file__).resolve().parent.parent.parent / "assets"
OSWALD = BASE / "fontes" / "Oswald-SemiBold.ttf"
SELO = BASE / "marca" / "central_meionorte_branco.png"
MARCA_PE = BASE / "marca" / "meionorte_empilhado_branco.png"
FOTOS = RAIZ / "dados" / "fotos"
AZUL = (28, 72, 240, 255)
PROPORCAO_VIDEO = 1080 / 960


def caixa_citacao(texto: str, destino: Path) -> Path:
    """Caixa azul arredondada com a frase entre aspas, quebrada pela largura real."""
    from PIL import Image, ImageDraw, ImageFont
    texto = texto.strip().strip('"“”').strip()
    texto = f'"{texto}"' if texto else ""
    tam = 70
    while True:
        fonte = ImageFont.truetype(str(OSWALD), tam)
        linhas, atual = [], ""
        for p in texto.split():
            teste = f"{atual} {p}".strip()
            if atual and fonte.getlength(teste) > 860:
                linhas.append(atual)
                atual = p
            else:
                atual = teste
        if atual:
            linhas.append(atual)
        if len(linhas) <= 3 or tam <= 52:
            break
        tam -= 6
    passo = int(tam * 1.12)
    alt = 2 * 34 + passo * len(linhas)
    img = Image.new("RGBA", (934, alt), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, 933, alt - 1), radius=10, fill=AZUL)
    y = 34 - int(tam * 0.12)
    for l in linhas:
        w = fonte.getlength(l)
        d.text(((934 - w) / 2, y), l, font=fonte, fill=(255, 255, 255, 255))
        y += passo
    img.save(destino)
    return destino


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def fotos_da_biblioteca(texto: str, maximo: int = 2) -> list[Path]:
    """Fotos de dados/fotos cujo nome (ex.: lula.jpg, flavio-bolsonaro.jpg) aparece no texto."""
    if not FOTOS.exists():
        return []
    alvo = " " + re.sub(r"[^a-z0-9]+", " ", _norm(texto)) + " "
    achadas = []
    for f in sorted(FOTOS.glob("*")):
        if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp") or f.stem.startswith("tg_"):
            continue
        nome = re.sub(r"[^a-z0-9]+", " ", _norm(f.stem)).strip()
        if nome and f" {nome} " in alvo:
            pos = alvo.index(f" {nome} ")
            achadas.append((pos, f))
    return [f for _, f in sorted(achadas)][:maximo]


def renderizar(entrada: Path, saida: Path, citacao: str, fotos: list[Path] | None = None,
               crop: str | None = None) -> Path:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg não instalado")
    saida.parent.mkdir(parents=True, exist_ok=True)
    pasta = saida.parent / (saida.stem + "_tmp")
    pasta.mkdir(exist_ok=True)
    try:
        caixa = caixa_citacao(citacao, pasta / "caixa.png")
        from PIL import Image
        alt_caixa = Image.open(caixa).height
        fotos = [Path(f) for f in (fotos or []) if Path(f).exists()][:2]
        entradas = ["-i", str(entrada), "-i", str(SELO), "-i", str(MARCA_PE), "-i", str(caixa)]
        for f in fotos:
            entradas += ["-i", str(f)]
        g = [f"[0:v]{crop + ',' if crop else ''}scale=1080:960:force_original_aspect_ratio=increase,"
             "crop=1080:960,setsar=1[vid]",
             "color=c=black:s=1080x1920:r=30[fundo]",
             "[fundo][vid]overlay=0:0:shortest=1[b0]"]
        if len(fotos) == 2:
            g += ["[4:v]scale=540:960:force_original_aspect_ratio=increase,crop=540:960:(iw-540)/2:(ih-960)*0.15,"
                  "setsar=1[f0]",
                  "[5:v]scale=540:960:force_original_aspect_ratio=increase,crop=540:960:(iw-540)/2:(ih-960)*0.15,"
                  "setsar=1[f1]",
                  "[b0][f0]overlay=0:960[b1]", "[b1][f1]overlay=540:960[b2]"]
        elif len(fotos) == 1:
            g += ["[4:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960:(iw-1080)/2:(ih-960)*0.15,"
                  "setsar=1[f0]", "[b0][f0]overlay=0:960[b2]"]
        else:  # sem foto: repete o vídeo desfocado na metade de baixo
            g += ["[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,boxblur=20:2,"
                  "eq=brightness=-0.1,setsar=1[fb]", "[b0][fb]overlay=0:960:shortest=1[b2]"]
        g += ["[1:v]scale=400:-1[selo]", "[b2][selo]overlay=(W-w)/2:100[b3]",
              "[2:v]scale=250:-1[pe]", "[b3][pe]overlay=(W-w)/2:1640[b4]",
              f"[b4][3:v]overlay=73:{960 - alt_caixa // 2}[b5]",
              "[b5]setsar=1[v]"]
        cmd = ["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(g),
               "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "superfast", "-crf", "23",
               "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1", "-aspect", "9:16", "-r", "30",
               "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", str(saida)]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if p.returncode != 0:
            raise RuntimeError("ffmpeg: " + p.stderr[-800:])
        return saida
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
