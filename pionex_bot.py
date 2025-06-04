from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import requests
import os
from datetime import datetime

app = Flask(__name__)

API_KEY = os.getenv("PIONEX_API_KEY")
API_SECRET = os.getenv("PIONEX_API_SECRET")
API_BASE = "https://api.pionex.com"

status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None
}

def get_timestamp():
    return str(int(time.time() * 1000))

def sign_request(timestamp, method, request_path, body_str=""):
    message = timestamp + method + request_path + body_str
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return signature

def get_headers(method, path, body=""):
    timestamp = get_timestamp()
    signature = sign_request(timestamp, method, path, body)
    return {
        "PIONEX-KEY": API_KEY,
        "PIONEX-SIGNATURE": signature,
        "PIONEX-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

def get_balance():
    path = "/api/v1/account/balances"
    url = API_BASE + path
    headers = get_headers("GET", path)
    res = requests.get(url, headers=headers)
    data = res.json()
    return {item['asset']: float(item['free']) for item in data['data']}

def get_price(pair):
    path = f"/api/v1/market/ticker?symbol={pair}"
    url = API_BASE + path
    res = requests.get(url)
    data = res.json()
    return float(data['data']['price'])

def create_order(symbol, side, quote_amount):
    price = get_price(symbol)
    qty = round(quote_amount / price, 6)  # cuidado com casas decimais
    print(f"[ORDENANDO] {side.upper()} {symbol} com {qty} ({quote_amount} USDT ao preço de {price})")

    path = "/api/v1/order"
    url = API_BASE + path
    body = {
        "symbol": symbol,
        "side": side,
        "type": "market",
        "quantity": str(qty)
    }
    body_str = json.dumps(body)
    headers = get_headers("POST", path, body_str)
    res = requests.post(url, headers=headers, data=body_str)
    print("[RESPOSTA API]", res.status_code, res.text)
    return res.status_code == 200

@app.route("/status")
def status():
    return jsonify(status_data)

@app.route("/pionexbot", methods=["POST"])
def webhook():
    data = request.json
    print("[WEBHOOK RECEBIDO]", data)

    pair = data.get("pair")
    signal = data.get("signal")
    amount = float(data.get("amount", 0))

    if not pair or not signal:
        return "Faltando dados.", 400

    # Atualiza status
    status_data["ultimo_horario"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_data["ultimo_sinal"] = signal.upper()

    # Adapta par BTCUSDT -> BTC_USDT
    symbol = pair.replace("USDT", "_USDT")
    balance = get_balance()

    usdt_available = balance.get("USDT", 0)
    quote_amount = amount if amount > 0 else usdt_available

    if signal.lower() == "buy":
        if quote_amount > 0:
            success = create_order(symbol, "BUY", quote_amount)
            return ("Ordem de compra executada." if success else "Erro ao comprar."), 200
        else:
            return "Sem saldo USDT disponível.", 200

    elif signal.lower() == "sell":
        asset = symbol.split("_")[0]
        qty = balance.get(asset, 0)
        if qty > 0:
            print(f"[VENDA] {qty} {asset}")
            path = "/api/v1/order"
            url = API_BASE + path
            body = {
                "symbol": symbol,
                "side": "SELL",
                "type": "market",
                "quantity": str(qty)
            }
            body_str = json.dumps(body)
            headers = get_headers("POST", path, body_str)
            res = requests.post(url, headers=headers, data=body_str)
            print("[RESPOSTA API]", res.status_code, res.text)
            return ("Ordem de venda executada." if res.status_code == 200 else "Erro ao vender."), 200
        else:
            return f"Sem saldo de {asset} para vender.", 200

    return "Sinal inválido.", 400

if __name__ == '__main__':
    app.run(debug=True)
