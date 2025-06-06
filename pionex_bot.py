import os
# 'requests' é mantido pois 'python-binance' pode usá-lo indiretamente.
# hmac e hashlib não são mais usados diretamente para assinatura da API da Binance,
# pois a biblioteca 'binance.client' lida com isso internamente.
import requests 
import json
from flask import Flask, request, jsonify
from datetime import datetime
import pytz
import traceback
import logging

# === BIBLIOTECAS E EXCEÇÕES ESPECÍFICAS DA BINANCE ===
from binance.client import Client 
from binance.exceptions import BinanceAPIException 

# === CONFIGURAÇÃO DO LOGGER ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === CHAVES DE AMBIENTE (Carregadas do Render) ===
API_KEY = os.getenv("API_KEY") # Sua API Key da Binance
API_SECRET = os.getenv("API_SECRET") # Sua Secret Key da Binance
BASE_URL = os.getenv("BASE_URL") # Deve ser 'https://api.binance.com' para produção da Binance

# === INICIALIZAÇÃO DO CLIENTE DA BINANCE ===
# O objeto 'binance_client' é a ponte para a API da Binance
binance_client = Client(API_KEY, API_SECRET, base_url=BASE_URL)

# === STATUS DO BOT ===
# Dicionário para armazenar o status atual do bot, visível na rota /status
status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None,
    "versao": "2.0_binance_final_oficial" # Identificador da versão Binance
}

app = Flask(__name__)
# Define o fuso horário para os logs e status (Brasil)
tz = pytz.timezone('America/Sao_Paulo')

# === Função: Consulta Saldo Disponível em USDT na Binance ===
def get_balance_usdt() -> float:
    try:
        logger.info("🔄 Consultando saldo USDT disponível na Binance...")
        # Usa o método 'get_asset_balance' da biblioteca python-binance
        balances = binance_client.get_asset_balance(asset='USDT')
        
        # Pega o saldo 'livre' (free) para uso em ordens
        saldo = float(balances.get('free', 0.0)) 
        
        logger.info(f"💰 Saldo disponível em USDT na Binance: {saldo:.8f}")
        return saldo

    except BinanceAPIException as e:
        # Tratamento de erros específicos da API da Binance (ex: -2015 para API Key inválida/permissão)
        logger.error(f"❌ Erro da API Binance ao consultar saldo: Código {e.code}, Mensagem: {e.message}")
        return 0.0
    except Exception as e:
        # Tratamento de outros erros inesperados
        logger.error(f"❌ Erro inesperado ao consultar saldo na Binance: {e}")
        logger.error(traceback.format_exc()) # Imprime o stack trace completo do erro
        return 0.0

# === ROTA DE STATUS ===
# Rota GET para verificar o status e informações básicas do bot
@app.route("/status", methods=["GET"])
def status():
    status_data["hora_servidor"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(status_data)

# === ROTA PRINCIPAL: /pionexbot (Recebe Sinais) ===
# Esta rota continua com o nome 'pionexbot' por conveniência, mas a lógica interna é para Binance.
@app.route("/pionexbot", methods=["POST"])
def receive_signal():
    try:
        data = request.get_json(silent=True) 
        
        if not data:
            error_msg = "Nenhum dado JSON válido recebido ou 'Content-Type' incorreto. Certifique-se de enviar 'application/json'."
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        # Extrai os parâmetros do sinal (esperamos "BTCUSDT", "buy", "sell")
        pair = data.get("pair") 
        signal = data.get("signal") 
        amount_str = data.get("amount") # Opcional: quantidade para a ordem

        logger.info(f"\n🔔 Sinal recebido: Par='{pair}', Sinal='{signal}', Quantidade='{amount_str}'")

        if not pair or not signal:
            error_msg = "Parâmetros obrigatórios ausentes: 'pair' ou 'signal'."
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        trade_amount = 0.0
        if amount_str:
            # Se 'amount' foi especificado no sinal
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
            # Se 'amount' não foi especificado, consulta o saldo disponível em USDT para 'buy'
            # ou assume que 'trade_amount' será definido para 'sell'
            logger.info("ℹ️ Quantidade não especificada no sinal, consultando saldo USDT disponível para a ordem de mercado (para compra)...")
            trade_amount = get_balance_usdt() # Isso só é relevante para compras a mercado com saldo total
            if trade_amount <= 0:
                error_msg = "Saldo insuficiente em USDT ou erro ao consultar saldo para executar a ordem."
                logger.error(f"❌ {error_msg}")
                return jsonify({"error": error_msg}), 400
        
        # === FORMATAÇÃO PARA TERMOS DA BINANCE ===
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
            'type': Client.ORDER_TYPE_MARKET # Define o tipo de ordem como "Mercado"
        }

        if binance_side == "BUY":
            # Para uma ordem de COMPRA a mercado (BUY MARKET):
            # 'quoteOrderQty' é o VALOR em USDT (moeda de cotação) que você quer gastar.
            order_params['quoteOrderQty'] = f"{trade_amount:.8f}" # Formata para 8 casas decimais
            logger.info(f"Comprando {trade_amount:.8f} USDT de {symbol_binance} (ordem de mercado).")
        elif binance_side == "SELL":
            # Para uma ordem de VENDA a mercado (SELL MARKET):
            # 'quantity' é a QUANTIDADE da moeda base (ex: BTC) que você quer vender.
            # ATENÇÃO: Se seu sinal de VENDA com 'amount' vier em USDT, você precisa converter
            # para a quantidade da moeda base aqui, usando o preço de mercado atual.
            # Por simplicidade, este código assume que 'trade_amount' para SELL JÁ É a quantidade da moeda base.
            order_params['quantity'] = f"{trade_amount:.8f}" # Formata para 8 casas decimais
            logger.info(f"Vendendo {trade_amount:.8f} de {symbol_binance} (ordem de mercado).")

        logger.info("\n📤 Enviando ordem para Binance:")
        logger.info(f"  🪙 Par: {symbol_binance}")
        logger.info(f"  📊 Sinal: {binance_side}")
        logger.info(f"  💵 Quantidade para API (quoteOrderQty/quantity): {trade_amount:.8f}")
        logger.info(f"  📦 Parâmetros da Ordem: {json.dumps(order_params, indent=2)}")

        order_response = None
        # === ENVIO DA ORDEM USANDO MÉTODOS ESPECÍFICOS DA BINANCE ===
        if binance_side == "BUY":
            order_response = binance_client.order_market_buy(**order_params)
        elif binance_side == "SELL":
            order_response = binance_client.order_market_sell(**order_params)
        
        logger.info(f"📥 Resposta COMPLETA da Binance: {json.dumps(order_response, indent=2)}")

        # Atualiza o status do bot
        status_data["ultimo_horario"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        status_data["ultimo_sinal"] = f"{binance_side} {symbol_binance}"

        # Verifica se a ordem foi executada com sucesso (status 'FILLED')
        if order_response and order_response.get("status") == "FILLED":
            success_msg = f"✅ ORDEM EXECUTADA com sucesso na Binance: {binance_side} {symbol_binance} com Order ID: {order_response.get('orderId')}. Preço médio: {order_response.get('fills')[0].get('price') if order_response.get('fills') else 'N/A'}"
            logger.info(success_msg)
            return jsonify({"success": True, "message": success_msg, "response": order_response})
        else:
            # Caso a ordem não seja FILLED imediatamente (ex: PARTIALLY_FILLED, CANCELED ou outro status)
            error_msg_binance = order_response.get('msg', 'Mensagem de erro desconhecida da Binance.') if order_response else "Nenhuma resposta da Binance."
            full_error_msg = f"❌ ERRO NA ORDEM na Binance. Status da ordem: {order_response.get('status', 'N/A')}. Mensagem da Binance: '{error_msg_binance}'"
            logger.error(full_error_msg)
            return jsonify({"error": full_error_msg, "response": order_response}), 400

    except BinanceAPIException as e:
        # Captura e loga erros específicos da API da Binance (ex: saldo insuficiente, símbolo inválido)
        full_error_msg = f"❌ ERRO DA API BINANCE: Código {e.code}, Mensagem: {e.message}"
        logger.error(full_error_msg)
        logger.error(traceback.format_exc()) 
        return jsonify({"error": full_error_msg, "code": e.code, "message": e.message}), 400
    except EnvironmentError as e:
        # Erro se as variáveis de ambiente não estiverem configuradas
        logger.critical(f"[ERRO DE CONFIGURAÇÃO CRÍTICO] {e}")
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Captura e loga quaisquer outros erros inesperados no código do bot
        full_traceback = traceback.format_exc()
        logger.critical(f"[ERRO INTERNO INESPERADO DO BOT] {str(e)}\n{full_traceback}")
        return jsonify({"error": str(e), "traceback": full_traceback}), 500

# === EXECUÇÃO LOCAL (para testes no seu computador) ===
# Esta parte só é executada se você rodar o script diretamente (não na Render)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"🚀 Bot Binance rodando na porta {port}. Verifique os logs na Render após o deploy.")
    app.run(host="0.0.0.0", port=port, debug=True)
