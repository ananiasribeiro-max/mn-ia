"""Linha de comando do MN-IA.

    python -m mnia init-db         cria as tabelas
    python -m mnia status          verifica banco, Claude e Telegram
    python -m mnia testar-fontes   testa cada fonte do fontes.yaml
    python -m mnia radar           roda uma rodada do radar
    python -m mnia resumo          envia o resumo do radar agora
    python -m mnia clipping        gera e envia o clipping agora
    python -m mnia triagem         roda a triagem do e-mail agora
    python -m mnia saude           envia o relatório técnico
    python -m mnia rodar           liga tudo no agendador (modo servidor)
    python -m mnia demo            demonstração completa com dados de exemplo
"""
from __future__ import annotations

import argparse
import logging
import sys

from .config import config, fontes


def _log():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def cmd_status() -> int:
    from sqlalchemy import text

    from .db import engine, init_db
    from .telegram import enviar
    cfg = config()
    ok = True
    try:
        init_db()
        with engine().connect() as c:
            c.execute(text("select 1"))
        print("✅ Banco conectado:", cfg.database_url.split("@")[-1])
    except Exception as e:
        ok = False
        print("❌ Banco:", e)
    if cfg.modo_simulado:
        print("⚠️  Claude em MODO SIMULADO (sem ANTHROPIC_API_KEY ou MNIA_SIMULADO=1)")
    else:
        try:
            from .llm import chamar
            r = chamar(modulo="status", tarefa='Responda {"ok": true}', conteudo="teste",
                       modelo=cfg.modelo_classificacao, max_tokens=20)
            print("✅ Claude respondendo:", r)
        except Exception as e:
            ok = False
            print("❌ Claude:", e)
    print("✅ Telegram" if cfg.telegram_token else "⚠️  Telegram sem token (mensagens vão para o console)")
    enviar(cfg.chat_tecnico, "🧪 MN-IA: teste de status OK", tipo="tecnico")
    print(f"ℹ️  {len(fontes())} fontes ativas")
    return 0 if ok else 1


def cmd_testar_fontes() -> int:
    from .coletores import coletar_fonte
    falhas = 0
    for f in fontes():
        try:
            itens = coletar_fonte(f)
            marca = "✅" if itens else "⚠️ "
            print(f"{marca} {f['id']:<16} {len(itens):>3} itens  {f['url']}")
            if itens:
                print(f"      ex.: {itens[0].titulo[:90]}")
            else:
                falhas += 1
        except Exception as e:
            falhas += 1
            print(f"❌ {f['id']:<16} {type(e).__name__}: {str(e)[:80]}")
    print(f"\n{len(fontes()) - falhas}/{len(fontes())} fontes funcionando.")
    return 0


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="mnia", description="MN-IA — IA como infraestrutura do Meio Norte")
    p.add_argument("comando", choices=["init-db", "status", "testar-fontes", "radar", "resumo",
                                       "clipping", "triagem", "saude", "rodar", "demo"])
    a = p.parse_args(argv)
    _log()

    from .db import init_db
    init_db()

    if a.comando == "init-db":
        print("Tabelas criadas.")
    elif a.comando == "status":
        sys.exit(cmd_status())
    elif a.comando == "testar-fontes":
        sys.exit(cmd_testar_fontes())
    elif a.comando == "radar":
        from .radar.pipeline import rodar_radar
        e = rodar_radar()
        print(f"Radar: {e.itens_novos} novos, {e.itens_analisados} analisados, {e.alertas} alertas.")
    elif a.comando == "resumo":
        from .radar.pipeline import enviar_resumo
        print(f"{enviar_resumo()} itens no resumo.")
    elif a.comando == "clipping":
        from .clipping.matinal import rodar_clipping
        rodar_clipping()
    elif a.comando == "triagem":
        from .triagem.email_pauta import rodar_triagem
        e = rodar_triagem()
        print(f"Triagem: {e.itens_novos} e-mails novos, {e.alertas} encaminhados.")
    elif a.comando == "saude":
        from .agendador import relatorio_saude
        from .telegram import enviar
        enviar(config().chat_tecnico, relatorio_saude(), tipo="tecnico")
    elif a.comando == "rodar":
        from .agendador import iniciar
        iniciar()
    elif a.comando == "demo":
        from .demo import rodar_demo
        rodar_demo()
