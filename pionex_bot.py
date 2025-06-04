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
QUANTIDADE_USDT = float(os.getenv("QUANTIDADE_USDT"))
EMAIL_ORIGEM = os.getenv("EMAIL_ORIGEM")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")
EMAIL_SENHA = os.getenv("EMAIL_SENHA")
SMTP_SERVIDOR = os.getenv("SMTP_SERVIDOR")
SMTP_PORTA = int(os.getenv("SMTP_PORTA"))

BASE_URL = "https://api.pionex.com"

def criar_ordem_market(symbol, side, amount_usdt):
    endpoint = "/api/v1/order"
    timestamp = str(int(time.time() * 1000))
    corpo = {
        "symbol": symbol,
        "side": side.upper(),
        "type": "market",
        "quoteOrderQty": str(amount_usdt)
    }

    query = f"timestamp={timestamp}"
    assinatura = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    headers = { "X-MBX-APIKEY": API_KEY }

    resposta = requests.post(
        BASE_URL + endpoint + "?" + query + f"&signature={assinatura}",
        headers=headers,
        json=corpo
    )
    return resposta.json()

def enviar_email(mensagem):
    try:
        msg = MIMEText(mensagem)
        msg["Subject"] = "📊 Ordem Executada com Sucesso"
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
        return "Sinal ou par inválido", 400

    resposta = criar_ordem_market(par, sinal, QUANTIDADE_USDT)
    mensagem = f"💡 Sinal: {sinal.upper()} | Par: {par}\n\n📥 Resposta:\n{json.dumps(resposta, indent=2)}"
    enviar_email(mensagem)

    return json.dumps(resposta)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
