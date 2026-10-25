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
CACHE = RAIZ / "dados" / "youtube_canal_v2.txt"
FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
PADROES_ID = [
    r'"externalId":"(UC[\w-]{22})"',
    r'<meta itemprop="identifier" content="(UC[\w-]{22})"',
    r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
    r'"channelId":"(UC[\w-]{22})"',
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


def _datas(e: dict) -> datetime | None:
    if e.get("timestamp"):
        return datetime.fromtimestamp(int(e["timestamp"]), tz=timezone.utc)
    d = e.get("upload_date") or e.get("release_date")
    if d and len(str(d)) == 8:
        return datetime.strptime(str(d), "%Y%m%d").replace(tzinfo=timezone.utc)
    return None


def listar_via_ytdlp(url_canal: str, por_aba: int = 15) -> list[Video]:
    """Lista vídeos e transmissões do canal pela própria página (mais novos primeiro)."""
    import yt_dlp

    from .legendas import opcoes_base
    base = url_canal.rstrip("/")
    vistos, videos = set(), []
    for aba in ("videos", "streams"):
        opcoes = {**opcoes_base(), "extract_flat": "in_playlist", "playlistend": por_aba,
                  "skip_download": True, "ignoreerrors": True}
        try:
            with yt_dlp.YoutubeDL(opcoes) as ydl:
                info = ydl.extract_info(f"{base}/{aba}", download=False) or {}
        except Exception as e:  # aba inexistente no canal
            log.info("Aba %s indisponível: %s", aba, str(e)[:120])
            continue
        for e in info.get("entries") or []:
            if not e or not e.get("id") or e["id"] in vistos:
                continue
            if e.get("live_status") in ("is_upcoming",):
                continue
            vistos.add(e["id"])
            videos.append(Video(video_id=e["id"], titulo=(e.get("title") or "").strip(),
                                url=f"https://www.youtube.com/watch?v={e['id']}",
                                publicado_em=_datas(e), descricao=(e.get("description") or "")[:1500]))
    return videos


def listar_videos(url_canal: str) -> list[Video]:
    try:
        videos = listar_via_ytdlp(url_canal)
        if videos:
            return videos
    except Exception as e:
        log.warning("Listagem pelo yt-dlp falhou (%s); tentando o feed.", str(e)[:150])
    cid = resolver_channel_id(url_canal)
    return interpretar_feed(baixar(FEED.format(cid=cid)))
