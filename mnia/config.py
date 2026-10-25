"""Configuração central do MN-IA.

Lê variáveis de ambiente (arquivo .env) e os YAML de config/.
Nenhuma chave fica no código.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
PASTA_CONFIG = Path(os.getenv("MNIA_CONFIG_DIR", RAIZ / "config"))


def _carregar_env(caminho: Path) -> None:
    """Carrega um .env simples (CHAVE=valor) sem dependência extra."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


_carregar_env(RAIZ / ".env")


def _bool(nome: str, padrao: bool = False) -> bool:
    return os.getenv(nome, str(int(padrao))).strip().lower() in {"1", "true", "sim", "yes"}


@dataclass
class Config:
    # Banco
    database_url: str = field(default_factory=lambda: os.getenv(
        "MNIA_DATABASE_URL", f"sqlite:///{RAIZ / 'dados' / 'mnia.db'}"))

    # Claude
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    modelo_classificacao: str = field(default_factory=lambda: os.getenv(
        "MNIA_MODELO_CLASSIFICACAO", "claude-haiku-5-5"))
    modelo_redacao: str = field(default_factory=lambda: os.getenv(
        "MNIA_MODELO_REDACAO", "claude-sonnet-5-5"))
    modelo_analise: str = field(default_factory=lambda: os.getenv(
        "MNIA_MODELO_ANALISE", "claude-opus-5-5"))

    # Telegram
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    chat_radar: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_RADAR", ""))
    chat_clipping: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_CLIPPING", ""))
    chat_triagem: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_TRIAGEM", ""))
    chat_tecnico: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_TECNICO", ""))
    # Produção (laudas) e Digital (matérias, títulos, cortes). Sem grupo próprio,
    # usam o grupo do radar, para nada se perder.
    chat_producao: str = field(default_factory=lambda: os.getenv(
        "TELEGRAM_CHAT_PRODUCAO", os.getenv("TELEGRAM_CHAT_RADAR", "")))
    chat_digital: str = field(default_factory=lambda: os.getenv(
        "TELEGRAM_CHAT_DIGITAL", os.getenv("TELEGRAM_CHAT_RADAR", "")))
    # Canal só de cortes (Cortes MN); sem ele, os cortes vão para o grupo digital/radar
    chat_cortes: str = field(default_factory=lambda: os.getenv(
        "TELEGRAM_CHAT_CORTES", os.getenv("TELEGRAM_CHAT_DIGITAL", os.getenv("TELEGRAM_CHAT_RADAR", ""))))

    # YouTube / vídeo
    youtube_canal: str = field(default_factory=lambda: os.getenv(
        "MNIA_YOUTUBE_CANAL", "https://www.youtube.com/@meionortemais"))
    youtube_intervalo_min: int = field(default_factory=lambda: int(os.getenv("MNIA_YOUTUBE_INTERVALO_MIN", "15")))
    youtube_max_videos: int = field(default_factory=lambda: int(os.getenv("MNIA_YOUTUBE_MAX_VIDEOS", "3")))
    cortes_por_video: int = field(default_factory=lambda: int(os.getenv("MNIA_CORTES_POR_VIDEO", "1")))
    cortes_ligados: bool = field(default_factory=lambda: _bool("MNIA_CORTES_LIGADOS", True))

    # Laudas
    laudas_por_hora: int = field(default_factory=lambda: int(os.getenv("MNIA_LAUDAS_POR_HORA", "3")))
    lauda_relevancia_minima: int = field(default_factory=lambda: int(os.getenv("MNIA_LAUDA_RELEVANCIA_MINIMA", "8")))

    # E-mail de pauta (triagem)
    imap_host: str = field(default_factory=lambda: os.getenv("IMAP_HOST", ""))
    imap_usuario: str = field(default_factory=lambda: os.getenv("IMAP_USUARIO", ""))
    imap_senha: str = field(default_factory=lambda: os.getenv("IMAP_SENHA", ""))
    imap_pasta: str = field(default_factory=lambda: os.getenv("IMAP_PASTA", "INBOX"))

    # Comportamento
    simulado: bool = field(default_factory=lambda: _bool("MNIA_SIMULADO", False))
    fuso: str = field(default_factory=lambda: os.getenv("MNIA_FUSO", "America/Fortaleza"))
    radar_intervalo_min: int = field(default_factory=lambda: int(os.getenv("MNIA_RADAR_INTERVALO_MIN", "5")))
    radar_resumo_horario: bool = field(default_factory=lambda: _bool("MNIA_RADAR_RESUMO_HORARIO", True))
    # individual: cada tópico relevante vai sozinho, a cada rodada (5 min); resumo: um resumo por hora
    radar_modo: str = field(default_factory=lambda: os.getenv("MNIA_RADAR_MODO", "individual"))
    radar_max_envios: int = field(default_factory=lambda: int(os.getenv("MNIA_RADAR_MAX_ENVIOS", "8")))
    clipping_horario: str = field(default_factory=lambda: os.getenv("MNIA_CLIPPING_HORARIO", "05:30"))
    triagem_intervalo_min: int = field(default_factory=lambda: int(os.getenv("MNIA_TRIAGEM_INTERVALO_MIN", "10")))
    relevancia_minima_alerta: int = field(default_factory=lambda: int(os.getenv("MNIA_RELEVANCIA_MINIMA", "6")))
    max_itens_por_rodada: int = field(default_factory=lambda: int(os.getenv("MNIA_MAX_ITENS_RODADA", "60")))

    @property
    def modo_simulado(self) -> bool:
        """Simulado se pedido explicitamente ou se não há chave da API."""
        return self.simulado or not self.anthropic_api_key


@lru_cache
def config() -> Config:
    return Config()


@lru_cache
def regras_casa() -> dict:
    return yaml.safe_load((PASTA_CONFIG / "regras_casa.yaml").read_text(encoding="utf-8"))


@lru_cache
def fontes() -> list[dict]:
    dados = yaml.safe_load((PASTA_CONFIG / "fontes.yaml").read_text(encoding="utf-8"))
    return [f for f in dados.get("fontes", []) if f.get("ativo", True)]
