"""Descobre o canal e lista os vídeos novos pelo feed público do YouTube."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser

from ..config import RAIZ
from ..coletores.http import baixar

log = logging.getLogger("mnia.youtube")
CACHE = RAIZ / "dados" / "youtube_canal.txt"
FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
PADROES_ID = [
    r'"channelId":"(UC[\w-]{22})"',
    r'<meta itemprop="identifier" content="(UC[\w-]{22})"',
    r'"externalId":"(UC[\w-]{22})"',
    r'youtube\.com/channel/(UC[\w-]{22})',
]


@dataclass
class Video:
    video_id: str
    titulo: str
    url: str
    publicado_em: datetime | None
    descricao: str


def extrair_channel_id(html: str) -> str | None:
    for p in PADROES_ID:
        m = re.search(p, html)
        if m:
            return m.group(1)
    return None


def resolver_channel_id(url_canal: str) -> str:
    m = re.search(r"/channel/(UC[\w-]{22})", url_canal)
    if m:
        return m.group(1)
    if CACHE.exists():
        dados = CACHE.read_text().split()
        if len(dados) == 2 and dados[0] == url_canal:
            return dados[1]
    cid = extrair_channel_id(baixar(url_canal))
    if not cid:
        raise RuntimeError(f"Não encontrei o ID do canal em {url_canal}")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(f"{url_canal} {cid}")
    return cid


def interpretar_feed(conteudo: str) -> list[Video]:
    feed = feedparser.parse(conteudo)
    videos = []
    for e in feed.entries:
        vid = e.get("yt_videoid") or (e.get("id", "").split(":")[-1])
        if not vid:
            continue
        pub = None
        if e.get("published_parsed"):
            pub = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
        desc = e.get("media_description") or e.get("summary") or ""
        videos.append(Video(video_id=vid, titulo=(e.get("title") or "").strip(),
                            url=f"https://www.youtube.com/watch?v={vid}", publicado_em=pub,
                            descricao=re.sub(r"\s+", " ", desc)[:1500]))
    return videos


def listar_videos(url_canal: str) -> list[Video]:
    cid = resolver_channel_id(url_canal)
    return interpretar_feed(baixar(FEED.format(cid=cid)))
