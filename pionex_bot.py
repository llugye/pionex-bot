from flask import Flask, request, jsonify
import os
import time
import hmac
import hashlib
import requests
import json
from email.mime.text import MIMEText
import smtplib
from datetime import datetime

app = Flask(__name__)

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
EMAIL_ORIGEM = os.getenv("EMAIL_ORIGEM")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")
EMAIL_SENHA = os.getenv("EMAIL_SENHA")
SMTP_SERVIDOR = os.getenv("SMTP_SERVIDOR")
SMTP_PORTA = int(os.getenv("SMTP_PORTA"))

BASE_URL = "https://api.pionex.com"
ULTIMO_SINAL = {"horario": None, "sinal": None}

def gerar_assinatura(timestamp, method, path, body):
    mensagem = f"{timestamp}{method}{path}{body}"
    return hmac.new(API_SECRET.encode(), mensagem.encode(), hashlib.sha256).hexdigest()

def get_headers(method, path, body):
    timestamp = str(int(time.time() * 1000))
    signature = gerar_assinatura(timestamp, method, path, body)
    return {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": signature,
        "PIONEX-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

def criar_ordem_spot(symbol, side, quote_qty):
    path = "/api/v1/order"
    method = "POST"
    body_dict = {
        "symbol": symbol,
        "side": side.upper(),
        "type": "market",
        "quoteOrderQty": str(quote_qty)
    }
    body = json.dumps(body_dict)
    headers = get_headers(method, path, body)
    resposta = requests.post(BASE_URL + path, headers=headers, data=body)
    return resposta.json()

def enviar_email(mensagem):
    try:
        msg = MIMEText(mensagem)
        msg["Subject"] = "🔔 Ordem executada no Pionex"
        msg["From"] = EMAIL_ORIGEM
        msg["To"] = EMAIL_DESTINO

        with smtplib.SMTP(SMTP_SERVIDOR, SMTP_PORTA) as servidor:
            servidor.starttls()
            servidor.login(EMAIL_ORIGEM, EMAIL_SENHA)
            servidor.sendmail(EMAIL_ORIGEM, EMAIL_DESTINO, msg.as_string())
    except Exception as erro:
        print("Erro ao enviar e-mail:", erro)

@app.route("/pionexbot", methods=["POST"])
def receber_alerta():
    dados = request.json
    par = dados.get("pair", "").replace("/", "").upper()
    sinal = dados.get("signal", "").lower()
    valor = dados.get("amount")

    if not par or sinal not in ["buy", "sell"]:
        return "Par ou sinal inválido", 400

    try:
        valor_float = float(valor)
    except:
        return "Valor inválido", 400

    print(f"[DEBUG] Sinal recebido: {sinal.upper()} {valor_float} USDT no par {par}")

    resposta = criar_ordem_spot(par, sinal, valor_float)

    print("[DEBUG] Resultado da ordem:", resposta)

    ULTIMO_SINAL["horario"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ULTIMO_SINAL["sinal"] = sinal.upper()

    mensagem = f"🟢 ORDEM ENVIADA: {sinal.upper()} {valor_float} USDT em {par}\n\nResposta: {json.dumps(resposta, indent=2)}"
    enviar_email(mensagem)

    return jsonify(resposta)

@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "status": "online",
        "ultimo_horario": ULTIMO_SINAL["horario"],
        "ultimo_sinal": ULTIMO_SINAL["sinal"]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
