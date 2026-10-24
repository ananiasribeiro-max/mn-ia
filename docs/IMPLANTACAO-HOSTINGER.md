# Implantação na Hostinger só com o Docker Manager (sem terminal)

Quando o plano da Hostinger não dá acesso ao terminal, o MN-IA é instalado
como **imagem pronta**: o GitHub constrói a imagem sozinho e o Docker Manager
baixa e roda.

```
 Você edita no GitHub  →  GitHub Actions testa e constrói a imagem  →  ghcr.io
                                                                          │
                       Docker Manager (Hostinger) baixa a imagem  ←───────┘
```

---

## Parte 1 — GitHub (uma vez)

1. Crie uma conta em github.com (grátis), se ainda não tiver.
2. Crie um repositório **privado** chamado `mn-ia`.
3. Envie o código para o repositório (Claude pode fazer isso por você
   a partir da conversa; ou arraste o conteúdo da pasta em
   *Add file → Upload files*, incluindo a pasta `.github`).
4. Abra a aba **Actions** do repositório e aguarde o selo verde
   (testes + construção da imagem, ~3 minutos).
5. A imagem aparece em **Packages** no seu perfil, com o nome `mn-ia`.

### Imagem privada ou pública?

- O Docker Manager precisa conseguir **baixar** a imagem.
- Se o painel da Hostinger tiver campo de **login em registro privado**
  (usuário do GitHub + token com permissão `read:packages`), mantenha a
  imagem privada e use esse login.
- Se não tiver, a alternativa é tornar **só o pacote** público
  (Packages → mn-ia → Package settings → Change visibility).
  O repositório continua privado. A imagem **não contém nenhuma senha ou
  chave** (elas ficam só nas variáveis do painel), mas o código do sistema
  fica visível para quem souber o endereço. Decisão de negócio: avalie.

---

## Parte 2 — Docker Manager (Hostinger)

1. hPanel → **VPS** → **Gerenciar** → **Docker Manager** → **Compose**.
2. Escolha **Compose manualmente** (colar YAML).
3. Cole o conteúdo de `docker-compose.hostinger.yml` e troque
   `SEU-USUARIO` pelo seu usuário do GitHub, em minúsculas.
4. Em **variáveis de ambiente**, preencha:

| Variável | O que é |
|---|---|
| `POSTGRES_PASSWORD` | Uma senha forte inventada por você (só o sistema usa) |
| `ANTHROPIC_API_KEY` | Chave da API da Anthropic |
| `TELEGRAM_BOT_TOKEN` | Token do bot |
| `TELEGRAM_CHAT_RADAR` | ID do grupo Radar MN |
| `TELEGRAM_CHAT_CLIPPING` | ID do grupo Clipping MN |
| `TELEGRAM_CHAT_TRIAGEM` | ID do grupo Triagem MN |
| `TELEGRAM_CHAT_TECNICO` | ID do grupo Técnico MN |
| `IMAP_HOST`, `IMAP_USUARIO`, `IMAP_SENHA` | E-mail de pauta (opcional; sem isso a triagem fica desligada) |

   Se o painel não tiver campo de variáveis, substitua cada `${...}` no
   próprio YAML pelo valor (o YAML fica salvo só na sua VPS).

5. Clique em **Deploy**.

---

## Parte 3 — Como saber que funcionou (sem terminal)

No grupo **Técnico MN** do Telegram chegam, em ordem:

1. 🟢 **MN-IA ligado** — com o modo (Claude ativo ou simulado).
2. 📡 **Radar: linha de base formada** — quantas manchetes e quais fontes
   falharam. Mande esse relatório para o Claude ajustar o `fontes.yaml`.
3. A partir da rodada seguinte (5 min), alertas no grupo **Radar MN**.
4. Todo dia às 7h, o relatório de saúde e custo.

No Docker Manager, os **logs** do container `mnia` mostram o mesmo em detalhe.

---

## Atualizar regras, fontes ou código

1. No GitHub, edite `config/regras_casa.yaml` ou `config/fontes.yaml`
   direto no navegador (ícone de lápis) e salve (*Commit changes*).
2. Aguarde o selo verde em **Actions**.
3. No Docker Manager, abra o projeto `mn-ia` e mande **atualizar /
   redeploy** (baixa a imagem `latest` nova).

---

## Limitações deste modo

- A **caixa de entrada de redes** (`dados/entrada/`) não é acessível sem
  terminal; integrações de redes sociais, quando vierem, devem enviar os
  dados por API (Etapa 2 do passo a passo).
- Para as **Fases 2 e 3** (captura de vídeo, integrações pesadas) será
  preciso um plano de VPS com acesso root/SSH.
