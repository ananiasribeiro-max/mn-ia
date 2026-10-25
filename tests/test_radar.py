from sqlalchemy import select

from mnia.coletores import ItemColetado
from mnia.db import Alerta, Item, sessao
from mnia.llm import extrair_json
from mnia.radar import pipeline
from mnia.radar.classificador import normalizar_analise


def _item(fonte_id, tipo, titulo, texto=None, peso=2):
    return ItemColetado(fonte_id=fonte_id, fonte_nome=fonte_id.upper(), fonte_tipo=tipo,
                        titulo=titulo, texto=texto, url=f"https://{fonte_id}.com/{abs(hash(titulo))}", peso=peso)


def test_deduplicacao():
    lote = [_item("a", "concorrente", "Prefeitura de Teresina anuncia mutirão de limpeza no centro")]
    assert pipeline.gravar_itens(lote, "radar") == 1
    assert pipeline.gravar_itens(lote, "radar") == 0


def test_ciclo_completo_linha_de_base_e_alerta(monkeypatch):
    base = [_item("a", "concorrente", "Feira de artesanato reúne expositores no centro de Teresina")]
    monkeypatch.setattr(pipeline, "coletar_tudo", lambda f=None: (base, []))
    e1 = pipeline.rodar_radar()
    assert e1.alertas == 0  # primeira rodada não alerta

    novos = [
        _item("a", "concorrente", "Incêndio atinge galpão na zona sul de Teresina; bombeiros no local", peso=3),
        _item("mn", "proprio", "Incêndio atinge galpão na zona sul de Teresina, diz Corpo de Bombeiros", peso=3),
        _item("gov", "oficial", "Governo do Piauí anuncia concurso com 1.200 vagas para a educação", peso=3),
    ]
    monkeypatch.setattr(pipeline, "coletar_tudo", lambda f=None: (novos, []))
    e2 = pipeline.rodar_radar()
    assert e2.itens_novos == 3 and e2.itens_analisados == 3
    assert e2.alertas == 1

    with sessao() as s:
        urg = s.scalars(select(Item).where(Item.prioridade == "urgente", Item.fonte_tipo == "concorrente")).one()
        assert urg.alertado
        # MN e concorrente sobre o mesmo fato ficam no mesmo assunto
        mn = s.scalars(select(Item).where(Item.fonte_tipo == "proprio", Item.titulo.like("Incêndio%"))).one()
        assert mn.assunto_chave == urg.assunto_chave
        assert (urg.analise_extra or {}).get("concorrencia") in {"mn_ja_deu", "mn_deu_primeiro"}

    # resumo leva o concurso e não repete o urgente
    assert pipeline.enviar_resumo() == 1
    with sessao() as s:
        tipos = [a.tipo for a in s.scalars(select(Alerta))]
    assert tipos.count("urgente") == 1 and tipos.count("resumo_hora") == 1
    assert pipeline.enviar_resumo() == 0  # nada novo


def test_concorrencia_mn_nao_deu(monkeypatch):
    monkeypatch.setattr(pipeline, "coletar_tudo", lambda f=None: ([], []))
    pipeline.rodar_radar()
    lote = [_item("b", "concorrente", "Prefeitura de Picos decreta emergência por falta de água nos bairros")]
    monkeypatch.setattr(pipeline, "coletar_tudo", lambda f=None: (lote, []))
    pipeline.rodar_radar()
    with sessao() as s:
        it = s.scalars(select(Item)).one()
        assert it.analise_extra["concorrencia"] == "mn_nao_deu"


def test_normalizar_analise_corrige_valores_invalidos():
    a = normalizar_analise({"prioridade": "URGENTÍSSIMO", "risco": "azul", "relevancia": "15",
                            "plataformas": ["tv", "jornal"], "editoria": "xyz",
                            "assunto_chave": "Greve Professores Teresina"})
    assert a["prioridade"] == "acompanhar" and a["risco"] == "amarelo" and a["relevancia"] == 10
    assert a["plataformas"] == ["tv"] and a["editoria"] is None
    assert a["assunto_chave"] == "greve-professores-teresina"


def test_extrair_json_tolera_texto_em_volta():
    assert extrair_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extrair_json('Segue: {"itens": [1, 2]} fim') == {"itens": [1, 2]}


def test_lote_com_falha_nao_derruba_a_rodada(monkeypatch):
    from mnia.llm import ErroLLM
    from mnia.radar import classificador

    original = classificador.classificar

    def classificar_falho(itens, assuntos, modulo="radar"):
        if any("QUEBRA" in i["titulo"] for i in itens):
            raise ErroLLM("resposta sem JSON")
        return original(itens, assuntos, modulo=modulo)

    monkeypatch.setattr(pipeline, "classificar", classificar_falho)
    lote = [_item("a", "concorrente", f"Prefeitura de Teresina anuncia obra numero {n} no bairro Centro")
            for n in range(5)] + [_item("b", "concorrente", "Manchete QUEBRA que a IA nao consegue analisar hoje")]
    pipeline.gravar_itens(lote, "radar")
    assert pipeline.analisar_pendentes("radar") == 5
    with sessao() as s:
        assert s.scalars(select(Item).where(Item.analisado.is_(False))).one().titulo.startswith("Manchete QUEBRA")
