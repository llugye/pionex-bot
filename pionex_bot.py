from flask import Flask, request
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

# Função para assinar requisições

def assinar(query_string):
    return hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()

# Consultar saldo da carteira

def consultar_saldo():
    endpoint = "/api/v1/account"
    timestamp = str(int(time.time() * 1000))
    query_string = f"timestamp={timestamp}"
    signature = assinar(query_string)
    headers = {"X-MBX-APIKEY": API_KEY}

    resposta = requests.get(
        f"{BASE_URL}{endpoint}?{query_string}&signature={signature}", headers=headers)

    if resposta.status_code == 200:
        return resposta.json()
    else:
        return None

# Função para obter saldo disponível de um ativo específico

def saldo_ativo(ativo):
    dados = consultar_saldo()
    if not dados:
        return 0.0
    for item in dados.get("balances", []):
        if item["asset"] == ativo:
            return float(item["free"])
    return 0.0

# Criar ordem de mercado

def criar_ordem_market(par, lado, quantidade):
    endpoint = "/api/v1/order"
    timestamp = str(int(time.time() * 1000))
    headers = {"X-MBX-APIKEY": API_KEY}

    corpo = {
        "symbol": par,
        "side": lado.upper(),
        "type": "market"
    }

    if lado.lower() == "buy":
        corpo["quoteOrderQty"] = str(quantidade)  # Em USDT
    else:
        corpo["quantity"] = str(quantidade)  # Em cripto

    query = f"timestamp={timestamp}"
    assinatura = assinar(query)

    resposta = requests.post(
        f"{BASE_URL}{endpoint}?{query}&signature={assinatura}",
        headers=headers,
        json=corpo
    )
    return resposta.json()

# Enviar email com resultado

def enviar_email(mensagem):
    try:
        msg = MIMEText(mensagem)
        msg["Subject"] = "📊 Ordem Executada"
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

    if not par or sinal not in ["buy", "sell"]:
        return "Par ou sinal inválido", 400

    if sinal == "buy":
        saldo_usdt = saldo_ativo("USDT")
        resposta = criar_ordem_market(par, "buy", saldo_usdt)
    elif sinal == "sell":
        moeda = par.replace("USDT", "")
        saldo_moeda = saldo_ativo(moeda)
        resposta = criar_ordem_market(par, "sell", saldo_moeda)

    mensagem = f"💡 Sinal: {sinal.upper()} | Par: {par}\n\n📥 Resposta:\n{json.dumps(resposta, indent=2)}"
    enviar_email(mensagem)
    return json.dumps(resposta)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
