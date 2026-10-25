"""Enquadramento automático do comentarista nos cortes verticais.

Programas de TV mudam de plano o tempo todo: tela dividida (comentarista à esquerda,
arte à direita), plano aberto do comentarista, plano do âncora, plano a dois.
Recortar sempre a mesma região mostra GC, arte e gente errada.

Como funciona:
1. Amostra o trecho a cada 0,4 s e separa os planos (troca brusca de cor = corte de câmera).
2. Em cada plano, detecta rostos acima da faixa do GC (parte de baixo da tela).
3. A pessoa-alvo é a que aparece no início do corte (é de onde a redação mandou cortar);
   nos outros planos, escolhe o rosto cuja roupa/tom mais se parece com o dela.
4. Tela dividida do Central Meio Norte (arte escura à direita): usa a janela da esquerda.
5. Gera um recorte de tamanho fixo que muda de posição só na troca de plano (sem "passeio").
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("mnia.enquadrar")

PROPORCAO = 1080 / 1040        # área de vídeo do modelo MN
LIMITE_GC = 0.72               # abaixo disto (fração da altura) fica o GC
JANELA_ESQ = (0.005, 0.104, 0.352, 0.600)   # janela da comentarista na tela dividida


@dataclass
class Plano:
    t0: float
    t1: float
    x: int
    y: int
    tipo: str


def _hist(img):
    import cv2
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
    cv2.normalize(h, h)
    return h


def _assinatura(frame, rosto):
    """Cor do rosto + tronco: identifica a mesma pessoa em planos diferentes."""
    x, y, w, h = rosto
    H, W = frame.shape[:2]
    x0, x1 = max(0, x - w // 2), min(W, x + w + w // 2)
    y0, y1 = y, min(H, y + h * 3)
    return _hist(frame[y0:y1, x0:x1])


def _tela_dividida(frame) -> bool:
    """Arte escura ocupando a direita e janela clara à esquerda (padrão do Central MN)."""
    H, W = frame.shape[:2]
    direita = frame[int(H * 0.15):int(H * 0.65), int(W * 0.40):int(W * 0.95)]
    esquerda = frame[int(H * 0.15):int(H * 0.65), int(W * 0.02):int(W * 0.34)]
    return direita.mean() < 55 and esquerda.mean() > 90


def planejar(video: Path, passo: float = 0.4, proporcao: float = PROPORCAO) -> tuple[int, int, list[Plano]]:
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    ch = int(H * JANELA_ESQ[3]) // 2 * 2
    cw = min(W, int(ch * proporcao)) // 2 * 2
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    amostras = []   # (t, frame)
    n = 0
    salto = max(1, int(fps * passo))
    while True:
        ok = cap.grab()
        if not ok:
            break
        if n % salto == 0:
            ok, fr = cap.retrieve()
            if ok:
                amostras.append((n / fps, fr))
        n += 1
    cap.release()
    duracao = (total or n) / fps
    if not amostras:
        return cw, ch, [Plano(0, duracao, (W - cw) // 2, 0, "vazio")]

    # 1. separa planos por troca brusca de cor
    grupos, atual, ant = [], [amostras[0]], _hist(amostras[0][1])
    for t, fr in amostras[1:]:
        h = _hist(fr)
        if cv2.compareHist(ant, h, cv2.HISTCMP_CORREL) < 0.55:
            grupos.append(atual)
            atual = []
        atual.append((t, fr))
        ant = h
    grupos.append(atual)

    alvo = None
    planos: list[Plano] = []
    for gi, g in enumerate(grupos):
        t0 = 0.0 if gi == 0 else g[0][0]
        t1 = grupos[gi + 1][0][0] if gi + 1 < len(grupos) else duracao
        meio = g[len(g) // 2][1]
        if _tela_dividida(meio):
            x, y = int(W * JANELA_ESQ[0]), int(H * JANELA_ESQ[1])
            planos.append(Plano(t0, t1, min(x, W - cw), min(y, H - ch), "dividida"))
            if alvo is None:
                cinza = cv2.cvtColor(meio, cv2.COLOR_BGR2GRAY)
                rs = detector.detectMultiScale(cinza[:, : int(W * 0.36)], 1.1, 5, minSize=(int(H * 0.06),) * 2)
                if len(rs):
                    alvo = _assinatura(meio, max(rs, key=lambda r: r[2]))
            continue
        # 2. rostos acima do GC, em até 3 quadros do plano
        rostos = []
        for _, fr in g[:: max(1, len(g) // 3)][:3]:
            cinza = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            for r in detector.detectMultiScale(cinza, 1.1, 5, minSize=(int(H * 0.07),) * 2):
                if r[1] + r[3] < H * LIMITE_GC:
                    rostos.append((fr, tuple(int(v) for v in r)))
        if not rostos:
            planos.append(Plano(t0, t1, (W - cw) // 2, max(0, int(H * LIMITE_GC) - ch), "sem rosto"))
            continue
        # 3. escolhe a pessoa-alvo
        if alvo is None:
            fr, rosto = max(rostos, key=lambda fr_r: fr_r[1][2])
            alvo = _assinatura(fr, rosto)
            tipo = "alvo"
        else:
            dist = [(cv2.compareHist(alvo, _assinatura(fr, r), cv2.HISTCMP_BHATTACHARYYA), r) for fr, r in rostos]
            d, rosto = min(dist, key=lambda x: x[0])
            tipo = "alvo" if d < 0.45 else "outro"
            if tipo == "outro":
                rosto = max((r for _, r in rostos), key=lambda r: r[2])
        x, y, w, h = rosto
        cx = x + w // 2
        px = min(max(0, cx - cw // 2), W - cw)
        py = min(max(0, y - int(ch * 0.22)), max(0, int(H * LIMITE_GC) - ch))
        planos.append(Plano(t0, t1, px, py, tipo))

    # junta planos vizinhos com o mesmo recorte
    juntos: list[Plano] = []
    for p in planos:
        if juntos and abs(juntos[-1].x - p.x) < 8 and abs(juntos[-1].y - p.y) < 8:
            juntos[-1].t1 = p.t1
        else:
            juntos.append(p)
    return cw, ch, juntos


def filtro_crop(cw: int, ch: int, planos: list[Plano]) -> str:
    """crop com posição que muda por plano (expressão de tempo do ffmpeg)."""
    def expr(attr: str) -> str:
        e = str(getattr(planos[-1], attr))
        for p in reversed(planos[:-1]):
            e = f"if(lt(t,{p.t1:.2f}),{getattr(p, attr)},{e})"
        return e
    return f"crop={cw}:{ch}:'{expr('x')}':'{expr('y')}'"
