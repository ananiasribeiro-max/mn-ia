"""Demonstração do ciclo completo com dados FICTÍCIOS.

Usa um banco separado (dados/demo.db) e a caixa de entrada para simular
duas rodadas do radar, o resumo de hora e o clipping. Funciona sem chave
de API (modo simulado) ou com chave (Claude de verdade).
"""
from __future__ import annotations

import json
import os

from .config import RAIZ

RODADA_1 = [  # linha de base: o que já existia antes de ligar o sistema
    {"fonte_id": "conc_a", "fonte_nome": "Portal Concorrente A (exemplo)", "fonte_tipo": "concorrente",
     "titulo": "Feira de artesanato reúne expositores no centro de Teresina", "peso": 2},
    {"fonte_id": "mn", "fonte_nome": "Portal Meio News (exemplo)", "fonte_tipo": "proprio",
     "titulo": "Previsão indica calor forte em Teresina nesta semana", "peso": 3},
]

RODADA_2 = [  # o que chega depois
    {"fonte_id": "conc_a", "fonte_nome": "Portal Concorrente A (exemplo)", "fonte_tipo": "concorrente",
     "titulo": "Incêndio atinge galpão na zona sul de Teresina; bombeiros estão no local",
     "texto": "Fumaça pode ser vista de vários bairros. Ainda não há informação sobre feridos.", "peso": 3},
    {"fonte_id": "gov", "fonte_nome": "Governo do Estado (exemplo)", "fonte_tipo": "oficial",
     "titulo": "Governo do Piauí anuncia concurso com 1.200 vagas para a educação",
     "texto": "Edital deve sair em novembro, segundo a secretaria.", "peso": 3},
    {"fonte_id": "conc_b", "fonte_nome": "Portal Concorrente B (exemplo)", "fonte_tipo": "concorrente",
     "titulo": "Governo do Piauí confirma concurso com 1.200 vagas na educação", "peso": 2},
    {"fonte_id": "pref", "fonte_nome": "Prefeitura (exemplo)", "fonte_tipo": "oficial",
     "titulo": "Prefeitura de Parnaíba inicia recuperação de ruas no bairro São José", "peso": 2},
    {"fonte_id": "rede1", "fonte_nome": "Perfil de rede social (exemplo)", "fonte_tipo": "rede",
     "titulo": "Vídeo que viraliza mostra suposta briga em escola de Picos",
     "texto": "[engajamento: 18000] Origem do vídeo não confirmada.", "peso": 2},
    {"fonte_id": "nac", "fonte_nome": "Agência nacional (exemplo)", "fonte_tipo": "nacional",
     "titulo": "Bolsa fecha em leve alta com dados do exterior", "peso": 1},
    {"fonte_id": "mn", "fonte_nome": "Portal Meio News (exemplo)", "fonte_tipo": "proprio",
     "titulo": "Prefeitura de Parnaíba começa obras de recuperação de ruas no São José", "peso": 3},
]


def _depositar(itens: list[dict], nome: str) -> None:
    pasta = RAIZ / "dados" / "entrada"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome).write_text(json.dumps(itens, ensure_ascii=False), encoding="utf-8")


def rodar_demo() -> None:
    demo_db = RAIZ / "dados" / "demo.db"
    if demo_db.exists():
        demo_db.unlink()
    os.environ["MNIA_DATABASE_URL"] = f"sqlite:///{demo_db}"
    from . import config as cfgmod
    from . import db
    cfgmod.config.cache_clear()
    db.reiniciar_conexao()
    db.init_db()

    from .clipping.matinal import rodar_clipping
    from .radar.pipeline import enviar_resumo, rodar_radar

    modo = "SIMULADO (heurística)" if cfgmod.config().modo_simulado else "CLAUDE REAL"
    print(f"\n######## DEMO MN-IA — modo {modo} — dados fictícios ########\n")

    print(">> Rodada 1 (linha de base, sem alertas)")
    _depositar(RODADA_1, "demo_1.json")
    e = rodar_radar(lista_fontes=[])
    print(f"   {e.itens_novos} itens, {e.alertas} alertas\n")

    print(">> Rodada 2 (novidades chegando)")
    _depositar(RODADA_2, "demo_2.json")
    e = rodar_radar(lista_fontes=[])
    print(f"   {e.itens_novos} itens novos, {e.itens_analisados} analisados, {e.alertas} alertas urgentes\n")

    print(">> Resumo de hora")
    enviar_resumo()

    print(">> Clipping matinal")
    rodar_clipping()
    print("######## Fim da demo. Mensagens também em dados/telegram_simulado.log ########")
