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
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")

status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None
}

def get_timestamp():
    return str(int(time.time() * 1000))

def send_email(subject, body):
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO

        with smtplib.SMTP("smtp.hostgator.com", 587) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASS)
            server.send_message(msg)
    except Exception as e:
        print("Erro ao enviar e-mail:", e)

def sign_request(method, path, query='', body=''):
    timestamp = get_timestamp()
    base_string = f"{method}{path}{query}{timestamp}{body}"
    signature = hmac.new(API_SECRET.encode(), base_string.encode(), hashlib.sha256).hexdigest()
    return timestamp, signature

def get_balance():
    path = "/api/v1/account/balances"
    method = "GET"
    query = ""
    timestamp, signature = sign_request(method, path, query)
    headers = {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": signature,
        "timestamp": timestamp
    }
    response = requests.get(API_BASE + path, headers=headers)
    data = response.json()
    if data.get("result"):
        return data["data"].get("balances", [])
    return []

def get_usdt_balance():
    for item in get_balance():
        if item["coin"] == "USDT":
            return float(item["free"])
    return 0

def create_order(symbol, side, amount):
    path = "/api/v1/trade/order"
    method = "POST"
    body_dict = {
        "symbol": symbol,
        "side": side.upper(),
        "orderType": "MARKET",
        "quoteOrderQty": str(amount) if side.lower() == "buy" else None,
        "baseOrderQty": str(amount) if side.lower() == "sell" else None
    }
    body = {k: v for k, v in body_dict.items() if v is not None}
    body_str = str(body).replace("'", '"')
    timestamp, signature = sign_request(method, path, '', body_str)
    headers = {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": signature,
        "timestamp": timestamp,
        "Content-Type": "application/json"
    }
    response = requests.post(API_BASE + path, json=body, headers=headers)
    return response.json()

@app.route("/pionexbot", methods=["POST"])
def pionexbot():
    try:
        data = request.get_json()
        symbol = data.get("pair")
        signal = data.get("signal")
        amount = data.get("amount")

        if not symbol or not signal:
            return jsonify({"error": "Parâmetros ausentes"}), 400

        if not amount:
            amount = get_usdt_balance()

        result = create_order(symbol, signal, amount)

        now = datetime.now(pytz.timezone("America/Sao_Paulo"))
        status_data["ultimo_horario"] = now.strftime("%Y-%m-%d %H:%M:%S")
        status_data["ultimo_sinal"] = signal.upper()

        if result.get("result"):
            send_email(f"ORDEM EXECUTADA", f"{signal.upper()} {amount} USDT em {symbol}")
            return jsonify({"success": True, "data": result}), 200
        else:
            send_email("FALHA NA ORDEM", str(result))
            return jsonify({"success": False, "data": result}), 500

    except Exception as e:
        send_email("ERRO NO BOT", str(e))
        return jsonify({"error": str(e)}), 500

@app.route("/status", methods=["GET"])
def status():
    return jsonify(status_data)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
