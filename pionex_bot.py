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
    "versao": "1.0.6" # Versão atualizada para refletir as correções
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
        # Lança um erro claro se as chaves de API não estiverem configuradas
        raise EnvironmentError("Erro: API_KEY ou API_SECRET não definidos. Por favor, configure-as nas variáveis de ambiente da Render.")
    
    timestamp = get_timestamp()
    message = f"{method.upper()}{path}{timestamp}{body}"
    signature = hmac.new(API_SECRET.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()
    
    return timestamp, signature

# === ENVIA E-MAIL ===
def enviar_email(assunto: str, corpo: str):
    if not all([EMAIL_ORIGEM, EMAIL_DESTINO, EMAIL_SENHA, SMTP_SERVIDOR]):
        logger.warning("[AVISO] Configurações de e-mail incompletas. E-mail de alerta não será enviado. Verifique suas variáveis de ambiente.")
        return
        
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
        logger.info(f"[EMAIL ENVIADO] Assunto: '{assunto}' para {EMAIL_DESTINO}")
    except Exception as e:
        logger.error(f"[ERRO AO ENVIAR EMAIL] Ocorreu um erro: {e}")
        logger.error(traceback.format_exc())

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
            enviar_email("❌ ERRO AO CONSULTAR SALDO", f"Erro da API Pionex: {error_msg_api}\nResposta Completa: {json.dumps(data, indent=2)}")
            return 0.0

    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Erro de requisição HTTP ao consultar saldo: {e}")
        enviar_email("❌ ERRO DE REQUISIÇÃO (SALDO)", str(e))
        return 0.0
    except EnvironmentError as e: # Captura o erro de variáveis de ambiente
        logger.critical(f"[ERRO DE CONFIGURAÇÃO CRÍTICO] {e}")
        return 0.0 # Retorna 0.0 para que a ordem não prossiga
    except Exception as e:
        logger.error(f"❌ Erro inesperado ao processar saldo: {e}")
        logger.error(traceback.format_exc())
        enviar_email("❌ ERRO INTERNO (SALDO)", f"Erro inesperado: {str(e)}\n\nTraceback:\n{traceback.format_exc()}")
        return 0.0

# === ROTA DE STATUS ===
@app.route("/status", methods=["GET"])
def status():
    status_data["hora_servidor"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(status_data)

# === ROTA PRINCIPAL /pionexbot ===
@app.route("/pionexbot", methods=["POST"])
def receive_signal():
    try: # Adicionado um try/except mais abrangente para capturar erros iniciais
        data = request.get_json(silent=True) 
        
        if not data:
            error_msg = "Nenhum dado JSON válido recebido ou 'Content-Type' incorreto. Certifique-se de enviar 'application/json'."
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        pair = data.get("pair")
        signal = data.get("signal")
        amount_str = data.get("amount") # O 'amount' do sinal de entrada é sempre o que o usuário quer como referência
        
        logger.info(f"\n🔔 Sinal recebido: Par='{pair}', Sinal='{signal}', Quantidade='{amount_str}'")

        if not pair or not signal:
            error_msg = "Parâmetros obrigatórios ausentes: 'pair' ou 'signal'."
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        trade_amount = 0.0 # Essa será a quantidade a ser enviada para a API (amount ou size)
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
        else: # Se 'amount' não for especificado no sinal, usamos o saldo total
            logger.info("ℹ️ Quantidade não especificada no sinal, consultando saldo USDT disponível para a ordem de mercado...")
            trade_amount = get_balance_usdt() # Isso buscará o saldo em USDT
            if trade_amount <= 0:
                error_msg = "Saldo insuficiente em USDT ou erro ao consultar saldo para executar a ordem."
                logger.error(f"❌ {error_msg}")
                enviar_email("❌ SALDO INSUFICIENTE", error_msg)
                return jsonify({"error": error_msg}), 400
            
        method = "POST"
        path = "/api/v1/trade/order"
        pionex_side = signal.upper() 
        
        if pionex_side not in ["BUY", "SELL"]:
            error_msg = f"Sinal inválido: '{signal}'. Deve ser 'buy' ou 'sell'."
            logger.error(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400

        # === CONSTRUÇÃO DO CORPO DA REQUISIÇÃO PARA A PIONEX - CORRIGIDA ===
        body_dict = {
            "symbol": pair.upper(),
            "side": pionex_side,
            "type": "MARKET" # Ordem de mercado
        }

        if pionex_side == "BUY":
            # Para compra de mercado, Pionex espera 'amount' (valor em USDT a ser gasto)
            body_dict["amount"] = f"{trade_amount:.8f}" 
        elif pionex_side == "SELL":
            # Para venda de mercado, Pionex espera 'size' (quantidade da moeda base a ser vendida)
            # ATENÇÃO: Se o 'amount' do sinal recebido for em USDT e a intenção for vender BTC,
            # VOCÊ PRECISARÁ DE UMA LÓGICA AQUI PARA CALCULAR O 'size' (quantidade de BTC)
            # BASEADO NO PREÇO ATUAL DE BTC/USDT. Por enquanto, estamos assumindo que 'amount'
            # no sinal DE VENDA já representa a quantidade da moeda base.
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
            enviar_email("✅ ORDEM EXECUTADA", success_msg + f"\nDetalhes da Ordem: {json.dumps(res_json, indent=2)}")
            return jsonify({"success": True, "message": success_msg, "response": res_json})
        else:
            error_msg_api = res_json.get('message', 'Nenhuma mensagem de erro específica da Pionex.')
            full_error_msg = f"❌ ERRO NA ORDEM: {pionex_side} {pair.upper()}. Status HTTP: {response.status_code}. Mensagem da Pionex: '{error_msg_api}'"
            logger.error(full_error_msg)
            enviar_email("❌ ERRO NA ORDEM", full_error_msg + f"\nResposta Completa da Pionex: {json.dumps(res_json, indent=2)}")
            return jsonify({"error": res_json}), response.status_code if response.status_code >= 400 else 400

    except EnvironmentError as e:
        logger.critical(f"[ERRO DE CONFIGURAÇÃO CRÍTICO] {e}") # Use critical para erros que impedem o funcionamento
        enviar_email("❌ ERRO DE CONFIGURAÇÃO CRÍTICO", str(e))
        return jsonify({"error": str(e)}), 500
    except requests.exceptions.RequestException as e:
        logger.error(f"[ERRO DE CONEXÃO] Erro ao conectar à API da Pionex: {e}")
        enviar_email("❌ ERRO DE CONEXÃO", f"Erro ao conectar à Pionex: {str(e)}")
        return jsonify({"error": f"Erro de conexão com a Pionex: {e}"}), 500
    except Exception as e:
        full_traceback = traceback.format_exc()
        logger.critical(f"[ERRO INTERNO INESPERADO DO BOT] {str(e)}\n{full_traceback}")
        enviar_email("❌ ERRO INTERNO DO BOT CRÍTICO", f"Um erro inesperado ocorreu:\n{str(e)}\n\nTraceback:\n{full_traceback}")
        return jsonify({"error": str(e), "traceback": full_traceback}), 500

# === EXECUÇÃO LOCAL ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"🚀 Bot Pionex rodando na porta {port}. Verifique os logs na Render após o deploy.")
    # debug=True ainda é útil para o Flask, mas os logs agora virão do 'logging'
    app.run(host="0.0.0.0", port=port, debug=True)
