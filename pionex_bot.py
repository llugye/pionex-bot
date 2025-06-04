from flask import Flask, request, jsonify
import os
import requests
import hmac
import hashlib
import time
import smtplib
from email.mime.text import MIMEText
import json
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

# Variáveis de ambiente
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
EMAIL_ORIGEM = os.getenv("EMAIL_ORIGEM")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")
EMAIL_SENHA = os.getenv("EMAIL_SENHA")
SMTP_SERVIDOR = os.getenv("SMTP_SERVIDOR")
SMTP_PORTA = int(os.getenv("SMTP_PORTA"))

if not API_KEY or not API_SECRET:
    raise Exception("❌ API_KEY ou API_SECRET não configuradas no ambiente do Render.")

BASE_URL = "https://api.pionex.com"
ULTIMO_SINAL = {"horario": None, "sinal": None}

# Gera assinatura HMAC para a Pionex
def assinar_pionex(payload_str, timestamp):
    mensagem = str(timestamp) + payload_str
    assinatura = hmac.new(API_SECRET.encode(), mensagem.encode(), hashlib.sha256).hexdigest()
    return assinatura

# Consulta o saldo de USDT
def consultar_saldo():
    endpoint = "/api/v1/balances"
    url = BASE_URL + endpoint
    timestamp = str(int(time.time() * 1000))
    payload = ""
    assinatura = assinar_pionex(payload, timestamp)

    headers = {
        "P-ACCESS-KEY": API_KEY,
        "P-ACCESS-SIGN": assinatura,
        "P-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

    resposta = requests.get(url, headers=headers)
    dados = resposta.json()

    for ativo in dados.get("data", []):
        if ativo["asset"] == "USDT":
            return float(ativo["free"])
    return 0.0

# Envia ordem de mercado
def criar_ordem_market(symbol, side, amount_usdt):
    endpoint = "/api/v1/order"
    url = BASE_URL + endpoint
    corpo = {
        "symbol": symbol,
        "side": side.lower(),
        "type": "market",
        "quoteOrderQty": str(amount_usdt)
    }

    payload_str = json.dumps(corpo)
    timestamp = str(int(time.time() * 1000))
    assinatura = assinar_pionex(payload_str, timestamp)

    headers = {
        "P-ACCESS-KEY": API_KEY,
        "P-ACCESS-SIGN": assinatura,
        "P-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

    try:
        resposta = requests.post(url, headers=headers, json=corpo)
        print(f"[{datetime.now()}] ORDEM ENVIADA: {side.upper()} {amount_usdt} USDT em {symbol}", flush=True)
        print("Resposta da API:", resposta.status_code, resposta.text, flush=True)
        return resposta.json()
    except Exception as e:
        print("❌ ERRO AO ENVIAR ORDEM:", str(e), flush=True)
        return {"erro": str(e)}

# Envia e-mail com o resultado
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
        print("Erro ao enviar e-mail:", erro, flush=True)

# Endpoint principal
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

    print(f"[DEBUG] Sinal recebido: {sinal.upper()} {valor_usdt} USDT no par {par}", flush=True)

    resposta = criar_ordem_market(par, sinal, valor_usdt)

    print(f"[DEBUG] Resultado da ordem: {resposta}", flush=True)

    fuso_brasilia = timezone(timedelta(hours=-3))
    ULTIMO_SINAL["horario"] = datetime.now(fuso_brasilia).strftime("%Y-%m-%d %H:%M:%S")
    ULTIMO_SINAL["sinal"] = sinal.upper()

    mensagem = f"💹 Sinal: {sinal.upper()} | Par: {par}\n💵 Valor: {valor_usdt} USDT\n📨 Resposta:\n{json.dumps(resposta, indent=2)}"
    enviar_email(mensagem)

    return jsonify(resposta)

# Endpoint de status
@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "status": "online",
        "ultimo_horario": ULTIMO_SINAL["horario"],
        "ultimo_sinal": ULTIMO_SINAL["sinal"]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
