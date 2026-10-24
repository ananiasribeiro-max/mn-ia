from mnia.coletores import html_home, rss

FONTE_HTML = {"id": "x", "nome": "Portal X", "tipo": "concorrente", "url": "https://www.portalx.com.br", "peso": 2}

HOME = """
<html><body>
  <nav><a href="/assine">Assine agora e tenha acesso ilimitado ao nosso conteúdo</a></nav>
  <a href="/noticia/2026/10/24/chuva-alaga-avenidas-na-zona-norte-de-teresina">
     Chuva forte alaga avenidas na zona norte de Teresina nesta tarde</a>
  <a href="https://www.portalx.com.br/noticia/obra-ponte-parnaiba">Obra da ponte em Parnaíba entra na fase final, diz secretaria</a>
  <a href="https://outrosite.com/materia">Matéria de outro domínio com título bem longo aqui</a>
  <a href="/tag/politica">Política</a>
  <a href="/curta">Curto</a>
  <a href="/noticia/2026/10/24/chuva-alaga-avenidas-na-zona-norte-de-teresina">
     Chuva forte alaga avenidas na zona norte de Teresina nesta tarde</a>
</body></html>
"""

FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Governo anuncia novo hospital em Picos</title><link>https://ex.com/1</link>
<description>&lt;p&gt;Unidade terá 120 leitos.&lt;/p&gt;</description>
<pubDate>Sat, 24 Oct 2026 12:00:00 GMT</pubDate></item>
<item><title></title><link>https://ex.com/2</link></item>
</channel></rss>"""


def test_html_extrai_manchetes_do_proprio_dominio():
    itens = html_home.interpretar(FONTE_HTML, HOME)
    titulos = [i.titulo for i in itens]
    assert len(itens) == 2
    assert any("Chuva forte" in t for t in titulos)
    assert any("Parnaíba" in t for t in titulos)
    assert all("Assine" not in t for t in titulos)
    assert all(i.url.startswith("https://www.portalx.com.br/") for i in itens)


def test_rss_interpreta_e_limpa_html():
    itens = rss.interpretar({"id": "f", "nome": "Feed", "tipo": "oficial", "peso": 3}, FEED)
    assert len(itens) == 1
    assert itens[0].texto == "Unidade terá 120 leitos."
    assert itens[0].publicado_em.year == 2026
    assert itens[0].peso == 3
