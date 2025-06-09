import json
import os
import time
import asyncio
import aiohttp
from bxsolana_trader_proto import api as proto
from bxsolana.transaction import signing
from websockets.exceptions import ConnectionClosedError
from asyncio import IncompleteReadError
from colorama import Fore, Back, Style

# Importando formatadores
from formatters import format_info, format_success, format_error, format_warning, format_price, format_sol

async def get_token_balance(owner: str, token_mint: str) -> float:
    """
    Consulta o endpoint getTokenAccountsByOwner do Helius para obter o saldo atualizado
    do token especificado, retornando o valor em uiAmount.
    """
    api_key = os.getenv("HELIUS_API_KEY", "")
    if not api_key:
        print(format_error("API Key do Helius não encontrada no ambiente (.env)"))
        return 0.0
    url = f"https://mainnet.helius-rpc.com/?api-key={api_key}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            owner,
            {"mint": token_mint},
            {"encoding": "jsonParsed", "commitment": "processed"}
        ]
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            data = await response.json()
            accounts = data.get("result", {}).get("value", [])
            if accounts:
                info = accounts[0]["account"]["data"]["parsed"]["info"]
                return info["tokenAmount"]["uiAmount"]
    return 0.0

async def verify_transaction_status(signature: str, max_attempts: int = 10, sleep_time: int = 2) -> bool:
    """
    Verifica o status de uma transação na blockchain Solana.
    
    Args:
        signature: Assinatura da transação a ser verificada
        max_attempts: Número máximo de tentativas de verificação
        sleep_time: Tempo de espera entre as tentativas em segundos
        
    Returns:
        bool: True se a transação foi confirmada, False caso contrário
    """
    api_key = os.getenv("HELIUS_API_KEY", "")
    if not api_key:
        print(format_error("API Key do Helius não encontrada no ambiente (.env)"))
        return False
        
    url = f"https://mainnet.helius-rpc.com/?api-key={api_key}"
    
    for attempt in range(max_attempts):
        try:
            await asyncio.sleep(sleep_time)
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [signature, {"commitment": "confirmed"}]
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    data = await response.json()
                    result = data.get("result")
                    
                    if result:
                        # Se temos um resultado, verificamos o status
                        if result.get("meta") is not None:
                            meta = result.get("meta", {})
                            
                            # Verificar se há erro na transação
                            err = meta.get("err")
                            if err is not None:
                                # Verifica erros específicos
                                if isinstance(err, dict) and "InstructionError" in str(err):
                                    error_detail = str(err)
                                    print(format_error(f"Erro de instrução na transação: {error_detail}"))
                                    
                                    # Detectar erro específico do IllegalOwner
                                    if "IllegalOwner" in error_detail:
                                        print(format_error("Erro de IllegalOwner detectado. Problemas com ATA ou permissões."))
                                    return False
                                else:
                                    print(format_error(f"Transação falhou: {err}"))
                                    return False
                            
                            # Se não há erro e temos o slot, consideramos confirmada
                            if result.get("slot") and meta.get("err") is None:
                                return True
                            
                            # Formato antigo de status
                            status_info = meta.get("status", {})
                            if isinstance(status_info, dict):
                                if "Ok" in status_info:
                                    return True
                                elif "Err" in status_info:
                                    print(format_error(f"Transação falhou: {status_info.get('Err')}"))
                                    return False
                    
                    if attempt + 1 < max_attempts:
                        print(f"{Fore.CYAN}⏳ Verificando transação... ({attempt+1}/{max_attempts}){Style.RESET_ALL}")
                    
        except Exception as e:
            print(format_warning(f"Erro ao verificar transação (tentativa {attempt+1}): {str(e)}"))
    
    # Se chegamos aqui, atingimos o número máximo de tentativas sem confirmação
    return False

async def get_transaction_time(signature: str, api_key: str) -> int:
    """
    Consulta o endpoint getTransaction para obter o blockTime (timestamp Unix)
    da transação finalizada, utilizando o commitment "finalized".
    Se o blockTime não estiver disponível, retorna 0.
    """
    if not api_key:
        print(format_error("API Key do Helius não fornecida"))
        return 0
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

class RaydiumTrader:
    def __init__(self, api, config):
        """
        :param api: Instância da API obtida via trader_api(provider)
        :param config: Configurações do bot (carregadas do config.json).
                       Também espera que "drop_timestamp" esteja definido quando a queda for identificada.
        """
        self.api = api
        self.config = config

    async def custom_submit(self, tx_messages, **submit_params):
        """
        Submete transações utilizando o endpoint 'submit', passando os parâmetros de submissão.

        Parâmetros padrão (para compra):
          - skip_pre_flight: True
          - front_running_protection: True
          - fast_best_effort: True
          - use_staked_rpcs: False

        Para venda, você pode sobrescrever esses valores, por exemplo:
          front_running_protection=False, fast_best_effort=False, use_staked_rpcs=True

        OBS: O parâmetro 'use_staked_rpcs' será definido no objeto PostSubmitRequest via setattr apenas se for True.
        """
        defaults = {
            "skip_pre_flight": True,
            "front_running_protection": True,
            "fast_best_effort": True,
            "use_staked_rpcs": False
        }
        merged_params = {**defaults, **submit_params}
        pk = self.api.require_private_key()
        signatures = []
        for tx in tx_messages:
            if isinstance(tx, str):
                tx_message_obj = proto.TransactionMessage(content=tx, is_cleanup=False)
            else:
                tx_message_obj = tx
            signed_tx_message = signing.sign_tx_message_with_private_key(tx_message_obj, pk)
            request = proto.PostSubmitRequest(
                transaction=signed_tx_message,
                skip_pre_flight=merged_params["skip_pre_flight"],
                front_running_protection=merged_params["front_running_protection"],
                fast_best_effort=merged_params["fast_best_effort"]
            )
            if merged_params["use_staked_rpcs"]:
                setattr(request, "useStakedRPCs", merged_params["use_staked_rpcs"])
            result = await self.api.post_submit(post_submit_request=request)
            signatures.append(result.signature)
        return signatures

    async def execute_buy(self):
        """
        Executa um swap de compra utilizando o endpoint raydium_swap.
        Após a submissão, calcula e exibe o tempo decorrido desde a detecção da queda até receber a resposta do submit.
        Armazena a assinatura da compra para ser utilizada após o ciclo de venda.
        """
        # Obtém as configurações específicas de compra ou usa valores padrão
        buy_settings = self.config.get("buy_settings", {})
        
        # Converte SOL para lamports (1 SOL = 1,000,000,000 lamports)
        LAMPORTS_PER_SOL = 1_000_000_000
        
        # Obter valores em SOL e converter para lamports
        compute_price_sol = buy_settings.get("compute_price_sol", 0.001)
        priority_fee_sol = buy_settings.get("priority_fee_sol", 0.001)
        
        # Converter para lamports
        compute_price = int(compute_price_sol * LAMPORTS_PER_SOL)
        priority_fee = int(priority_fee_sol * LAMPORTS_PER_SOL)
        
        # Fallback para valores em lamports diretos, se disponíveis
        if compute_price == 0:
            compute_price = buy_settings.get("compute_price", 1_000_000)
        if priority_fee == 0:
            priority_fee = buy_settings.get("priority_fee", 1_000_000)
        
        print(f"\n{Fore.WHITE}{Back.BLUE} INICIANDO COMPRA {Style.RESET_ALL}")
        print(f"• Compute Price: {format_sol(compute_price_sol)}")
        print(f"• Priority Fee: {format_sol(priority_fee_sol)}")
        
        request = proto.PostRaydiumSwapRequest(
            owner_address=self.config["owner_address"],
            in_token=self.config["in_token"],
            out_token=self.config["out_token"],
            in_amount=self.config["trade_amount"],
            slippage=self.config["slippage"],
            compute_limit=1400000,
            compute_price=compute_price,
            tip=priority_fee
        )
        try:
            swap_response = await self.api.post_raydium_swap(post_raydium_swap_request=request)
            unsigned_tx = swap_response.transactions[0].content
            if not unsigned_tx:
                print(format_error("Transação unsigned de compra está vazia"))
                return None

            print(format_info("Enviando transação para a blockchain..."))
            signatures = await self.custom_submit([unsigned_tx])
            if signatures:
                elapsed_submit = time.time() - self.config["drop_timestamp"]
                print(f"{Fore.YELLOW}⏱ Tempo de resposta: {elapsed_submit:.2f} segundos{Style.RESET_ALL}")
                
                # Armazena o tempo até o envio da transação para uso posterior
                self.config["submit_time"] = elapsed_submit
                
                # Verifica confirmação da transação
                signature = signatures[0]
                
                # Exibe assinatura formatada
                short_sig = signature[:8] + "..." + signature[-8:]
                print(f"• Assinatura: {Fore.CYAN}{short_sig}{Style.RESET_ALL}")
                
                print(format_info("Verificando confirmação na blockchain..."))
                confirmed = await verify_transaction_status(signature)
                
                if not confirmed:
                    print(format_warning("Transação enviada mas aguardando confirmação"))
                    print(f"• Verificar em: {Fore.CYAN}https://solscan.io/tx/{signature}{Style.RESET_ALL}")
                
                # Armazena a assinatura da compra para consulta posterior
                self.config["buy_signature"] = signature
                await asyncio.sleep(2)
                
                # Obtém o saldo após a compra
                bought_amount = await get_token_balance(self.config["owner_address"], self.config["out_token"])
                if bought_amount is None or bought_amount <= 0:
                    print(format_error("Não foi possível obter o saldo após a compra"))
                    return signature
                
                # Calcula o preço de compra
                trade_amount = self.config["trade_amount"]
                buy_price = trade_amount / bought_amount
                self.config["bought_amount"] = bought_amount
                self.config["bought_price"] = buy_price
                
                # Exibe informações da compra
                print(f"\n{Fore.WHITE}{Back.CYAN} DETALHES DA COMPRA {Style.RESET_ALL}")
                print(f"• Quantidade: {Fore.WHITE}{bought_amount:.6f} tokens{Style.RESET_ALL}")
                print(f"• Preço: {format_price(buy_price)}")
                
                if confirmed:
                    print(format_success("Transação confirmada com sucesso na blockchain"))
                
                return signature
            return None
        except (ConnectionClosedError, IncompleteReadError) as e:
            print(format_error(f"Erro na execução da compra: {e}"))
            return None

    async def execute_sell(self):
        """
        Executa um swap de venda utilizando o endpoint raydium_swap.
        Os parâmetros de submissão para a venda são:
          - skipPreFlight: True
          - frontRunningProtection: False
          - fastBestEffort: False
          - useStakedRPCs: True
        """
        owner = self.config["owner_address"]
        token_mint = self.config["out_token"]
        bought_amount = await get_token_balance(owner, token_mint)
        if bought_amount is None or bought_amount <= 0:
            print(format_error("Saldo de tokens insuficiente para venda"))
            return None

        # Obtém as configurações específicas de venda ou usa valores padrão
        sell_settings = self.config.get("sell_settings", {})
        
        # Converte SOL para lamports (1 SOL = 1,000,000,000 lamports)
        LAMPORTS_PER_SOL = 1_000_000_000
        
        # Obter valores em SOL e converter para lamports
        compute_price_sol = sell_settings.get("compute_price_sol", 0.001)
        priority_fee_sol = sell_settings.get("priority_fee_sol", 0.001)
        
        # Converter para lamports
        compute_price = int(compute_price_sol * LAMPORTS_PER_SOL)
        priority_fee = int(priority_fee_sol * LAMPORTS_PER_SOL)
        
        # Fallback para valores em lamports diretos, se disponíveis
        if compute_price == 0:
            compute_price = sell_settings.get("compute_price", 1_000_000)
        if priority_fee == 0:
            priority_fee = sell_settings.get("priority_fee", 1_000_000)
        
        print(f"\n{Fore.WHITE}{Back.BLUE} INICIANDO VENDA {Style.RESET_ALL}")
        print(f"• Compute Price: {format_sol(compute_price_sol)}")
        print(f"• Priority Fee: {format_sol(priority_fee_sol)}")
        print(f"• Quantidade: {Fore.WHITE}{bought_amount:.6f} tokens{Style.RESET_ALL}")
        
        # Aumentar o compute_limit para operações com ATAs
        compute_limit = 1400000  # Aumentado de 1400000
        
        request = proto.PostRaydiumSwapRequest(
            owner_address=self.config["owner_address"],
            in_token=self.config["out_token"],
            out_token=self.config["in_token"],
            in_amount=bought_amount,
            slippage=self.config["slippage"],
            compute_limit=compute_limit,
            compute_price=compute_price,
            tip=priority_fee,
        )
        
        try:
            print(format_info("Solicitando construção de transação de venda..."))
            swap_response = await self.api.post_raydium_swap(post_raydium_swap_request=request)
            tx_entry = swap_response.transactions[0]
            if hasattr(tx_entry, "error") and tx_entry.error:
                print(format_error(f"Erro na transação de venda: {tx_entry.error}"))
                return None

            unsigned_tx = tx_entry.content
            if not unsigned_tx:
                print(format_error("Transação unsigned de venda está vazia"))
                return None

            print(format_info("Enviando transação para a blockchain..."))
            signatures = await self.custom_submit(
                [unsigned_tx],
                front_running_protection=False,
                fast_best_effort=False,
                use_staked_rpcs=True
            )
            
            if signatures:
                signature = signatures[0]
                
                # Exibe assinatura formatada
                short_sig = signature[:8] + "..." + signature[-8:]
                print(f"• Assinatura: {Fore.CYAN}{short_sig}{Style.RESET_ALL}")
                
                # Verifica a confirmação da transação
                try:
                    print(format_info("Verificando confirmação na blockchain..."))
                    confirmed = await verify_transaction_status(signature, max_attempts=15, sleep_time=3)
                    
                    if confirmed:
                        print(format_success("Transação confirmada com sucesso na blockchain"))
                        return signature
                    else:
                        # NÃO retorna a assinatura se a transação falhou
                        print(format_error("Transação falhou ou não foi confirmada"))
                        print(f"• Verificar em: {Fore.CYAN}https://solscan.io/tx/{signature}{Style.RESET_ALL}")
                        return None
                except Exception as e:
                    print(format_error(f"Erro ao confirmar transação: {str(e)}"))
                    return None
        except Exception as e:
            print(format_error(f"Erro durante execução da venda: {str(e)}"))
            if 'provided owner is not allowed' in str(e).lower() or 'illegalowner' in str(e).lower():
                print(format_warning("Erro na conta de token associada. Verifique se o owner_address está correto no config.json"))
                
        return None
