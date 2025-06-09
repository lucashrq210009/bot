import asyncio
import json
import logging
import os
import time
import base58
from dotenv import load_dotenv
import aiohttp
from datetime import datetime, timezone
from colorama import Fore, Back, Style, init
import sys
import random
import traceback

# Inicializa o colorama para funcionar corretamente no Windows
init()

# Garante que o diretório de logs existe
os.makedirs("logs", exist_ok=True)

# Configuração de logging - direcionar logs para arquivo e não para console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/bot.log"),
        # Removendo o StreamHandler para evitar saída duplicada no console
    ]
)

# Importando funções de formatação
from formatters import (
    format_success, format_error, format_warning, format_info, 
    format_price, format_percent, format_header, format_subheader,
    format_pool, format_sol, format_timestamp
)

from trader import RaydiumTrader, verify_transaction_status
from monitor_grpc import PriceMonitorGRPC
from bxsolana.provider.http import http  # Utiliza o provider http
from bxsolana.provider import constants
from telegram_notifier import TelegramNotifier  # Importação do notificador Telegram

load_dotenv()

# Carrega variáveis de ambiente e sanitiza AUTH_HEADER
AUTH_HEADER = os.getenv("AUTH_HEADER", "").replace('[', '').replace(']', '')
PUBLIC_KEY = os.getenv("PUBLIC_KEY", "")
PRIVATE_KEY_ENV = os.getenv("PRIVATE_KEY", "SUA_PRIVATE_KEY")

if PRIVATE_KEY_ENV:
    try:
        if PRIVATE_KEY_ENV.strip().startswith('['):
            key_list = json.loads(PRIVATE_KEY_ENV)
            key_bytes = bytes(key_list)
            PRIVATE_KEY = list(key_bytes)
            PRIVATE_KEY_BASE58 = base58.b58encode(key_bytes).decode('utf-8')
        else:
            PRIVATE_KEY_BASE58 = PRIVATE_KEY_ENV.strip()
            key_bytes = base58.b58decode(PRIVATE_KEY_BASE58)
            PRIVATE_KEY = list(key_bytes)
    except Exception as e:
        raise ValueError(f"Erro ao processar PRIVATE_KEY. Se estiver em formato JSON, verifique a formatação. Detalhes: {e}")
else:
    PRIVATE_KEY = None
    PRIVATE_KEY_BASE58 = None

if PRIVATE_KEY_BASE58:
    os.environ["PRIVATE_KEY"] = PRIVATE_KEY_BASE58
os.environ["AUTH_HEADER"] = AUTH_HEADER
os.environ["PUBLIC_KEY"] = PUBLIC_KEY

def load_trade_config():
    with open("config.json", "r") as f:
        config = json.load(f)
    return config

def chunk_list(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]

async def get_pool_info_by_token(token_mint: str):
    """
    Obtém informações da pool usando o endpoint /pools/info/mint da API da Raydium.
    
    :param token_mint: Endereço do token (out_token)
    :return: Configuração da pool ou None se não encontrada
    """
    sol_mint = "So11111111111111111111111111111111111111112"
    base_url = 'https://api-v3.raydium.io/pools/info/mint'
    params = {
        "mint1": token_mint,
        "mint2": sol_mint,
        "poolType": "standard",
        "poolSortField": "default",
        "sortType": "desc",
        "pageSize": 2,
        "page": 1
    }
    
    async with aiohttp.ClientSession() as session:
        url = (f"{base_url}?mint1={params['mint1']}&mint2={params['mint2']}"
               f"&poolType={params['poolType']}&poolSortField={params['poolSortField']}"
               f"&sortType={params['sortType']}&pageSize={params['pageSize']}&page={params['page']}")
        async with session.get(url) as response:
            if response.status != 200:
                print(f"Erro ao obter informações da pool para o token {token_mint}: {response.status}")
                return None
            response_json = await response.json()
        
        data_obj = response_json.get("data", {})
        pools_list = data_obj.get("data", [])
        
        if not pools_list:
            print(f"Nenhuma pool encontrada para o token {token_mint}")
            return None
        
        # Pegamos a primeira pool encontrada
        pool = pools_list[0]
        
        # Construímos o nome da pool com base nos tokens
        mintA = pool.get("mintA", {})
        mintB = pool.get("mintB", {})
        
        # Determinamos a posição do SOL na resposta da API
        sol_is_mintA = mintA.get("address") == sol_mint
        
        if sol_is_mintA:
            non_sol_mint = mintB
            pool_name = f"{mintB.get('symbol')}/WSOL"
            sol_reserve = pool.get("mintAmountA", 0)
        else:
            non_sol_mint = mintA
            pool_name = f"{mintA.get('symbol')}/WSOL"
            sol_reserve = pool.get("mintAmountB", 0)
        
        # Obtém dados adicionais úteis da pool
        volume_24h = pool.get("day", {}).get("volume", 0)
        tvl = pool.get("tvl", 0)
        
        print(f"{format_info('Pool encontrada:')} {format_pool(pool_name)}")
        print(f"  • Reserva: {format_sol(sol_reserve)}  • TVL: {format_sol(tvl)}  • Volume 24h: {format_sol(volume_24h)}")
        
        # Retornamos a configuração da pool
        return {
            "pool_address": pool.get("id"),
            "token1_mint_address": non_sol_mint.get("address"),
            "token2_mint_address": sol_mint,
            "token1_mint_symbol": non_sol_mint.get("symbol"),
            "token2_mint_symbol": "WSOL",
            "sol_reserve": sol_reserve,
            "sol_decimals": mintA.get("decimals") if sol_is_mintA else mintB.get("decimals"),
            "pool": pool_name,
            "sol_is_mintA": sol_is_mintA  # Adicionamos esta informação
        }

async def build_pool_config_from_token(token_config, trade_config):
    """
    Constrói a configuração completa da pool a partir de um token definido manualmente.
    
    :param token_config: Configuração do token definido manualmente
    :param trade_config: Configurações gerais de trading
    :return: Configuração completa da pool ou None se não encontrada
    """
    # Obtém informações da pool via API
    token_mint = token_config.get("out_token")
    print(f"Verificando token: {Fore.CYAN}{token_mint}{Style.RESET_ALL}")
    pool_info = await get_pool_info_by_token(token_mint)
    
    if not pool_info:
        print(format_error(f"Não foi possível obter informações para o token {token_mint}"))
        return None
        
    # Verifica se a pool tem a reserva mínima de SOL configurada
    min_sol_reserve = trade_config.get("min_sol_reserve", 0)
    sol_reserve = pool_info.get("sol_reserve", 0)
    
    if sol_reserve < min_sol_reserve:
        print(format_warning(f"Pool {pool_info.get('pool')} ignorada: reserva de SOL ({sol_reserve:.2f}) menor que o mínimo ({min_sol_reserve})"))
        return None
    
    # Obtém o valor padrão de priority_fee
    default_priority_fee = 1000000
    if "buy_settings" in trade_config and "priority_fee_sol" in trade_config["buy_settings"]:
        LAMPORTS_PER_SOL = 1_000_000_000
        default_priority_fee = int(trade_config["buy_settings"]["priority_fee_sol"] * LAMPORTS_PER_SOL)
    
    # Se o token_pair não foi definido, use o nome da pool da API
    token_pair = token_config.get("token_pair") or pool_info.get("pool")
    
    # Usa o pair_address da configuração manual ou da API
    pair_address = token_config.get("pair_address") or pool_info.get("pool_address")
    
    sol_mint = "So11111111111111111111111111111111111111112"
    
    # Determina o valor de sol_in_quote com base na pool_info
    # Se sol_is_mintA for True, então sol_in_quote deve ser False (precisamos trocar)
    # Se sol_is_mintA for False, então sol_in_quote deve ser True (não precisamos trocar)
    sol_in_quote = token_config.get("sol_in_quote")
    if sol_in_quote is None and "sol_is_mintA" in pool_info:
        sol_in_quote = not pool_info["sol_is_mintA"]
    
    # Imprime informação sobre a ordem dos tokens
    if sol_in_quote:
        print(f"  • Configuração: {format_info('SOL está no quote')} (denominador)")
    else:
        print(f"  • Configuração: {format_info('SOL está no base')} (numerador)")
    
    config = {
        "token_pair": token_pair,
        "pair_address": pair_address,
        "owner_address": trade_config["owner_address"],
        "price_drop_percentage": trade_config["price_drop_percentage"],
        "max_price_drop_percentage": trade_config["max_price_drop_percentage"],
        "profit_target_percentage": trade_config["profit_target_percentage"],
        "trade_amount": trade_config["trade_amount"],
        "slippage": trade_config["slippage"],
        "priority_fee": default_priority_fee,
        "in_token": sol_mint,
        "out_token": token_mint,
        "sol_reserve": sol_reserve,  # Adicionamos a reserva de SOL para referência
        "buy_settings": trade_config.get("buy_settings", {}),
        "sell_settings": trade_config.get("sell_settings", {}),
        "sol_in_quote": sol_in_quote  # Definimos sol_in_quote
    }
    
    # Se existirem campos adicionais na configuração do token, adicione-os
    for key, value in token_config.items():
        if key not in config and key != "out_token":
            config[key] = value
    
    return config

async def monitor_pool(pool_config):
    grpc_rpc_fqdn = os.getenv("GRPC_RPC_FQDN", "inseminates-nutritionally-afnmdcxbdf-dedicated-lb.helius-rpc.com:2053")
    grpc_x_token = os.getenv("GRPC_X_TOKEN", "")
    monitor = PriceMonitorGRPC(pool_config, grpc_rpc_fqdn, grpc_x_token)
    pool_name = pool_config['token_pair']
    previous_price = None
    last_print_time = 0
    print_interval = 10  # segundos
    last_notification_time = 0
    notification_interval = 3600  # enviar notificação a cada 1 hora
    
    # Adicionar variáveis para rastreamento de preços e proteção contra MEV
    price_history = []  # Lista de tuplas (preço, timestamp)
    price_history_window = 60  # Janela de tempo em segundos para rastrear preços
    suspicious_pump_threshold = pool_config.get("mev_protection_pump_threshold", 5)  # % de alta para detectar pump de MEV
    mev_protection_time_window = pool_config.get("mev_protection_time_window", 30)  # Tempo em segundos para considerar queda após pump como suspeita
    recent_pump_detected = False
    pump_timestamp = 0
    
    async with monitor as m:
        async for price in m.stream_price():
            current_time = time.time()
            
            # Adiciona preço atual ao histórico
            price_history.append((price, current_time))
            
            # Remove preços antigos que estão fora da janela de tempo
            price_history = [p for p in price_history if current_time - p[1] <= price_history_window]
            
            if previous_price is None:
                previous_price = price
                print(f"{format_pool(pool_name)} Preço inicial: {format_price(price, 10)}")
            else:
                delta = ((previous_price - price) / previous_price) * 100
                is_drop = delta > 0
                
                # Se não é queda (é alta), verifica se é uma alta súbita (possível pump de MEV)
                if not is_drop and abs(delta) >= suspicious_pump_threshold:
                    recent_pump_detected = True
                    pump_timestamp = current_time
                    pump_percentage = abs(delta)
                    print(f"{format_pool(pool_name)} {Fore.MAGENTA}⚠️ ALTA SÚBITA DETECTADA: {format_percent(pump_percentage, True)} (possível MEV){Style.RESET_ALL}")
                
                # Verifica se o pump foi recente
                if recent_pump_detected and (current_time - pump_timestamp > mev_protection_time_window):
                    recent_pump_detected = False  # Reseta o flag após o período de proteção
                    print(f"{format_pool(pool_name)} {Fore.CYAN}ℹ️ Período de proteção MEV encerrado{Style.RESET_ALL}")
                
                # Simplifica a saída para mostrar mudanças significativas ou periodicamente
                should_print = (abs(delta) >= 1.0 or 
                               (current_time - last_print_time >= print_interval))
                
                # Imprime cabeçalho com hora atual a cada 5 minutos
                if int(current_time) % 300 < 1:
                    print(f"\n{format_timestamp()} Monitoramento em andamento...")
                
                if should_print:
                    direction = "↓" if is_drop else "↑"
                    print(f"{format_pool(pool_name)} {direction} {format_price(price, 10)} | {format_percent(delta, not is_drop)}")
                    last_print_time = current_time
                
                # Removendo notificação de quedas significativas que não resultam em compra
                
                min_drop = pool_config.get("price_drop_percentage", 7)
                max_drop = pool_config.get("max_price_drop_percentage", 37)
                
                if delta >= min_drop and delta <= max_drop:
                    # Verifica se estamos no período de proteção MEV após um pump
                    if recent_pump_detected:
                        print(f"{format_pool(pool_name)} {Fore.YELLOW}🛡️ QUEDA APÓS PUMP DETECTADA {Style.RESET_ALL} {format_percent(delta)}")
                        print(f"  Ignorando possível manipulação de preço (MEV). Queda: {format_percent(delta)}")
                    else:
                        pool_config["drop_timestamp"] = time.time()
                        pool_config["triggered_price"] = price
                        print(f"\n{format_pool(pool_name)} {Fore.WHITE}{Back.RED} ALERTA: QUEDA DETECTADA {Style.RESET_ALL} {format_percent(delta)}")
                        print(f"  Preço atual: {format_price(price)} | Queda: {format_percent(delta)}")
                        
                        # Adicionar notificação de alerta de preço
                        from telegram_notifier import TelegramNotifier
                        notifier = TelegramNotifier()
                        await notifier.send_price_alert(
                            pool_name.split('/')[0],  # Nome do token
                            price,                     # Preço atual
                            delta,                    # Percentual de queda
                            previous_price,           # Preço anterior
                            {
                                "tvl": pool_config.get("tvl", 0),
                                "volume_24h": pool_config.get("volume_24h", 0),
                                "sol_reserve": pool_config.get("sol_reserve", 0)
                            }
                        )
                        
                        return pool_config
                elif delta > max_drop:
                    print(f"{format_pool(pool_name)} {format_warning(f'Queda de {delta:.2f}% excede o limite máximo de {max_drop}%; ignorando.')}")
                
                previous_price = price
    return None

async def get_transaction_time(signature: str, api_key: str) -> int:
    """
    Consulta o endpoint getTransaction para obter o blockTime (timestamp Unix)
    da transação finalizada, utilizando o commitment "finalized".
    Se o blockTime não estiver disponível, retorna 0.
    """
    url = f"https://mainnet.helius-rpc.com/?api-key={api_key}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"commitment": "finalized"}]
    }
    timeout = 30
    start = time.time()
    while time.time() - start < timeout:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                data = await response.json()
                result = data.get("result")
                if result and result.get("blockTime") is not None:
                    return result["blockTime"]
        await asyncio.sleep(1)
    return 0

async def monitor_profit(pool_config, buy_price):
    grpc_rpc_fqdn = os.getenv("GRPC_RPC_FQDN", "inseminates-nutritionally-afnmdcxbdf-dedicated-lb.helius-rpc.com:2053")
    grpc_x_token = os.getenv("GRPC_X_TOKEN", "7ceb5e41-f6ea-4197-8ba1-90cf23b92a5a")
    from monitor_grpc import PriceMonitorGRPC
    monitor = PriceMonitorGRPC(pool_config, grpc_rpc_fqdn, grpc_x_token)
    pool_config["reference_price"] = buy_price
    pool_name = pool_config['token_pair']
    target = pool_config.get("profit_target_percentage", 5)
    
    # Obtém o timeout em minutos para exibir informação
    timeout_minutes = pool_config.get("profit_timeout_minutes", 5)
    
    print(f"\n{format_header(' MONITORANDO LUCRO ')} {format_pool(pool_name)}")
    print(f"  Preço de compra: {format_price(buy_price)} | Meta de lucro: {format_percent(target, True)} | Timeout: {timeout_minutes} minutos")
    
    last_print_time = 0
    print_interval = 5  # segundos
    
    async with monitor as m:
        last_warning_time = 0
        warning_interval = 15  # Intervalo em segundos para exibir mensagens de aviso
        while True:
            try:
                price = await asyncio.wait_for(m.stream_price().__anext__(), timeout=5)
            except asyncio.TimeoutError:
                price = pool_config.get("reference_price", buy_price)
                print(f"{format_pool(pool_name)} {format_warning('Sem atualização via gRPC')} | Usando preço de referência: {format_price(price)}")
            
            profit = ((price - buy_price) / buy_price) * 100
            current_time = time.time()
            
            # Imprime a cada X segundos ou em mudanças de lucro significativas
            if current_time - last_print_time >= print_interval or abs(profit - pool_config.get("last_profit", 0)) >= 0.5:
                print(f"{format_pool(pool_name)} Preço atual: {format_price(price)} | Lucro: {format_percent(profit)}")
                pool_config["last_profit"] = profit
                last_print_time = current_time
            
            pool_config["reference_price"] = price
            pool_config["current_price"] = price
            
            if profit >= target:
                print(f"\n{format_pool(pool_name)} {Fore.BLACK}{Back.GREEN} META DE LUCRO ATINGIDA {Style.RESET_ALL} {format_percent(profit)}")
                print(f"  Preço de compra: {format_price(buy_price)} | Preço atual: {format_price(price)}")
                return pool_config
            else:
                # Exibe mensagem de meta não atingida apenas a cada intervalo definido
                if current_time - last_warning_time >= warning_interval:
                    print(format_warning(f"Aguardando meta de lucro: {format_percent(profit)} (alvo: {format_percent(target)})"))
                    last_warning_time = current_time
                await asyncio.sleep(1)

async def central_manager():
    trade_config = load_trade_config()
    
    # Inicializa o notificador Telegram
    telegram = TelegramNotifier()
    
    # Configuração para resumo periódico
    last_summary_time = time.time()
    summary_interval = 6 * 3600  # 6 horas em segundos
    
    # Configuração para resumo diário
    last_daily_summary = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    daily_stats = {"daily_trades": 0, "daily_profit": 0}
    
    # Verificar se a chave de API do Helius está configurada
    helius_api_key = os.getenv("HELIUS_API_KEY", "")
    
    if not helius_api_key:
        print("⚠️ ATENÇÃO: API Key do Helius não está configurada no arquivo .env")
        await telegram.send_error_notification(
            "API Key do Helius não está configurada no arquivo .env. O monitoramento de transações pode ser afetado.",
            error_type="Configuração",
            suggestions=[
                "Adicione HELIUS_API_KEY no arquivo .env",
                "Obtenha uma API key gratuita em https://dev.helius.xyz/dashboard"
            ]
        )
    
    # Log de configurações
    print("\n" + format_header(" CONFIGURAÇÕES DO BOT ").center(80))
    print(f"  • Queda mínima de preço: {format_percent(trade_config['price_drop_percentage'])}")
    print(f"  • Queda máxima de preço: {format_percent(trade_config['max_price_drop_percentage'])}")
    print(f"  • Meta de lucro: {format_percent(trade_config['profit_target_percentage'], True)}")
    print(f"  • Valor de cada trade: {format_sol(trade_config['trade_amount'])}")
    print(f"  • Slippage: {format_percent(trade_config['slippage'])}")
    print(f"  • Reserva mínima de SOL: {format_sol(trade_config.get('min_sol_reserve', 0))}")
    
    # Adiciona logs para as configurações de proteção contra MEV
    print("\n" + format_subheader(" CONFIGURAÇÕES DE PROTEÇÃO MEV ").center(80))
    mev_pump_threshold = trade_config.get("mev_protection_pump_threshold", 5)
    mev_time_window = trade_config.get("mev_protection_time_window", 30)
    print(f"  • Alta repentina mínima: {format_percent(mev_pump_threshold, True)}")
    print(f"  • Janela de proteção: {mev_time_window} segundos após pump")
    
    # Configurações de compra e venda
    buy_settings = trade_config.get("buy_settings", {})
    sell_settings = trade_config.get("sell_settings", {})
    
    print("\n" + format_subheader(" CONFIGURAÇÕES DE COMPRA ").center(80))
    priority_fee_sol = buy_settings.get("priority_fee_sol", 0.001)
    compute_price_sol = buy_settings.get("compute_price_sol", 0.001)
    LAMPORTS_PER_SOL = 1_000_000_000
    priority_fee_lamports = int(priority_fee_sol * LAMPORTS_PER_SOL)
    compute_price_lamports = int(compute_price_sol * LAMPORTS_PER_SOL)
    print(f"  • Priority Fee: {format_sol(priority_fee_sol)} ({priority_fee_lamports:,} lamports)")
    print(f"  • Compute Price: {format_sol(compute_price_sol)} ({compute_price_lamports:,} lamports)")
    
    print("\n" + format_subheader(" CONFIGURAÇÕES DE VENDA ").center(80))
    priority_fee_sol = sell_settings.get("priority_fee_sol", 0.001)
    compute_price_sol = sell_settings.get("compute_price_sol", 0.001)
    priority_fee_lamports = int(priority_fee_sol * LAMPORTS_PER_SOL)
    compute_price_lamports = int(compute_price_sol * LAMPORTS_PER_SOL)
    print(f"  • Priority Fee: {format_sol(priority_fee_sol)} ({priority_fee_lamports:,} lamports)")
    print(f"  • Compute Price: {format_sol(compute_price_sol)} ({compute_price_lamports:,} lamports)")
    
    print(f"\n  • API Helius: {Fore.GREEN + 'Configurada ✅' if helius_api_key else Fore.RED + 'Não configurada ❌'}")
    print("\n" + "=" * 80)
    
    # Inicializa a lista de pools para monitoramento
    pool_configs = []
    
    # Obtém a lista de tokens a serem monitorados a partir do config.json
    tokens_to_monitor = trade_config.get("tokens_to_monitor", [])
    if not tokens_to_monitor:
        print(format_error("Nenhum token configurado para monitoramento. Adicione tokens em 'tokens_to_monitor' no config.json"))
        await telegram.send_error_notification("Nenhum token configurado para monitoramento em config.json. O bot não pode operar sem tokens para monitorar.")
        return
    
    print(f"\n{format_header(f' CARREGANDO INFORMAÇÕES DE {len(tokens_to_monitor)} TOKENS ')}")
    
    # Processa cada token configurado
    for token_config in tokens_to_monitor:
        if not token_config.get("out_token"):
            print(format_warning(f"Token ignorado: 'out_token' não definido: {token_config}"))
            continue
        
        token_mint = token_config.get("out_token")
        
        # Obtém informações da pool via API da Raydium
        config = await build_pool_config_from_token(token_config, trade_config)
        if config:
            pool_configs.append(config)
            print(format_success(f"Pool configurada: {format_pool(config['token_pair'])} | Reserva: {format_sol(config.get('sol_reserve', 0))}"))
        else:
            print(format_error(f"Não foi possível configurar a pool para o token: {token_mint}"))
    
    # Verifica se há pools para monitorar
    if not pool_configs:
        error_msg = "Nenhuma pool válida para monitorar. Verifique a configuração dos tokens e a conectividade com a API."
        print(format_error(error_msg + " Reiniciando..."))
        await telegram.send_error_notification(error_msg)
        await asyncio.sleep(10)
        return
        
    # Log final das pools selecionadas
    print(f"\n{format_header(f' {len(pool_configs)} POOLS CONFIGURADAS PARA MONITORAMENTO ')}")
    
    # Ordenar pools por reserva para visualização mais clara
    sorted_pools = sorted(pool_configs, key=lambda x: x.get('sol_reserve', 0), reverse=True)
    
    for i, cfg in enumerate(sorted_pools, 1):
        print(f"  {i:2d}. {format_pool(cfg['token_pair'])} | Reserva: {format_sol(cfg.get('sol_reserve', 0))}")
    print()

    # Log para arquivo apenas
    for cfg in pool_configs:
        logging.info("Monitorando pool: %s | Endereço: %s", cfg['token_pair'], cfg['pair_address'])

    # Notifica o início do bot via Telegram
    await telegram.send_bot_status(
        'iniciado',
        len(pool_configs),
        sorted_pools[:5],  # Envia as 5 maiores pools
        trade_config       # Envia as configurações de trading
    )

    while True:
        try:
            async with http() as p:
                from bxsolana import trader_api
                api = await trader_api(p)
                # Log apenas para arquivo, não exibir no console
                logging.info("Bot Multi-Pool iniciado!")
                print(format_header(" BOT INICIADO E PRONTO PARA OPERAR ").center(80))
                while True:
                    # Envia um resumo periódico do monitoramento
                    current_time = time.time()
                    current_datetime = datetime.now()
                    
                    # Verificar se é hora de enviar resumo diário (a cada 24h às 00:00)
                    if current_datetime.day != last_daily_summary.day:
                        await telegram.send_daily_summary(pool_configs, daily_stats)
                        last_daily_summary = current_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
                        # Resetar estatísticas diárias
                        daily_stats = {"daily_trades": 0, "daily_profit": 0}
                    
                    # Enviar resumo periódico
                    if current_time - last_summary_time >= summary_interval:
                        active_pools = [
                            {
                                'token_pair': cfg['token_pair'],
                                'sol_reserve': cfg.get('sol_reserve', 0)
                            }
                            for cfg in pool_configs
                        ]
                        # Ordena por reserva de SOL
                        active_pools.sort(key=lambda x: x['sol_reserve'], reverse=True)
                        
                        await telegram.send_bot_status(
                            'monitorando',
                            len(pool_configs),
                            active_pools,
                            trade_config
                        )
                        last_summary_time = current_time
                    
                    tasks = [asyncio.create_task(monitor_pool(config)) for config in pool_configs]
                    print(format_info(f"Monitorando {len(pool_configs)} pools simultaneamente..."))
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for t in pending:
                        t.cancel()
                    selected_config = None
                    for task in done:
                        result = task.result()
                        if result is not None:
                            selected_config = result
                            break
                    if selected_config is None:
                        print(format_warning("Nenhuma pool disparou a condição. Reiniciando ciclo..."))
                        continue
                    
                    print("\n" + "=" * 80)
                    print(format_header(f" EXECUTANDO TRADE PARA {selected_config['token_pair']} ").center(80))
                    print("=" * 80)
                    
                    # Adiciona as configurações de compra e venda ao selected_config
                    selected_config["buy_settings"] = trade_config.get("buy_settings", {})
                    selected_config["sell_settings"] = trade_config.get("sell_settings", {})
                    
                    trader = RaydiumTrader(api, selected_config)
                    print(format_info("Iniciando operação de compra..."))
                    buy_sig = await trader.execute_buy()
                    if buy_sig:
                        print(format_success(f"COMPRA executada para {selected_config['token_pair']} (tx: {Fore.CYAN}{buy_sig}{Style.RESET_ALL})"))
                        print(f"  • Verificar em: {Fore.CYAN}https://solscan.io/tx/{buy_sig}{Style.RESET_ALL}")
                        # Log para arquivo
                        logging.info("COMPRA executada para %s, assinatura: %s", 
                                    selected_config['token_pair'], buy_sig)
                        selected_config["buy_signature"] = buy_sig
                        
                        # Iniciar a obtenção do timestamp em uma tarefa separada para não bloquear o fluxo
                        async def get_blockchain_timestamp():
                            helius_api_key = os.getenv("HELIUS_API_KEY", "")
                            if helius_api_key:
                                print(format_info("Obtendo timestamp da blockchain em segundo plano..."))
                                tx_time = await get_transaction_time(buy_sig, helius_api_key)
                                if tx_time > 0:
                                    drop_time = selected_config.get("drop_timestamp", 0)
                                    blockchain_execution_time = tx_time - int(drop_time)
                                    selected_config["blockchain_execution_time"] = blockchain_execution_time
                                    print(format_info(f"✓ Timestamp da blockchain obtido com sucesso"))
                            return
                        
                        # Executa a obtenção do timestamp em segundo plano sem bloquear o fluxo principal
                        timestamp_task = asyncio.create_task(get_blockchain_timestamp())
                        
                        # Envia notificação de compra para o Telegram (sem incluir o tempo de execução)
                        await telegram.send_trade_notification(
                            "COMPRA", 
                            selected_config['token_pair'].split('/')[0], 
                            selected_config.get('bought_amount', 0), 
                            selected_config.get('bought_price', 0),
                            selected_config['token_pair'],
                            buy_sig,  # Adiciona a assinatura da transação
                            {
                                "tvl": selected_config.get("tvl", 0),
                                "volume_24h": selected_config.get("volume_24h", 0),
                                "sol_reserve": selected_config.get("sol_reserve", 0)
                            }
                        )
                        
                        # Usa o preço de compra registrado como referência para monitorar lucro
                        bought_price = selected_config.get("bought_price")
                        bought_amount = selected_config.get("bought_amount", 0)
                        
                        if not bought_price:
                            print(format_warning("Preço de compra não registrado corretamente"))
                            continue
                            
                        print(format_info(f"Compra: {format_sol(selected_config['trade_amount'])} por {format_price(bought_price)} | Quantidade: {Fore.WHITE}{bought_amount:,.6f} tokens"))

                        try:
                            # Obtém o timeout em minutos do config.json ou usa 5 minutos como padrão
                            timeout_minutes = trade_config.get("profit_timeout_minutes", 5)
                            timeout_seconds = timeout_minutes * 60
                            
                            # Adiciona o timeout na configuração da pool para uso na função monitor_profit
                            selected_config["profit_timeout_minutes"] = timeout_minutes
                            
                            print(format_info(f"Iniciando monitoramento de lucro (timeout: {timeout_minutes} minutos)..."))
                            profit_config = await asyncio.wait_for(
                                monitor_profit(selected_config, bought_price),
                                timeout=timeout_seconds
                            )
                        except asyncio.TimeoutError:
                            print(format_warning(f"{timeout_minutes} minutos se passaram sem atingir a meta de lucro; executando venda com o preço atual"))
                            profit_config = selected_config
                        
                        if profit_config is not None:
                            # Executa o ciclo de venda
                            sell_sig = None
                            max_sell_attempts = 20
                            await asyncio.sleep(2)
                            
                            print(format_info("Iniciando operação de venda..."))
                            
                            for attempt in range(max_sell_attempts):
                                if attempt > 0:
                                    print(format_warning(f"Tentativa {attempt+1}/{max_sell_attempts} de venda..."))
                                
                                sell_sig = await trader.execute_sell()
                                if sell_sig:
                                    print(format_success(f"VENDA executada para {selected_config['token_pair']} (tx: {Fore.CYAN}{sell_sig}{Style.RESET_ALL})"))
                                    print(f"  • Verificar em: {Fore.CYAN}https://solscan.io/tx/{sell_sig}{Style.RESET_ALL}")
                                    # Log para arquivo
                                    logging.info("VENDA executada para %s, assinatura: %s", 
                                                selected_config['token_pair'], sell_sig)
                                    
                                    # Confirmação adicional por api
                                    print(format_info("Verificando confirmação final da transação de venda..."))
                                    helius_api_key = os.getenv("HELIUS_API_KEY", "")
                                    tx_confirmed = False
                                    
                                    # Espere um pouco para garantir que a transação esteja confirmada
                                    await asyncio.sleep(3)
                                    
                                    if helius_api_key:
                                        # Verificar o status da transação de forma mais detalhada
                                        print(format_info("Consultando status detalhado da transação..."))
                                        
                                        # Verificação explícita para erros de IllegalOwner
                                        url = f"https://mainnet.helius-rpc.com/?api-key={helius_api_key}"
                                        payload = {
                                            "jsonrpc": "2.0",
                                            "id": 1,
                                            "method": "getTransaction",
                                            "params": [sell_sig, {"commitment": "confirmed", "encoding": "json"}]
                                        }
                                        
                                        # Consulta manual para verificar erros específicos
                                        error_detected = False
                                        async with aiohttp.ClientSession() as session:
                                            async with session.post(url, json=payload) as response:
                                                data = await response.json()
                                                result = data.get("result")
                                                
                                                if result and result.get("meta"):
                                                    meta = result.get("meta")
                                                    if meta.get("err"):
                                                        error_detected = True
                                                        error_detail = str(meta.get("err"))
                                                        print(format_error(f"Erro na transação detectado: {error_detail}"))
                                                        
                                                        if "IllegalOwner" in error_detail:
                                                            print(format_error("Erro de IllegalOwner detectado. A venda falhou."))
                                        
                                        if error_detected:
                                            tx_confirmed = False
                                        else:
                                            # Usar o verify_transaction_status para uma verificação padrão
                                            tx_confirmed = await verify_transaction_status(sell_sig, max_attempts=10, sleep_time=2)
                                    else:
                                        print(format_warning("API Key do Helius não configurada. Não é possível verificar detalhes da transação."))
                                        # Mesmo sem API key, tentamos verificar com a função básica
                                        tx_confirmed = await verify_transaction_status(sell_sig, max_attempts=10, sleep_time=2)
                                    
                                    if not tx_confirmed:
                                        print(format_warning("Transação de venda enviada mas não foi possível confirmar seu sucesso."))
                                        print(format_info("Tentando nova venda após 5 segundos..."))
                                        await asyncio.sleep(5)
                                        continue
                                    
                                    # Envia notificação de venda para o Telegram
                                    await telegram.send_trade_notification(
                                        "VENDA", 
                                        selected_config['token_pair'].split('/')[0], 
                                        bought_amount, 
                                        profit_config.get('current_price', bought_price),
                                        selected_config['token_pair'],
                                        sell_sig,  # Adiciona a assinatura da transação
                                        {
                                            "tvl": selected_config.get("tvl", 0),
                                            "volume_24h": selected_config.get("volume_24h", 0),
                                            "sol_reserve": selected_config.get("sol_reserve", 0)
                                        }
                                    )
                                    
                                    # Calcula lucro
                                    bought_price = selected_config.get('bought_price', 0)
                                    bought_amount = selected_config.get('bought_amount', 0)
                                    current_price = profit_config.get('current_price', bought_price)
                                    profit_percentage = ((current_price - bought_price) / bought_price) * 100 if bought_price > 0 else 0
                                    profit_amount = (current_price - bought_price) * bought_amount if bought_price > 0 and bought_amount > 0 else 0
                                    
                                    # Atualiza estatísticas diárias
                                    daily_stats["daily_trades"] += 1
                                    daily_stats["daily_profit"] += profit_amount

                                    # Exibe resultado do trade
                                    print("\n" + format_header(" RESULTADO DO TRADE ").center(80))
                                    print(f"  • Token: {Fore.YELLOW}{selected_config['token_pair'].split('/')[0]}{Style.RESET_ALL}")
                                    print(f"  • Quantidade: {Fore.WHITE}{bought_amount:,.4f} tokens{Style.RESET_ALL}")
                                    print(f"  • Preço de compra: {format_price(bought_price)}")
                                    print(f"  • Preço de venda: {format_price(current_price)}")
                                    print(f"  • Lucro percentual: {format_percent(profit_percentage)}")
                                    print(f"  • Lucro em SOL: {format_sol(profit_amount)}")
                                    
                                    # Exibe tempo de execução
                                    start_time_str = datetime.fromtimestamp(selected_config.get("drop_timestamp", 0)).strftime("%H:%M:%S.%f")[:-3]
                                    end_time_str = datetime.now().strftime("%H:%M:%S")
                                    time_elapsed = time.time() - selected_config.get("drop_timestamp", 0)
                                    print("\n" + format_subheader(" TEMPO DE EXECUÇÃO ").center(80))
                                    print(f"  • Detecção da queda: {Fore.CYAN}{start_time_str}{Style.RESET_ALL}")
                                    print(f"  • Finalização: {Fore.CYAN}{end_time_str}{Style.RESET_ALL}")
                                    print(f"  • Tempo total (ciclo completo): {Fore.GREEN if time_elapsed > 0 else Fore.RED}{time_elapsed:.2f} segundos{Style.RESET_ALL}")
                                    
                                    # Exibe tempos detalhados de execução se disponíveis
                                    if "submit_time" in selected_config:
                                        submit_time = selected_config["submit_time"]
                                        print(f"  • Tempo até envio da transação: {Fore.YELLOW}{submit_time:.2f} segundos{Style.RESET_ALL}")
                                    
                                    if "blockchain_execution_time" in selected_config:
                                        blockchain_time = selected_config["blockchain_execution_time"]
                                        print(f"  • Tempo de execução da compra: {Fore.CYAN}{blockchain_time} segundos{Style.RESET_ALL}")
                                    
                                    # Envio de notificação de lucro
                                    token_name = selected_config['token_pair'].split('/')[0]
                                    
                                    # Prepara dados adicionais incluindo o tempo de execução da compra
                                    trade_data = {
                                        "quantity": bought_amount
                                    }
                                    
                                    # Adiciona o tempo até o envio da transação se disponível
                                    if "submit_time" in selected_config:
                                        trade_data["submit_time"] = selected_config["submit_time"]
                                    
                                    # Adiciona o tempo de execução da compra se disponível
                                    if "blockchain_execution_time" in selected_config:
                                        trade_data["buy_execution_time"] = selected_config["blockchain_execution_time"]
                                    
                                    await telegram.send_profit_notification(
                                        token_name,
                                        profit_percentage,
                                        profit_amount,
                                        buy_price=bought_price,
                                        sell_price=current_price,
                                        time_elapsed=time_elapsed,
                                        trade_data=trade_data
                                    )
                                    
                                    break
                            else:
                                # Esse bloco é executado se o loop terminar sem um break (ou seja, todas as tentativas falharam)
                                print(format_error(f"Todas as {max_sell_attempts} tentativas de venda falharam."))
                                # Enviar notificação de erro para o Telegram
                                await telegram.send_error_notification(
                                    f"Falha na venda de {selected_config['token_pair'].split('/')[0]} após {max_sell_attempts} tentativas",
                                    error_type="Transação",
                                    suggestions=[
                                        "Verificar saldo do token",
                                        "Verificar conexão com a rede Solana",
                                        "Verificar se a pool ainda está ativa"
                                    ]
                                )
                    else:
                        print(format_error(f"COMPRA falhou para {selected_config['token_pair']}"))
                        await asyncio.sleep(1)
                    
                    print("\n" + format_header(" REINICIANDO CICLO DE MONITORAMENTO ").center(80))
                    await asyncio.sleep(1)
        except Exception as e:
            error_traceback = traceback.format_exc()
            logging.error("Erro na conexão gRPC: %s. Tentando reconectar em 5 segundos...\n%s", e, error_traceback)
            print(format_error(f"Erro na conexão gRPC: {e}\nTentando reconectar em 5 segundos..."))
            
            # Envia notificação de erro com mais detalhes
            await telegram.send_error_notification(
                f"Erro na conexão gRPC: {str(e)}",
                error_type="Conexão",
                suggestions=[
                    "Verifique se o servidor gRPC está online",
                    "Verifique se as credenciais de API estão corretas",
                    "Aguarde alguns minutos e tente novamente"
                ]
            )
            
            await asyncio.sleep(5)

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print(format_header(" BOT DE TRADING RAYDIUM - MULTI-POOL ").center(80))
    print("=" * 80)
    print(format_info("Iniciando o bot..."))
    notifier = None
    try:
        # Inicializar o notificador fora do central_manager para podermos usá-lo nos tratamentos de erro
        notifier = TelegramNotifier()
        asyncio.run(central_manager())
    except KeyboardInterrupt:
        print(format_warning("\nOperação interrompida pelo usuário. Encerrando..."))
        if notifier:
            asyncio.run(notifier.send_bot_status('parado', None, None))
    except Exception as e:
        print(format_error(f"Erro fatal: {e}"))
        logging.exception("Erro fatal")
        if notifier:
            error_traceback = traceback.format_exc()
            error_message = f"{str(e)}\n\nDetalhes técnicos:\n{error_traceback[-300:]}"  # Últimos 300 caracteres do traceback
            asyncio.run(notifier.send_error_notification(error_message))
    finally:
        print(format_info("Bot encerrado."))
        print("=" * 80)
