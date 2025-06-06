import os
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from datetime import datetime
import pytz

# === CHAVES E URL DA BINANCE ===
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
BASE_URL = "https://api.binance.com"

# === STATUS DO BOT ===
status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None,
    "versao": "2.0.0-binance"
}

app = Flask(__name__)
tz = pytz.timezone("America/Sao_Paulo")

# === TIMESTAMP EM MILISSEGUNDOS ===
def get_timestamp() -> int:
    return int(time.time() * 1000)

# === GERA ASSINATURA BINANCE ===
def sign_query(query_string: str) -> str:
    return hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()

# === CONSULTA SALDO USDT ===
def get_balance_usdt() -> float:
    try:
        timestamp = get_timestamp()
        query = f"timestamp={timestamp}"
        signature = sign_query(query)
        url = f"{BASE_URL}/api/v3/account?{query}&signature={signature}"
        headers = {
            "X-MBX-APIKEY": API_KEY
        }

        response = requests.get(url, headers=headers)
        data = response.json()

        if "balances" in data:
            for asset in data["balances"]:
                if asset["asset"] == "USDT":
                    return float(asset["free"])
    except Exception as e:
        print(f"❌ Erro ao consultar saldo: {e}")
    return 0.0

# === STATUS DO BOT ===
@app.route("/status", methods=["GET"])
def status():
    status_data["hora_servidor"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(status_data)

# === RECEBE SINAL DE COMPRA/VENDA ===
@app.route("/pionexbot", methods=["POST"])
def receive_signal():
    try:
        data = request.get_json()
        pair = str(data.get("pair", "")).upper()
        signal = str(data.get("signal", "")).upper()
        amount = data.get("amount")

        if not pair or not signal:
            return jsonify({"error": "Parâmetros obrigatórios ausentes: 'pair' ou 'signal'."}), 400

        if not amount:
            amount = get_balance_usdt()
            if amount <= 0:
                return jsonify({"error": "Saldo insuficiente para executar ordem."}), 400
        else:
            amount = float(amount)

        timestamp = get_timestamp()
        query_string = f"symbol={pair}&side={signal}&type=MARKET&quoteOrderQty={amount}&timestamp={timestamp}"
        signature = sign_query(query_string)
        url = f"{BASE_URL}/api/v3/order?{query_string}&signature={signature}"

        headers = {
            "X-MBX-APIKEY": API_KEY,
            "Content-Type": "application/x-www-form-urlencoded"
        }

        print("\n📤 Enviando ordem para Binance")
        print("🪙 Par:", pair)
        print("📈 Sinal:", signal)
        print("💵 Quantidade:", amount)

        response = requests.post(url, headers=headers)
        res_json = response.json()
        print("📥 Resposta:", response.status_code, res_json)

        # Atualiza status do bot
        status_data["ultimo_horario"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        status_data["ultimo_sinal"] = f"{signal} {pair}"

        if response.status_code == 200:
            return jsonify({"success": True, "response": res_json})
        else:
            return jsonify({"error": res_json}), 400

    except Exception as e:
        print(f"❌ ERRO INTERNO: {e}")
        return jsonify({"error": str(e)}), 500

# === EXECUÇÃO LOCAL OU RENDER ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
