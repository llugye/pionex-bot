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
    "versao": "2.0.0-binance-debug"
}

app = Flask(__name__)
tz = pytz.timezone('America/Sao_Paulo')

# === GERA TIMESTAMP EM MILISSEGUNDOS ===
def get_timestamp():
    return int(time.time() * 1000)

# === ASSINATURA HMAC SHA256 ===
def sign_query(query_string: str) -> str:
    return hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()

# === CONSULTA SALDO DISPONÍVEL EM USDT ===
def get_balance_usdt():
    try:
        timestamp = get_timestamp()
        query = f"timestamp={timestamp}"
        signature = sign_query(query)
        url = f"{BASE_URL}/api/v3/account?{query}&signature={signature}"
        headers = { "X-MBX-APIKEY": API_KEY }

        response = requests.get(url, headers=headers)
        data = response.json()

        print("📊 Resposta da Binance (saldo):", data)

        if "balances" in data:
            for asset in data["balances"]:
                if asset["asset"] == "USDT":
                    return float(asset["free"])
    except Exception as e:
        print(f"❌ Erro ao consultar saldo: {e}")
    return 0.0

# === ROTA DE STATUS ===
@app.route("/status", methods=["GET"])
def status():
    status_data["hora_servidor"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(status_data)

# === ROTA PRINCIPAL DE ORDENS ===
@app.route("/pionexbot", methods=["POST"])
def receive_signal():
    try:
        print("\n📥 Requisição recebida em /pionexbot")
        print("➡ Headers:", dict(request.headers))
        print("➡ Raw body:", request.data)

        data = request.get_json(silent=True)

        if data is None:
            print("❌ Erro: JSON malformado ou vazio.")
            return jsonify({"error": "JSON inválido ou ausente."}), 400

        print("📦 JSON recebido:", data)

        pair = data.get("pair")
        signal = data.get("signal")
        amount = data.get("amount")

        if not pair or not signal:
            return jsonify({"error": "Parâmetros obrigatórios ausentes: 'pair' ou 'signal'."}), 400

        if not amount:
            amount = get_balance_usdt()
            if amount <= 0:
                return jsonify({"error": "Saldo insuficiente para executar ordem."}), 400
        else:
            amount = float(amount)

        side = signal.upper()
        timestamp = get_timestamp()
        query_string = f"symbol={pair}&side={side}&type=MARKET&quoteOrderQty={amount}&timestamp={timestamp}"
        signature = sign_query(query_string)

        url = f"{BASE_URL}/api/v3/order?{query_string}&signature={signature}"
        headers = {
            "X-MBX-APIKEY": API_KEY,
            "Content-Type": "application/x-www-form-urlencoded"
        }

        print("\n📤 Enviando ordem para Binance")
        print("🪙 Par:", pair)
        print("📈 Sinal:", side)
        print("💵 Quantidade:", amount)
        print("🔗 URL:", url)

        response = requests.post(url, headers=headers)
        res_json = response.json()
        print("📥 Resposta da Binance:", response.status_code, res_json)

        # Atualiza status
        status_data["ultimo_horario"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        status_data["ultimo_sinal"] = f"{side} {pair}"

        if response.status_code == 200:
            return jsonify({"success": True, "response": res_json})
        else:
            return jsonify({"error": res_json}), 400

    except Exception as e:
        print(f"❌ ERRO INTERNO: {str(e)}")
        return jsonify({"error": str(e)}), 500

# === EXECUÇÃO LOCAL/RENDER ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)), debug=True)
