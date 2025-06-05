from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

app = Flask(__name__)

API_KEY = os.getenv("PIONEX_API_KEY")
API_SECRET = os.getenv("PIONEX_API_SECRET")
BASE_URL = "https://api.pionex.com"

EMAIL_HOST = "smtp.hostgator.com.br"
EMAIL_PORT = 587
EMAIL_USER = os.getenv("EMAIL_USER")  # contato@falcaofilmes.com.br
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")  # seu email destino para alertas

status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None,
    "ultimo_erro": None,
    "saldo_atual": {}
}

def enviar_email(assunto, corpo):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_TO
        msg['Subject'] = assunto

        msg.attach(MIMEText(corpo, 'plain'))

        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
    except Exception as e:
        print("Erro ao enviar email:", str(e))

def gerar_assinatura(metodo, path, query_string='', corpo=''):
    base_string = f"{metodo}{path}"
    if query_string:
        base_string += f"?{query_string}"
    if corpo:
        base_string += corpo

    assinatura = hmac.new(API_SECRET.encode(), base_string.encode(), hashlib.sha256).hexdigest()
    return assinatura

def consultar_saldo():
    timestamp = str(int(time.time() * 1000))
    path = "/api/v1/account/balances"
    query = f"timestamp={timestamp}"
    assinatura = gerar_assinatura("GET", path, query)

    headers = {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": assinatura
    }

    url = f"{BASE_URL}{path}?{query}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200 and response.json().get("result"):
        return response.json()["data"]["balances"]
    else:
        raise Exception("Erro ao consultar saldo: " + response.text)

def executar_ordem(par, direcao, valor_usdt):
    timestamp = str(int(time.time() * 1000))
    path = "/api/v1/trade/order"
    query = f"timestamp={timestamp}"

    body = {
        "symbol": par,
        "side": direcao.upper(),
        "type": "MARKET",
        "quoteOrderQty": valor_usdt
    }

    assinatura = gerar_assinatura("POST", path, query, str(body).replace("'", '"'))
    headers = {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": assinatura,
        "Content-Type": "application/json"
    }
    url = f"{BASE_URL}{path}?{query}"

    response = requests.post(url, headers=headers, json=body)
    if response.status_code == 200 and response.json().get("result"):
        return response.json()["data"]
    else:
        raise Exception("Erro ao executar ordem: " + response.text)

@app.route("/status", methods=["GET"])
def status():
    return jsonify(status_data)

@app.route("/pionexbot", methods=["POST"])
def webhook():
    try:
        conteudo = request.get_json()
        par = conteudo.get("pair") or conteudo.get("symbol")
        sinal = conteudo.get("signal") or conteudo.get("sinal")
        amount = conteudo.get("amount")  # valor opcional

        if not par or not sinal:
            return jsonify({"erro": "Campos obrigatórios: pair e signal"}), 400

        status_data["ultimo_horario"] = time.strftime('%Y-%m-%d %H:%M:%S')
        status_data["ultimo_sinal"] = f"{sinal.upper()} em {par}"

        saldo = consultar_saldo()
        status_data["saldo_atual"] = {item['coin']: item['free'] for item in saldo if float(item['free']) > 0}

        if amount:
            valor = float(amount)
        else:
            usdt_disponivel = next((float(i['free']) for i in saldo if i['coin'] == 'USDT'), 0)
            if usdt_disponivel <= 0:
                raise Exception("Saldo USDT insuficiente")
            valor = usdt_disponivel

        resultado = executar_ordem(par, sinal, valor)

        mensagem = f"Ordem executada: {sinal.upper()} {par} no valor de {valor} USDT\n\nDetalhes: {resultado}"
        enviar_email(f"🚀 Ordem executada: {sinal.upper()} {par}", mensagem)

        return jsonify({"mensagem": "Ordem enviada com sucesso", "detalhes": resultado})

    except Exception as e:
        erro = str(e)
        status_data["ultimo_erro"] = erro
        enviar_email("❌ Erro no Bot Pionex", erro)
        return jsonify({"erro": erro}), 500

if __name__ == "__main__":
    app.run(debug=False)
