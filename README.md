# Agente Pessoal — versão Telegram + GitHub Actions

Este agente roda 100% na nuvem (nos servidores do GitHub), então funciona mesmo
com o teu notebook desligado. O notebook só é usado para configurar tudo uma vez.

## Como funciona, resumido

A cada 5 minutos, o GitHub "liga" o script atavés de um estimula externo, ele confere se é
hora de um bloco de estudo (considerando a repetição espaçada) e te manda uma
mensagem no Telegram. Tu respondes pelo próprio Telegram quando terminares.

## Passo 1 — Criar o bot no Telegram (5 min)

## Passo 2 — Descobrir teu Chat ID (2 min)


## Passo 3 — Preparar o repositório no GitHub

## Passo 4 — Guardar o token e o chat id em segredo (não no código!)

**Importante:** nunca cole o token e o chat id dentro do `config.json` ou de
qualquer arquivo do repositório — eles ficam guardados à parte, criptografados.

## Passo 5 — Ativar o agendamento (GitHub Actions)


A partir daqui, roda sozinho, pra sempre, sem precisar do notebook ligado.

## Comandos que respondes pelo Telegram

```
/concluido RTIEBT     -> marca o bloco de hoje daquele eixo como feito
/revisar               -> lista o que está vencido pra revisão agora
/status                 -> resumo de progresso por eixo
/ajuda                  -> lista os comandos
```

**Atenção:** como o robô só roda a cada 5 minutos, a resposta a um comando
pode demorar até 55 min pra chegar. Não é instantâneo como um chat normal.

## Eixos de estudo configurados (em ordem de prioridade)

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

