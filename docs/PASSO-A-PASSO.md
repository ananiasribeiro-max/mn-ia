# MN-IA — Passo a passo de construção e implantação

Roteiro completo, na ordem, para você (produto e redação) e o desenvolvedor
(infraestrutura e integrações). Cada etapa diz **quem faz**, **o que entregar**
e **como saber que ficou pronto**.

Legenda: ✅ já construído neste pacote · 🔨 próximo a construir · ⏳ fases seguintes

---

## ETAPA 0 — Preparação (semana 1)

| # | Tarefa | Quem | Pronto quando |
|---|---|---|---|
| 0.1 | Contratar VPS (4 vCPU, 8 GB RAM, Ubuntu 24.04) ou usar o servidor do Editor MN | Dev | Acesso SSH funcionando |
| 0.2 | Instalar Docker e Docker Compose | Dev | `docker compose version` responde |
| 0.3 | Criar conta na API da Anthropic, gerar chave, definir limite de gasto mensal | Ananias | Chave no cofre de senhas |
| 0.4 | Criar bot no Telegram (@BotFather) ou reaproveitar o do Editor MN | Ananias | Token do bot |
| 0.5 | Criar grupos no Telegram: **Radar MN**, **Clipping MN**, **Triagem MN**, **Técnico MN** e adicionar o bot | Ananias | IDs dos grupos (o dev obtém) |
| 0.6 | Criar e-mail dedicado de pauta (ex.: pauta@...) com acesso IMAP | Dev + TI MN | Login IMAP testado |
| 0.7 | Revisar e ajustar `config/regras_casa.yaml` e `config/fontes.yaml` | Ananias | Lista de fontes e regras validadas |

---

## ETAPA 1 — Espinha dorsal (semana 1–2) ✅

| # | Tarefa | Status |
|---|---|---|
| 1.1 | Núcleo: config, banco, motor Claude, Telegram, regras da casa, agendador | ✅ |
| 1.2 | Subir com `docker compose up -d` e rodar `mnia init-db` | Dev |
| 1.3 | Testar em modo simulado (`MNIA_SIMULADO=1`) e depois com chave real | Dev |
| 1.4 | Alerta técnico: erro em qualquer módulo avisa o grupo **Técnico MN** | ✅ |
| 1.5 | Rotina de backup diário do banco | Dev |
| 1.6 | Redigir a **Política de IA do MN** e criar o **Comitê de IA** | Ananias |

**Pronto quando:** `mnia status` mostra banco conectado, Claude respondendo e
Telegram entregando mensagem de teste.

---

## ETAPA 2 — Fluxo do jornalismo, parte 1 (semana 2–4)

| # | Módulo | Status | Saída |
|---|---|---|---|
| 2.1 | **Radar em tempo real** — coleta a cada 5 min, classifica relevância, prioridade, risco, plataforma; alerta urgentes na hora e manda resumo por hora | ✅ | Grupo Radar MN |
| 2.2 | **Clipping matinal** — às 5h30, consolida o que entrou na madrugada e gera o clipping com sugestão de pauta | ✅ | Grupo Clipping MN |
| 2.3 | **Triagem de entrada** — lê o e-mail de pauta, dá nota de relevância, descarta lixo, encaminha o que importa | ✅ | Grupo Triagem MN |
| 2.4 | **Comparação com concorrência** — marca no radar o que concorrentes deram e o MN não | ✅ (via `tipo: concorrente` nas fontes) | Alertas do radar |
| 2.5 | **Lauda de TV** — de hora em hora, rascunho de lauda (retranca, cabeça, OFF, sonoras a gravar, passagem, nota pé, GC, tempo) para as pautas fortes do radar | ✅ | Grupo Produção MN (ou Radar) |
| 2.6 | **Rotina por programa** — portar o skill central-rotina e generalizar para todos os programas | 🔨 | Pauta, perguntas, resumo pós-programa |
| 2.7 | **Dossiê de entrevistado** — busca no banco + web, monta ficha | 🔨 | PDF/mensagem |

**Teste de aceitação (2.1–2.3):** durante 1 semana, os editores de cada turno
marcam no Telegram se cada alerta foi útil (👍/👎). Meta: ≥ 70% útil antes de
expandir.

---

## ETAPA 3 — Distribuição digital (semana 4–8)

| # | Módulo | Status | Observação |
|---|---|---|---|
| 3.1 | **VT → matéria**: vídeos novos do canal Meio Norte+ no YouTube → legenda → matéria para o portal | ✅ | Grupo Digital MN (ou Radar) |
| 3.2 | **Assistente de títulos**: 5 opções de título + linha fina por matéria | ✅ | Junto com 3.1 |
| 3.3 | **Padrão da casa automático** para releases e material de parceiros | 🔨 | Usa a triagem como entrada |
| 3.4 | **Integração com o CMS do Meio News** (salvar como rascunho, nunca publicar) | 🔨 | Depende de qual CMS (WordPress tem API pronta) |
| 3.5 | **Fábrica de derivados**: post para redes ✅ · cortes verticais 9:16 legendados ✅ · carrossel e newsletter 🔨 | |
| 3.6 | **Otimização de YouTube**: título, descrição, tags, capítulos | 🔨 | Integra com a API do YouTube |
| 3.7 | **Contexto e relacionadas** no portal | ⏳ | Usa o banco de itens como memória |

---

## ETAPA 4 — Comercial (mês 2–3)

| # | Módulo | Status |
|---|---|---|
| 4.1 | **Base de conhecimento comercial** (tabelas, formatos, cases em chat) | 🔨 |
| 4.2 | **Media kit / proposta automatizada** | 🔨 |
| 4.3 | **Prospecção inteligente** | ⏳ |
| 4.4 | **Relatório pós-campanha e calendário de renovação** | ⏳ |
| 4.5 | **Estúdio de conteúdo de marca** | ⏳ |
| 4.6 | **Cauda longa self-serve** | ⏳ |

---

## ETAPA 5 — Planejamento anual 2027 (novembro–dezembro)

| # | Entrega | Status |
|---|---|---|
| 5.1 | Calendário editorial do Piauí 2027 (datas, festejos, sazonalidade) | 🔨 |
| 5.2 | Calendário comercial casado com o editorial, com cotas | 🔨 |
| 5.3 | Balanço de audiência 2026 (precisa dos dados do MN) | 🔨 |
| 5.4 | Painel de metas e revisões trimestrais | ⏳ |

---

## ETAPA 6 — Fase 2 (mês 3–6)

- **Monitor do poder público**: transcrição das sessões da Câmara de Teresina,
  ALEPI e TCE (a partir das transmissões no YouTube), alertas por palavra-chave.
- **Corte ao vivo do telejornal**: a versão a partir do YouTube já funciona
  (cortes depois que o vídeo é publicado). Próximo: captura direta do sinal
  durante a transmissão, para cortar enquanto está no ar.
- **Matéria → vídeo curto** (modelo Videofy, código aberto da Schibsted).
- **Boletins das rádios do interior** (texto revisado, locução humana).
- **Painel da diretoria**.
- **Bootcamps para todas as áreas**.

## ETAPA 7 — Fase 3 (mês 6–12)

- Estúdio de conteúdo de marca · cauda longa self-serve · atendimento ao
  público via WhatsApp · eventos (Pirifolia, OléTV) · novos papéis internos.

---

## Divisão de trabalho

**Ananias**
- Regras da casa, fontes, prompts e critérios editoriais
- Teste com editores e coleta de feedback
- Política de IA, comitê, bootcamps
- Relação com a direção do MN

**Desenvolvedor**
- Servidor, Docker, banco, backup, segurança
- Integrações (e-mail, CMS, YouTube, captura de vídeo)
- Monitoramento e correção de falhas
- Novos coletores de fontes

**Claude**
- Código dos módulos, prompts, regras e documentação
- Diagnóstico de problemas quando acionado
- Conteúdo dos treinamentos e materiais da agência

---

## Como trabalhar comigo nas próximas etapas

Para cada módulo 🔨, abra uma conversa com:
1. o nome do módulo (ex.: "Etapa 2.5 — Lauda e espelho");
2. exemplos reais (3 laudas boas do MN, por exemplo);
3. onde a saída deve chegar.

Eu devolvo o módulo pronto no mesmo padrão deste pacote, com testes.

---

## Vídeo e YouTube — notas de operação

- O canal monitorado é definido em `MNIA_YOUTUBE_CANAL`. Na primeira rodada, só o
  vídeo mais recente é processado; os anteriores formam a linha de base.
- Legenda automática do YouTube pode levar algumas horas para sair. O sistema
  tenta de novo a cada rodada (até 8 vezes).
- Transmissões ao vivo são processadas quando terminam.
- Para testar um vídeo específico: `python -m mnia video https://www.youtube.com/watch?v=...`
- Se o YouTube pedir verificação ("confirme que não é um robô") para o servidor,
  o grupo Técnico recebe o aviso. Solução: exportar os cookies de uma conta do
  YouTube logada (extensão "Get cookies.txt") e salvar em `dados/cookies.txt`
  na máquina. Use uma conta dedicada, não a pessoal.
- Cortes ficam em `dados/cortes/` por 7 dias e depois são apagados.
