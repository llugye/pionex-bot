from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
import os
import smtplib
from email.message import EmailMessage
from datetime import datetime
from pytz import timezone

app = Flask(__name__)

API_KEY = os.getenv("PIONEX_API_KEY")
API_SECRET = os.getenv("PIONEX_API_SECRET")
API_BASE = "https://api.pionex.com"

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_SMTP = os.getenv("EMAIL_SMTP", "smtp.hostgator.com.br")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_TO = os.getenv("EMAIL_TO", EMAIL_ADDRESS)

status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None
}

def sign_request(timestamp, method, path, body):
    message = f"{timestamp}{method.upper()}{path}{body}"
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return signature

def get_headers(method, path, body=""):
    timestamp = str(int(time.time() * 1000))
    signature = sign_request(timestamp, method, path, body)
    return {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": signature,
        "PIONEX-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

def enviar_email(assunto, corpo):
    try:
        msg = EmailMessage()
        msg.set_content(corpo)
        msg["Subject"] = assunto
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = EMAIL_TO

        with smtplib.SMTP(EMAIL_SMTP, EMAIL_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)

    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")

@app.route("/pionexbot", methods=["POST"])
def receber_sinal():
    data = request.json
    pair = data.get("pair")
    signal = data.get("signal")
    amount = data.get("amount")

    status_data["ultimo_sinal"] = signal.upper()
    status_data["ultimo_horario"] = datetime.now(timezone("America/Sao_Paulo")).strftime("%Y-%m-%d %H:%M:%S")

    print(f"[DEBUG] Sinal recebido: {signal.upper()} {amount} USDT no par {pair}")

    order_side = "BUY" if signal.lower() == "buy" else "SELL"
    body_dict = {
        "symbol": pair,
        "side": order_side,
        "type": "MARKET",
        "quoteOrderQty": amount
    }
    path = "/api/v1/order"
    body_json = json.dumps(body_dict, separators=(",", ":"))

    headers = get_headers("POST", path, body_json)

    response = requests.post(API_BASE + path, headers=headers, data=body_json)
    resposta = response.json()

    print(f"[{status_data['ultimo_horario']}] ORDEM ENVIADA: {order_side} {amount} USDT em {pair}")
    print("Resposta da API:", resposta)

    enviar_email(
        assunto=f"[PionexBot] Ordem {order_side}",
        corpo=f"Sinal: {signal}\nPar: {pair}\nValor: {amount} USDT\nResposta: {resposta}"
    )

    return jsonify({"status": "ok", "resposta": resposta})

@app.route("/status", methods=["GET"])
def status():
    return jsonify(status_data)
