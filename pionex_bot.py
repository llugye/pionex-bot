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

# === CHAVES DE AMBIENTE ===
# Certifique-se de configurar estas variáveis no ambiente da Render
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
BASE_URL = "https://api.pionex.com"

EMAIL_ORIGEM = os.getenv("EMAIL_ORIGEM")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")
EMAIL_SENHA = os.getenv("EMAIL_SENHA")
SMTP_SERVIDOR = os.getenv("SMTP_SERVIDOR")
SMTP_PORTA = int(os.getenv("SMTP_PORTA", 587))

# === STATUS DO BOT ===
status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None,
    "versao": "1.0.1" # Versão atualizada
}

app = Flask(__name__)
tz = pytz.timezone('America/Sao_Paulo')

# === TIMESTAMP EM MILISSEGUNDOS ===
def get_timestamp() -> str:
    return str(int(datetime.utcnow().timestamp() * 1000))

# === GERA ASSINATURA DA REQUISIÇÃO ===
# A chave aqui é garantir que a "message" seja EXATAMENTE o que a Pionex espera.
# Para POST com JSON body, a estrutura geralmente é: METHOD + PATH + TIMESTAMP + BODY_AS_STRING
def sign_request(method: str, path: str, body: str = '') -> tuple:
    if not API_KEY or not API_SECRET:
        raise EnvironmentError("Erro: API_KEY ou API_SECRET não definidos. Por favor, configure-as.")
    
    timestamp = get_timestamp()
    
    # Constrói a mensagem para assinatura.
    # Para POSTs com body, o path é o caminho puro (sem query params)
    # e o body é a string JSON serializada.
    message = f"{method.upper()}{path}{timestamp}{body}"
    
    signature = hmac.new(API_SECRET.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()
    return timestamp, signature

# === ENVIA E-MAIL ===
def enviar_email(assunto: str, corpo: str):
    if not all([EMAIL_ORIGEM, EMAIL_DESTINO, EMAIL_SENHA, SMTP_SERVIDOR]):
        print("[AVISO] Configurações de e-mail incompletas. E-mail não será enviado.")
        return
        
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ORIGEM
        msg['To'] = EMAIL_DESTINO
        msg['Subject'] = assunto
        msg.attach(MIMEText(corpo, 'plain'))

        with smtplib.SMTP(SMTP_SERVIDOR, SMTP_PORTA) as servidor:
            servidor.starttls()
            servidor.login(EMAIL_ORIGEM, EMAIL_SENHA)
            servidor.sendmail(EMAIL_ORIGEM, EMAIL_DESTINO, msg.as_string())
        print(f"[EMAIL ENVIADO] Assunto: {assunto}")
    except Exception as e:
        print(f"[ERRO AO ENVIAR EMAIL] {e}")

# === CONSULTA SALDO DISPONÍVEL EM USDT ===
def get_balance_usdt() -> float:
    try:
        method = "GET"
        path = "/api/v1/account/balances"
        timestamp, signature = sign_request(method, path) # Não há body para GET
        headers = {
            "PIONEX-KEY": API_KEY,
            "PIONEX-SIGNATURE": signature,
            "timestamp": timestamp
        }

        print(f"🔄 Consultando saldo USDT em {BASE_URL + path}")
        response = requests.get(BASE_URL + path, headers=headers)
        response.raise_for_status() # Lança exceção para status de erro (4xx ou 5xx)
        data = response.json()

        if data.get("result"):
            for coin in data["data"]["balances"]:
                if coin["coin"] == "USDT":
                    # Usa .get para evitar KeyError e um fallback para "0"
                    valor = coin.get("free") or coin.get("available") or "0"
                    saldo = float(valor)
                    print(f"💰 Saldo disponível em USDT: {saldo}")
                    return saldo
            print("❗ USDT não encontrado na lista de saldos.")
            return 0.0
        else:
            print(f"❌ Erro ao consultar saldo: {data.get('message', 'Mensagem de erro desconhecida')}")
            enviar_email("❌ ERRO AO CONSULTAR SALDO", json.dumps(data))
            return 0.0

    except requests.exceptions.RequestException as e:
        print(f"❌ Erro de requisição ao consultar saldo: {e}")
        enviar_email("❌ ERRO DE REQUISIÇÃO SALDO", str(e))
        return 0.0
    except Exception as e:
        print(f"❌ Erro inesperado ao processar saldo: {e}")
        enviar_email("❌ ERRO INESPERADO SALDO", str(e))
        return 0.0

# === ROTA DE STATUS ===
@app.route("/status", methods=["GET"])
def status():
    status_data["hora_servidor"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(status_data)

# === ROTA PRINCIPAL /pionexbot ===
@app.route("/pionexbot", methods=["POST"])
def receive_signal():
    data = request.get_json(silent=False)
    
    # Validação inicial dos dados recebidos
    if not data:
        return jsonify({"error": "Nenhum dado JSON recebido."}), 400

    pair = data.get("pair")
    signal = data.get("signal")
    amount_str = data.get("amount") # Recebemos como string para tratar float
    
    print(f"\n🔔 Sinal recebido: Par={pair}, Sinal={signal}, Quantidade={amount_str}")

    try:
        if not pair or not signal:
            error_msg = "Parâmetros obrigatórios ausentes: 'pair' ou 'signal'."
            print(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        amount = 0.0
        if amount_str:
            try:
                amount = float(amount_str)
                if amount <= 0:
                    error_msg = "Quantidade 'amount' deve ser um valor positivo."
                    print(f"❌ {error_msg}")
                    return jsonify({"error": error_msg}), 400
            except ValueError:
                error_msg = "A quantidade 'amount' não é um número válido."
                print(f"❌ {error_msg}")
                return jsonify({"error": error_msg}), 400
        else:
            # Se 'amount' não for fornecido, tenta usar o saldo USDT
            print("ℹ️ Quantidade não especificada, consultando saldo USDT...")
            amount = get_balance_usdt()
            if amount <= 0:
                error_msg = "Saldo insuficiente para executar ordem ou erro ao consultar saldo."
                print(f"❌ {error_msg}")
                enviar_email("❌ SALDO INSUFICIENTE", error_msg)
                return jsonify({"error": error_msg}), 400
            # Adicione uma margem de segurança ou trate valores mínimos aqui, se necessário
            # Ex: amount = max(amount * 0.98, MIN_ORDER_AMOUNT)

        method = "POST"
        path = "/api/v1/trade/order"
        
        # O side da Pionex deve ser 'BUY' ou 'SELL' (maiúsculas)
        # Sua função já converte para lowercase, então vamos ajustar
        pionex_side = signal.upper() 
        if pionex_side not in ["BUY", "SELL"]:
            error_msg = f"Sinal inválido: '{signal}'. Deve ser 'buy' ou 'sell'."
            print(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        body_dict = {
            "symbol": pair,
            "side": pionex_side,
            "quoteOrderQty": f"{amount:.8f}" # Formatar para garantir precisão e string
        }
        body_json = json.dumps(body_dict)
        
        # AQUI É A MUDANÇA CRÍTICA: passando o body para sign_request
        timestamp, signature = sign_request(method, path, body=body_json)

        headers = {
            "PIONEX-KEY": API_KEY,
            "PIONEX-SIGNATURE": signature,
            "timestamp": timestamp,
            "Content-Type": "application/json"
        }

        print("\n📤 Enviando ordem para Pionex:")
        print(f"  🪙 Par: {pair}")
        print(f"  📊 Sinal: {pionex_side}")
        print(f"  💵 Quantidade (USDT): {amount:.8f}")
        print(f"  📦 Payload (assinado): {body_json}")
        print(f"  PIONEX-KEY: {API_KEY[:5]}...") # Mostra só o começo por segurança
        print(f"  PIONEX-SIGNATURE: {signature[:10]}...") # Mostra só o começo
        print(f"  Timestamp: {timestamp}")

        # CORREÇÃO: usar `data=body_json` em vez de `json=`
        response = requests.post(BASE_URL + path, headers=headers, data=body_json)
        
        print(f"📥 Resposta da Pionex: Status={response.status_code}, Corpo={response.text}")

        try:
            res_json = response.json()
        except requests.exceptions.JSONDecodeError:
            print("⚠️ A resposta da Pionex não é um JSON válido. Verifique os logs brutos.")
            res_json = {"error": "Erro ao interpretar resposta da API da Pionex (não é JSON).", "raw_response": response.text}
        except Exception:
            res_json = {"error": "Erro inesperado ao processar resposta da API da Pionex.", "raw_response": response.text}

        status_data["ultimo_horario"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        status_data["ultimo_sinal"] = f"{pionex_side} {pair}"

        if response.status_code == 200 and res_json.get("result"):
            success_msg = f"✅ ORDEM EXECUTADA com sucesso: {pionex_side} {pair} com {amount:.8f} USDT"
            print(success_msg)
            enviar_email("✅ ORDEM EXECUTADA", success_msg + f"\nDetalhes: {json.dumps(res_json, indent=2)}")
            return jsonify({"success": True, "message": success_msg, "response": res_json})
        else:
            error_msg = f"❌ ERRO NA ORDEM: {pionex_side} {pair}. Status: {response.status_code}. Mensagem: {res_json.get('message', 'Nenhuma mensagem de erro específica.')}"
            print(error_msg)
            enviar_email("❌ ERRO NA ORDEM", error_msg + f"\nDetalhes: {json.dumps(res_json, indent=2)}")
            return jsonify({"error": res_json}), response.status_code # Retorna o status code original da Pionex

    except Exception as e:
        import traceback
        full_traceback = traceback.format_exc()
        print(f"[ERRO INTERNO INESPERADO] {str(e)}\n{full_traceback}")
        enviar_email("❌ ERRO INTERNO DO BOT", f"Um erro inesperado ocorreu:\n{str(e)}\n\nTraceback:\n{full_traceback}")
        return jsonify({"error": str(e), "traceback": full_traceback}), 500

# === EXECUÇÃO LOCAL ===
if __name__ == "__main__":
    # Para rodar localmente, você pode definir as variáveis de ambiente aqui
    # Ex:
    # os.environ["API_KEY"] = "SUA_API_KEY_AQUI"
    # os.environ["API_SECRET"] = "SUA_API_SECRET_AQUI"
    # os.environ["EMAIL_ORIGEM"] = "seu_email@dominio.com"
    # os.environ["EMAIL_DESTINO"] = "email_destino@dominio.com"
    # os.environ["EMAIL_SENHA"] = "sua_senha_de_email"
    # os.environ["SMTP_SERVIDOR"] = "smtp.gmail.com" # Ou o seu servidor SMTP
    # os.environ["SMTP_PORTA"] = "587"

    # Na Render, a porta é fornecida pela variável de ambiente PORT
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Bot Pionex rodando na porta {port}")
    app.run(host="0.0.0.0", port=port)
