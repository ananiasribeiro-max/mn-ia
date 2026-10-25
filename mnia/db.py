"""Banco de dados do MN-IA (SQLAlchemy 2).

SQLite para testes; PostgreSQL em produção (basta trocar MNIA_DATABASE_URL).
"""
from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer,
                        String, Text, create_engine, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import config


def agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # UTC sem fuso (padrão do banco)


class Base(DeclarativeBase):
    pass


class Item(Base):
    """Qualquer coisa que entra no sistema: notícia, e-mail, post, trecho de sessão."""
    __tablename__ = "itens"

    id: Mapped[int] = mapped_column(primary_key=True)
    hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    origem: Mapped[str] = mapped_column(String(30), index=True)       # radar | triagem | ...
    fonte_id: Mapped[str] = mapped_column(String(60), index=True)
    fonte_nome: Mapped[str] = mapped_column(String(120))
    fonte_tipo: Mapped[str] = mapped_column(String(30), index=True)   # proprio | concorrente | oficial ...
    url: Mapped[str | None] = mapped_column(Text)
    titulo: Mapped[str] = mapped_column(Text)
    texto: Mapped[str | None] = mapped_column(Text)
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime)
    coletado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)

    # Análise da IA
    analisado: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    relevancia: Mapped[int | None] = mapped_column(Integer, index=True)       # 0-10
    prioridade: Mapped[str | None] = mapped_column(String(20), index=True)    # urgente|pauta|acompanhar|descartar
    risco: Mapped[str | None] = mapped_column(String(10))                     # verde|amarelo|vermelho
    editoria: Mapped[str | None] = mapped_column(String(30))
    plataformas: Mapped[list | None] = mapped_column(JSON)
    resumo: Mapped[str | None] = mapped_column(Text)
    porque_importa: Mapped[str | None] = mapped_column(Text)
    assunto_chave: Mapped[str | None] = mapped_column(String(200), index=True)  # agrupa itens do mesmo fato
    analise_extra: Mapped[dict | None] = mapped_column(JSON)

    alertado: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class Alerta(Base):
    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("itens.id"))
    tipo: Mapped[str] = mapped_column(String(30))       # urgente | resumo_hora | clipping | triagem | tecnico
    canal: Mapped[str] = mapped_column(String(60))
    texto: Mapped[str] = mapped_column(Text)
    enviado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    sucesso: Mapped[bool] = mapped_column(Boolean, default=True)
    feedback: Mapped[str | None] = mapped_column(String(20))   # util | inutil (fase 2: botões no Telegram)


class Aprovacao(Base):
    """Portão humano: o que foi aprovado/rejeitado por quem (usado a partir da Etapa 2.5)."""
    __tablename__ = "aprovacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("itens.id"))
    modulo: Mapped[str] = mapped_column(String(40))
    conteudo: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pendente")  # pendente|aprovado|rejeitado
    decidido_por: Mapped[str | None] = mapped_column(String(80))
    decidido_em: Mapped[datetime | None] = mapped_column(DateTime)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class Execucao(Base):
    __tablename__ = "execucoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    modulo: Mapped[str] = mapped_column(String(40), index=True)
    inicio: Mapped[datetime] = mapped_column(DateTime, default=agora)
    fim: Mapped[datetime | None] = mapped_column(DateTime)
    itens_novos: Mapped[int] = mapped_column(Integer, default=0)
    itens_analisados: Mapped[int] = mapped_column(Integer, default=0)
    alertas: Mapped[int] = mapped_column(Integer, default=0)
    erros: Mapped[list | None] = mapped_column(JSON)
    sucesso: Mapped[bool] = mapped_column(Boolean, default=True)


class Custo(Base):
    __tablename__ = "custos"

    id: Mapped[int] = mapped_column(primary_key=True)
    modulo: Mapped[str] = mapped_column(String(40), index=True)
    modelo: Mapped[str] = mapped_column(String(60))
    tokens_entrada: Mapped[int] = mapped_column(Integer, default=0)
    tokens_saida: Mapped[int] = mapped_column(Integer, default=0)
    custo_usd: Mapped[float] = mapped_column(Float, default=0.0)
    em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)


# ---------------------------------------------------------------- conexão

_engine = None
_SessionLocal = None


def engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = config().database_url
        if url.startswith("sqlite:///"):
            Path(url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
            # Modo leve: espera até 30 s se outra tarefa estiver gravando e usa WAL
            _engine = create_engine(url, future=True, connect_args={"timeout": 30,
                                                                    "check_same_thread": False})
            from sqlalchemy import event

            @event.listens_for(_engine, "connect")
            def _wal(conn, _):
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=30000")
                cur.close()
        else:
            _engine = create_engine(url, future=True, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def reiniciar_conexao() -> None:
    """Usado nos testes para trocar de banco."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def init_db() -> None:
    Base.metadata.create_all(engine())


@contextmanager
def sessao() -> Iterator[Session]:
    engine()
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ---------------------------------------------------------------- utilidades

def normalizar_titulo(titulo: str) -> str:
    t = titulo.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def gerar_hash(fonte_id: str, titulo: str, url: str | None) -> str:
    base = f"{fonte_id}|{url or ''}|{normalizar_titulo(titulo)}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def item_existe(s: Session, hash_: str) -> bool:
    return s.scalar(select(Item.id).where(Item.hash == hash_)) is not None
