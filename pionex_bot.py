import os
import hmac
import hashlib
import requests
import json
from flask import Flask, request, jsonify
from datetime import datetime
import pytz
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# === CHAVES DE AMBIENTE ===
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
BASE_URL = "https://api.pionex.com"

EMAIL_ORIGEM = os.getenv("EMAIL_ORIGEM")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")
EMAIL_SENHA = os.getenv("EMAIL_SENHA")
SMTP_SERVIDOR = os.getenv("SMTP_SERVIDOR")
SMTP_PORTA = int(os.getenv("SMTP_PORTA", 587))

# === STATUS DO BOT ===
status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None,
    "versao": "1.0.0"
}

app = Flask(__name__)
tz = pytz.timezone('America/Sao_Paulo')

# === TIMESTAMP EM MILISSEGUNDOS ===
def get_timestamp() -> str:
    return str(int(datetime.utcnow().timestamp() * 1000))

# === GERA ASSINATURA DA REQUISIÇÃO ===
def sign_request(method: str, path: str, query: str = '', body: str = '') -> tuple:
    if not API_KEY or not API_SECRET:
        raise EnvironmentError("Erro: API_KEY ou API_SECRET não definidos.")
    timestamp = get_timestamp()
    sorted_query = '&'.join(sorted(filter(None, query.split('&'))))
    full_path = f"{path}?{sorted_query}" if sorted_query else path
    message = f"{method.upper()}{full_path}{timestamp}{body}"
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return timestamp, signature

# === ENVIA E-MAIL ===
def enviar_email(assunto: str, corpo: str):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ORIGEM
        msg['To'] = EMAIL_DESTINO
        msg['Subject'] = assunto
        msg.attach(MIMEText(corpo, 'plain'))

        with smtplib.SMTP(SMTP_SERVIDOR, SMTP_PORTA) as servidor:
            servidor.starttls()
            servidor.login(EMAIL_ORIGEM, EMAIL_SENHA)
            servidor.sendmail(EMAIL_ORIGEM, EMAIL_DESTINO, msg.as_string())
    except Exception as e:
        print(f"[ERRO AO ENVIAR EMAIL] {e}")

# === CONSULTA SALDO DISPONÍVEL EM USDT ===
def get_balance_usdt() -> float:
    try:
        method = "GET"
        path = "/api/v1/account/balances"
        timestamp, signature = sign_request(method, path)
        headers = {
            "PIONEX-KEY": API_KEY,
            "PIONEX-SIGNATURE": signature,
            "timestamp": timestamp
        }

        response = requests.get(BASE_URL + path, headers=headers)
        data = response.json()

        if data.get("result"):
            for coin in data["data"]["balances"]:
                if coin["coin"] == "USDT":
                    valor = coin.get("free") or coin.get("available") or "0"
                    saldo = float(valor)
                    print(f"💰 Saldo disponível em USDT: {saldo}")
                    return saldo

    except requests.exceptions.RequestException as e:
        print(f"❌ Erro de requisição ao consultar saldo: {e}")
    except Exception as e:
        print(f"❌ Erro ao processar saldo: {e}")

    return 0.0

# === ROTA DE STATUS ===
@app.route("/status", methods=["GET"])
def status():
    status_data["hora_servidor"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(status_data)

# === ROTA PRINCIPAL /pionexbot ===
@app.route("/pionexbot", methods=["POST"])
def receive_signal():
    data = request.get_json(silent=False)
    pair = data.get("pair")
    signal = data.get("signal")
    amount = data.get("amount")

    try:
        if not pair or not signal:
            return jsonify({"error": "Parâmetros obrigatórios ausentes: 'pair' ou 'signal'."}), 400

        if not amount:
            amount = get_balance_usdt()
            if amount <= 0:
                return jsonify({"error": "Saldo insuficiente para executar ordem."}), 400
        else:
            amount = float(amount)

        method = "POST"
        path = "/api/v1/trade/order"
        body_dict = {
            "symbol": pair,
            "side": signal.lower(),
            "quoteOrderQty": amount
        }
        body_json = json.dumps(body_dict)
        timestamp, signature = sign_request(method, path, '', body_json)

        headers = {
            "PIONEX-KEY": API_KEY,
            "PIONEX-SIGNATURE": signature,
            "timestamp": timestamp,
            "Content-Type": "application/json"
        }

        print("\n📤 Enviando ordem para Pionex")
        print("🪙 Par:", pair)
        print("📊 Sinal:", signal)
        print("💵 Quantidade:", amount)
        print("📦 Payload:", body_json)

        # CORREÇÃO PRINCIPAL: usar `data=body_json` em vez de `json=`
        response = requests.post(BASE_URL + path, headers=headers, data=body_json)
        print("📥 Resposta:", response.status_code, response.text)

        try:
            res_json = response.json()
        except Exception:
            res_json = {"error": "Erro ao interpretar resposta da API da Pionex."}

        status_data["ultimo_horario"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        status_data["ultimo_sinal"] = f"{signal.upper()} {pair}"

        if res_json.get("result"):
            enviar_email("✅ ORDEM EXECUTADA", f"{signal.upper()} {pair} com {amount} USDT")
            return jsonify({"success": True, "response": res_json})
        else:
            enviar_email("❌ ERRO NA ORDEM", json.dumps(res_json))
            return jsonify({"error": res_json}), 400

    except Exception as e:
        print(f"[ERRO INTERNO] {str(e)}")
        enviar_email("❌ ERRO INTERNO", str(e))
        return jsonify({"error": str(e)}), 500

# === EXECUÇÃO LOCAL ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
