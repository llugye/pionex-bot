from flask import Flask, request, jsonify
import requests
import os
import hmac
import hashlib
import time
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import pytz

app = Flask(__name__)

API_KEY = os.getenv("PIONEX_API_KEY")
API_SECRET = os.getenv("PIONEX_API_SECRET")
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")
API_BASE = "https://api.pionex.com"

def get_timestamp():
    return str(int(time.time() * 1000))

def send_email(subject, body):
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_TO

        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_TO, msg.as_string())
    except Exception as e:
        print("Erro ao enviar e-mail:", e)

def sign_request(method, path, query='', body=''):
    timestamp = get_timestamp()
    if query:
        path_url = f"{path}?{query}&timestamp={timestamp}"
    else:
        path_url = f"{path}?timestamp={timestamp}"

    if method == 'POST':
        message = method + path_url + body
    else:
        message = method + path_url

    signature = hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    headers = {
        'PIONEX-KEY': API_KEY,
        'PIONEX-SIGNATURE': signature,
        'Content-Type': 'application/json'
    }
    return path_url, headers

def get_balance():
    path = "/api/v1/account/balances"
    path_url, headers = sign_request("GET", path)
    url = f"{API_BASE}{path_url}"
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        if data.get("result"):
            return data["data"]["balances"]
        else:
            send_email("Erro ao obter saldo", str(data))
            return []
    except Exception as e:
        send_email("Erro ao consultar saldo", str(e))
        return []

def criar_ordem(par, lado, amount):
    path = "/api/v1/trade/order"
    body_data = {
        "symbol": par,
        "side": lado.upper(),
        "type": "MARKET"
    }

    if amount:
        body_data["quoteOrderQty"] = float(amount)
    else:
        balances = get_balance()
        usdt = next((b for b in balances if b['coin'] == 'USDT'), None)
        if usdt:
            body_data["quoteOrderQty"] = float(usdt['free'])

    body_json = json.dumps(body_data, separators=(',', ':'))
    path_url, headers = sign_request("POST", path, body=body_json)
    url = f"{API_BASE}{path_url}"

    try:
        response = requests.post(url, headers=headers, data=body_json)
        data = response.json()
        if data.get("result"):
            send_email("Ordem Executada", f"{lado.upper()} {par} no valor de {body_data['quoteOrderQty']}")
        else:
            send_email("Erro ao criar ordem", str(data))
        return data
    except Exception as e:
        send_email("Erro de execução de ordem", str(e))
        return {"erro": str(e)}

@app.route("/pionexbot", methods=['POST'])
def sinal():
    conteudo = request.get_json()
    par = conteudo.get("pair")
    sinal = conteudo.get("signal")
    amount = conteudo.get("amount")
    
    if not par or not sinal:
        return jsonify({"erro": "Par ou sinal ausente"}), 400

    resultado = criar_ordem(par, sinal, amount)
    return jsonify(resultado)

@app.route("/status", methods=['GET'])
def status():
    balances = get_balance()
    tz_sp = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(tz_sp).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({
        "status": "online",
        "horario_sao_paulo": agora,
        "saldos": balances
    })

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)
