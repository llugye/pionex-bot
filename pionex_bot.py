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

# Variáveis de ambiente do Render
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
EMAIL_ORIGEM = os.getenv("EMAIL_ORIGEM")
EMAIL_DESTINO = os.getenv("EMAIL_DESTINO")
EMAIL_SENHA = os.getenv("EMAIL_SENHA")
SMTP_SERVIDOR = os.getenv("SMTP_SERVIDOR")
SMTP_PORTA = int(os.getenv("SMTP_PORTA"))

BASE_URL = "https://api.pionex.com"
ULTIMO_SINAL = {"horario": None, "sinal": None}

def assinar(query_string):
    return hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def consultar_saldo():
    endpoint = "/api/v1/account"
    timestamp = str(int(time.time() * 1000))
    query_string = f"timestamp={timestamp}"
    assinatura = assinar(query_string)
    headers = {"X-MBX-APIKEY": API_KEY}

    resposta = requests.get(
        BASE_URL + endpoint + "?" + query_string + f"&signature={assinatura}",
        headers=headers
    )
    dados = resposta.json()
    for ativo in dados.get("balances", []):
        if ativo["asset"] == "USDT":
            return float(ativo["free"])
    return 0.0

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
        msg["Subject"] = "🔔 Ordem executada no Pionex"
        msg["From"] = EMAIL_ORIGEM
        msg["To"] = EMAIL_DESTINO

        with smtplib.SMTP(SMTP_SERVIDOR, SMTP_PORTA) as servidor:
            servidor.starttls()
            servidor.login(EMAIL_ORIGEM, EMAIL_SENHA)
            servidor.sendmail(EMAIL_ORIGEM, EMAIL_DESTINO, msg.as_string())
    except Exception as erro:
        print(f"Erro ao enviar e-mail: {erro}", flush=True)

@app.route("/pionexbot", methods=["POST"])
def receber_alerta():
    try:
        dados = request.json
        par = dados.get("pair", "").replace("/", "").upper()
        sinal = dados.get("signal", "").lower()
        valor_personalizado = dados.get("amount")

        if not par or sinal not in ["buy", "sell"]:
            return "Sinal ou par inválido", 400

        # Valor enviado ou consulta saldo
        if valor_personalizado is not None:
            try:
                valor_usdt = float(valor_personalizado)
            except:
                return "Valor de 'amount' inválido", 400
        else:
            valor_usdt = consultar_saldo()

        # Fuso horário
        fuso = pytz.timezone("America/Sao_Paulo")
        horario_atual = datetime.now(fuso).strftime("%Y-%m-%d %H:%M:%S")

        print(f"[DEBUG] Sinal recebido: {sinal.upper()} {valor_usdt} USDT no par {par}", flush=True)

        resposta = criar_ordem_market(par, sinal, valor_usdt)

        print(f"[{horario_atual}] ORDEM ENVIADA: {sinal.upper()} {valor_usdt} USDT em {par}", flush=True)
        print(f"Resposta da API: {json.dumps(resposta, indent=2)}", flush=True)

        mensagem = f"💹 Sinal: {sinal.upper()} | Par: {par}\n💵 Valor: {valor_usdt} USDT\n🕒 Horário: {horario_atual}\n📨 Resposta:\n{json.dumps(resposta, indent=2)}"
        enviar_email(mensagem)

        # Atualiza status
        ULTIMO_SINAL["horario"] = horario_atual
        ULTIMO_SINAL["sinal"] = sinal.upper()

        return jsonify(resposta)

    except Exception as e:
        print(f"[ERRO] Falha no processamento: {e}", flush=True)
        return jsonify({"erro": str(e)}), 500

@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "status": "online",
        "ultimo_horario": ULTIMO_SINAL["horario"],
        "ultimo_sinal": ULTIMO_SINAL["sinal"]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
