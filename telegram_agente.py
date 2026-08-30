#!/usr/bin/env python3
"""
Agente Pessoal — versão Telegram (roda na nuvem via GitHub Actions)
--------------------------------------------------------------------
Este script é chamado automaticamente pelo GitHub Actions a cada 15 minutos.
Ele faz duas coisas em cada execução:

1. Lê mensagens novas que tu mandaste pro bot no Telegram (ex: /concluido RTIEBT)
   e processa os comandos (com validação estrita de remetente e chat).
2. Verifica se agora é hora de um bloco de estudo e, se for, manda uma
   mensagem no Telegram avisando qual eixo estudar.

Toda a configuração fica em config.json. O progresso fica em estado.json,
que é salvo de volta no repositório automaticamente pelo GitHub Actions.

Comandos que tu podes mandar pro bot no Telegram:
  /concluido NOME_DO_EIXO [nota opcional]     -> marca o bloco de hoje como feito
  /topico NOME_DO_EIXO texto                 -> adiciona um tópico novo à lista do eixo
  /feito NOME_DO_EIXO texto                  -> marca esse tópico como concluído
  /topicos NOME_DO_EIXO                      -> lista os tópicos do eixo
  /revisar                                   -> lista o que está vencido pra revisão agora
  /status                                    -> resumo de progresso por eixo
  /ajuda                                     -> lista os comandos
"""

import base64
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

DIAS_PT = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]

# Variáveis de ambiente e IDs autorizados
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ALLOWED_USER_ID = os.environ.get("TELEGRAM_ALLOWED_USER_ID") or CHAT_ID
PROGRESSO_TOKEN = os.environ.get("PROGRESSO_REPO_TOKEN")


def carregar_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def caminho_estado(cfg):
    return BASE_DIR / cfg["arquivo_estado"]


def eixo_info_default():
    return {
        "ultima_data": None,
        "faltas_seguidas": 0,
        "total_blocos": 0,
        "nivel_revisao": 0,
        "proxima_revisao": None,
    }


def carregar_estado(cfg):
    caminho = caminho_estado(cfg)
    if caminho.exists():
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    return {
        "eixos": {e["nome"]: eixo_info_default() for e in cfg["eixos_estudo"]},
        "janela_notificada_hoje": {},
        "sugestao_hoje": {},
        "ultimo_update_id_telegram": 0,
    }


def salvar_estado(cfg, estado):
    with open(caminho_estado(cfg), "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def agora_local(cfg):
    if ZoneInfo:
        from datetime import datetime
        return datetime.now(ZoneInfo(cfg.get("fuso_horario", "Europe/Lisbon")))
    from datetime import datetime
    return datetime.now()


# ---------- Telegram ----------

def telegram_api(metodo, **params):
    if not BOT_TOKEN:
        print("Aviso: TELEGRAM_BOT_TOKEN não configurado, pulando chamada Telegram.")
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{metodo}"
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Erro ao chamar Telegram ({metodo}): {e}")
        return None


def enviar_mensagem(texto):
    if not CHAT_ID:
        print(f"[sem CHAT_ID configurado] Mensagem que seria enviada:\n{texto}")
        return
    telegram_api("sendMessage", chat_id=CHAT_ID, text=texto)
    print(f"Mensagem enviada: {texto}")


def buscar_mensagens_novas(estado):
    offset = estado.get("ultimo_update_id_telegram", 0)
    resposta = telegram_api("getUpdates", offset=offset + 1, timeout=0)
    if not resposta or not resposta.get("ok"):
        return []
    return resposta.get("result", [])


def mensagem_autorizada(msg_obj):
    """Verifica se o remetente (user_id) e a conversa (chat_id) são os permitidos."""
    if not msg_obj:
        return False
    remetente_id = str(msg_obj.get("from", {}).get("id", ""))
    chat_id = str(msg_obj.get("chat", {}).get("id", ""))

    return remetente_id == str(ALLOWED_USER_ID) and chat_id == str(CHAT_ID)


# ---------- Lógica de repetição espaçada ----------

def dias_atraso(hoje, proxima_str):
    if not proxima_str:
        return 9999
    proxima = date.fromisoformat(proxima_str)
    return (hoje - proxima).days


def escolher_eixo(cfg, estado, hoje):
    limite = cfg["regra_never_miss_twice"]["faltas_para_subir_prioridade"]

    vencidos = []
    for eixo in cfg["eixos_estudo"]:
        nome = eixo["nome"]
        info = estado["eixos"].get(nome, eixo_info_default())
        atraso = dias_atraso(hoje, info["proxima_revisao"])
        if atraso >= 0:
            vencidos.append((eixo["peso"], atraso, nome))

    if vencidos:
        vencidos.sort(key=lambda x: (-x[0], -x[1]))
        peso, atraso, nome = vencidos[0]
        return nome, True, (0 if atraso == 9999 else atraso)

    candidatos = []
    for eixo in cfg["eixos_estudo"]:
        nome = eixo["nome"]
        info = estado["eixos"].get(nome, eixo_info_default())
        peso = eixo["peso"]
        if cfg["regra_never_miss_twice"]["ativa"] and info["faltas_seguidas"] >= limite:
            peso += 3
        candidatos.append((peso, info["ultima_data"] or "", nome))
    candidatos.sort(key=lambda x: (-x[0], x[1]))
    return candidatos[0][2], False, 0


def listar_vencidos(cfg, estado, hoje):
    vencidos = []
    for eixo in cfg["eixos_estudo"]:
        nome = eixo["nome"]
        info = estado["eixos"].get(nome, eixo_info_default())
        atraso = dias_atraso(hoje, info["proxima_revisao"])
        if atraso >= 0:
            vencidos.append((atraso, nome, info["proxima_revisao"]))
    vencidos.sort(key=lambda x: -x[0])
    return vencidos


def marcar_concluido(cfg, estado, nome_eixo, hoje):
    intervalos = cfg["intervalos_revisao_dias"]
    nomes_validos = [e["nome"] for e in cfg["eixos_estudo"]]
    if nome_eixo not in nomes_validos:
        return f"Eixo '{nome_eixo}' não existe. Eixos válidos: {', '.join(nomes_validos)}"

    info = estado["eixos"].setdefault(nome_eixo, eixo_info_default())
    nivel = info.get("nivel_revisao", 0)
    proxima_anterior = info.get("proxima_revisao")

    if proxima_anterior is None:
        nivel = 0
    else:
        atraso = dias_atraso(hoje, proxima_anterior)
        if atraso <= intervalos[nivel]:
            nivel = min(nivel + 1, len(intervalos) - 1)
        else:
            nivel = max(nivel - 1, 0)

    info["ultima_data"] = hoje.isoformat()
    info["faltas_seguidas"] = 0
    info["total_blocos"] += 1
    info["nivel_revisao"] = nivel
    info["proxima_revisao"] = (hoje + timedelta(days=intervalos[nivel])).isoformat()
    return (
        f"Registado: bloco de {nome_eixo} concluído hoje. Total: {info['total_blocos']} blocos. "
        f"Próxima revisão: {info['proxima_revisao']} (nível {nivel})."
    )


def texto_status(cfg, estado):
    linhas = ["Resumo por eixo:"]
    for eixo in cfg["eixos_estudo"]:
        nome = eixo["nome"]
        info = estado["eixos"].get(nome, eixo_info_default())
        linhas.append(
            f"- {nome}: {info['total_blocos']} blocos | última: {info['ultima_data'] or 'nunca'} | "
            f"nível {info.get('nivel_revisao', 0)} | próxima revisão: {info.get('proxima_revisao') or 'a definir'}"
        )
    return "\n".join(linhas)


def texto_revisar(cfg, estado, hoje):
    vencidos = listar_vencidos(cfg, estado, hoje)
    if not vencidos:
        return "Nada vencido agora — tudo em dia com a repetição espaçada."
    linhas = ["Pendente de revisão (mais atrasado primeiro):"]
    for atraso, nome, proxima in vencidos:
        if proxima is None:
            linhas.append(f"- {nome}: nunca revisado ainda")
        elif atraso == 0:
            linhas.append(f"- {nome}: vence hoje")
        else:
            linhas.append(f"- {nome}: atrasado há {atraso} dias (venceu em {proxima})")
    return "\n".join(linhas)


TEXTO_AJUDA = (
    "Comandos disponíveis:\n"
    "/concluido NOME_DO_EIXO [nota opcional] — marca o bloco de hoje como feito, "
    "e se escreveres uma nota, ela vai pro diário do repositório do eixo\n"
    "/topico NOME_DO_EIXO texto — adiciona um tópico novo\n"
    "/feito NOME_DO_EIXO texto — marca esse tópico como concluído\n"
    "/topicos NOME_DO_EIXO — lista os tópicos pendentes e concluídos\n"
    "/revisar — o que está vencido agora\n"
    "/status — resumo de progresso\n"
    "/ajuda — esta mensagem\n"
    "(as respostas podem levar até 15 min, é quando o robô roda de novo)"
)


# ---------- Repositório por eixo (GitHub API): tópicos + diário ----------

def repo_do_eixo(cfg, nome_eixo):
    for eixo in cfg["eixos_estudo"]:
        if eixo["nome"] == nome_eixo:
            return eixo.get("repo_owner"), eixo.get("repo_nome")
    return None, None


def api_ler_arquivo(owner, repo, caminho):
    """Retorna (conteudo, sha). sha é None se o arquivo ainda não existe."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{caminho}"
    headers = {
        "Authorization": f"Bearer {PROGRESSO_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code == 200:
        dados = r.json()
        return base64.b64decode(dados["content"]).decode("utf-8"), dados["sha"]
    elif r.status_code == 404:
        return None, None
    else:
        raise RuntimeError(f"Erro ao ler {owner}/{repo}/{caminho}: {r.status_code} {r.text}")


def api_gravar_arquivo(owner, repo, caminho, novo_conteudo, sha, mensagem_commit):
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{caminho}"
    headers = {
        "Authorization": f"Bearer {PROGRESSO_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "message": mensagem_commit,
        "content": base64.b64encode(novo_conteudo.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=headers, json=payload, timeout=15)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Erro ao gravar {owner}/{repo}/{caminho}: {r.status_code} {r.text}")


def registrar_diario(cfg, nome_eixo, notas, hoje):
    """Acrescenta uma entrada no diario.md do repositório do eixo."""
    if not PROGRESSO_TOKEN:
        print("Aviso: PROGRESSO_REPO_TOKEN não configurado, pulando registo de diário.")
        return
    owner, repo = repo_do_eixo(cfg, nome_eixo)
    if not owner:
        return
    caminho = cfg.get("arquivo_diario", "diario.md")
    try:
        conteudo, sha = api_ler_arquivo(owner, repo, caminho)
        if conteudo is None:
            conteudo = f"# Diário de progresso — {nome_eixo}\n"
        entrada = f"\n## {hoje.isoformat()}\n"
        if notas:
            entrada += f"{notas}\n"
        api_gravar_arquivo(
            owner, repo, caminho, conteudo + entrada, sha,
            f"Diário: {nome_eixo} em {hoje.isoformat()}"
        )
    except Exception as e:
        print(f"Erro ao registar diário de {nome_eixo}: {e}")


def adicionar_topico(cfg, nome_eixo, topico_texto):
    if not PROGRESSO_TOKEN:
        return "PROGRESSO_REPO_TOKEN não configurado — não consigo gravar no GitHub agora."
    owner, repo = repo_do_eixo(cfg, nome_eixo)
    if not owner:
        return f"O eixo {nome_eixo} não tem repositório configurado."
    caminho = cfg.get("arquivo_topicos", "topicos.md")
    try:
        conteudo, sha = api_ler_arquivo(owner, repo, caminho)
        if conteudo is None:
            conteudo = f"# Tópicos — {nome_eixo}\n\n"
        novo_conteudo = conteudo.rstrip("\n") + f"\n- [ ] {topico_texto}\n"
        api_gravar_arquivo(
            owner, repo, caminho, novo_conteudo, sha,
            f"Novo tópico em {nome_eixo}: {topico_texto}"
        )
        return f"Tópico adicionado em {nome_eixo}: {topico_texto}"
    except Exception as e:
        return f"Erro ao adicionar tópico: {e}"


def marcar_topico_concluido(cfg, nome_eixo, topico_texto):
    if not PROGRESSO_TOKEN:
        return "PROGRESSO_REPO_TOKEN não configurado — não consigo gravar no GitHub agora."
    owner, repo = repo_do_eixo(cfg, nome_eixo)
    if not owner:
        return f"O eixo {nome_eixo} não tem repositório configurado."
    caminho = cfg.get("arquivo_topicos", "topicos.md")
    try:
        conteudo, sha = api_ler_arquivo(owner, repo, caminho)
        if conteudo is None:
            return f"Ainda não há tópicos registados em {nome_eixo}."
        linhas = conteudo.split("\n")
        encontrado = False
        for i, linha in enumerate(linhas):
            if linha.strip().startswith("- [ ]") and topico_texto.lower() in linha.lower():
                linhas[i] = linha.replace("- [ ]", "- [x]", 1)
                encontrado = True
                break
        if not encontrado:
            return f"Não encontrei um tópico pendente parecido com '{topico_texto}' em {nome_eixo}."
        api_gravar_arquivo(
            owner, repo, caminho, "\n".join(linhas), sha,
            f"Tópico concluído em {nome_eixo}: {topico_texto}"
        )
        return f"Marcado como concluído em {nome_eixo}: {topico_texto}"
    except Exception as e:
        return f"Erro ao marcar tópico: {e}"


def listar_topicos(cfg, nome_eixo):
    owner, repo = repo_do_eixo(cfg, nome_eixo)
    if not owner:
        return f"O eixo {nome_eixo} não tem repositório configurado."
    caminho = cfg.get("arquivo_topicos", "topicos.md")
    try:
        conteudo, _sha = api_ler_arquivo(owner, repo, caminho)
        if conteudo is None:
            return f"Ainda não há tópicos registados em {nome_eixo}. Usa /topico {nome_eixo} <texto> pra começar."
        pendentes = [l.strip()[6:] for l in conteudo.split("\n") if l.strip().startswith("- [ ]")]
        feitos = [l.strip()[6:] for l in conteudo.split("\n") if l.strip().startswith("- [x]")]
        linhas = [f"Tópicos de {nome_eixo} — {len(feitos)} feitos, {len(pendentes)} pendentes:"]
        for t in pendentes:
            linhas.append(f"⬜ {t}")
        for t in feitos:
            linhas.append(f"✅ {t}")
        return "\n".join(linhas) if (pendentes or feitos) else f"Nenhum tópico ainda em {nome_eixo}."
    except Exception as e:
        return f"Erro ao listar tópicos: {e}"


def separar_eixo_e_notas(texto_apos_comando, nomes_validos):
    """Reconhece o eixo mesmo com nome composto (ex: 'Motores Elétricos WEG'),
    pegando o nome válido mais longo que bate no início do texto, e trata
    o resto como nota/tópico."""
    texto_apos_comando = texto_apos_comando.strip()
    candidatos = [n for n in nomes_validos if texto_apos_comando == n or texto_apos_comando.startswith(n + " ")]
    if not candidatos:
        return None, None
    nome = max(candidatos, key=len)
    notas = texto_apos_comando[len(nome):].strip()
    return nome, notas


# ---------- Processamento das mensagens recebidas ----------

def processar_mensagens(cfg, estado, hoje):
    mensagens = buscar_mensagens_novas(estado)
    for msg in mensagens:
        update_id = msg["update_id"]
        estado["ultimo_update_id_telegram"] = max(estado.get("ultimo_update_id_telegram", 0), update_id)

        msg_obj = msg.get("message") or msg.get("edited_message")
        if not msg_obj:
            continue

        # --- TRAVA DE SEGURANÇA: REMETENTE E CHAT ---
        if not mensagem_autorizada(msg_obj):
            sender_id = msg_obj.get("from", {}).get("id")
            sender_user = msg_obj.get("from", {}).get("username")
            chat_id = msg_obj.get("chat", {}).get("id")
            print(f"⚠️ Acesso bloqueado: @{sender_user} (User ID: {sender_id} | Chat ID: {chat_id})")
            continue
        # ---------------------------------------------

        texto = msg_obj.get("text", "").strip()
        if not texto:
            continue

        if texto.startswith("/concluido"):
            partes = texto.split(maxsplit=1)
            if len(partes) < 2:
                enviar_mensagem("Uso: /concluido NOME_DO_EIXO [nota opcional] (ex: /concluido RTIEBT revisei esquemas)")
                continue
            nomes_validos = [e["nome"] for e in cfg["eixos_estudo"]]
            nome_eixo, notas = separar_eixo_e_notas(partes[1], nomes_validos)
            if nome_eixo is None:
                enviar_mensagem(f"Eixo não reconhecido. Eixos válidos: {', '.join(nomes_validos)}")
                continue
            resposta = marcar_concluido(cfg, estado, nome_eixo, hoje)
            enviar_mensagem(resposta)
            registrar_diario(cfg, nome_eixo, notas, hoje)

        elif texto.startswith("/topicos"):
            partes = texto.split(maxsplit=1)
            nomes_validos = [e["nome"] for e in cfg["eixos_estudo"]]
            if len(partes) < 2:
                enviar_mensagem(f"Uso: /topicos NOME_DO_EIXO. Eixos válidos: {', '.join(nomes_validos)}")
                continue
            nome_eixo, _resto = separar_eixo_e_notas(partes[1], nomes_validos)
            if nome_eixo is None:
                enviar_mensagem(f"Eixo não reconhecido. Eixos válidos: {', '.join(nomes_validos)}")
                continue
            enviar_mensagem(listar_topicos(cfg, nome_eixo))

        elif texto.startswith("/topico"):
            partes = texto.split(maxsplit=1)
            nomes_validos = [e["nome"] for e in cfg["eixos_estudo"]]
            if len(partes) < 2:
                enviar_mensagem("Uso: /topico NOME_DO_EIXO texto do tópico")
                continue
            nome_eixo, topico_texto = separar_eixo_e_notas(partes[1], nomes_validos)
            if nome_eixo is None:
                enviar_mensagem(f"Eixo não reconhecido. Eixos válidos: {', '.join(nomes_validos)}")
                continue
            if not topico_texto:
                enviar_mensagem("Falta o texto do tópico. Ex: /topico RTIEBT Esquemas trifásicos")
                continue
            enviar_mensagem(adicionar_topico(cfg, nome_eixo, topico_texto))

        elif texto.startswith("/feito"):
            partes = texto.split(maxsplit=1)
            nomes_validos = [e["nome"] for e in cfg["eixos_estudo"]]
            if len(partes) < 2:
                enviar_mensagem("Uso: /feito NOME_DO_EIXO texto do tópico já concluído")
                continue
            nome_eixo, topico_texto = separar_eixo_e_notas(partes[1], nomes_validos)
            if nome_eixo is None:
                enviar_mensagem(f"Eixo não reconhecido. Eixos válidos: {', '.join(nomes_validos)}")
                continue
            if not topico_texto:
                enviar_mensagem("Falta o texto do tópico. Ex: /feito RTIEBT Esquemas trifásicos")
                continue
            enviar_mensagem(marcar_topico_concluido(cfg, nome_eixo, topico_texto))

        elif texto.startswith("/revisar"):
            enviar_mensagem(texto_revisar(cfg, estado, hoje))

        elif texto.startswith("/status"):
            enviar_mensagem(texto_status(cfg, estado))

        elif texto.startswith("/ajuda") or texto.startswith("/start"):
            enviar_mensagem(TEXTO_AJUDA)

        else:
            enviar_mensagem("Não entendi. " + TEXTO_AJUDA)


# ---------- Janela de estudo ----------

def dentro_de(hora_atual, inicio, fim):
    return inicio <= hora_atual <= fim


def janela_ativa_agora(cfg, agora):
    dia = DIAS_PT[agora.weekday()]
    hora = agora.strftime("%H:%M")
    for janela in cfg["janelas_estudo"]:
        if dia in janela["dias"] and dentro_de(hora, janela["inicio"], janela["fim"]):
            return janela
    return None


def verificar_bloco_de_estudo(cfg, estado, agora):
    hoje_str = agora.date().isoformat()
    janela = janela_ativa_agora(cfg, agora)
    if not janela:
        return

    if estado["janela_notificada_hoje"].get(janela["nome"]) == hoje_str:
        return

    eixo, eh_revisao, atraso = escolher_eixo(cfg, estado, agora.date())
    duracao = cfg["duracao_bloco_min"]
    if eh_revisao:
        rotulo = "🔁 Revisão vencida" if atraso > 0 else "🔁 Revisão"
        extra = f" (atrasada há {atraso} dias)" if atraso > 0 else ""
    else:
        rotulo, extra = "📘 Estudo", ""

    enviar_mensagem(
        f'{rotulo}\nBloco "{janela["nome"]}" — foco em {eixo}{extra} ({duracao} min).\n'
        f'Quando terminar, responde aqui: /concluido {eixo}'
    )
    estado["janela_notificada_hoje"][janela["nome"]] = hoje_str
    estado.setdefault("sugestao_hoje", {})[janela["nome"]] = eixo


def fechar_dia_se_necessario(cfg, estado, agora):
    """Se já passou das 23:45 e o dia ainda não foi 'fechado', regista faltas
    dos blocos sugeridos e não concluídos, e reseta os marcadores diários."""
    hoje_str = agora.date().isoformat()
    if estado.get("ultimo_fechamento") == hoje_str:
        return
    if agora.strftime("%H:%M") < "23:45":
        return

    sugestoes = estado.get("sugestao_hoje", {})
    for _janela_nome, eixo in sugestoes.items():
        info = estado["eixos"].setdefault(eixo, eixo_info_default())
        if info["ultima_data"] != hoje_str:
            info["faltas_seguidas"] += 1
            if info["faltas_seguidas"] >= cfg["regra_never_miss_twice"]["faltas_para_subir_prioridade"]:
                enviar_mensagem(f"⚠️ {eixo} ficou pra trás — prioridade sobe (never miss twice).")

    estado["sugestao_hoje"] = {}
    estado["janela_notificada_hoje"] = {}
    estado["ultimo_fechamento"] = hoje_str


def cmd_check():
    cfg = carregar_config()
    estado = carregar_estado(cfg)
    agora = agora_local(cfg)
    hoje = agora.date()

    processar_mensagens(cfg, estado, hoje)
    verificar_bloco_de_estudo(cfg, estado, agora)
    fechar_dia_se_necessario(cfg, estado, agora)

    salvar_estado(cfg, estado)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        cmd_check()
    else:
        print(__doc__)
       
