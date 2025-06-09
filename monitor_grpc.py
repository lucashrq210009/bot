import asyncio
import grpc
import base58
import logging
from typing import AsyncIterator
from colorama import Fore, Style, init

# Inicializa o colorama
init(autoreset=True)

import geyser_pb2
import geyser_pb2_grpc

# Configuração simplificada de logging - apenas para arquivo, não para console
logger = logging.getLogger("monitor_grpc")
logger.setLevel(logging.INFO)

# Função para formatar mensagens de pool
def format_pool_msg(pool_name, message):
    return f"{Fore.YELLOW}[{pool_name}]{Style.RESET_ALL} {message}"

SOL_MINT = "So11111111111111111111111111111111111111112"

class TritonAuthMetadataPlugin(grpc.AuthMetadataPlugin):
    """
    Plugin para enviar o x-token em cada chamada gRPC.
    """
    def __init__(self, x_token: str):
        self.x_token = x_token

    def __call__(self, context, callback):
        metadata = (("x-token", self.x_token),)
        callback(metadata, None)

class PriceMonitorGRPC:
    def __init__(self, config: dict, rpc_fqdn: str, x_token: str):
        """
        :param config: Configurações da pool (do config.json). Se "sol_in_quote" for true, 
                       o SOL ficará no denominador (vault quote). Se não, e se "swap_vaults" estiver ativo,
                       a troca dos vaults será forçada.
        :param rpc_fqdn: Domínio completo do nó gRPC.
        :param x_token: Token para autenticação nas chamadas gRPC.
        """
        self.config = config
        self.rpc_fqdn = rpc_fqdn
        self.x_token = x_token
        self.channel = None
        self.stub = None

        # Vaults serão identificados uma única vez
        self.base_vault = None
        self.quote_vault = None

        # Decimais extraídos da conta de liquidez
        self.base_decimals = None
        self.quote_decimals = None

        self.base_balance = None
        self.quote_balance = None

        # Fila para atualizações
        self._update_queue = asyncio.Queue()
        self._subscription_tasks = []

    async def __aenter__(self):
        ssl_creds = grpc.ssl_channel_credentials()
        call_creds = grpc.metadata_call_credentials(TritonAuthMetadataPlugin(self.x_token))
        composite_creds = grpc.composite_channel_credentials(ssl_creds, call_creds)
        self.channel = grpc.aio.secure_channel(self.rpc_fqdn, composite_creds)
        self.stub = geyser_pb2_grpc.GeyserStub(self.channel)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        for task in self._subscription_tasks:
            task.cancel()
        await self.channel.close()

    def decode_liquidity_state(self, data: bytes) -> dict:
        try:
            decoded = data
            base_decimal = int.from_bytes(decoded[32:40], 'little')
            quote_decimal = int.from_bytes(decoded[40:48], 'little')
            # Verifica se os decimais estão dentro de um intervalo plausível (ex.: entre 1 e 30)
            if not (1 <= base_decimal <= 30 and 1 <= quote_decimal <= 30):
                logger.info(format_pool_msg(self.config.get("token_pair"), "Ignorando pool CPMM (decimais fora do esperado: base=%d, quote=%d)"), base_decimal, quote_decimal)
                return {}
            base_vault_bytes = decoded[336:368]
            quote_vault_bytes = decoded[368:400]
            base_vault = base58.b58encode(base_vault_bytes).decode('utf-8')
            quote_vault = base58.b58encode(quote_vault_bytes).decode('utf-8')
            return {
                "base_decimal": base_decimal,
                "quote_decimal": quote_decimal,
                "base_vault": base_vault,
                "quote_vault": quote_vault
            }
        except Exception as e:
            logger.error(format_pool_msg(self.config.get("token_pair"), "Erro ao decodificar liquidity state: %s"), e)
            return {}

    async def subscribe_account(self, account_address: str) -> AsyncIterator[geyser_pb2.SubscribeUpdate]:
        from geyser_pb2 import SubscribeRequest, SubscribeRequestFilterAccounts, CommitmentLevel
        filter_accounts = SubscribeRequestFilterAccounts()
        filter_accounts.account.extend([account_address])
        subscribe_request = SubscribeRequest(
            accounts={"accountSubscribe": filter_accounts},
            accounts_data_slice=[],
            commitment=CommitmentLevel.PROCESSED
        )
        async def request_iterator():
            yield subscribe_request
        response_iterator = self.stub.Subscribe(request_iterator())
        return response_iterator

    async def init_vaults(self):
        pool_address = self.config["pair_address"]
        token_pair = self.config.get("token_pair", "N/A")
        logger.info(format_pool_msg(token_pair, "Subscrevendo a pool: %s"), pool_address)
        pool_subscription = await self.subscribe_account(pool_address)
        async for update in pool_subscription:
            if update.HasField("account"):
                account_info = update.account.account
                if hasattr(account_info, "data") and account_info.data:
                    state = self.decode_liquidity_state(account_info.data)
                    if state:
                        base_vault = state.get("base_vault")
                        quote_vault = state.get("quote_vault")
                        base_decimals = state.get("base_decimal")
                        quote_decimals = state.get("quote_decimal")
                        
                        # Para pares com WSOL, usamos a configuração sol_in_quote para determinar
                        # a ordem correta dos vaults
                        if self.config.get("sol_in_quote", False):
                            # Se sol_in_quote é true, mantemos a ordem original
                            self.base_vault = base_vault
                            self.quote_vault = quote_vault
                            self.base_decimals = base_decimals
                            self.quote_decimals = quote_decimals
                        else:
                            # Se sol_in_quote é false, trocamos os vaults
                            self.base_vault = quote_vault
                            self.quote_vault = base_vault
                            self.base_decimals = quote_decimals
                            self.quote_decimals = base_decimals
                            
                        logger.info(
                            format_pool_msg(token_pair, "Vaults identificados: base=%s, quote=%s | Decimais: base=%d, quote=%d"),
                            self.base_vault, self.quote_vault, self.base_decimals, self.quote_decimals
                        )
                        break
        if not self.base_vault or not self.quote_vault:
            logger.error(format_pool_msg(token_pair, "Não foi possível identificar os vaults a partir da pool."))
            raise Exception("Falha na identificação dos vaults")

    async def start_update_tasks(self):
        token_pair = self.config.get("token_pair", "N/A")
        scale_base = 10 ** self.base_decimals if self.base_decimals is not None else 1e9
        scale_quote = 10 ** self.quote_decimals if self.quote_decimals is not None else 1e6

        async def process_subscription(account_address: str, vault_type: str, scale: float):
            subscription = await self.subscribe_account(account_address)
            async for update in subscription:
                if update.HasField("account"):
                    account_info = update.account.account
                    if hasattr(account_info, "data") and account_info.data:
                        try:
                            decoded = account_info.data
                            balance_raw = int.from_bytes(decoded[64:72], "little")
                            balance = float(balance_raw) / scale
                            await self._update_queue.put((vault_type, balance))
                        except Exception as e:
                            logger.error(format_pool_msg(token_pair, "Erro ao processar atualização do %s: %s"), vault_type, e)
        task_base = asyncio.create_task(process_subscription(self.base_vault, "base", scale_base))
        task_quote = asyncio.create_task(process_subscription(self.quote_vault, "quote", scale_quote))
        self._subscription_tasks.extend([task_base, task_quote])

    async def stream_price(self) -> AsyncIterator[float]:
        token_pair = self.config.get("token_pair", "N/A")
        if self.base_vault is None or self.quote_vault is None:
            await self.init_vaults()
            await self.start_update_tasks()
        last_logged_price = None
        PRICE_CHANGE_THRESHOLD = 0.0001
        while True:
            vault_type, balance = await self._update_queue.get()
            if vault_type == "base":
                self.base_balance = balance
            elif vault_type == "quote":
                self.quote_balance = balance
            if self.base_balance is not None and self.quote_balance is not None and self.quote_balance != 0:
                price = self.quote_balance / self.base_balance
                if last_logged_price is None or abs(price - last_logged_price) / last_logged_price > PRICE_CHANGE_THRESHOLD:
                    logger.info(format_pool_msg(token_pair, "Novo preço calculado: %.10f"), price)
                    last_logged_price = price
                yield price
