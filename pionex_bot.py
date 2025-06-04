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

# Estado atual
estado_bot = {
    "status": "online",
    "ultimo_sinal": None,
    "ultimo_horario": None
}

def assinar(query_string):
    return hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def consultar_saldo():
    endpoint = "/api/v1/account"
    timestamp = str(int(time.time() * 1000))
    query = f"timestamp={timestamp}"
    assinatura = assinar(query)
    headers = {"X-MBX-APIKEY": API_KEY}
    url = f"{BASE_URL}{endpoint}?{query}&signature={assinatura}"
    resposta = requests.get(url, headers=headers)
    for ativo in resposta.json().get("balances", []):
        if ativo["asset"] == "USDT":
            return float(ativo["free"])
    return 0.0

def vender_tudo(symbol):
    endpoint = "/api/v1/order"
    timestamp = str(int(time.time() * 1000))

    # Consulta saldo da moeda
    saldo_url = f"{BASE_URL}/api/v1/account?timestamp={timestamp}&signature={assinar(f'timestamp={timestamp}')}"
    headers = {"X-MBX-APIKEY": API_KEY}
    resposta = requests.get(saldo_url, headers=headers).json()
    moeda = symbol.replace("USDT", "")
    quantidade = 0.0

    for ativo in resposta.get("balances", []):
        if ativo["asset"] == moeda:
            quantidade = float(ativo["free"])
            break

    if quantidade <= 0:
        return {"erro": f"Sem saldo em {moeda}"}

    corpo = {
        "symbol": symbol,
        "side": "SELL",
        "type": "market",
        "quantity": str(quantidade)
    }

    query = f"timestamp={timestamp}"
    assinatura = assinar(query)
    url = f"{BASE_URL}{endpoint}?{query}&signature={assinatura}"
    return requests.post(url, headers=headers, json=corpo).json()

def comprar_tudo(symbol):
    usdt = consultar_saldo()
    if usdt < 5:  # valor mínimo por ordem
        return {"erro": "Saldo USDT insuficiente"}

    endpoint = "/api/v1/order"
    timestamp = str(int(time.time() * 1000))
    corpo = {
        "symbol": symbol,
        "side": "BUY",
        "type": "market",
        "quoteOrderQty": str(usdt)
    }

    query = f"timestamp={timestamp}"
    assinatura = assinar(query)
    headers = {"X-MBX-APIKEY": API_KEY}
    url = f"{BASE_URL}{endpoint}?{query}&signature={assinatura}"
    return requests.post(url, headers=headers, json=corpo).json()

def enviar_email(mensagem):
    try:
        msg = MIMEText(mensagem)
        msg["Subject"] = "📊 Sinal do Bot Executado"
        msg["From"] = EMAIL_ORIGEM
        msg["To"] = EMAIL_DESTINO
        with smtplib.SMTP(SMTP_SERVIDOR, SMTP_PORTA) as servidor:
            servidor.starttls()
            servidor.login(EMAIL_ORIGEM, EMAIL_SENHA)
            servidor.sendmail(EMAIL_ORIGEM, EMAIL_DESTINO, msg.as_string())
    except Exception as e:
        print("Erro ao enviar e-mail:", e)

@app.route("/pionexbot", methods=["POST"])
def receber_alerta():
    dados = request.json
    symbol = dados.get("pair", "").replace("/", "").upper()
    signal = dados.get("signal", "").lower()

    if not symbol or signal not in ["buy", "sell"]:
        return jsonify({"erro": "Sinal inválido"}), 400

    if signal == "buy":
        resposta = comprar_tudo(symbol)
    else:
        resposta = vender_tudo(symbol)

    estado_bot["ultimo_sinal"] = signal.upper()
    estado_bot["ultimo_horario"] = time.strftime("%Y-%m-%d %H:%M:%S")

    mensagem = f"💡 Sinal: {signal.upper()} | Par: {symbol}\n\n📥 Resposta:\n{json.dumps(resposta, indent=2)}"
    enviar_email(mensagem)

    return jsonify(resposta)

@app.route("/status", methods=["GET"])
def status():
    return jsonify(estado_bot)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
