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
from datetime import datetime

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

# Armazena estado para o /status
estado_bot = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None
}

# ==== Funções utilitárias ====

def assinar(query_string):
    return hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def enviar_email(mensagem):
    try:
        msg = MIMEText(mensagem)
        msg["Subject"] = "📈 Ordem executada"
        msg["From"] = EMAIL_ORIGEM
        msg["To"] = EMAIL_DESTINO
        with smtplib.SMTP(SMTP_SERVIDOR, SMTP_PORTA) as servidor:
            servidor.starttls()
            servidor.login(EMAIL_ORIGEM, EMAIL_SENHA)
            servidor.sendmail(EMAIL_ORIGEM, EMAIL_DESTINO, msg.as_string())
    except Exception as e:
        print("❌ Erro ao enviar e-mail:", e)

def consultar_saldo_usdt():
    endpoint = "/api/v1/account"
    timestamp = str(int(time.time() * 1000))
    query = f"timestamp={timestamp}"
    assinatura = assinar(query)
    headers = {"X-MBX-APIKEY": API_KEY}
    resposta = requests.get(f"{BASE_URL}{endpoint}?{query}&signature={assinatura}", headers=headers)
    dados = resposta.json()
    for ativo in dados.get("balances", []):
        if ativo["asset"] == "USDT":
            return float(ativo["free"])
    return 0.0

def consultar_saldo_ativo(simbolo):
    endpoint = "/api/v1/account"
    timestamp = str(int(time.time() * 1000))
    query = f"timestamp={timestamp}"
    assinatura = assinar(query)
    headers = {"X-MBX-APIKEY": API_KEY}
    resposta = requests.get(f"{BASE_URL}{endpoint}?{query}&signature={assinatura}", headers=headers)
    dados = resposta.json()
    for ativo in dados.get("balances", []):
        if ativo["asset"] == simbolo:
            return float(ativo["free"])
    return 0.0

def criar_ordem_market(symbol, side, quantidade):
    endpoint = "/api/v1/order"
    timestamp = str(int(time.time() * 1000))
    query = f"timestamp={timestamp}"
    assinatura = assinar(query)
    headers = {"X-MBX-APIKEY": API_KEY}

    if side == "BUY":
        corpo = {
            "symbol": symbol,
            "side": side,
            "type": "market",
            "quoteOrderQty": str(quantidade)
        }
    else:
        corpo = {
            "symbol": symbol,
            "side": side,
            "type": "market",
            "quantity": str(quantidade)
        }

    resposta = requests.post(f"{BASE_URL}{endpoint}?{query}&signature={assinatura}",
                             headers=headers, json=corpo)
    print(f"🛒 Ordem {side} enviada | Par: {symbol} | Quantidade: {quantidade}")
    return resposta.json()

# ==== Rota principal ====

@app.route("/pionexbot", methods=["POST"])
def receber_sinal():
    dados = request.json
    par = dados.get("pair", "").upper()
    sinal = dados.get("signal", "").lower()

    if not par or sinal not in ["buy", "sell"]:
        return jsonify({"erro": "Par ou sinal inválido"}), 400

    print(f"\n📩 Sinal recebido: {sinal.upper()} | Par: {par}")

    if sinal == "buy":
        saldo = consultar_saldo_usdt()
        print(f"💰 Saldo USDT disponível: {saldo}")
        if saldo < 5:
            print("⚠️ Saldo insuficiente para comprar.")
            return jsonify({"erro": "Saldo insuficiente"}), 400
        resposta = criar_ordem_market(par, "BUY", saldo)

    elif sinal == "sell":
        ativo = par.replace("USDT", "")
        saldo = consultar_saldo_ativo(ativo)
        print(f"💼 Saldo {ativo} disponível: {saldo}")
        if saldo < 0.0001:
            print("⚠️ Nenhum saldo do ativo para vender.")
            return jsonify({"erro": "Sem saldo para vender"}), 400
        resposta = criar_ordem_market(par, "SELL", saldo)

    # Atualiza status
    estado_bot["ultimo_sinal"] = sinal.upper()
    estado_bot["ultimo_horario"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    enviar_email(json.dumps(resposta, indent=2))
    print(f"✅ Resposta da ordem: {json.dumps(resposta, indent=2)}\n")
    return jsonify(resposta)

# ==== Rota de status ====

@app.route("/status", methods=["GET"])
def status():
    return jsonify(estado_bot)

# ==== Início ====

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
