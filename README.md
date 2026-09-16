#  Agente Pessoal — Telegram + GitHub Actions

Este agente roda **100% na nuvem** (nos servidores do GitHub Actions), funcionando de forma autónoma mesmo com o teu computador desligado. O computador é utilizado apenas para a configuração inicial.

---

##  Como Funciona (Resumido)

1. **Execução Automática (Cron):** O GitHub Actions executa o script `telegram_agente.py` periodicamente.
2. **Gestão de Estudo & Repetição Espaçada:** O agente consulta o `config.json` e verifica se estás numa janela de estudo ativa, respeitando as prioridades do CTeSP (Eletrotecnia, EFQ, TM, DACIE), os intervalos de revisão espaçada [1, 2, 4, 7, 14, 30 dias] e a tua disponibilidade.
3. **Notificação Interativa:** Envia uma mensagem direta para o teu Telegram indicando o bloco ou revisão do momento.
4. **Registo Automático:** Tu respondes pelo Telegram e o bot atualiza o `estado.json` e os diários/tópicos nos repositórios associados.

>  **Nota sobre o tempo de resposta:** As tuas respostas e comandos pelo Telegram podem levar **até 15 minutos** para serem processados pelo bot, pois correspondem ao intervalo do workflow no GitHub Actions.

---

##  Regras de Blindagem Integradas

- **Sono Protegido:** Bloqueio de notificações entre as 23:30 e as 06:00 (Fuso horário `Europe/Lisbon`).
- **Recuperação:** Quinta-feira à noite livre (pós-19:45) e **Domingo Regenerativo (100% livre de estudo)**.
- **Segurança Absoluta:** Chaves e tokens ficam guardados exclusivamente em variáveis secretas do GitHub — **nunca** no código público.

---

##  Passo a Passo de Configuração

### Passo 1 — Criar o bot no Telegram (5 min)
1. Abre o Telegram e procura por `@BotFather`.
2. Envia `/newbot` e segue as instruções.
3. Copia e guarda o **API Token** gerado.

### Passo 2 — Descobrir o teu Chat ID (2 min)
1. Procura por `@userinfobot` no Telegram e envia `/start`.
2. Copia o teu número de **Id** de utilizador.

### Passo 3 — Preparar o repositório no GitHub
1. Garante que os ficheiros `config.json`, `requirements.txt` e `telegram_agente.py` estão na raiz do repositório.
2. O workflow deve estar localizado em `.github/workflows/agente.yml`.

### Passo 4 — Guardar as credenciais em segredo (Secrets)
> ⚠️ **Importante:** Nunca coles o token ou o chat id dentro do `config.json` ou de qualquer ficheiro do repositório — eles ficam guardados à parte, criptografados.

1. No GitHub, vai a **Settings** > **Secrets and variables** > **Actions**.
2. Cria os seguintes **Repository Secrets**:
   - `TELEGRAM_BOT_TOKEN`: O token do BotFather.
   - `TELEGRAM_CHAT_ID`: O teu ID numérico do Telegram.
   - `PROGRESSO_REPO_TOKEN`: Teu Personal Access Token (PAT) para push nos repositórios de notas.
   - `GOOGLE_SERVICE_ACCOUNT_JSON`: O conteúdo JSON da Service Account da Google Cloud.

### Passo 5 — Ativar o agendamento (GitHub Actions)
1. Acede ao separador **Actions** no repositório e ativa o workflow.
2. A partir daqui, o robô roda sozinho sem precisar do computador ligado.

---

## 💬 Comandos Disponíveis no Telegram

Envia estes comandos no chat do teu bot para gerir o progresso dos eixos de estudo:

| Comando | Descrição / Ação |
| :--- | :--- |
| `/concluido NOME_DO_EIXO [nota opcional]` | Marca o bloco de hoje como feito. Se escreveres uma nota, ela é enviada para o diário do repositório do eixo. |
| `/topico NOME_DO_EIXO texto` | Adiciona um novo tópico de estudo ao eixo. |
| `/feito NOME_DO_EIXO texto` | Marca esse tópico específico como concluído. |
| `/topicos NOME_DO_EIXO` | Lista todos os tópicos pendentes e concluídos desse eixo. |
| `/sincronizar NOME_DO_EIXO` | Puxa tópicos/subtópicos novos diretamente do Google Doc do eixo. |
| `/sincronizartudo` | Executa a sincronização para todos os eixos com `google_doc_id` configurado. |
| `/revisar` | Mostra os blocos e revisões que estão vencidos neste momento. |
| `/status` | Apresenta o resumo do teu progresso global e estado dos eixos. |
| `/ajuda` | Exibe a lista completa de comandos e instruções. |
| `/reiniciartudo CONFIRMAR` | **⚠️ Irreversível:** Zera a repetição espaçada, tópicos e diários de TODOS os eixos. |

*(Lembrete: as respostas podem levar até 15 min, que é quando o robô roda de novo no GitHub).*
