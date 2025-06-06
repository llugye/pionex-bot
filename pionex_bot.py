import os
import hmac
import hashlib
import requests
import json
from flask import Flask, request, jsonify
from datetime import datetime
import pytz
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import traceback # Para capturar o traceback completo em erros

# === CHAVES DE AMBIENTE ===
# Certifique-se de configurar estas variáveis no ambiente da Render
# Ex: API_KEY, API_SECRET, EMAIL_ORIGEM, EMAIL_DESTINO, EMAIL_SENHA, SMTP_SERVIDOR, SMTP_PORTA
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
BASE_URL = "https://api.pionex.com" # Base URL da API da Pionex

EMAIL_ORIGEM = os.getenv("EMAIL_ORIGEM")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")
EMAIL_SENHA = os.getenv("EMAIL_SENHA")
SMTP_SERVIDOR = os.getenv("SMTP_SERVIDOR")
SMTP_PORTA = int(os.getenv("SMTP_PORTA", 587)) # Porta padrão para SMTP TLS

# === STATUS DO BOT ===
status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None,
    "versao": "1.0.4" # Versão atualizada
}

app = Flask(__name__)
# Definir o fuso horário para Brasil/São Paulo para logs e timestamps locais
tz = pytz.timezone('America/Sao_Paulo')

# === TIMESTAMP EM MILISSEGUNDOS ===
def get_timestamp() -> str:
    # Retorna o timestamp UTC em milissegundos como string, essencial para a assinatura
    return str(int(datetime.utcnow().timestamp() * 1000))

# === GERA ASSINATURA DA REQUISIÇÃO ===
# Esta função é crucial para a segurança e autenticação da API.
# A mensagem para assinatura é construída como: HTTP_METHOD + REQUEST_PATH + TIMESTAMP + REQUEST_BODY.
# O REQUEST_BODY é a string JSON serializada para POST requests.
def sign_request(method: str, path: str, body: str = '') -> tuple:
    if not API_KEY or not API_SECRET:
        # Lança um erro claro se as chaves de API não estiverem configuradas
        raise EnvironmentError("Erro: API_KEY ou API_SECRET não definidos. Por favor, configure-as nas variáveis de ambiente da Render.")
    
    timestamp = get_timestamp()
    
    # Constrói a string da mensagem para ser assinada.
    # Para POSTs com body (como a criação de ordem), o 'path' é o caminho puro do endpoint.
    message = f"{method.upper()}{path}{timestamp}{body}"
    
    # Gera a assinatura HMAC SHA256 usando o API_SECRET
    signature = hmac.new(API_SECRET.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()
    
    return timestamp, signature

# === ENVIA E-MAIL ===
# Função para enviar notificações por e-mail sobre o status das ordens ou erros.
def enviar_email(assunto: str, corpo: str):
    # Verifica se todas as configurações de e-mail necessárias estão presentes
    if not all([EMAIL_ORIGEM, EMAIL_DESTINO, EMAIL_SENHA, SMTP_SERVIDOR]):
        print("[AVISO] Configurações de e-mail incompletas. E-mail de alerta não será enviado. Verifique suas variáveis de ambiente.")
        return
        
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ORIGEM
        msg['To'] = EMAIL_DESTINO
        msg['Subject'] = assunto
        msg.attach(MIMEText(corpo, 'plain'))

        with smtplib.SMTP(SMTP_SERVIDOR, SMTP_PORTA) as servidor:
            servidor.starttls() # Inicia a conexão TLS (criptografada)
            servidor.login(EMAIL_ORIGEM, EMAIL_SENHA)
            servidor.sendmail(EMAIL_ORIGEM, EMAIL_DESTINO, msg.as_string())
        print(f"[EMAIL ENVIADO] Assunto: '{assunto}' para {EMAIL_DESTINO}")
    except Exception as e:
        print(f"[ERRO AO ENVIAR EMAIL] Ocorreu um erro: {e}")
        # Imprime o traceback completo para depuração de problemas de e-mail
        print(traceback.format_exc()) 

# === CONSULTA SALDO DISPONÍVEL EM USDT ===
# Obtém o saldo de USDT na sua conta da Pionex.
def get_balance_usdt() -> float:
    try:
        method = "GET"
        path = "/api/v1/account/balances"
        # Para requisições GET de saldo, o 'body' da assinatura é vazio
        timestamp, signature = sign_request(method, path, body='') 
        
        headers = {
            "PIONEX-KEY": API_KEY,
            "PIONEX-SIGNATURE": signature,
            "timestamp": timestamp
        }

        print(f"🔄 Consultando saldo USDT em {BASE_URL + path}")
        response = requests.get(BASE_URL + path, headers=headers)
        response.raise_for_status() # Lança uma exceção HTTPError para respostas de erro (4xx ou 5xx)

        data = response.json()

        if data.get("result"): # A Pionex retorna "result: true" para sucesso
            for coin in data["data"]["balances"]:
                if coin["coin"] == "USDT":
                    # Pega o saldo 'free' ou 'available', com fallback para "0"
                    valor = coin.get("free") or coin.get("available") or "0"
                    saldo = float(valor)
                    print(f"💰 Saldo disponível em USDT: {saldo:.8f}") # Formata para 8 casas decimais
                    return saldo
            print("❗ Moeda USDT não encontrada na lista de saldos recebida da Pionex.")
            return 0.0
        else:
            # Se 'result' não for true, extrai e imprime a mensagem de erro da API
            error_msg_api = data.get('message', 'Mensagem de erro desconhecida da Pionex.')
            print(f"❌ Erro ao consultar saldo na Pionex: {error_msg_api}")
            enviar_email("❌ ERRO AO CONSULTAR SALDO", f"Erro da API Pionex: {error_msg_api}\nResposta Completa: {json.dumps(data, indent=2)}")
            return 0.0

    except requests.exceptions.RequestException as e:
        # Captura erros relacionados à requisição HTTP (conexão, timeout, etc.)
        print(f"❌ Erro de requisição HTTP ao consultar saldo: {e}")
        enviar_email("❌ ERRO DE REQUISIÇÃO (SALDO)", str(e))
        return 0.0
    except Exception as e:
        # Captura outros erros inesperados durante o processamento do saldo
        print(f"❌ Erro inesperado ao processar saldo: {e}")
        print(traceback.format_exc()) # Imprime o traceback completo para depuração
        enviar_email("❌ ERRO INTERNO (SALDO)", f"Erro inesperado: {str(e)}\n\nTraceback:\n{traceback.format_exc()}")
        return 0.0

# === ROTA DE STATUS ===
# Endpoint para verificar o status do bot.
@app.route("/status", methods=["GET"])
def status():
    # Atualiza o horário atual do servidor no fuso horário de São Paulo para o status
    status_data["hora_servidor"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(status_data)

# === ROTA PRINCIPAL /pionexbot ===
# Endpoint principal que recebe os sinais de compra/venda.
@app.route("/pionexbot", methods=["POST"])
def receive_signal():
    # Tenta obter o JSON do corpo da requisição. silent=True evita quebrar se não for JSON.
    data = request.get_json(silent=True) 
    
    # Validação inicial: verifica se um JSON válido foi recebido
    if not data:
        error_msg = "Nenhum dado JSON válido recebido ou 'Content-Type' incorreto. Certifique-se de enviar 'application/json'."
        print(f"❌ {error_msg}")
        return jsonify({"error": error_msg}), 400

    pair = data.get("pair") # Par de negociação (ex: "BTCUSDT")
    signal = data.get("signal") # Tipo de sinal ("buy" ou "sell")
    amount_str = data.get("amount") # Quantidade (opcional, pode ser string ou float)
    
    print(f"\n🔔 Sinal recebido: Par='{pair}', Sinal='{signal}', Quantidade='{amount_str}'")

    try:
        # Validação de parâmetros obrigatórios do sinal
        if not pair or not signal:
            error_msg = "Parâmetros obrigatórios ausentes: 'pair' ou 'signal'."
            print(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        amount = 0.0
        if amount_str:
            try:
                amount = float(amount_str) # Tenta converter a quantidade para float
                if amount <= 0:
                    error_msg = "A quantidade 'amount' deve ser um valor positivo."
                    print(f"❌ {error_msg}")
                    return jsonify({"error": error_msg}), 400
            except ValueError:
                error_msg = f"A quantidade '{amount_str}' não é um número válido."
                print(f"❌ {error_msg}")
                return jsonify({"error": error_msg}), 400
        else:
            # Se 'amount' não for fornecido no payload, tenta usar o saldo USDT total
            print("ℹ️ Quantidade não especificada no sinal, consultando saldo USDT disponível para a ordem de mercado...")
            amount = get_balance_usdt()
            if amount <= 0:
                error_msg = "Saldo insuficiente em USDT ou erro ao consultar saldo para executar a ordem."
                print(f"❌ {error_msg}")
                enviar_email("❌ SALDO INSUFICIENTE", error_msg)
                return jsonify({"error": error_msg}), 400
            
            # Recomenda-se adicionar uma margem de segurança ou verificar limites mínimos de ordem da Pionex aqui.
            # Ex: Se a ordem mínima for 10 USDT, e o saldo for 8, a ordem falharia.
            # amount = max(amount * 0.99, 10.0) # Exemplo: usar 99% do saldo ou no mínimo 10 USDT

        method = "POST"
        path = "/api/v1/trade/order" # Endpoint da Pionex para criar ordens

        # Converte o sinal para maiúsculas ("BUY" ou "SELL"), conforme exigido pela Pionex
        pionex_side = signal.upper() 
        if pionex_side not in ["BUY", "SELL"]:
            error_msg = f"Sinal inválido: '{signal}'. Deve ser 'buy' ou 'sell'."
            print(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        # Monta o corpo da requisição JSON para a API da Pionex.
        # "quoteOrderQty" indica uma ordem de mercado pelo valor total na moeda de cotação (USDT).
        body_dict = {
            "symbol": pair.upper(), # Símbolo do par em maiúsculas (ex: "BTCUSDT")
            "side": pionex_side,
            "quoteOrderQty": f"{amount:.8f}" # Quantidade de USDT para gastar/receber, formatado como string
        }
        body_json = json.dumps(body_dict) # Serializa o dicionário Python para uma string JSON

        # GERA A ASSINATURA: Passa o método, o caminho e o corpo JSON serializado.
        # Esta assinatura garante a autenticidade e integridade da requisição.
        timestamp, signature = sign_request(method, path, body=body_json)

        # Monta os cabeçalhos HTTP necessários para a autenticação e tipo de conteúdo
        headers = {
            "PIONEX-KEY": API_KEY,
            "PIONEX-SIGNATURE": signature,
            "timestamp": timestamp,
            "Content-Type": "application/json" # Informa que o corpo da requisição é JSON
        }

        print("\n📤 Enviando ordem para Pionex:")
        print(f"  🪙 Par: {pair.upper()}")
        print(f"  📊 Sinal: {pionex_side}")
        print(f"  💵 Quantidade (USDT): {amount:.8f}")
        print(f"  📦 Payload (assinado): {body_json}")
        # Para segurança, apenas as primeiras partes das chaves/assinaturas são impressas
        print(f"  PIONEX-KEY (início): {API_KEY[:5]}...") 
        print(f"  PIONEX-SIGNATURE (início): {signature[:10]}...") 
        print(f"  Timestamp: {timestamp}")

        # Realiza a requisição POST para a API da Pionex.
        # Crucial: usa 'data=body_json' para enviar a STRING JSON bruta que foi assinada,
        # e não 'json=body_dict' que serializaria novamente.
        response = requests.post(BASE_URL + path, headers=headers, data=body_json)
        
        # Imprime a resposta bruta da API da Pionex nos logs, essencial para depuração
        print(f"📥 Resposta BRUTA da Pionex: Status={response.status_code}, Corpo={response.text}")

        res_json = {} # Inicializa para garantir que sempre seja um dicionário
        try:
            res_json = response.json() # Tenta decodificar a resposta como JSON
        except requests.exceptions.JSONDecodeError:
            # Se a resposta não for um JSON válido, registra o erro e a resposta bruta
            print("⚠️ A resposta da Pionex NÃO É UM JSON válido. Isso pode indicar um erro grave na requisição ou na API.")
            res_json = {"error": "Resposta da API Pionex não é JSON válido.", "raw_response": response.text}
        except Exception as e:
            # Captura outras exceções inesperadas ao tentar decodificar o JSON
            print(f"⚠️ Erro inesperado ao decodificar JSON da resposta da Pionex: {e}")
            res_json = {"error": "Erro inesperado ao decodificar JSON da Pionex.", "raw_response": response.text}

        # Atualiza os dados de status do bot para monitoramento
        status_data["ultimo_horario"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        status_data["ultimo_sinal"] = f"{pionex_side} {pair.upper()}"

        # Verifica o resultado da ordem com base no status HTTP e no campo "result" do JSON
        if response.status_code == 200 and res_json.get("result"):
            success_msg = f"✅ ORDEM EXECUTADA com sucesso: {pionex_side} {pair.upper()} com {amount:.8f} USDT."
            print(success_msg)
            enviar_email("✅ ORDEM EXECUTADA", success_msg + f"\nDetalhes da Ordem: {json.dumps(res_json, indent=2)}")
            return jsonify({"success": True, "message": success_msg, "response": res_json})
        else:
            # Se a ordem falhou (status não 200 ou "result" falso), registra o erro
            error_msg_api = res_json.get('message', 'Nenhuma mensagem de erro específica da Pionex.')
            full_error_msg = f"❌ ERRO NA ORDEM: {pionex_side} {pair.upper()}. Status HTTP: {response.status_code}. Mensagem da Pionex: '{error_msg_api}'"
            print(full_error_msg)
            enviar_email("❌ ERRO NA ORDEM", full_error_msg + f"\nResposta Completa da Pionex: {json.dumps(res_json, indent=2)}")
            # Retorna o status code original da Pionex se for um erro de cliente/servidor (4xx/5xx), senão 400
            return jsonify({"error": res_json}), response.status_code if response.status_code >= 400 else 400

    except EnvironmentError as e:
        # Erro específico para chaves de API não configuradas
        print(f"[ERRO DE CONFIGURAÇÃO] {e}")
        enviar_email("❌ ERRO DE CONFIGURAÇÃO", str(e))
        return jsonify({"error": str(e)}), 500
    except requests.exceptions.RequestException as e:
        # Erros de conexão ou requisição HTTP para a API externa
        print(f"[ERRO DE CONEXÃO] Erro ao conectar à API da Pionex: {e}")
        enviar_email("❌ ERRO DE CONEXÃO", f"Erro ao conectar à Pionex: {str(e)}")
        return jsonify({"error": f"Erro de conexão com a Pionex: {e}"}), 500
    except Exception as e:
        # Captura qualquer outro erro inesperado no fluxo principal do bot
        full_traceback = traceback.format_exc() # Obtém o traceback completo da exceção
        print(f"[ERRO INTERNO INESPERADO DO BOT] {str(e)}\n{full_traceback}")
        enviar_email("❌ ERRO INTERNO DO BOT", f"Um erro inesperado ocorreu:\n{str(e)}\n\nTraceback:\n{full_traceback}")
        return jsonify({"error": str(e), "traceback": full_traceback}), 500

# === EXECUÇÃO LOCAL ===
if __name__ == "__main__":
    # Bloco para execução local do bot.
    # Em ambiente de produção (Render), as variáveis de ambiente são definidas externamente.
    # Para testes locais, você pode descomentar e preencher as variáveis abaixo:
    # os.environ["API_KEY"] = "SUA_API_KEY_AQUI"
    # os.environ["API_SECRET"] = "SUA_API_SECRET_AQUI"
    # os.environ["EMAIL_ORIGEM"] = "seu_email@dominio.com"
    # os.environ["EMAIL_DESTINO"] = "email_destino@dominio.com"
    # os.environ["EMAIL_SENHA"] = "sua_senha_de_email"
    # os.environ["SMTP_SERVIDOR"] = "smtp.gmail.com" # Exemplo: smtp.gmail.com, smtp.outlook.com
    # os.environ["SMTP_PORTA"] = "587" # Porta padrão para TLS

    # A porta para o servidor Flask é lida da variável de ambiente "PORT" (Render)
    # ou padrão 10000 para execução local.
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Bot Pionex rodando na porta {port}. Verifique os logs na Render após o deploy.")
    # DEBUG=TRUE Adicionado para ajudar a ver mais logs durante a depuração.
    # Lembre-se de REMOVER isso para ambiente de produção!
    app.run(host="0.0.0.0", port=port, debug=True)
