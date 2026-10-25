# MN-IA — IA como infraestrutura do Grupo Meio Norte

Linha de produção de agentes de IA para a redação, o digital e o comercial do
Meio Norte. Esta versão (0.1) entrega a **espinha dorsal** e os **três primeiros
módulos da Fase 1**:

| Módulo | O que faz | Onde entrega |
|---|---|---|
| **Radar em tempo real** | Coleta portais, órgãos oficiais, concorrentes e redes a cada 5 min; classifica relevância, prioridade, risco, editoria e plataforma; agrupa itens do mesmo fato; compara com a concorrência; alerta urgentes na hora e manda resumo de hora em hora | Grupo **Radar MN** |
| **Clipping matinal** | Às 5h30, principais do dia, destaques por editoria, o que a concorrência deu e o MN não, sugestões de pauta com ângulo e quem ouvir | Grupo **Clipping MN** |
| **Triagem de entrada** | Lê o e-mail de pauta (sem apagar nada), descarta publicidade e lixo, encaminha o que importa com ação sugerida | Grupo **Triagem MN** |
| **Laudas de TV** | De hora em hora, rascunho de lauda no padrão de telejornal para as pautas fortes do radar (sonoras sempre "a gravar", nunca inventadas) | Grupo **Produção MN** (ou Radar) |
| **VT → matéria + títulos** | Vídeos novos do canal Meio Norte+ no YouTube viram matéria para o portal com 5 opções de título, linha fina e post para redes | Grupo **Digital MN** (ou Radar) |
| **Cortes verticais** | Até 3 cortes 9:16 por vídeo, com título na tela e legenda, prontos para Reels/Shorts/TikTok | Grupo **Digital MN** (ou Radar) |
| **Saúde técnica** | Alerta de erro na hora + relatório diário de execuções e custo de IA | Grupo **Técnico MN** |

Documentação:
- `docs/ARQUITETURA.md` — como o sistema é montado
- `docs/PASSO-A-PASSO.md` — ordem de construção e implantação de **todas** as fases
- `docs/IMPLANTACAO-HOSTINGER.md` — instalação só pelo Docker Manager, sem terminal

---

## Teste rápido (sem servidor, sem chave, sem custo)

```bash
pip install -r requirements.txt
MNIA_SIMULADO=1 python -m mnia demo     # ciclo completo com dados fictícios
python -m pytest -q                     # 10 testes automatizados
```

No modo simulado a IA é substituída por uma heurística simples, só para validar
o fluxo. Com `ANTHROPIC_API_KEY` preenchida, a mesma demo roda com o Claude real.

---

## Implantação no servidor (desenvolvedor)

```bash
# 1. no servidor, com Docker instalado
git clone <repositório> mn-ia && cd mn-ia     # ou descompacte o .zip
cp .env.example .env && nano .env             # chaves, senha do banco, IDs do Telegram

# 2. subir
docker compose up -d --build

# 3. conferir
docker compose exec mnia python -m mnia status          # banco, Claude, Telegram
docker compose exec mnia python -m mnia testar-fontes   # quais fontes respondem
docker compose logs -f mnia                             # acompanhar
```

A primeira rodada do radar forma a **linha de base** (registra o que já existe
nos sites sem disparar alertas). Os alertas começam na rodada seguinte.

### Pegar o ID de um grupo do Telegram
1. Adicione o bot ao grupo e mande qualquer mensagem no grupo.
2. Abra `https://api.telegram.org/bot<TOKEN>/getUpdates` no navegador.
3. O número em `"chat":{"id": -100...}` é o ID. Cole no `.env`.

### Comandos úteis

```bash
python -m mnia radar          # uma rodada do radar agora
python -m mnia resumo         # resumo do radar agora
python -m mnia clipping       # clipping agora
python -m mnia triagem        # triagem do e-mail agora
python -m mnia saude          # relatório técnico agora
python -m mnia rodar          # modo servidor (o Docker já usa este)
```

---

## O que a redação pode ajustar sem programador

- `config/regras_casa.yaml` — prioridades, critérios de risco, portões humanos,
  temas e cidades de interesse, estilo.
- `config/fontes.yaml` — fontes monitoradas (adicionar, desligar, mudar peso).

Depois de editar: `docker compose restart mnia`.

## Redes sociais

As redes não oferecem RSS aberto. Qualquer serviço de monitoramento (ou script)
pode deixar arquivos JSON em `dados/entrada/` no formato descrito em
`mnia/coletores/caixa_entrada.py`; o radar processa junto com os portais.

---

## Estrutura

```
mnia/
  config.py          configuração (.env + YAML)
  db.py              banco: itens, alertas, aprovações, execuções, custos
  llm.py             motor Claude (regras da casa, JSON, retry, custo)
  regras.py          regras da casa → texto dos prompts
  telegram.py        envio para os grupos
  agendador.py       mantém tudo rodando
  cli.py             linha de comando
  coletores/         rss, html (manchetes de home), caixa de entrada
  radar/             classificador, pipeline, mensagens
  clipping/          clipping matinal
  triagem/           e-mail de pauta
  demo.py            demonstração com dados fictícios
config/              regras_casa.yaml, fontes.yaml
docs/                arquitetura e passo a passo
tests/               testes automatizados
```

## Princípios embutidos no código

- **Agentes sugerem, pessoas decidem.** Nada é publicado automaticamente.
- **Textos de fontes são dados, não instruções** (proteção contra manipulação).
- **Toda chamada de IA tem custo registrado** por módulo.
- **Falhou, avisou.** Erro em qualquer módulo vai para o grupo técnico.
