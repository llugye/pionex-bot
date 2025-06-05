import os
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from datetime import datetime
import pytz
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Variáveis de ambiente
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
BASE_URL = "https://api.pionex.com"

EMAIL_ORIGEM = os.getenv("EMAIL_ORIGEM")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")
EMAIL_SENHA = os.getenv("EMAIL_SENHA")
SMTP_SERVIDOR = os.getenv("SMTP_SERVIDOR")
SMTP_PORTA = int(os.getenv("SMTP_PORTA", 587))

# Dados de status
status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None,
    "versao": "1.0.0"
}

app = Flask(__name__)
tz = pytz.timezone('America/Sao_Paulo')

def get_timestamp():
    return str(int(datetime.utcnow().timestamp() * 1000))

def sign_request(method, path, query='', body=''):
    if not API_KEY or not API_SECRET:
        raise EnvironmentError("Erro: API_KEY ou API_SECRET não definidos.")
    timestamp = get_timestamp()
    full_path = f"{path}?{query}" if query else path
    message = f"{method.upper()}{full_path}{timestamp}{body}"
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return timestamp, signature

def enviar_email(assunto, corpo):
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
    except Exception as e:
        print(f"[ERRO EMAIL] {e}")

def get_balance_usdt():
    method = "GET"
    path = "/api/v1/account/balances"
    query = ""
    timestamp, signature = sign_request(method, path, query)

    headers = {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": signature,
        "timestamp": timestamp
    }

    response = requests.get(BASE_URL + path, headers=headers)
    data = response.json()

    if data.get("result"):
        for saldo in data["data"]["balances"]:
            if saldo["coin"] == "USDT":
                return float(saldo["free"])
    return 0

@app.route("/status", methods=["GET"])
def status():
    status_data["hora_servidor"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(status_data)

@app.route("/pionexbot", methods=["POST"])
def receive_signal():
    data = request.json
    pair = data.get("pair")
    signal = data.get("signal")
    amount = data.get("amount")

    try:
        if not pair or not signal:
            return jsonify({"error": "Parâmetros obrigatórios ausentes."}), 400

        # Remove underline e garante o formato correto
        pair = pair.replace("_", "").upper()

        if not amount:
            amount = get_balance_usdt()
        else:
            amount = float(amount)

        method = "POST"
        path = "/api/v1/trade/order"
        query = ""
        body = f'{{"symbol":"{pair}","side":"{signal}","quoteOrderQty":{amount}}}'

        timestamp, signature = sign_request(method, path, query, body)
        headers = {
            "PIONEX-KEY": API_KEY,
            "PIONEX-SIGNATURE": signature,
            "timestamp": timestamp,
            "Content-Type": "application/json"
        }

        print("\n===== ENVIANDO ORDEM PARA PIONEX =====")
        print("Pair:", pair)
        print("Signal:", signal)
        print("Amount:", amount)
        print("Body:", body)
        print("Headers:", headers)
        print("======================================\n")

        response = requests.post(BASE_URL + path, headers=headers, data=body)
        res_json = response.json()

        print("[RESPOSTA PIONEX]", res_json)

        status_data["ultimo_horario"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        status_data["ultimo_sinal"] = f"{signal.upper()} {pair}"

        if res_json.get("result"):
            enviar_email("✅ Ordem Executada", f"{signal.upper()} {pair} com {amount} USDT")
            return jsonify({"success": True, "response": res_json})
        else:
            enviar_email("❌ Erro ao Executar Ordem", str(res_json))
            return jsonify({"error": res_json}), 400

    except Exception as e:
        print(f"[ERRO GERAL] {str(e)}")
        enviar_email("❌ Erro Interno no Bot", str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
