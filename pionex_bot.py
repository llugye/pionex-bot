from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv
import requests
import hmac
import hashlib
import time
import smtplib
from email.mime.text import MIMEText
import json
from datetime import datetime, timedelta

load_dotenv()
app = Flask(__name__)

# Variáveis de ambiente
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
EMAIL_ORIGEM = os.getenv("EMAIL_ORIGEM")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")
EMAIL_SENHA = os.getenv("EMAIL_SENHA")
SMTP_SERVIDOR = os.getenv("SMTP_SERVIDOR")
SMTP_PORTA = int(os.getenv("SMTP_PORTA"))

BASE_URL = "https://api.pionex.com"

status_info = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None
}

def assinar(query_string):
    return hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def consultar_saldo_usdt():
    endpoint = "/api/v1/account"
    timestamp = str(int(time.time() * 1000))
    query_string = f"timestamp={timestamp}"
    signature = assinar(query_string)
    headers = {"X-MBX-APIKEY": API_KEY}

    url = f"{BASE_URL}{endpoint}?{query_string}&signature={signature}"
    resposta = requests.get(url, headers=headers)
    dados = resposta.json()

    for ativo in dados.get("balances", []):
        if ativo["asset"] == "USDT":
            return float(ativo["free"])
    return 0.0

def consultar_saldo_moeda(par):
    endpoint = "/api/v1/account"
    timestamp = str(int(time.time() * 1000))
    query_string = f"timestamp={timestamp}"
    signature = assinar(query_string)
    headers = {"X-MBX-APIKEY": API_KEY}

    url = f"{BASE_URL}{endpoint}?{query_string}&signature={signature}"
    resposta = requests.get(url, headers=headers)
    dados = resposta.json()

    moeda = par.replace("USDT", "")
    for ativo in dados.get("balances", []):
        if ativo["asset"] == moeda:
            return float(ativo["free"])
    return 0.0

def criar_ordem_market(symbol, side, quantidade):
    endpoint = "/api/v1/order"
    timestamp = str(int(time.time() * 1000))

    corpo = {
        "symbol": symbol,
        "side": side.upper(),
        "type": "market"
    }

    if side == "buy":
        corpo["quoteOrderQty"] = str(quantidade)
    else:
        corpo["quantity"] = str(quantidade)

    query = f"timestamp={timestamp}"
    assinatura = assinar(query)
    headers = {"X-MBX-APIKEY": API_KEY}

    resposta = requests.post(
        BASE_URL + endpoint + "?" + query + f"&signature={assinatura}",
        headers=headers,
        json=corpo
    )
    return resposta.json()

def enviar_email(mensagem):
    try:
        msg = MIMEText(mensagem)
        msg["Subject"] = "📊 Ordem executada no robô"
        msg["From"] = EMAIL_ORIGEM
        msg["To"] = EMAIL_DESTINO

        with smtplib.SMTP(SMTP_SERVIDOR, SMTP_PORTA) as servidor:
            servidor.starttls()
            servidor.login(EMAIL_ORIGEM, EMAIL_SENHA)
            servidor.sendmail(EMAIL_ORIGEM, EMAIL_DESTINO, msg.as_string())
    except Exception as erro:
        print("Erro ao enviar e-mail:", erro)

@app.route("/pionexbot", methods=["POST"])
def receber_sinal():
    dados = request.json
    par = dados.get("pair", "").replace("/", "").upper()
    sinal = dados.get("signal", "").lower()

    if not par or sinal not in ["buy", "sell"]:
        return jsonify({"erro": "Par ou sinal inválido"}), 400

    try:
        if sinal == "buy":
            saldo_usdt = consultar_saldo_usdt()
            if saldo_usdt > 5:
                resposta = criar_ordem_market(par, "buy", saldo_usdt)
            else:
                resposta = {"erro": "Saldo USDT insuficiente para compra"}
        elif sinal == "sell":
            saldo_moeda = consultar_saldo_moeda(par)
            if saldo_moeda > 0:
                resposta = criar_ordem_market(par, "sell", saldo_moeda)
            else:
                resposta = {"erro": "Sem moedas para vender"}

        # Atualiza status
        status_info["ultimo_sinal"] = sinal.upper()
        status_info["ultimo_horario"] = (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")

        enviar_email(json.dumps(resposta, indent=2))
        return jsonify(resposta)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route("/status", methods=["GET"])
def status():
    return jsonify(status_info)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
