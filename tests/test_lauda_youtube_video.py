import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from mnia.db import Alerta, Item, gerar_hash, sessao
from mnia.lauda import gerar as lauda
from mnia.youtube import canal, legendas
from mnia.youtube import pipeline as yp
from mnia.video import cortes as vc

VTT_AUTO = """WEBVTT
Kind: captions
Language: pt

00:00:00.000 --> 00:00:02.500
boa noite<00:00:01.000><c> começa</c> agora

00:00:02.500 --> 00:00:02.510
boa noite começa agora

00:00:02.510 --> 00:00:05.000
boa noite começa agora o jornal do piauí

00:00:05.000 --> 00:00:09.000
a prefeitura de teresina anunciou hoje
"""

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/"
 xmlns="http://www.w3.org/2005/Atom">
 <entry><id>yt:video:AAAAAAAAAAA</id><yt:videoId>AAAAAAAAAAA</yt:videoId>
  <title>Jornal do Piauí - edição de sexta</title><published>2026-10-24T22:00:00+00:00</published>
  <media:group><media:description>Edição completa</media:description></media:group></entry>
 <entry><id>yt:video:BBBBBBBBBBB</id><yt:videoId>BBBBBBBBBBB</yt:videoId>
  <title>Entrevista com secretário</title><published>2026-10-23T22:00:00+00:00</published></entry>
</feed>"""


def _video_sintetico(caminho: Path, segundos: int = 4) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=1280x720:rate=30:duration={segundos}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(caminho)], check=True)
    return caminho


# ------------------------------------------------------------------ lauda

def _pauta_forte(titulo, chave, rel=9):
    with sessao() as s:
        s.add(Item(hash=gerar_hash("x", titulo, None), origem="radar", fonte_id="x", fonte_nome="Portal X",
                   fonte_tipo="concorrente", titulo=titulo, url="https://x.com/1", analisado=True,
                   relevancia=rel, prioridade="pauta", risco="verde", editoria="cidades",
                   resumo=titulo, assunto_chave=chave, analise_extra={}))


def test_lauda_gera_uma_vez_por_assunto():
    _pauta_forte("Governo do Piauí anuncia concurso com 1.200 vagas", "concurso-educacao")
    _pauta_forte("Governo confirma concurso da educação com 1.200 vagas", "concurso-educacao")
    _pauta_forte("Assunto fraco", "fraco", rel=5)
    assert lauda.rodar_laudas() == 1
    with sessao() as s:
        a = s.scalars(select(Alerta).where(Alerta.tipo == "lauda")).one()
        assert "CABEÇA" in a.texto and "SONORA — A GRAVAR" in a.texto and "NOTA PÉ" in a.texto
    assert lauda.rodar_laudas() == 0


def test_tempo_estimado():
    l = {"cabeca": " ".join(["palavra"] * 25), "nota_pe": "", "vt": [
        {"tipo": "OFF", "texto": " ".join(["palavra"] * 50)}, {"tipo": "SONORA"}]}
    assert lauda.tempo_estimado(l) == int(75 / 2.5 + 15)


# ------------------------------------------------------------------ youtube

def test_vtt_automatico_sem_eco():
    t = legendas.interpretar_vtt(VTT_AUTO)
    textos = [x.texto for x in t]
    assert textos[0] == "boa noite começa agora"
    assert "o jornal do piauí" in textos
    assert textos[-1] == "a prefeitura de teresina anunciou hoje"
    assert all("<" not in x for x in textos)


def test_feed_e_channel_id():
    v = canal.interpretar_feed(FEED)
    assert [x.video_id for x in v] == ["AAAAAAAAAAA", "BBBBBBBBBBB"]
    assert v[0].url.endswith("v=AAAAAAAAAAA")
    assert canal.extrair_channel_id('{"channelId":"UCabcdefghijklmnopqrstuv"}') == "UCabcdefghijklmnopqrstuv"


def test_primeira_rodada_deixa_so_o_mais_recente_pendente():
    assert yp.registrar_novos(canal.interpretar_feed(FEED)) == 2
    with sessao() as s:
        pend = s.scalars(select(Item).where(Item.origem == "youtube", Item.analisado.is_(False))).all()
        assert [p.analise_extra["video_id"] for p in pend] == ["AAAAAAAAAAA"]
    assert yp.registrar_novos(canal.interpretar_feed(FEED)) == 0


def test_srt_relativo_ao_corte():
    trechos = [legendas.Trecho(10, 14, "primeira frase do trecho"), legendas.Trecho(14, 18, "segunda frase"),
               legendas.Trecho(40, 44, "fora do corte")]
    srt = vc.srt_do_trecho(trechos, 12, 20)
    assert "00:00:00,000 --> 00:00:02,000" in srt and "fora do corte" not in srt


# ------------------------------------------------------------------ vídeo

@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
def test_montar_vertical_gera_1080x1920(tmp_path):
    entrada = _video_sintetico(tmp_path / "in.mp4")
    srt = "1\n00:00:00,500 --> 00:00:03,000\nLegenda de teste do corte\n"
    saida = vc.montar_vertical(entrada, tmp_path / "out.mp4", "Prefeitura anuncia mutirão de limpeza", srt)
    dims = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height", "-of", "csv=p=0", str(saida)],
                          capture_output=True, text=True).stdout.strip()
    assert dims == "1080,1920"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
def test_processar_video_completo(monkeypatch, tmp_path):
    yp.registrar_novos(canal.interpretar_feed(FEED))
    trechos = [legendas.Trecho(i * 5, i * 5 + 5, f"frase número {i} do telejornal") for i in range(24)]
    monkeypatch.setattr(yp.legendas, "obter", lambda url: (trechos, {"duration": 120, "is_live": False}))

    def corte_local(vid, url, c, tr, n):
        bruto = _video_sintetico(tmp_path / f"b{n}.mp4", 3)
        return vc.montar_vertical(bruto, tmp_path / f"c{n}.mp4", c["titulo"], vc.srt_do_trecho(tr, 0, 3))
    monkeypatch.setattr(yp.vc, "gerar_corte", corte_local)

    with sessao() as s:
        item_id = s.scalar(select(Item.id).where(Item.origem == "youtube", Item.analisado.is_(False)))
    r = yp.processar_video(item_id)
    assert r["status"] == "ok" and r["materias"] == 1 and r["cortes"] == 1
    with sessao() as s:
        tipos = sorted(a.tipo for a in s.scalars(select(Alerta)))
        assert tipos == ["materia", "post"]  # o corte simulado não grava alerta, só o log simulado
        assert s.get(Item, item_id).analisado is True


def test_tres_modelos_de_corte_renderizam(tmp_path):
    import shutil
    import subprocess
    import pytest
    if not shutil.which("ffmpeg"):
        pytest.skip("sem ffmpeg")
    from mnia.video import layouts
    from mnia.youtube.legendas import Trecho
    entrada = tmp_path / "in.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                    "-f", "lavfi", "-i", "sine", "-t", "2", "-pix_fmt", "yuv420p", str(entrada)], check=True)
    for m in layouts.MODELOS:
        out = layouts.renderizar(entrada, tmp_path / f"{m}.mp4", m, "Manchete de teste com acentuação: São João",
                                 [Trecho(0, 2, "uma frase de teste para a legenda")], 0, 2)
        info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                               "stream=width,height,sample_aspect_ratio", "-of", "csv=p=0", str(out)],
                              capture_output=True, text=True).stdout.strip()
        assert info == "1080,1920,1:1", (m, info)


def test_procurar_frase_tolera_erros_de_transcricao():
    from mnia.youtube.aovivo import procurar
    texto = "boa noite a todos a onda vermelho do partido dos trabalhador chegou ao nordeste e"
    palavras = [(float(i), float(i) + 0.5, w) for i, w in enumerate(texto.split())]
    assert procurar(palavras, "A onda vermelha do Partido dos Trabalhadores") == 4.0
    assert procurar(palavras, "frase que nunca foi dita aqui de jeito nenhum") is None
