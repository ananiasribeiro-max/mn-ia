import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def banco_temporario(tmp_path, monkeypatch):
    """Cada teste roda num banco SQLite novo, em modo simulado e sem Telegram."""
    monkeypatch.setenv("MNIA_DATABASE_URL", f"sqlite:///{tmp_path / 'teste.db'}")
    monkeypatch.setenv("MNIA_SIMULADO", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    from mnia import config as cfg
    from mnia import db
    cfg.config.cache_clear()
    db.reiniciar_conexao()
    db.init_db()
    yield
    db.reiniciar_conexao()
    cfg.config.cache_clear()
