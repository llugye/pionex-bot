import os
# As importações hmac, hashlib e requests eram usadas para a API da Pionex,
# mas são mantidas pois 'requests' ainda é usado indiretamente por 'python-binance',
# e as outras podem ser úteis para futuras extensões.
# No entanto, a lógica de assinatura de requisições Hmac/Hashlib agora é tratada pela biblioteca 'binance.client'.
import hmac
import hashlib
import requests 
import json
from flask import Flask, request, jsonify
from datetime import datetime
import pytz
import traceback
import logging

# === TERMOS ESPECÍFICOS DA BINANCE COMEÇAM AQUI ===
from binance.client import Client # ESSA É A BIBLIOTECA OFICIAL DA BINANCE
from binance.exceptions import BinanceAPIException # Para capturar erros específicos da API da Binance
# === TERMOS ESPECÍFICOS DA BINANCE TERMINAM AQUI ===

# === CONFIGURAÇÃO DO LOGGER ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === CHAVES DE AMBIENTE ===
API_KEY = os.getenv("API_KEY") # Sua API Key da Binance, carregada do Render
API_SECRET = os.getenv("API_SECRET") # Sua Secret Key da Binance, carregada do Render
BASE_URL = os.getenv("BASE_URL") # 'https://api.binance.com' para produção, 'https://testnet.binance.vision' para testnet

# === INICIALIZAÇÃO DO CLIENTE DA BINANCE ===
# O 'binance_client' é a instância que se comunica diretamente com a API da Binance
binance_client = Client(API_KEY, API_SECRET, base_url=BASE_URL)

# === STATUS DO BOT ===
status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None,
    "versao": "1.2.0_binance_final_confirmado" # Nova versão para confirmar revisão
}

app = Flask(__name__)
tz = pytz.timezone('America/Sao_Paulo')

# === Consulta Saldo Disponível em USDT na Binance ===
def get_balance_usdt() -> float:
    try:
        logger.info("🔄 Consultando saldo USDT na Binance...")
        # === MÉTODO DA BINANCE: get_asset_balance ===
        # Este método é da biblioteca python-binance e consulta o saldo de um ativo específico
        balances = binance_client.get_asset_balance(asset='USDT') 
        
        # O resultado é um dicionário que contém 'free' (livre para uso) e 'locked' (em ordens abertas)
        saldo = float(balances.get('free', 0.0))
        
        logger.info(f"💰 Saldo disponível em USDT na Binance: {saldo:.8f}")
        return saldo

    # === TRATAMENTO DE ERROS ESPECÍFICOS DA BINANCE ===
    except BinanceAPIException as e:
        logger.error(f"❌ Erro da API Binance ao consultar saldo: Código {e.code}, Mensagem: {e.message}")
        return 0.0
    except Exception as e:
        logger.error(f"❌ Erro inesperado ao consultar saldo na Binance: {e}")
        logger.error(traceback.format_exc())
        return 0.0

# === ROTA DE STATUS ===
@app.route("/status", methods=["GET"])
def status():
    status_data["hora_servidor"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(status_data)

# === ROTA PRINCIPAL: /pionexbot ===
# Embora a rota seja /pionexbot, a lógica interna AGORA se comunica com a Binance.
@app.route("/pionexbot", methods=["POST"])
def receive_signal():
    try:
        data = request.get_json(silent=True) 
        
        if not data:
            error_msg = "Nenhum dado JSON válido recebido ou 'Content-Type' incorreto."
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        pair = data.get("pair") # Ex: "BTCUSDT"
        signal = data.get("signal") # Ex: "buy" ou "sell"
        amount_str = data.get("amount") # Opcional

        logger.info(f"\n🔔 Sinal recebido: Par='{pair}', Sinal='{signal}', Quantidade='{amount_str}'")

        if not pair or not signal:
            error_msg = "Parâmetros obrigatórios ausentes: 'pair' ou 'signal'."
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        trade_amount = 0.0
        if amount_str:
            try:
                trade_amount = float(amount_str)
                if trade_amount <= 0:
                    error_msg = "A quantidade 'amount' deve ser um valor positivo."
                    logger.error(f"❌ {error_msg}")
                    return jsonify({"error": error_msg}), 400
            except ValueError:
                error_msg = f"A quantidade '{amount_str}' não é um número válido."
                logger.error(f"❌ {error_msg}")
                return jsonify({"error": error_msg}), 400
        else:
            logger.info("ℹ️ Quantidade não especificada no sinal, consultando saldo USDT disponível para a ordem de mercado...")
            trade_amount = get_balance_usdt()
            if trade_amount <= 0:
                error_msg = "Saldo insuficiente em USDT ou erro ao consultar saldo para executar a ordem."
                logger.error(f"❌ {error_msg}")
                return jsonify({"error": error_msg}), 400
        
        # === TERMOS DE PAR E SINAL DA BINANCE ===
        # Converte o par para o formato da Binance (ex: "BTCUSDT" sem barras)
        symbol_binance = pair.upper().replace("/", "") 
        # Converte o sinal para o formato da Binance ("BUY" ou "SELL")
        binance_side = signal.upper() 
        
        if binance_side not in ["BUY", "SELL"]:
            error_msg = f"Sinal inválido: '{signal}'. Deve ser 'buy' ou 'sell'."
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        # --- PREPARAÇÃO DOS PARÂMETROS DA ORDEM PARA BINANCE ---
        order_params = {
            'symbol': symbol_binance,
            'side': binance_side,
            # === TIPO DE ORDEM DA BINANCE: Client.ORDER_TYPE_MARKET ===
            'type': Client.ORDER_TYPE_MARKET 
        }

        if binance_side == "BUY":
            # === PARÂMETRO DE COMPRA DA BINANCE: quoteOrderQty ===
            # Para COMPRA a mercado, 'quoteOrderQty' é o valor em USDT a ser gasto.
            order_params['quoteOrderQty'] = f"{trade_amount:.8f}"
            logger.info(f"Comprando {trade_amount:.8f} USDT de {symbol_binance} (ordem de mercado).")
        elif binance_side == "SELL":
            # === PARÂMETRO DE VENDA DA BINANCE: quantity ===
            # Para VENDA a mercado, 'quantity' é a quantidade da moeda base a ser vendida.
            # Se 'amount' do sinal for em USDT para venda, você precisará converter para a moeda base.
            order_params['quantity'] = f"{trade_amount:.8f}"
            logger.info(f"Vendendo {trade_amount:.8f} de {symbol_binance} (ordem de mercado).")

        logger.info("\n📤 Enviando ordem para Binance:")
        logger.info(f"  🪙 Par: {symbol_binance}")
        logger.info(f"  📊 Sinal: {binance_side}")
        logger.info(f"  💵 Quantidade para API (quoteOrderQty/quantity): {trade_amount:.8f}")
        logger.info(f"  📦 Parâmetros da Ordem: {json.dumps(order_params, indent=2)}")

        order_response = None
        # === MÉTODOS DE ORDEM DA BINANCE: order_market_buy / order_market_sell ===
        if binance_side == "BUY":
            order_response = binance_client.order_market_buy(**order_params)
        elif binance_side == "SELL":
            order_response = binance_client.order_market_sell(**order_params)
        
        logger.info(f"📥 Resposta COMPLETA da Binance: {json.dumps(order_response, indent=2)}")

        status_data["ultimo_horario"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        status_data["ultimo_sinal"] = f"{binance_side} {symbol_binance}"

        if order_response and order_response.get("status") == "FILLED":
            success_msg = f"✅ ORDEM EXECUTADA com sucesso na Binance: {binance_side} {symbol_binance} com Order ID: {order_response.get('orderId')}. Preço médio: {order_response.get('fills')[0].get('price') if order_response.get('fills') else 'N/A'}"
            logger.info(success_msg)
            return jsonify({"success": True, "message": success_msg, "response": order_response})
        else:
            error_msg_binance = order_response.get('msg', 'Mensagem de erro desconhecida da Binance.') if order_response else "Nenhuma resposta da Binance."
            full_error_msg = f"❌ ERRO NA ORDEM na Binance. Status da ordem: {order_response.get('status', 'N/A')}. Mensagem da Binance: '{error_msg_binance}'"
            logger.error(full_error_msg)
            return jsonify({"error": full_error_msg, "response": order_response}), 400

    # === TRATAMENTO DE ERROS DA BINANCEAPIException ===
    except BinanceAPIException as e:
        full_error_msg = f"❌ ERRO DA API BINANCE: Código {e.code}, Mensagem: {e.message}"
        logger.error(full_error_msg)
        logger.error(traceback.format_exc())
        return jsonify({"error": full_error_msg, "code": e.code, "message": e.message}), 400
    except EnvironmentError as e:
        logger.critical(f"[ERRO DE CONFIGURAÇÃO CRÍTICO] {e}")
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        full_traceback = traceback.format_exc()
        logger.critical(f"[ERRO INTERNO INESPERADO DO BOT] {str(e)}\n{full_traceback}")
        return jsonify({"error": str(e), "traceback": full_traceback}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"🚀 Bot Binance rodando na porta {port}. Verifique os logs na Render após o deploy.")
    app.run(host="0.0.0.0", port=port, debug=True)
