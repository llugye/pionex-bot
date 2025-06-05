from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import pytz

app = Flask(__name__)

API_KEY = os.getenv("PIONEX_API_KEY")
API_SECRET = os.getenv("PIONEX_API_SECRET")
API_BASE = "https://api.pionex.com"

EMAIL_HOST = "smtp.hostgator.com"
EMAIL_PORT = 587
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")

status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None,
    "versao": "1.0.0"
}

def get_timestamp():
    return str(int(time.time() * 1000))

def sign_request(method, path, query="", body=""):
    if not API_SECRET:
        raise Exception("API_SECRET nao encontrado no ambiente")
    timestamp = get_timestamp()
    path_url = path + ("?" + query if query else "")
    message = method + path_url + timestamp + body
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return timestamp, signature

def send_email(subject, body):
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_TO

        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
    except Exception as e:
        print(f"Erro ao enviar email: {e}")

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
    response = requests.get(API_BASE + path, headers=headers)
    data = response.json()
    for coin in data['data']['balances']:
        if coin['coin'] == 'USDT':
            return float(coin['free'])
    return 0.0

def place_order(pair, signal, amount):
    method = "POST"
    path = "/api/v1/trade/order"
    body = f'{{"symbol":"{pair}","side":"{signal}","quoteOrderQty":{amount}}}'
    timestamp, signature = sign_request(method, path, "", body)

    headers = {
        "Content-Type": "application/json",
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": signature,
        "timestamp": timestamp
    }
    response = requests.post(API_BASE + path, headers=headers, data=body)
    return response.json()

@app.route("/pionexbot", methods=["POST"])
def receive_signal():
    try:
        content = request.get_json()
        pair = content.get("pair")
        signal = content.get("signal")
        amount = content.get("amount")

        if not pair or not signal:
            return jsonify({"erro": "Parâmetros ausentes"}), 400

        if not API_KEY or not API_SECRET:
            return jsonify({"erro": "API_KEY ou API_SECRET ausente"}), 500

        if not amount:
            amount = get_balance_usdt()

        result = place_order(pair, signal, amount)

        status_data["ultimo_horario"] = get_brazil_time()
        status_data["ultimo_sinal"] = {"par": pair, "tipo": signal, "valor": amount}

        send_email(
            subject=f"Ordem {signal.upper()} executada",
            body=f"Par: {pair}\nTipo: {signal}\nValor: {amount}\nResposta: {result}"
        )

        return jsonify(result)
    except Exception as e:
        send_email("Erro no bot Pionex", str(e))
        return jsonify({"erro": str(e)}), 500

def get_brazil_time():
    tz = pytz.timezone('America/Sao_Paulo')
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "hora_servidor": get_brazil_time(),
        **status_data
    })

if __name__ == '__main__':
    app.run(debug=False, host="0.0.0.0", port=10000)
