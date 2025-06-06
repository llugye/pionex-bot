import os
import hmac
import hashlib
import requests
import json
from flask import Flask, request, jsonify
from datetime import datetime
import pytz
import traceback
import logging

# === CONFIGURAÇÃO DO LOGGER ===
# Configura o logger para imprimir mensagens com timestamp e nível
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === CHAVES DE AMBIENTE ===
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
BASE_URL = "https://api.pionex.com"

# As variáveis de e-mail foram removidas daqui e das funções.

# === STATUS DO BOT ===
status_data = {
    "status": "online",
    "ultimo_horario": None,
    "ultimo_sinal": None,
    "versao": "1.0.7_sem_email" # Versão atualizada para indicar remoção de e-mail
}

app = Flask(__name__)
tz = pytz.timezone('America/Sao_Paulo')

# === TIMESTAMP EM MILISSEGUNDOS ===
def get_timestamp() -> str:
    return str(int(datetime.utcnow().timestamp() * 1000))

# === GERA ASSINATURA DA REQUISIÇÃO ===
def sign_request(method: str, path: str, body: str = '') -> tuple:
    if not API_KEY or not API_SECRET:
        logger.critical("Erro: API_KEY ou API_SECRET não definidos. Por favor, configure-as nas variáveis de ambiente da Render.")
        raise EnvironmentError("Erro: API_KEY ou API_SECRET não definidos. Por favor, configure-as nas variáveis de ambiente da Render.")
    
    timestamp = get_timestamp()
    message = f"{method.upper()}{path}{timestamp}{body}"
    signature = hmac.new(API_SECRET.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()
    
    return timestamp, signature

# === ENVIA E-MAIL (REMOVIDA COMPLETAMENTE) ===
# A função enviar_email e todas as suas chamadas foram removidas.

# === CONSULTA SALDO DISPONÍVEL EM USDT ===
def get_balance_usdt() -> float:
    try:
        method = "GET"
        path = "/api/v1/account/balances"
        timestamp, signature = sign_request(method, path, body='') 
        
        headers = {
            "PIONEX-KEY": API_KEY,
            "PIONEX-SIGNATURE": signature,
            "timestamp": timestamp
        }

        logger.info(f"🔄 Consultando saldo USDT em {BASE_URL + path}")
        response = requests.get(BASE_URL + path, headers=headers)
        response.raise_for_status()

        data = response.json()

        if data.get("result"):
            for coin in data["data"]["balances"]:
                if coin["coin"] == "USDT":
                    valor = coin.get("free") or coin.get("available") or "0"
                    saldo = float(valor)
                    logger.info(f"💰 Saldo disponível em USDT: {saldo:.8f}")
                    return saldo
            logger.warning("❗ Moeda USDT não encontrada na lista de saldos recebida da Pionex.")
            return 0.0
        else:
            error_msg_api = data.get('message', 'Mensagem de erro desconhecida da Pionex.')
            logger.error(f"❌ Erro ao consultar saldo na Pionex: {error_msg_api}")
            # enviar_email("❌ ERRO AO CONSULTAR SALDO", f"Erro da API Pionex: {error_msg_api}\nResposta Completa: {json.dumps(data, indent=2)}") # Removido
            return 0.0

    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Erro de requisição HTTP ao consultar saldo: {e}")
        # enviar_email("❌ ERRO DE REQUISIÇÃO (SALDO)", str(e)) # Removido
        return 0.0
    except EnvironmentError as e:
        logger.critical(f"[ERRO DE CONFIGURAÇÃO CRÍTICO] {e}")
        return 0.0
    except Exception as e:
        logger.error(f"❌ Erro inesperado ao processar saldo: {e}")
        logger.error(traceback.format_exc())
        # enviar_email("❌ ERRO INTERNO (SALDO)", f"Erro inesperado: {str(e)}\n\nTraceback:\n{traceback.format_exc()}") # Removido
        return 0.0

# === ROTA DE STATUS ===
@app.route("/status", methods=["GET"])
def status():
    status_data["hora_servidor"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(status_data)

# === ROTA PRINCIPAL /pionexbot ===
@app.route("/pionexbot", methods=["POST"])
def receive_signal():
    try:
        data = request.get_json(silent=True) 
        
        if not data:
            error_msg = "Nenhum dado JSON válido recebido ou 'Content-Type' incorreto. Certifique-se de enviar 'application/json'."
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        pair = data.get("pair")
        signal = data.get("signal")
        amount_str = data.get("amount")
        
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
                # enviar_email("❌ SALDO INSUFICIENTE", error_msg) # Removido
                return jsonify({"error": error_msg}), 400
            
        method = "POST"
        path = "/api/v1/trade/order"
        pionex_side = signal.upper() 
        
        if pionex_side not in ["BUY", "SELL"]:
            error_msg = f"Sinal inválido: '{signal}'. Deve ser 'buy' ou 'sell'."
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        body_dict = {
            "symbol": pair.upper(),
            "side": pionex_side,
            "type": "MARKET"
        }

        if pionex_side == "BUY":
            body_dict["amount"] = f"{trade_amount:.8f}" 
        elif pionex_side == "SELL":
            logger.warning("⚠️ Atenção: Para sinais de VENDA ('SELL'), o parâmetro 'amount' no sinal deveria ser a QUANTIDADE da moeda base (ex: BTC), não USDT. A API da Pionex espera 'size' para venda de mercado. Ajustando para usar 'amount' como 'size' para fins de teste.")
            body_dict["size"] = f"{trade_amount:.8f}"
            
        body_json = json.dumps(body_dict)

        timestamp, signature = sign_request(method, path, body=body_json)

        headers = {
            "PIONEX-KEY": API_KEY,
            "PIONEX-SIGNATURE": signature,
            "timestamp": timestamp,
            "Content-Type": "application/json"
        }

        logger.info("\n📤 Enviando ordem para Pionex:")
        logger.info(f"  🪙 Par: {pair.upper()}")
        logger.info(f"  📊 Sinal: {pionex_side}")
        logger.info(f"  💵 Quantidade para API (amount/size): {trade_amount:.8f}")
        logger.info(f"  📦 Payload (assinado): {body_json}")
        logger.info(f"  PIONEX-KEY (início): {API_KEY[:5]}...")
        logger.info(f"  PIONEX-SIGNATURE (início): {signature[:10]}...")
        logger.info(f"  Timestamp: {timestamp}")

        response = requests.post(BASE_URL + path, headers=headers, data=body_json)
        
        logger.info(f"📥 Resposta BRUTA da Pionex: Status={response.status_code}, Corpo={response.text}")

        res_json = {}
        try:
            res_json = response.json()
        except requests.exceptions.JSONDecodeError:
            logger.warning("⚠️ A resposta da Pionex NÃO É UM JSON válido. Isso pode indicar um erro grave na requisição ou na API.")
            res_json = {"error": "Resposta da API Pionex não é JSON válido.", "raw_response": response.text}
        except Exception as e:
            logger.warning(f"⚠️ Erro inesperado ao decodificar JSON da resposta da Pionex: {e}")
            res_json = {"error": "Erro inesperado ao decodificar JSON da Pionex.", "raw_response": response.text}

        status_data["ultimo_horario"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        status_data["ultimo_sinal"] = f"{pionex_side} {pair.upper()}"

        if response.status_code == 200 and res_json.get("result"):
            success_msg = f"✅ ORDEM EXECUTADA com sucesso: {pionex_side} {pair.upper()} com {trade_amount:.8f} USDT (ou base_coin)."
            logger.info(success_msg)
            # enviar_email("✅ ORDEM EXECUTADA", success_msg + f"\nDetalhes da Ordem: {json.dumps(res_json, indent=2)}") # Removido
            return jsonify({"success": True, "message": success_msg, "response": res_json})
        else:
            error_msg_api = res_json.get('message', 'Nenhuma mensagem de erro específica da Pionex.')
            full_error_msg = f"❌ ERRO NA ORDEM: {pionex_side} {pair.upper()}. Status HTTP: {response.status_code}. Mensagem da Pionex: '{error_msg_api}'"
            logger.error(full_error_msg)
            # enviar_email("❌ ERRO NA ORDEM", full_error_msg + f"\nResposta Completa da Pionex: {json.dumps(res_json, indent=2)}") # Removido
            return jsonify({"error": res_json}), response.status_code if response.status_code >= 400 else 400

    except EnvironmentError as e:
        logger.critical(f"[ERRO DE CONFIGURAÇÃO CRÍTICO] {e}")
        # enviar_email("❌ ERRO DE CONFIGURAÇÃO CRÍTICO", str(e)) # Removido
        return jsonify({"error": str(e)}), 500
    except requests.exceptions.RequestException as e:
        logger.error(f"[ERRO DE CONEXÃO] Erro ao conectar à API da Pionex: {e}")
        # enviar_email("❌ ERRO DE CONEXÃO", f"Erro ao conectar à Pionex: {str(e)}") # Removido
        return jsonify({"error": f"Erro de conexão com a Pionex: {e}"}), 500
    except Exception as e:
        full_traceback = traceback.format_exc()
        logger.critical(f"[ERRO INTERNO INESPERADO DO BOT] {str(e)}\n{full_traceback}")
        # enviar_email("❌ ERRO INTERNO DO BOT CRÍTICO", f"Um erro inesperado ocorreu:\n{str(e)}\n\nTraceback:\n{full_traceback}") # Removido
        return jsonify({"error": str(e), "traceback": full_traceback}), 500

# === EXECUÇÃO LOCAL ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"🚀 Bot Pionex rodando na porta {port}. Verifique os logs na Render após o deploy.")
    app.run(host="0.0.0.0", port=port, debug=True)
