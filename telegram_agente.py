#!/usr/bin/env python3
"""
Agente Pessoal — versão Telegram (roda na nuvem via GitHub Actions)
--------------------------------------------------------------------
Este script é chamado automaticamente pelo GitHub Actions a cada 15 minutos.
Ele faz duas coisas em cada execução:

1. Lê mensagens novas que tu mandaste pro bot no Telegram (ex: /concluido RTIEBT)
   e processa os comandos.
2. Verifica se agora é hora de um bloco de estudo e, se for, manda uma
   mensagem no Telegram avisando qual eixo estudar.

Toda a configuração fica em config.json. O progresso fica em estado.json,
que é salvo de volta no repositório automaticamente pelo GitHub Actions.

Comandos que tu podes mandar pro bot no Telegram:
  /concluido RTIEBT                         -> marca o bloco de hoje como feito (repetição espaçada)
  /concluido RTIEBT fiz revisão de esquemas -> marca feito E regista a nota no diário do repositório do eixo
  /topico RTIEBT Esquemas trifásicos        -> adiciona um tópico novo à lista do eixo
  /feito RTIEBT Esquemas trifásicos          -> marca esse tópico como concluído
  /topicos RTIEBT                            -> lista os tópicos (pendentes e concluídos) do eixo
  /sincronizar RTIEBT                        -> puxa tópicos/subtópicos do Google Doc do eixo pro topicos.md
  /sincronizartudo                           -> faz isso pra todos os eixos que já têm google_doc_id configurado
  /revisar            -> lista o que está vencido pra revisão agora
  /status             -> resumo de progresso por eixo
  /ajuda              -> lista os comandos
"""

import base64
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build as google_build

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9, não deve acontecer no runner do GitHub Actions
    ZoneInfo = None

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

DIAS_PT = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]

GOOGLE_SA_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PROGRESSO_TOKEN = os.environ.get("PROGRESSO_REPO_TOKEN")


def carregar_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def caminho_estado(cfg):
    return BASE_DIR / cfg["arquivo_estado"]


def eixo_info_default():
    return {"ultima_data": None, "faltas_seguidas": 0, "total_blocos": 0,
            "nivel_revisao": 0, "proxima_revisao": None}


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


# ---------- Lógica de repetição espaçada (igual à versão local) ----------

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
    return (f"Registado: bloco de {nome_eixo} concluído hoje. Total: {info['total_blocos']} blocos. "
            f"Próxima revisão: {info['proxima_revisao']} (nível {nivel}).")


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
    "/sincronizar NOME_DO_EIXO — puxa tópicos/subtópicos novos do Google Doc do eixo\n"
    "/sincronizartudo — faz isso pra todos os eixos com google_doc_id configurado\n"
    "/reiniciartudo CONFIRMAR — zera repetição espaçada, tópicos e diários de TODOS os eixos (irreversível)\n"
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
        api_gravar_arquivo(owner, repo, caminho, conteudo + entrada, sha,
                            f"Diário: {nome_eixo} em {hoje.isoformat()}")
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
        api_gravar_arquivo(owner, repo, caminho, novo_conteudo, sha,
                            f"Novo tópico em {nome_eixo}: {topico_texto}")
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
        api_gravar_arquivo(owner, repo, caminho, "\n".join(linhas), sha,
                            f"Tópico concluído em {nome_eixo}: {topico_texto}")
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


# ---------- Google Docs: extrair tópicos/subtópicos por estilo de título ----------

def obter_servico_docs():
    if not GOOGLE_SA_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON não configurado.")
    info = json.loads(GOOGLE_SA_JSON)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/documents.readonly"]
    )
    return google_build("docs", "v1", credentials=creds)


def texto_do_paragrafo(paragraph):
    partes = []
    for elemento in paragraph.get("elements", []):
        run = elemento.get("textRun")
        if run:
            partes.append(run.get("content", ""))
    return "".join(partes).strip()


def extrair_estrutura_do_doc(doc_id):
    """Lê o Google Doc e retorna uma lista de tópicos na ordem em que aparecem:
    [{"topico": "1. Motor Elétrico",
      "subtopicos": [{"subtopico": "Potência", "subsubtopicos": ["Pu", "Pa"]}, ...]}, ...]
    Só considera parágrafos com estilo Heading 1 (tópico), Heading 2 (subtópico)
    e Heading 3 (sub-subtópico); todo o resto do texto (definições, corpo do
    documento) é ignorado. Um Heading 3 sem um Heading 2 antes dele (dentro do
    mesmo tópico) é ignorado, pois não tem onde encaixar na hierarquia."""
    servico = obter_servico_docs()
    doc = servico.documents().get(documentId=doc_id).execute()

    estrutura = []
    topico_atual = None
    subtopico_atual = None
    for elemento in doc.get("body", {}).get("content", []):
        paragrafo = elemento.get("paragraph")
        if not paragrafo:
            continue
        estilo = paragrafo.get("paragraphStyle", {}).get("namedStyleType", "")
        texto = texto_do_paragrafo(paragrafo)
        if not texto:
            continue

        if estilo == "HEADING_1":
            topico_atual = {"topico": texto, "subtopicos": []}
            estrutura.append(topico_atual)
            subtopico_atual = None
        elif estilo == "HEADING_2" and topico_atual is not None:
            subtopico_atual = {"subtopico": texto, "subsubtopicos": []}
            topico_atual["subtopicos"].append(subtopico_atual)
        elif estilo == "HEADING_3" and subtopico_atual is not None:
            subtopico_atual["subsubtopicos"].append(texto)
        # qualquer outro estilo (texto normal, bullets de definição, etc.) é ignorado

    return estrutura


def parsear_topicos_md(conteudo):
    """Lê o conteúdo atual de topicos.md e devolve (cabecalho, arvore_de_topicos).
    Cada nó é {"texto":..., "feito": bool, "subs": [nó, nó, ...]}, com profundidade
    ilimitada — o nível é determinado pela indentação (2 espaços por nível)."""
    linhas = conteudo.split("\n") if conteudo else []
    cabecalho = []
    raiz = []
    pilha = []  # [(nivel, node), ...] dos nós ainda "abertos"
    dentro_da_lista = False

    for linha in linhas:
        semi = linha.strip()
        if semi.startswith("- [ ]") or semi.startswith("- [x]"):
            dentro_da_lista = True
            feito = semi.startswith("- [x]")
            texto = semi[5:].strip()
            indent = len(linha) - len(linha.lstrip(" \t"))
            nivel = indent // 2
            node = {"texto": texto, "feito": feito, "subs": []}
            while pilha and pilha[-1][0] >= nivel:
                pilha.pop()
            if pilha:
                pilha[-1][1]["subs"].append(node)
            else:
                raiz.append(node)
            pilha.append((nivel, node))
        elif not dentro_da_lista:
            cabecalho.append(linha)
        # linhas em branco dentro da lista são só ignoradas na reconstrução

    return "\n".join(cabecalho).rstrip("\n"), raiz


def montar_topicos_md(cabecalho, topicos):
    linhas = [cabecalho.rstrip("\n"), ""]

    def escrever(nodes, nivel):
        for n in nodes:
            marca = "x" if n["feito"] else " "
            linhas.append("  " * nivel + f"- [{marca}] {n['texto']}")
            escrever(n["subs"], nivel + 1)

    escrever(topicos, 0)
    return "\n".join(linhas).rstrip("\n") + "\n"


def mesclar_estrutura_no_topicos_md(conteudo_atual, nome_eixo, estrutura_doc):
    """Junta a estrutura vinda do Google Doc (até 3 níveis: tópico, subtópico,
    sub-subtópico) com o topicos.md existente, só ADICIONANDO o que ainda não
    existe (por texto exato em cada nível), sem nunca desmarcar ou remover o
    que já está lá. Retorna (novo_conteudo, resumo)."""
    if conteudo_atual is None:
        cabecalho = f"# Tópicos — {nome_eixo}"
        topicos = []
    else:
        cabecalho, topicos = parsear_topicos_md(conteudo_atual)
        if not cabecalho:
            cabecalho = f"# Tópicos — {nome_eixo}"

    contadores = {"topicos": 0, "subtopicos": 0, "subsubtopicos": 0}

    def encontrar_ou_criar(lista_nodes, texto):
        for n in lista_nodes:
            if n["texto"] == texto:
                return n, False
        novo = {"texto": texto, "feito": False, "subs": []}
        lista_nodes.append(novo)
        return novo, True

    for item in estrutura_doc:
        node_topico, criado = encontrar_ou_criar(topicos, item["topico"])
        if criado:
            contadores["topicos"] += 1
        for sub in item.get("subtopicos", []):
            node_sub, criado_sub = encontrar_ou_criar(node_topico["subs"], sub["subtopico"])
            if criado_sub:
                contadores["subtopicos"] += 1
            for nome_subsub in sub.get("subsubtopicos", []):
                _, criado_subsub = encontrar_ou_criar(node_sub["subs"], nome_subsub)
                if criado_subsub:
                    contadores["subsubtopicos"] += 1

    novo_conteudo = montar_topicos_md(cabecalho, topicos)
    resumo = (f"{contadores['topicos']} tópico(s), {contadores['subtopicos']} subtópico(s) e "
              f"{contadores['subsubtopicos']} sub-subtópico(s) novo(s)")
    return novo_conteudo, resumo


def sincronizar_topicos_do_doc(cfg, nome_eixo):
    owner, repo = repo_do_eixo(cfg, nome_eixo)
    if not owner:
        return f"O eixo {nome_eixo} não tem repositório configurado."
    if not PROGRESSO_TOKEN:
        return "PROGRESSO_REPO_TOKEN não configurado — não consigo gravar no GitHub agora."

    doc_id = None
    for eixo in cfg["eixos_estudo"]:
        if eixo["nome"] == nome_eixo:
            doc_id = eixo.get("google_doc_id")
    if not doc_id:
        return f"O eixo {nome_eixo} ainda não tem google_doc_id configurado em config.json."

    try:
        estrutura = extrair_estrutura_do_doc(doc_id)
    except Exception as e:
        return f"Erro ao ler o Google Doc de {nome_eixo}: {e}"

    if not estrutura:
        return (f"Não encontrei nenhum título Heading 1 no doc de {nome_eixo}. "
                f"Confere se os tópicos estão marcados com o estilo 'Título 1' e os subtópicos com 'Título 2'.")

    caminho = cfg.get("arquivo_topicos", "topicos.md")
    try:
        conteudo_atual, sha = api_ler_arquivo(owner, repo, caminho)
        novo_conteudo, resumo = mesclar_estrutura_no_topicos_md(conteudo_atual, nome_eixo, estrutura)
        if novo_conteudo == conteudo_atual:
            return f"Sincronizado com {nome_eixo}: nada novo (já estava tudo atualizado)."
        api_gravar_arquivo(owner, repo, caminho, novo_conteudo, sha,
                            f"Sincronização com Google Doc: {nome_eixo}")
        return f"Sincronizado com {nome_eixo}: {resumo}."
    except Exception as e:
        return f"Erro ao gravar tópicos sincronizados de {nome_eixo}: {e}"


def sincronizar_todos_os_eixos(cfg):
    """Roda a sincronização do Google Doc pra todo eixo que tiver google_doc_id
    preenchido, pulando os demais. Retorna um texto-resumo único."""
    linhas = ["Sincronização de todos os eixos:"]
    algum_configurado = False
    for eixo in cfg["eixos_estudo"]:
        nome = eixo["nome"]
        if not eixo.get("google_doc_id"):
            linhas.append(f"- {nome}: sem google_doc_id configurado, pulei")
            continue
        algum_configurado = True
        try:
            resultado = sincronizar_topicos_do_doc(cfg, nome)
        except Exception as e:
            resultado = f"erro: {e}"
        linhas.append(f"- {nome}: {resultado}")

    if not algum_configurado:
        return "Nenhum eixo tem google_doc_id configurado ainda em config.json."
    return "\n".join(linhas)


# ---------- Reinício completo (repetição espaçada + tópicos + diários) ----------

def reiniciar_estado_estudo(cfg, estado):
    """Zera o progresso de repetição espaçada de todos os eixos, mantendo o
    offset do Telegram intacto (pra não reprocessar mensagens antigas)."""
    estado["eixos"] = {e["nome"]: eixo_info_default() for e in cfg["eixos_estudo"]}
    estado["janela_notificada_hoje"] = {}
    estado["sugestao_hoje"] = {}
    estado["ultimo_fechamento"] = None


def desmarcar_todos_recursivo(nodes):
    for n in nodes:
        n["feito"] = False
        desmarcar_todos_recursivo(n["subs"])


def reiniciar_topicos_e_diario_do_eixo(cfg, nome_eixo):
    """Desmarca todos os tópicos (sem apagar a lista) e limpa o diario.md,
    voltando só ao título. Retorna uma mensagem de status."""
    owner, repo = repo_do_eixo(cfg, nome_eixo)
    if not owner:
        return f"{nome_eixo}: sem repositório configurado, pulei"
    if not PROGRESSO_TOKEN:
        return f"{nome_eixo}: PROGRESSO_REPO_TOKEN não configurado"

    caminho_topicos = cfg.get("arquivo_topicos", "topicos.md")
    caminho_diario = cfg.get("arquivo_diario", "diario.md")
    partes_msg = []

    try:
        conteudo_topicos, sha_topicos = api_ler_arquivo(owner, repo, caminho_topicos)
        if conteudo_topicos is not None:
            cabecalho, topicos = parsear_topicos_md(conteudo_topicos)
            desmarcar_todos_recursivo(topicos)
            novo_conteudo = montar_topicos_md(cabecalho or f"# Tópicos — {nome_eixo}", topicos)
            if novo_conteudo != conteudo_topicos:
                api_gravar_arquivo(owner, repo, caminho_topicos, novo_conteudo, sha_topicos,
                                    f"Reinício: tópicos desmarcados em {nome_eixo}")
            partes_msg.append("tópicos desmarcados")
        else:
            partes_msg.append("sem topicos.md ainda")
    except Exception as e:
        partes_msg.append(f"erro nos tópicos ({e})")

    try:
        _conteudo_diario, sha_diario = api_ler_arquivo(owner, repo, caminho_diario)
        novo_diario = f"# Diário de progresso — {nome_eixo}\n"
        api_gravar_arquivo(owner, repo, caminho_diario, novo_diario, sha_diario,
                            f"Reinício: diário zerado em {nome_eixo}")
        partes_msg.append("diário zerado")
    except Exception as e:
        partes_msg.append(f"erro no diário ({e})")

    return f"{nome_eixo}: " + ", ".join(partes_msg)


def reiniciar_tudo(cfg, estado):
    reiniciar_estado_estudo(cfg, estado)
    linhas = ["Reinício completo:"]
    for eixo in cfg["eixos_estudo"]:
        linhas.append("- " + reiniciar_topicos_e_diario_do_eixo(cfg, eixo["nome"]))
    linhas.append("")
    linhas.append("Repetição espaçada zerada pra todos os eixos. A partir de agora, é como começar do zero.")
    return "\n".join(linhas)


# ---------- Processamento das mensagens recebidas ----------

def processar_mensagens(cfg, estado, hoje):
    mensagens = buscar_mensagens_novas(estado)
    for msg in mensagens:
        update_id = msg["update_id"]
        estado["ultimo_update_id_telegram"] = max(estado.get("ultimo_update_id_telegram", 0), update_id)

        mensagem = msg.get("message", {}) or {}
        texto = mensagem.get("text", "").strip()
        remetente_chat_id = str(mensagem.get("chat", {}).get("id", ""))

        if not texto:
            continue

        # Segurança: ignora qualquer mensagem que não venha do teu chat.
        # Isso garante que, mesmo que alguém descubra o username do bot,
        # não consiga executar comandos nem ler nenhuma resposta.
        if not CHAT_ID or remetente_chat_id != str(CHAT_ID):
            print(f"Mensagem ignorada de chat não autorizado: {remetente_chat_id}")
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

        elif texto.startswith("/reiniciartudo"):
            partes = texto.split(maxsplit=1)
            if len(partes) < 2 or partes[1].strip().upper() != "CONFIRMAR":
                enviar_mensagem(
                    "⚠️ Isso vai zerar TODA a repetição espaçada, desmarcar todos os tópicos "
                    "concluídos e apagar todos os diários de progresso, em todos os eixos. "
                    "Não tem como desfazer.\n\n"
                    "Se tens certeza, manda: /reiniciartudo CONFIRMAR"
                )
                continue
            enviar_mensagem(reiniciar_tudo(cfg, estado))

        elif texto.startswith("/sincronizartudo"):
            enviar_mensagem(sincronizar_todos_os_eixos(cfg))

        elif texto.startswith("/sincronizar"):
            partes = texto.split(maxsplit=1)
            nomes_validos = [e["nome"] for e in cfg["eixos_estudo"]]
            if len(partes) < 2:
                enviar_mensagem(f"Uso: /sincronizar NOME_DO_EIXO. Eixos válidos: {', '.join(nomes_validos)}")
                continue
            nome_eixo, _resto = separar_eixo_e_notas(partes[1], nomes_validos)
            if nome_eixo is None:
                enviar_mensagem(f"Eixo não reconhecido. Eixos válidos: {', '.join(nomes_validos)}")
                continue
            enviar_mensagem(sincronizar_topicos_do_doc(cfg, nome_eixo))

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
