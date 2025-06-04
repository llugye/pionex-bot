from flask import Flask, request, jsonify
import os
import requests
import hmac
import hashlib
import time
import smtplib
from email.mime.text import MIMEText
import json
from datetime import datetime
import pytz

app = Flask(__name__)

# Variáveis de ambiente fornecidas pelo Render
API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
EMAIL_ORIGEM = os.environ.get("EMAIL_ORIGEM")
EMAIL_DESTINO = os.environ.get("EMAIL_DESTINO")
EMAIL_SENHA = os.environ.get("EMAIL_SENHA")
SMTP_SERVIDOR = os.environ.get("SMTP_SERVIDOR")
SMTP_PORTA = int(os.environ.get("SMTP_PORTA"))

BASE_URL = "https://api.pionex.com"
ULTIMO_SINAL = {"horario": None, "sinal": None}

def assinar_requisicao(method, path, params=None, body=None):
    timestamp = str(int(time.time() * 1000))
    if params is None:
        params = {}
    params['timestamp'] = timestamp
    sorted_params = sorted(params.items())
    query_string = '&'.join(f"{k}={v}" for k, v in sorted_params)
    path_url = f"{path}?{query_string}"
    message = f"{method.upper()}{path_url}"
    if body:
        message += json.dumps(body, separators=(',', ':'))
    assinatura = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return assinatura, timestamp, query_string

def consultar_saldo():
    path = "/api/v1/account"
    assinatura, timestamp, query_string = assinar_requisicao("GET", path)
    headers = {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": assinatura
    }
    resposta = requests.get(f"{BASE_URL}{path}?{query_string}", headers=headers)
    dados = resposta.json()
    for ativo in dados.get("data", {}).get("balances", []):
        if ativo["asset"] == "USDT":
            return float(ativo["free"])
    return 0.0

def criar_ordem_market(symbol, side, amount_usdt):
    path = "/api/v1/trade/order"
    body = {
        "symbol": symbol,
        "side": side.upper(),
        "type": "MARKET",
        "amount": str(amount_usdt)
    }
    assinatura, timestamp, query_string = assinar_requisicao("POST", path, body=body)
    headers = {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": assinatura,
        "Content-Type": "application/json"
    }
    resposta = requests.post(f"{BASE_URL}{path}?{query_string}", headers=headers, json=body)
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
    valor_personalizado = dados.get("amount")

    if not par or sinal not in ["buy", "sell"]:
        return "Sinal ou par inválido", 400

    if valor_personalizado is not None:
        try:
            valor_usdt = float(valor_personalizado)
        except:
            return "Valor de 'amount' inválido", 400
    else:
        valor_usdt = consultar_saldo()

    resposta = criar_ordem_market(par, sinal, valor_usdt)

    fuso_horario = pytz.timezone("America/Sao_Paulo")
    horario_atual = datetime.now(fuso_horario).strftime("%Y-%m-%d %H:%M:%S")
    ULTIMO_SINAL["horario"] = horario_atual
    ULTIMO_SINAL["sinal"] = sinal.upper()

    mensagem = f"💹 Sinal: {sinal.upper()} | Par: {par}\n💵 Valor: {valor_usdt} USDT\n📨 Resposta:\n{json.dumps(resposta, indent=2)}"
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
