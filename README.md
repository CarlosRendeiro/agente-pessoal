# Agente Pessoal — versão Telegram + GitHub Actions

Este agente roda 100% na nuvem (nos servidores do GitHub), então funciona mesmo
com o teu notebook desligado. O notebook só é usado para configurar tudo uma vez.

## Como funciona, resumido

A cada 15 minutos, o GitHub "liga" o script por conta própria, ele confere se é
hora de um bloco de estudo (considerando a repetição espaçada) e te manda uma
mensagem no Telegram. Tu respondes pelo próprio Telegram quando terminares.

## Passo 1 — Criar o bot no Telegram (5 min)

1. Abre o Telegram e procura por **@BotFather** (é o bot oficial pra criar bots).
2. Manda a mensagem `/newbot`.
3. Ele vai pedir um nome (qualquer um, ex: "Agente de Estudos") e depois um
   "username" único terminado em `bot` (ex: `carlos_agente_bot`).
4. Ao final, o BotFather te dá um **token**, algo como:
   `123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw`
   **Guarda esse token** — vamos usar no Passo 3.
5. Agora manda **qualquer mensagem** (ex: "oi") pro bot que acabaste de criar
   (procura pelo username que escolheste).

## Passo 2 — Descobrir teu Chat ID (2 min)

1. No navegador, acessa este link, trocando `SEU_TOKEN` pelo token do Passo 1:
   ```
   https://api.telegram.org/botSEU_TOKEN/getUpdates
   ```
2. Vai aparecer um texto (JSON). Procura por `"chat":{"id":` — o número logo
   depois é o teu **Chat ID** (ex: `987654321`). Guarda esse número também.
   Se não aparecer nada, confirma que mandaste mesmo uma mensagem pro bot no Passo 1.

## Passo 3 — Preparar o repositório no GitHub

1. Entra em [github.com/CarlosRendeiro](https://github.com/CarlosRendeiro) e cria
   um repositório novo, ex: `agente-pessoal` (pode ser privado ou público — se
   for público, qualquer pessoa consegue ver teu progresso de estudos, mas não
   o token nem o chat id, esses ficam protegidos à parte).
2. Copia estes 4 arquivos/pastas pra dentro do repositório (mantendo os nomes
   e a pasta `.github/workflows/` exatamente como estão):
   - `telegram_agente.py`
   - `config.json`
   - `requirements.txt`
   - `.github/workflows/agente.yml`
3. Sobe (commit + push) esses arquivos pro GitHub. Se nunca usaste git antes,
   dá pra fazer isso direto pela interface web do GitHub: botão "Add file" →
   "Upload files", arrastando os arquivos.

## Passo 4 — Guardar o token e o chat id em segredo (não no código!)

**Importante:** nunca cole o token e o chat id dentro do `config.json` ou de
qualquer arquivo do repositório — eles ficam guardados à parte, criptografados.

1. No repositório, vai em **Settings** → **Secrets and variables** → **Actions**.
2. Clica em **New repository secret**.
3. Cria dois segredos:
   - Nome: `TELEGRAM_BOT_TOKEN` — Valor: o token do Passo 1
   - Nome: `TELEGRAM_CHAT_ID` — Valor: o número do Passo 2

## Passo 5 — Ativar o agendamento (GitHub Actions)

1. Vai na aba **Actions** do repositório.
2. Se aparecer um aviso pra ativar workflows, clica em ativar.
3. Deve aparecer o workflow "Agente Pessoal". Clica nele e depois em
   **Run workflow** pra testar manualmente uma vez (não precisa esperar os 15 min).
4. Se tudo estiver certo, deve chegar uma mensagem no teu Telegram em
   até 1 minuto. Se não chegar, confere os logs dessa execução (clica em
   cima dela na aba Actions) — geralmente o erro mais comum é token ou
   chat id digitado errado.

A partir daqui, roda sozinho, pra sempre, sem precisar do notebook ligado.

## Comandos que respondes pelo Telegram

```
/concluido RTIEBT     -> marca o bloco de hoje daquele eixo como feito
/revisar               -> lista o que está vencido pra revisão agora
/status                 -> resumo de progresso por eixo
/ajuda                  -> lista os comandos
```

**Atenção:** como o robô só roda a cada 15 minutos, a resposta a um comando
pode demorar até 15 min pra chegar. Não é instantâneo como um chat normal.

## Eixos de estudo configurados (em ordem de prioridade)

1. **RTIEBT** (peso 3)
2. **Motores Elétricos WEG** (peso 3)
3. Cartografia e SIG — ArcGIS Pro, QGIS (peso 1)
4. Banco de dados geoespacial — PostgreSQL/PostGIS (peso 1)
5. Administração Linux — Rocky Linux, Podman (peso 1)
6. Python (peso 1)

Isso é editável a qualquer momento no `config.json`, direto pela interface
web do GitHub (não precisa reinstalar nada) — só editar o arquivo e commitar.

## Repetição espaçada (como antes, sem mudanças)

Cada eixo tem um nível (0-5) com intervalos de 1, 2, 4, 7, 14 e 30 dias.
Revisões vencidas sempre têm prioridade sobre estudo novo. Se atrasares
muito, o nível desce e a revisão volta a ser mais frequente.

## Se algo parar de funcionar

- Confere a aba **Actions** do repositório — cada execução fica registrada,
  com erro detalhado se algo falhar.
- O erro mais comum é os secrets (`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`)
  errados ou removidos sem querer.
- Se o GitHub avisar que desativou o agendamento por inatividade do repositório
  (isso acontece após ~60 dias sem nenhum commit), basta ir em Actions e
  reativar — ou fazer qualquer commit pequeno.

