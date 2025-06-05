from flask import Flask, request, jsonify
import os
import time
import hmac
import hashlib
import requests
import pytz
from datetime import datetime
import smtplib
from email.mime.text import MIMEText

app = Flask(__name__)

# Ambiente Render
API_KEY = os.getenv("PIONEX_API_KEY")
API_SECRET = os.getenv("PIONEX_API_SECRET")
SMTP_USER = os.getenv("EMAIL_USER")
SMTP_PASS = os.getenv("EMAIL_PASS")
SMTP_TO = os.getenv("EMAIL_TO")

API_BASE = "https://api.pionex.com"

status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None
}

def get_timestamp():
    return str(int(time.time() * 1000))

def get_server_time():
    tz = pytz.timezone("America/Sao_Paulo")
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

def sign_request(method, path, query_string="", body=""):
    timestamp = get_timestamp()
    message = method + path + query_string + timestamp + body
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return timestamp, signature

def get_balance_usdt():
    path = "/api/v1/account/balances"
    method = "GET"
    query = ""
    timestamp, signature = sign_request(method, path, query)
    headers = {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": signature,
        "Content-Type": "application/json"
    }
    url = f"{API_BASE}{path}?timestamp={timestamp}"
    response = requests.get(url, headers=headers)
    data = response.json()
    for item in data.get("data", {}).get("balances", []):
        if item["coin"] == "USDT":
            return float(item["free"])
    return 0.0

def send_email(subject, body):
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = SMTP_TO
        with smtplib.SMTP("smtp.hostgator.com.br", 587) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    except Exception as e:
        print("Erro ao enviar e-mail:", e)

@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "status": status_data["status"],
        "ultimo_horario": status_data["ultimo_horario"],
        "ultimo_sinal": status_data["ultimo_sinal"],
        "versao": "1.0.0",
        "hora_servidor": get_server_time()
    })

@app.route("/status", methods=["GET"])
def status():
    return jsonify(status_data)

@app.route("/pionexbot", methods=["POST"])
def receive_signal():
    data = request.get_json()
    pair = data.get("pair")
    signal = data.get("signal").upper()
    amount = data.get("amount")

    status_data["ultimo_horario"] = get_server_time()
    status_data["ultimo_sinal"] = signal

    if not pair or signal not in ["BUY", "SELL"]:
        msg = "Par ou sinal inválido"
        send_email("Erro ao executar operação", msg)
        return jsonify({"erro": msg}), 400

    if not amount:
        amount = get_balance_usdt()
    else:
        try:
            amount = float(amount)
        except:
            return jsonify({"erro": "Valor inválido"}), 400

    path = "/api/v1/order/market"
    method = "POST"
    query = ""
    timestamp, signature = sign_request(method, path, query, body := f'{{"symbol":"{pair}","side":"{signal}","quoteOrderQty":{amount}}}')
    headers = {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": signature,
        "Content-Type": "application/json"
    }

    url = f"{API_BASE}{path}?timestamp={timestamp}"
    response = requests.post(url, headers=headers, data=body)
    data = response.json()

    if data.get("result"):
        msg = f"✅ ORDEM {signal} ENVIADA:\nPar: {pair}\nValor: {amount} USDT\n{get_server_time()}"
        send_email(f"Ordem executada {signal}", msg)
        return jsonify(data)
    else:
        msg = f"❌ FALHA NA ORDEM:\n{data}\n{get_server_time()}"
        send_email("Erro na operação", msg)
        return jsonify(data), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
