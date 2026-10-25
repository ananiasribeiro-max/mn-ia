"""Modelos visuais dos cortes verticais (1080x1920, Reels/Shorts/TikTok).

Cada modelo monta: fundo, faixa da marca, manchete, vídeo e legenda dinâmica.
A legenda é um .ass com PlayRes 1080x1920, então tamanhos e posições são em pixels.

Áreas seguras (Reels e Shorts): a interface cobre ~220 px no alto, ~420 px embaixo
e ~130 px na lateral direita. Manchete e legenda ficam fora dessas faixas.

Marca: se existir dados/marca/logo.png (fundo transparente), ele entra no lugar
do nome escrito. Programa, @perfil e chamada vêm do .env (MNIA_CORTE_*).
"""
from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass
from pathlib import Path

from ..config import RAIZ

FONTES = Path(__file__).resolve().parent.parent.parent / "assets" / "fontes"
BOLD = FONTES / "Poppins-Bold.ttf"
MEDIUM = FONTES / "Poppins-Medium.ttf"
ITALICO = FONTES / "Poppins-BoldItalic.ttf"
LOGO = RAIZ / "dados" / "marca" / "logo.png"
LOGO_PADRAO = Path(__file__).resolve().parent.parent.parent / "assets" / "marca" / "logo_central.png"
INTER_XB = FONTES / "InterDisplay-ExtraBold.otf"
INTER_BLACK = FONTES / "InterDisplay-Black.otf"
INTER_MED = FONTES / "InterDisplay-Medium.otf"

AZUL = "0x202C68"
VERMELHO = "0xD71920"
AMARELO = "0xFFD200"

# Enquadramentos prontos (frações do quadro original: x, y, largura, altura).
# "comentarista": janela da esquerda na tela dividida do Central Meio Norte, sem o GC.
QUADROS = {
    "comentarista": (0.005, 0.104, 0.352, 0.600),
}


def quadro_de(valor: str | None) -> tuple[float, float, float, float] | None:
    if not valor:
        return None
    if valor in QUADROS:
        return QUADROS[valor]
    partes = [float(x) for x in valor.split(",")]
    if len(partes) != 4:
        raise ValueError("quadro deve ser um nome conhecido ou x,y,largura,altura")
    return tuple(partes)  # type: ignore[return-value]


MODELOS = {
    "mn": "Modelo MN — vídeo no alto, faixa com selo do programa e horário, manchete com destaque amarelo",
    "card": "Card Meio Norte — evolução do modelo atual (manchete no card branco, vídeo 16:9, faixa do programa)",
    "cheia": "Tela cheia — vídeo ocupando a tela, manchete em tarja vermelha e legenda grande palavra a palavra",
    "manchete": "Manchete de portal — manchete grande em fundo branco, vídeo 4:3 e rodapé da marca",
}


@dataclass
class Marca:
    programa: str = "CENTRAL MEIO NORTE"
    perfil: str = "@centralmeionorte"
    chamada: str = "SEG A SEX · 7H30"
    site: str = "MEIONORTE.COM"
    editoria: str = ""

    @classmethod
    def do_ambiente(cls) -> "Marca":
        return cls(
            programa=os.getenv("MNIA_CORTE_PROGRAMA", cls.programa),
            perfil=os.getenv("MNIA_CORTE_PERFIL", cls.perfil),
            chamada=os.getenv("MNIA_CORTE_CHAMADA", cls.chamada),
            site=os.getenv("MNIA_CORTE_SITE", cls.site),
        )


def _esc(caminho: Path) -> str:
    return str(caminho).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _texto(pasta: Path, nome: str, conteudo: str) -> str:
    arq = pasta / nome
    arq.write_text(conteudo, encoding="utf-8")
    return _esc(arq)


def _dt(rotulo_in: str, rotulo_out: str, arq: str, fonte: Path, tam: int, cor: str, x: str, y: str,
        extra: str = "") -> str:
    return (f"[{rotulo_in}]drawtext=fontfile='{_esc(fonte)}':textfile='{arq}':fontsize={tam}:"
            f"fontcolor={cor}:x={x}:y={y}{extra}[{rotulo_out}]")


# ---------------- legenda .ass ----------------

def _ts_ass(seg: float) -> str:
    seg = max(0.0, seg)
    h, r = divmod(seg, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


ESTILOS_ASS = {
    "mn": ("Inter Display ExtraBold", 56, "&H00FFFFFF", "&H00000000", 1, 5, 2, 0),
    # nome: (fonte, tamanho, cor primária, cor contorno/caixa, borda, contorno, alinhamento, margemV)
    "card": ("Poppins", 66, "&H00682C20", "&H0000D2FF", 3, 16, 2, 0),
    "cheia": ("Poppins", 86, "&H00FFFFFF", "&H00000000", 1, 7, 2, 0),
    "manchete": ("Poppins", 62, "&H00FFFFFF", "&H00000000", 3, 14, 2, 0),
}
# Onde a legenda fica (centro vertical em px) em cada modelo
LEGENDA_Y = {"mn": 965, "card": 1405, "cheia": 1330, "manchete": 1335}


def ass_legenda(modelo: str, trechos, ini: float, fim: float, y: int | None = None) -> str:
    """Legenda em blocos curtos (até ~4 palavras); no modelo 'cheia' a palavra atual fica amarela."""
    fonte, tam, cor, contorno, borda, larg, alin, _ = ESTILOS_ASS[modelo]
    y = y or LEGENDA_Y[modelo]
    cab = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: L,{fonte},{tam},{cor},{cor},{contorno},{contorno},1,0,0,0,100,100,0,0,{borda},{larg},0,"
        f"{alin},90,150,0,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    linhas = []
    for t in trechos:
        if t.fim <= ini or t.inicio >= fim:
            continue
        palavras = t.texto.split()
        if not palavras:
            continue
        a, b = max(t.inicio, ini) - ini, min(t.fim, fim) - ini
        if b - a < 0.3:
            continue
        grupos = [palavras[i:i + 4] for i in range(0, len(palavras), 4)]
        passo = (b - a) / len(grupos)
        for g, grupo in enumerate(grupos):
            gi, gf = a + g * passo, a + (g + 1) * passo
            if modelo in ("cheia",):
                p_passo = (gf - gi) / len(grupo)
                for w in range(len(grupo)):
                    txt = " ".join(("{\\c&H0000D2FF&}" + p + "{\\c&H00FFFFFF&}") if k == w else p
                                   for k, p in enumerate(grupo)).upper()
                    linhas.append(f"Dialogue: 0,{_ts_ass(gi + w * p_passo)},{_ts_ass(gi + (w + 1) * p_passo)},"
                                  f"L,,0,0,0,,{{\\an5\\pos(540,{y})}}{txt}")
            else:
                linhas.append(f"Dialogue: 0,{_ts_ass(gi)},{_ts_ass(gf)},L,,0,0,0,,"
                              f"{{\\an5\\pos(540,{y})}}{' '.join(grupo)}")
    return cab + "\n".join(linhas) + "\n"


# ---------------- modelos ----------------

def _quebrar(texto: str, largura: int, max_linhas: int) -> str:
    linhas = textwrap.wrap(texto, largura)
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas]
        linhas[-1] = linhas[-1].rstrip(" ,.;:") + "…"
    return "\n".join(linhas)


def quebrar_px(texto: str, fonte: Path, tam: int, largura: int) -> list[str]:
    """Quebra por largura real em pixels (mede com a própria fonte)."""
    from PIL import ImageFont
    f = ImageFont.truetype(str(fonte), tam)
    linhas, atual = [], ""
    for p in texto.split():
        teste = f"{atual} {p}".strip()
        if atual and f.getlength(teste) > largura:
            linhas.append(atual)
            atual = p
        else:
            atual = teste
    if atual:
        linhas.append(atual)
    return linhas


def manchete_mn(titulo: str, destaque: str = "", max_linhas: int = 4) -> tuple[list[str], set[int], int]:
    """Linhas da manchete, índices das linhas em destaque e tamanho da fonte."""
    for tam in (76, 68, 60, 54):
        linhas = quebrar_px(titulo, INTER_BLACK, tam, 940)
        if len(linhas) <= max_linhas:
            break
    linhas = linhas[:max_linhas]
    marcadas: set[int] = set()
    d = " ".join(destaque.split()).lower()
    if d and d in " ".join(linhas).lower():
        pos, ini = 0, " ".join(linhas).lower().index(d)
        for i, l in enumerate(linhas):
            a, b = pos, pos + len(l)
            if a < ini + len(d) and b > ini:
                marcadas.add(i)
            pos = b + 1
    if not marcadas and len(linhas) > 1:
        marcadas = {len(linhas) - 2, len(linhas) - 1} if len(linhas) >= 3 else {len(linhas) - 1}
    return linhas, marcadas, tam


def _fotos_mn(f: list[str], ant: str, fotos: list[tuple[Path, str]], primeira_entrada: int,
              pasta: Path, credito: str, topo: int) -> str:
    """Faixa de fotos no pé do modelo MN (1 ou 2 fotos lado a lado, com nome e crédito)."""
    n = len(fotos)
    alt = 300
    larg = 952 if n == 1 else 460
    for i, (_, nome) in enumerate(fotos):
        x = 64 + i * (larg + 32)
        f.append(f"[{primeira_entrada + i}:v]scale={larg}:{alt}:force_original_aspect_ratio=increase,"
                 f"crop={larg}:{alt}:(iw-{larg})/2:(ih-{alt})*0.2,setsar=1[foto{i}]")
        f.append(f"[{ant}][foto{i}]overlay={x}:{topo}[pf{i}]")
        ant = f"pf{i}"
        if nome:
            f.append(_dt(ant, f"pn{i}", _texto(pasta, f"nome{i}.txt", nome.upper()), INTER_BLACK, 28, "white",
                         str(x + 14), str(topo + alt - 50), f":box=1:boxcolor={VERMELHO}:boxborderw=10"))
            ant = f"pn{i}"
    if credito:
        f.append(_dt(ant, "pcred", _texto(pasta, "credito.txt", credito), INTER_MED, 20, "white@0.75",
                     "1016-text_w", str(topo + alt + 10)))
        ant = "pcred"
    return ant


def filtros(modelo: str, titulo: str, marca: Marca, pasta: Path, ass: Path | None,
            tem_logo: bool, destaque: str = "", fotos: list[tuple[Path, str]] | None = None,
            credito: str = "") -> tuple[list[str], str]:
    """Devolve (lista de filtros, rótulo final). Entrada 0 = vídeo; entrada 1 = logo (se houver)."""
    f: list[str] = []
    leg = f"subtitles='{_esc(ass)}':fontsdir='{_esc(FONTES)}'" if ass else "null"

    if modelo == "mn":
        AZUL_FX, AZUL_FD, AMAR = "0x141F45", "0x1E2F63", "0xFFC72C"
        f += [
            f"color=c={AZUL_FD}:s=1080x1920:r=30[fundo]",
            "[0:v]scale=1080:1040:force_original_aspect_ratio=increase,crop=1080:1040,setsar=1[vid]",
            "[fundo][vid]overlay=0:0:shortest=1[b00]",
            f"[b00]{leg}[b0]",
            f"[b0]drawbox=x=0:y=1040:w=1080:h=160:color={AZUL_FX}:t=fill,"
            "drawbox=x=713:y=1078:w=2:h=84:color=0x3F4F86:t=fill[b1]",
        ]
        rot = "b1"
        x_nome = 60
        if tem_logo:
            f += ["[1:v]scale=116:116[logo]", "[b1][logo]overlay=56:1062[b2]"]
            rot, x_nome = "b2", 195
        f += [
            _dt(rot, "c1", _texto(pasta, "prog.txt", marca.programa), INTER_BLACK, 34, "white", str(x_nome), "1086"),
            _dt("c1", "c2", _texto(pasta, "perfil.txt", marca.perfil), INTER_MED, 26, "0xC9D1EA", str(x_nome), "1131"),
            _dt("c2", "c3", _texto(pasta, "chamada.txt", marca.chamada), INTER_BLACK, 30, "white",
                "1022-text_w", "1085"),
            _dt("c3", "c4", _texto(pasta, "marca.txt", "meionorte"), INTER_BLACK, 34, "white",
                "1022-text_w", "1122"),
        ]
        linhas, marcadas, tam = manchete_mn(titulo, destaque, 3 if fotos else 4)
        passo = int(tam * 1.04)
        ant = "c4"
        for i, l in enumerate(linhas):
            y = 1268 + i * passo
            extra = (f":box=1:boxcolor={AMAR}:boxborderw=8" if i in marcadas else "")
            cor = AZUL_FD if i in marcadas else "white"
            x = "72" if i in marcadas else "64"
            f.append(_dt(ant, f"h{i}", _texto(pasta, f"l{i}.txt", l), INTER_BLACK, tam, cor, x, str(y), extra))
            ant = f"h{i}"
        if fotos:
            fim_manchete = 1268 + len(linhas) * passo
            topo = min(max(fim_manchete + 30, 1540), 1580)
            ant = _fotos_mn(f, ant, fotos[:2], 2 if tem_logo else 1, pasta, credito, topo)
        f.append(f"[{ant}]setsar=1[v]")
        return f, "[v]"

    if modelo == "card":
        manchete = _quebrar(titulo, 27, 4)
        n = manchete.count("\n") + 1
        topo_card, alt_card = 230, 175 + n * 86 + 30
        y_video = topo_card + alt_card
        f += [
            f"color=c={AZUL}:s=1080x1920:r=30[fundo]",
            "[0:v]scale=1080:-2,setsar=1[vid]",
            f"[fundo][vid]overlay=0:{y_video}:shortest=1[b0]",
            f"[b0]drawbox=x=0:y={topo_card}:w=1080:h={alt_card}:color=white:t=fill[b1]",
            _dt("b1", "b2", _texto(pasta, "site.txt", f"SAIBA MAIS EM {marca.site}"), ITALICO, 30,
                "white@0.85", "60", "150"),
        ]
        if tem_logo:
            f += ["[1:v]scale=-1:96[logo]", f"[b2][logo]overlay=60:{topo_card + 34}[b3]"]
            x_nome = "190"
        else:
            f += [f"[b2]drawbox=x=60:y={topo_card + 40}:w=10:h=86:color={VERMELHO}:t=fill[b3]"]
            x_nome = "92"
        f += [
            _dt("b3", "b4", _texto(pasta, "prog.txt", marca.programa), BOLD, 40, AZUL, x_nome,
                str(topo_card + 38)),
            _dt("b4", "b5", _texto(pasta, "perfil.txt", marca.perfil), MEDIUM, 32, "0x6B7280", x_nome,
                str(topo_card + 90)),
            _dt("b5", "b6", _texto(pasta, "titulo.txt", manchete), BOLD, 58, "0x111111", "60",
                str(topo_card + 165), ":line_spacing=4"),
            # faixa do programa logo abaixo do vídeo (vídeo 16:9 = 608 px)
            f"[b6]drawbox=x=0:y={y_video + 608}:w=1080:h=96:color=0x16204F:t=fill[b7]",
            _dt("b7", "b8", _texto(pasta, "chamada.txt", marca.chamada), BOLD, 34, "white", "60",
                f"{y_video + 608 + 28}"),
            _dt("b8", "b9", _texto(pasta, "marca.txt", "meionorte"), BOLD, 44, "white", "w-text_w-60",
                f"{y_video + 608 + 18}"),
            f"[b9]{leg},setsar=1[v]",
        ]
        return f, "[v]"

    if modelo == "cheia":
        manchete = _quebrar(titulo.upper(), 24, 3)
        f += [
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[vid]",
            # leve escurecimento geral para dar leitura ao texto
            "[vid]eq=brightness=-0.06[b0]",
            _dt("b0", "b2", _texto(pasta, "prog.txt", f" {marca.programa} "), BOLD, 32, "white", "60", "250",
                f":box=1:boxcolor={AZUL}:boxborderw=14"),
            _dt("b2", "b3", _texto(pasta, "titulo.txt", manchete), BOLD, 58, "white", "60", "320",
                f":line_spacing=14:box=1:boxcolor={VERMELHO}@0.95:boxborderw=16"),
            _dt("b3", "b4", _texto(pasta, "perfil.txt", marca.perfil), MEDIUM, 34, "white@0.9", "60", "1490"),
            f"[b4]{leg},setsar=1[v]",
        ]
        if tem_logo:
            f[-1] = f"[b4]{leg}[b5]"
            f += ["[1:v]scale=-1:70[logo]", "[b5][logo]overlay=W-w-150:250,setsar=1[v]"]
        return f, "[v]"

    if modelo == "manchete":
        manchete = _quebrar(titulo, 24, 4)
        n = manchete.count("\n") + 1
        y_video = 330 + n * 96 + 40
        f += [
            "color=c=white:s=1080x1920:r=30[fundo]",
            "[0:v]scale=1080:810:force_original_aspect_ratio=increase,crop=1080:810,setsar=1[vid]",
            f"[fundo][vid]overlay=0:{y_video}:shortest=1[b0]",
            f"[b0]drawbox=x=0:y=0:w=1080:h=220:color={AZUL}:t=fill[b1]",
            _dt("b1", "b2", _texto(pasta, "site.txt", marca.site.lower()), BOLD, 34, "white@0.9", "60", "150"),
            _dt("b2", "b3", _texto(pasta, "prog.txt", f" {marca.programa} "), BOLD, 30, "white", "60", "252",
                f":box=1:boxcolor={VERMELHO}:boxborderw=12"),
            _dt("b3", "b4", _texto(pasta, "titulo.txt", manchete), BOLD, 66, "0x111111", "60", "330",
                ":line_spacing=4"),
            f"[b4]drawbox=x=0:y={y_video + 810}:w=1080:h=12:color={VERMELHO}:t=fill[b5]",
            _dt("b5", "b6", _texto(pasta, "chamada.txt", f"{marca.chamada}  ·  {marca.perfil}"), BOLD, 32,
                AZUL, "60", f"{y_video + 810 + 40}"),
            f"[b6]{leg},setsar=1[v]",
        ]
        if tem_logo:
            f[-1] = f"[b6]{leg}[b7]"
            f += ["[1:v]scale=-1:80[logo]", "[b7][logo]overlay=W-w-60:120,setsar=1[v]"]
        return f, "[v]"

    raise ValueError(f"modelo de corte desconhecido: {modelo}")


def legenda_y(modelo: str, titulo: str) -> int:
    """Centro vertical da legenda, ajustado à altura da manchete em cada modelo."""
    if modelo == "mn":
        return 965
    if modelo == "card":
        n = _quebrar(titulo, 27, 4).count("\n") + 1
        y_video = 230 + 175 + n * 86 + 30
        abaixo = y_video + 608 + 96 + 75
        # sem espaço acima da área da interface: legenda vai para o pé do vídeo
        return abaixo if abaixo <= 1440 else y_video + 608 - 75
    if modelo == "manchete":
        n = _quebrar(titulo, 24, 4).count("\n") + 1
        y_video = 330 + n * 96 + 40
        return min(y_video + 810 - 90, 1440)
    return LEGENDA_Y[modelo]


def renderizar(entrada: Path, saida: Path, modelo: str, titulo: str, trechos, ini: float, fim: float,
               marca: Marca | None = None, duracao_max: float | None = None, destaque: str = "",
               quadro: tuple[float, float, float, float] | None = None, crop: str | None = None,
               fotos: list[tuple[Path, str]] | None = None, credito: str = "") -> Path:
    """Monta o corte vertical no modelo escolhido. trechos em tempo do vídeo original; ini/fim do corte."""
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg não instalado")
    marca = marca or Marca.do_ambiente()
    saida.parent.mkdir(parents=True, exist_ok=True)
    pasta = saida.parent / (saida.stem + "_tmp")
    pasta.mkdir(exist_ok=True)
    try:
        ass = pasta / "legenda.ass"
        ass.write_text(ass_legenda(modelo, trechos, ini, fim, legenda_y(modelo, titulo)), encoding="utf-8")
        logo = LOGO if LOGO.exists() else (LOGO_PADRAO if modelo == "mn" and LOGO_PADRAO.exists() else None)
        fotos = [(Path(a), n) for a, n in (fotos or []) if Path(a).exists()][:2] if modelo == "mn" else []
        grafo, rotulo = filtros(modelo, titulo, marca, pasta, ass, logo is not None, destaque, fotos, credito)
        if quadro and not crop:
            x, y, w, h = quadro
            crop = f"crop=trunc(iw*{w}/2)*2:trunc(ih*{h}/2)*2:trunc(iw*{x}):trunc(ih*{y})"
        if crop:
            grafo = [g.replace("[0:v]", "[src]") for g in grafo]
            grafo.insert(0, f"[0:v]{crop}[src]")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(entrada)]
        if logo:
            cmd += ["-i", str(logo)]
        for arq, _ in fotos:
            cmd += ["-i", str(arq)]
        cmd += ["-filter_complex", ";".join(grafo), "-map", rotulo, "-map", "0:a?"]
        if duracao_max:
            cmd += ["-t", f"{duracao_max:.2f}"]
        cmd += ["-c:v", "libx264", "-preset", "superfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-profile:v", "high", "-level", "4.1", "-aspect", "9:16", "-r", "30",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", str(saida)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if proc.returncode != 0:
            raise RuntimeError("ffmpeg: " + proc.stderr[-800:])
        return saida
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
