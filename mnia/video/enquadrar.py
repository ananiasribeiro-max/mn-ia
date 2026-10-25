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
    vazio_acima: int = 0   # na tela dividida: altura (px) acima da janela que deve ficar preta


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


MODELO_ROSTO = Path(__file__).resolve().parent.parent.parent / "assets" / "modelos" / "face_detection_yunet_2023mar.onnx"
FRACAO_ROSTO = 0.30   # altura do rosto ≈ 30% da altura do recorte (enquadramento de ombro para cima)


class _Detector:
    """YuNet (rede neural leve do OpenCV, pega rosto de perfil/olhando para baixo); Haar como reserva."""

    def __init__(self):
        import cv2
        self.cv2 = cv2
        self.yunet = None
        if MODELO_ROSTO.exists() and hasattr(cv2, "FaceDetectorYN"):
            try:
                self.yunet = cv2.FaceDetectorYN.create(str(MODELO_ROSTO), "", (320, 320), 0.6)
            except Exception as e:
                log.warning("YuNet indisponível: %s", e)
        self.haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def __call__(self, img, minimo: int) -> list[tuple[int, int, int, int]]:
        h, w = img.shape[:2]
        if self.yunet is not None:
            self.yunet.setInputSize((w, h))
            _, r = self.yunet.detect(img)
            if r is not None:
                return [tuple(int(v) for v in x[:4]) for x in r if x[3] >= minimo]
            return []
        cinza = self.cv2.cvtColor(img, self.cv2.COLOR_BGR2GRAY)
        return [tuple(int(v) for v in r) for r in self.haar.detectMultiScale(cinza, 1.1, 5, minSize=(minimo,) * 2)]


def planejar(video: Path, passo: float = 0.4, proporcao: float = PROPORCAO, margem_topo: float = 0.22,
             folga_topo: int = 0) -> tuple[int, int, list[Plano]]:
    """margem_topo: onde fica o alto do rosto (fração da altura do recorte).
    folga_topo: quantos px o recorte pode subir acima do quadro (o vídeo é completado com preto em cima),
    para o rosto descer quando há selo/logotipo no alto do modelo. Com folga, o recorte também pode
    "abrir" (zoom out) para o rosto não ficar grande demais em close."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    detector = _Detector()

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
    base_ch = int(H * JANELA_ESQ[3]) // 2 * 2
    if not amostras:
        cw = min(W, int(base_ch * proporcao)) // 2 * 2
        return cw, base_ch, [Plano(0, duracao, (W - cw) // 2, 0, "vazio")]

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

    # 2. em cada plano: tela dividida? qual rosto é o da pessoa-alvo?
    alvo = None
    analise = []   # (t0, t1, tipo, rosto|None)
    for gi, g in enumerate(grupos):
        t0 = 0.0 if gi == 0 else g[0][0]
        t1 = grupos[gi + 1][0][0] if gi + 1 < len(grupos) else duracao
        meio = g[len(g) // 2][1]
        if _tela_dividida(meio):
            rs = detector(meio[:, : int(W * 0.36)], int(H * 0.06))
            r = max(rs, key=lambda r: r[2]) if rs else None
            if r is not None and alvo is None:
                alvo = _assinatura(meio, r)
            analise.append((t0, t1, "dividida", r))
            continue
        rostos = []
        for _, fr in g[:: max(1, len(g) // 3)][:3]:
            for r in detector(fr, int(H * 0.07)):
                if r[1] + r[3] / 2 < H * LIMITE_GC:   # centro do rosto acima do GC
                    rostos.append((fr, r))
        if not rostos:
            analise.append((t0, t1, "sem rosto", None))
            continue
        if alvo is None:
            fr, rosto = max(rostos, key=lambda fr_r: fr_r[1][2])
            alvo = _assinatura(fr, rosto)
            tipo = "alvo"
        else:
            d, rosto = min(((cv2.compareHist(alvo, _assinatura(fr, r), cv2.HISTCMP_BHATTACHARYYA), r)
                            for fr, r in rostos), key=lambda x: x[0])
            tipo = "alvo" if d < 0.45 else "outro"
            if tipo == "outro":
                rosto = max((r for _, r in rostos), key=lambda r: r[2])
        analise.append((t0, t1, tipo, rosto))

    # 3. tamanho único do recorte: abre (zoom out) quando há close, se houver folga para isso
    ch = base_ch
    tem_dividida = any(a[2] == "dividida" for a in analise)
    G = int(H * LIMITE_GC)
    rostos_alvo = [a[3] for a in analise if a[3] is not None and a[2] != "outro"] or \
        [a[3] for a in analise if a[3] is not None]
    if folga_topo and not tem_dividida and rostos_alvo:
        # escolhe o tamanho do recorte em que o rosto maior: (a) fica abaixo do selo (alto >= 26%),
        # (b) tem o queixo acima da caixa de texto (<= 80%), (c) não deixa o GC entrar; e, entre os que
        # servem, o que deixa o rosto mais perto de 30% da altura
        _, yf, _, hf = max(rostos_alvo, key=lambda r: r[3])
        yc = yf + hf
        melhor = None
        for c in range(base_ch, G + folga_topo + 1, 8):
            lo = max(-folga_topo, yc - 0.80 * c)
            hi = min(yf - 0.26 * c, G - c)
            if lo <= hi:
                nota = abs(hf / c - FRACAO_ROSTO)
                if melhor is None or nota < melhor[0]:
                    melhor = (nota, c)
        # nenhum tamanho atende tudo (close muito fechado): abre o máximo; o selo tem prioridade
        ch = melhor[1] if melhor else G + folga_topo
    cw = int(ch * proporcao)
    if cw > W:
        cw, ch = W, int(W / proporcao)
    cw, ch = cw // 2 * 2, ch // 2 * 2
    teto_gc = max(-folga_topo, int(H * LIMITE_GC) - ch)   # pé do recorte acima do GC

    planos: list[Plano] = []
    for t0, t1, tipo, r in analise:
        if tipo == "dividida":
            x, y = int(W * JANELA_ESQ[0]), int(H * JANELA_ESQ[1])
            py = min(y, H - ch)
            if r is not None:
                py = max(-folga_topo, min(py, r[1] - int(ch * margem_topo)))
            planos.append(Plano(t0, t1, min(x, W - cw), py, tipo, vazio_acima=y if py < y else 0))
        elif r is None:
            # sem rosto: centraliza e, se houver folga, desce o quadro para não ficar sob o selo
            planos.append(Plano(t0, t1, (W - cw) // 2, -folga_topo // 2 if folga_topo else min(0, teto_gc), tipo))
        else:
            x, y, w, h = r
            px = min(max(0, x + w // 2 - cw // 2), W - cw)
            # rosto grande: sobe um pouco para o queixo não descer demais
            m = max(min(margem_topo, 0.80 - h / ch), min(margem_topo, 0.26))
            alvo_py = y - int(ch * m)
            lo = max(-folga_topo, y + h - int(0.80 * ch)) if folga_topo else -folga_topo
            py = min(max(lo, alvo_py), max(teto_gc, -folga_topo))
            if folga_topo and y - py < 0.24 * ch:   # rosto sob o selo: desce, mesmo que entre um pouco de GC
                py = max(-folga_topo, y - int(0.26 * ch))
            planos.append(Plano(t0, t1, px, py, tipo))

    # junta planos vizinhos com o mesmo recorte
    juntos: list[Plano] = []
    for p in planos:
        if juntos and abs(juntos[-1].x - p.x) < 8 and abs(juntos[-1].y - p.y) < 8 \
                and juntos[-1].vazio_acima == p.vazio_acima:
            juntos[-1].t1 = p.t1
        else:
            juntos.append(p)
    return cw, ch, juntos


def filtro_crop(cw: int, ch: int, planos: list[Plano], folga_topo: int = 0) -> str:
    """crop com posição que muda por plano (expressão de tempo do ffmpeg).

    Com folga_topo, o quadro ganha uma faixa preta em cima (pad) e o recorte pode subir nela;
    na tela dividida, o que fica acima da janela é pintado de preto no plano correspondente.
    """
    def expr(attr: str, soma: int = 0) -> str:
        e = str(getattr(planos[-1], attr) + soma)
        for p in reversed(planos[:-1]):
            e = f"if(lt(t,{p.t1:.2f}),{getattr(p, attr) + soma},{e})"
        return e
    partes = []
    if folga_topo:
        partes.append(f"pad=iw:ih+{folga_topo}:0:{folga_topo}:black")
        for p in planos:
            if p.vazio_acima:
                partes.append(f"drawbox=x=0:y=0:w=iw:h={folga_topo + p.vazio_acima}:color=black:t=fill:"
                              f"enable='between(t,{p.t0:.2f},{p.t1:.2f})'")
    partes.append(f"crop={cw}:{ch}:'{expr('x')}':'{expr('y', folga_topo)}'")
    return ",".join(partes)
