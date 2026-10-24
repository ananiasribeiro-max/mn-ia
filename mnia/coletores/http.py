"""Cliente HTTP comum aos coletores."""
from __future__ import annotations

import httpx

CABECALHOS = {
    "User-Agent": "MN-IA Radar/1.0 (monitoramento jornalistico; Grupo Meio Norte)",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def baixar(url: str, timeout: float = 20) -> str:
    with httpx.Client(headers=CABECALHOS, follow_redirects=True, timeout=timeout) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text
