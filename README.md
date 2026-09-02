# Agente Pessoal — versão Telegram + GitHub Actions

Este agente roda 100% na nuvem (nos servidores do GitHub), então funciona mesmo
com o teu notebook desligado. O notebook só é usado para configurar tudo uma vez.

## Como funciona, resumido

A cada 5 minutos, o GitHub "liga" o script por conta própria, ele confere se é
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



