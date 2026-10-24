# MN-IA — Arquitetura do sistema

Sistema de IA como infraestrutura do Grupo Meio Norte. Este documento descreve
**como o sistema é montado**; o `PASSO-A-PASSO.md` descreve **em que ordem
construir e implantar**.

---

## 1. Visão geral

```
                 ┌────────────────────────────────────────────────────┐
  FONTES         │  Portais · Redes · Diário Oficial · Câmara · ALEPI │
  EXTERNAS       │  TCE · E-mail da redação · WhatsApp · Sinal TV/rádio│
                 └───────────────────────┬────────────────────────────┘
                                         │  coletores (1 por tipo de fonte)
                                         ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                       ESPINHA DORSAL (núcleo)                            │
 │                                                                          │
 │  Banco de dados ── itens, alertas, aprovações, execuções, custos         │
 │  Motor Claude   ── chamadas padronizadas, JSON validado, log de custo    │
 │  Regras da casa ── prioridades, risco, portões humanos (config/*.yaml)   │
 │  Notificador    ── Telegram (grupos por área/turno)                      │
 │  Agendador      ── jobs contínuos e horários fixos                       │
 └──────┬──────────────┬───────────────┬───────────────┬───────────────────┘
        │              │               │               │
        ▼              ▼               ▼               ▼
   JORNALISMO      DIGITAL         COMERCIAL       GESTÃO
   radar, triagem, VT→matéria,     prospecção,     painel diretoria,
   clipping, poder títulos,        media kit,      indicadores,
   público, lauda, derivados,      branded,        atendimento
   dossiê, rotina  cortes          renovação
        │              │               │               │
        └──────────────┴───────┬───────┴───────────────┘
                               ▼
                    PORTÃO HUMANO (sempre)
           editor / produtor / vendedor aprova no Telegram
                               ▼
                 TV · Rádio · Portal · Redes · Cliente
```

**Princípio central:** cada módulo é uma etapa de uma cadeia. Tudo que um
módulo produz vira um *item* no banco, e qualquer outro módulo pode consumir.
O radar encontra → vira pauta → vira lauda → vai ao ar → vira matéria → vira corte.

---

## 2. Componentes do núcleo (`mnia/`)

| Arquivo | Papel |
|---|---|
| `config.py` | Lê `.env` e os YAML de `config/`. Um só lugar para chaves e parâmetros. |
| `db.py` | Modelos do banco (SQLAlchemy). SQLite em teste, PostgreSQL em produção. |
| `llm.py` | Motor Claude: system prompt + regras da casa, resposta em JSON validado, retry, registro de tokens e custo por módulo. Modo simulado sem chave de API para testes. |
| `telegram.py` | Envio de alertas formatados para grupos por área. Modo simulado imprime no console. |
| `regras.py` | Carrega `config/regras_casa.yaml` (prioridades, risco, portões humanos) e injeta nos prompts. |
| `agendador.py` | APScheduler: radar a cada N minutos, clipping às 5h30, triagem a cada 10 min etc. |
| `cli.py` | Linha de comando: `mnia init-db`, `mnia radar`, `mnia clipping`, `mnia triagem`, `mnia rodar`. |

### Tabelas principais

- **itens** — tudo que entra (notícia, e-mail, post, trecho de sessão). Campos:
  fonte, url, título, texto, hash (deduplicação), coletado_em, e a análise da IA
  (relevância 0–10, prioridade, editoria, plataforma indicada, risco, resumo,
  porquê importa).
- **alertas** — o que foi enviado a quem, quando e por qual canal.
- **aprovacoes** — portões humanos: quem aprovou/rejeitou o quê (fase 2 em diante).
- **execucoes** — log de cada rodada de cada módulo (início, fim, itens, erros).
- **custos** — tokens e custo estimado por chamada e por módulo.

---

## 3. Regras da casa (`config/regras_casa.yaml`)

Escritas em linguagem simples, editáveis pela direção sem programador:

- **Prioridade**: `urgente` (para o ar agora) · `pauta` (entra no dia) · `acompanhar`.
- **Risco**: 🟢 publicável após revisão normal · 🟡 exige checagem extra ·
  🔴 não usar sem confirmação de fonte primária (boato, conteúdo suspeito,
  acusação sem prova, dado sensível).
- **Portões humanos**: lista do que **nunca** sai sem aprovação de uma pessoa.
- **Editorias e plataformas** do grupo.
- **Interesse do MN**: temas, regiões e personagens que pesam mais.

Toda chamada à IA recebe essas regras. Mudar a regra muda o comportamento
de todos os agentes de uma vez.

---

## 4. Modelos de IA

| Uso | Modelo sugerido | Por quê |
|---|---|---|
| Classificação em volume (radar, triagem) | `claude-haiku-5-5` | Rápido e barato para centenas de itens/dia |
| Redação (clipping, lauda, VT→matéria, títulos) | `claude-sonnet-5-5` | Qualidade de texto |
| Análises pesadas (dossiê, planejamento anual) | `claude-opus-5-5` | Raciocínio mais profundo |

Configurável no `.env` por módulo. O custo de cada chamada fica registrado.

---

## 5. Segurança e governança

- Chaves só no `.env` do servidor, nunca no código.
- Nenhum agente publica sozinho: a saída padrão é **sugestão no Telegram**.
- Conteúdo de fontes externas é tratado como **dado**, nunca como instrução
  (o prompt diz isso explicitamente — proteção contra textos maliciosos).
- Log completo de execuções e custos para auditoria do comitê de IA.
- LGPD: dados pessoais de leitores/ouvintes (WhatsApp) ficam só no banco,
  com retenção configurável.

---

## 6. Infraestrutura de produção

| Item | Recomendação inicial |
|---|---|
| Servidor | VPS Linux, 4 vCPU / 8 GB RAM (Fase 1). Mesmo do Editor MN serve. |
| Banco | PostgreSQL 16 (container) |
| Execução | Docker Compose (`docker-compose.yml` incluso) |
| Backup | Dump diário do Postgres para armazenamento externo |
| Monitoramento | Mensagem automática no Telegram da equipe técnica em caso de erro |
| Fase 2+ | Servidor de ingest de vídeo (captura do sinal) para cortes ao vivo |

---

## 7. Relação com o Editor MN (OpenClaw)

O Editor MN continua sendo o **assistente conversacional** (você conversa com
ele no Telegram). O MN-IA é a **linha de produção** que roda sozinha no
servidor. Os dois compartilham o mesmo bot/grupos do Telegram e podem ler o
mesmo banco: o Editor MN pode responder "o que o radar achou de Picos hoje?"
consultando a tabela `itens`.
