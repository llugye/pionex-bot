from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
import os
from datetime import datetime
import pytz
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Inicializa app Flask
app = Flask(__name__)

# Dados da API
API_KEY = os.getenv("PIONEX_API_KEY")
API_SECRET = os.getenv("PIONEX_API_SECRET")
BASE_URL = "https://api.pionex.com"

# Validação das variáveis de ambiente
if not API_KEY or not API_SECRET:
    raise EnvironmentError("Erro: API_KEY ou API_SECRET não estão definidos nas variáveis de ambiente do Render.")

# Configuração de e-mail
EMAIL_HOST = os.getenv("SMTP_HOST")
EMAIL_PORT = int(os.getenv("SMTP_PORT", 587))
EMAIL_USER = os.getenv("SMTP_USER")
EMAIL_PASS = os.getenv("SMTP_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")

status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None,
    "versao": "1.0.0"
}

def agora_sp():
    fuso = pytz.timezone('America/Sao_Paulo')
    return datetime.now(fuso).strftime("%Y-%m-%d %H:%M:%S")

def enviar_email(assunto, corpo):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_TO
        msg['Subject'] = assunto
        msg.attach(MIMEText(corpo, 'plain'))

        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")

def sign_request(method, path, query='', body=''):
    timestamp = str(int(time.time() * 1000))
    path_url = f"{path}?{query}&timestamp={timestamp}" if query else f"{path}?timestamp={timestamp}"
    message = f"{method.upper()}{path_url}{body}"
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return timestamp, signature

def get_balance_usdt():
    path = "/api/v1/account/balances"
    method = "GET"
    query = ""
    timestamp, signature = sign_request(method, path, query)
    headers = {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": signature
    }
    response = requests.get(f"{BASE_URL}{path}?timestamp={timestamp}", headers=headers)
    if response.status_code == 200:
        data = response.json()
        for b in data['data']['balances']:
            if b['coin'] == 'USDT':
                return float(b['free'])
    raise Exception("Erro ao consultar saldo USDT")

def criar_ordem(pair, side, amount):
    path = "/api/v1/trade/order"
    method = "POST"
    body = {"symbol": pair, "side": side.upper(), "quoteOrderQty": amount}
    body_str = '{"symbol":"%s","side":"%s","quoteOrderQty":%s}' % (pair, side.upper(), amount)
    query = ""
    timestamp, signature = sign_request(method, path, query, body_str)
    headers = {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": signature,
        "Content-Type": "application/json"
    }
    response = requests.post(f"{BASE_URL}{path}?timestamp={timestamp}", headers=headers, json=body)
    return response.json()

@app.route("/", methods=["GET"])
def home():
    status_data["hora_servidor"] = agora_sp()
    return jsonify(status_data)

@app.route("/pionexbot", methods=["POST"])
def receive_signal():
    try:
        content = request.json
        pair = content.get("pair")
        signal = content.get("signal")
        amount = content.get("amount")

        if not pair or not signal:
            return jsonify({"error": "Parâmetros obrigatórios ausentes"}), 400

        if not amount:
            amount = get_balance_usdt()

        resultado = criar_ordem(pair, signal, amount)

        status_data["ultimo_horario"] = agora_sp()
        status_data["ultimo_sinal"] = f"{signal.upper()} {pair} ({amount})"

        enviar_email("Ordem Executada", f"Sinal: {signal.upper()}\nPar: {pair}\nValor: {amount}\nResposta: {resultado}")

        return jsonify({"status": "sucesso", "detalhes": resultado})

    except Exception as e:
        enviar_email("Erro no Bot Pionex", str(e))
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
