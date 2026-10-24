from sqlalchemy import select

from mnia.clipping.matinal import rodar_clipping
from mnia.coletores import ItemColetado
from mnia.db import Alerta, Item, sessao
from mnia.radar import pipeline
from mnia.triagem import email_pauta


def test_clipping_gera_secoes(monkeypatch):
    itens = [
        ItemColetado("gov", "Governo (ex.)", "oficial", "Governo do Piauí anuncia concurso com 1.200 vagas", peso=3),
        ItemColetado("a", "Concorrente A", "concorrente", "Prefeitura de Teresina amplia horário dos postos de saúde", peso=3),
    ]
    monkeypatch.setattr(pipeline, "coletar_tudo", lambda f=None: (itens, []))
    pipeline.rodar_radar()
    texto = rodar_clipping()
    assert "CLIPPING MN" in texto
    assert "PRINCIPAIS DO DIA" in texto and "SUGESTÕES DE PAUTA" in texto
    assert "concurso" in texto


def test_clipping_sem_dados_avisa():
    assert "Verificar fontes" in rodar_clipping()


def test_triagem_descarta_publicidade_e_encaminha_denuncia(monkeypatch):
    emails = [
        {"message_id": "<1@x>", "remetente": "Loja <promo@loja.com>",
         "assunto": "Promoção imperdível: 50% de desconto", "texto": "Oferta só hoje", "data": None},
        {"message_id": "<2@x>", "remetente": "Morador <morador@email.com>",
         "assunto": "Denúncia: esgoto a céu aberto no bairro Dirceu", "texto": "Há meses sem solução", "data": None},
    ]
    monkeypatch.setattr(email_pauta, "ler_caixa", lambda dias=2: emails)
    e = email_pauta.rodar_triagem()
    assert e.itens_novos == 2 and e.alertas == 1
    with sessao() as s:
        promo = s.scalars(select(Item).where(Item.titulo.like("Promoção%"))).one()
        assert promo.prioridade == "descartar"
        alerta = s.scalars(select(Alerta).where(Alerta.tipo == "triagem")).one()
        assert "esgoto" in alerta.texto and "Promoção" not in alerta.texto
    # segunda leitura do mesmo e-mail não duplica
    assert email_pauta.rodar_triagem().itens_novos == 0
