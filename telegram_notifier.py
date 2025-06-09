import os
import logging
import asyncio
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta
import json

# Configuração de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()

# Verificar se as variáveis de ambiente estão definidas
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


class TelegramNotifier:
    def __init__(self, token=None, chat_id=None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        
        if not self.token:
            logger.warning("Token do bot não configurado. As notificações do Telegram não serão enviadas.")
            self.enabled = False
        elif not self.chat_id:
            logger.warning("Chat ID não configurado. As notificações do Telegram não serão enviadas.")
            self.enabled = False
        else:
            self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            self.enabled = True
            logger.info("Serviço de notificações do Telegram inicializado.")
            
        # Armazenar algumas estatísticas para futuros relatórios
        self.start_time = datetime.now()
        self.trades_count = {"compras": 0, "vendas": 0}
        self.total_profit = 0.0
        self.successful_trades = 0
    
    async def get_sol_price_usd(self):
        """Obtém o preço atual do SOL em USD"""
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
            async with requests.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("solana", {}).get("usd", 0)
        except Exception as e:
            logger.error(f"Erro ao obter preço do SOL: {str(e)}")
        return None  # Retorna None se não conseguir obter o preço

    async def send_message(self, message, parse_mode='HTML'):
        """
        Envia uma mensagem para o chat configurado
        
        Args:
            message (str): Mensagem a ser enviada
            parse_mode (str): Formato de análise ('HTML' ou 'Markdown')
        
        Returns:
            bool: True se a mensagem foi enviada com sucesso, False caso contrário
        """
        if not self.enabled:
            logger.warning("Tentativa de enviar mensagem, mas o notificador está desativado.")
            return False
            
        try:
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            
            response = requests.post(self.api_url, json=payload)
            response.raise_for_status()
            
            logger.info(f"Mensagem enviada com sucesso para o chat {self.chat_id}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem pelo Telegram: {e}")
            return False
            
    async def send_trade_notification(self, action, token, amount, price, pool_name=None, signature=None, pool_data=None):
        """
        Envia uma notificação formatada de trade
        
        Args:
            action (str): Tipo de ação ('COMPRA', 'VENDA')
            token (str): Símbolo do token
            amount (float): Quantidade
            price (float): Preço
            pool_name (str, optional): Nome da pool
            signature (str, optional): Assinatura da transação
            pool_data (dict, optional): Dados adicionais da pool (TVL, volume, etc)
        """
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        # Atualiza contador de trades (apenas para uso interno)
        if action == "COMPRA":
            self.trades_count["compras"] += 1
            emoji = "🟢"
            header = f"{emoji} <b>COMPRA REALIZADA</b> {emoji}"
            value_emoji = "💸"
        else:  # VENDA
            self.trades_count["vendas"] += 1
            emoji = "🔴"
            header = f"{emoji} <b>VENDA REALIZADA</b> {emoji}"
            value_emoji = "💰"
            
        # Formata o valor com separador de milhares e 4 casas decimais
        formatted_amount = f"{amount:,.4f}".replace(",", ".")
        formatted_price = f"{price:.10f}".replace(".", ",")
        
        # Calcula valor em SOL
        sol_value = amount * price
        
        # Tenta obter o preço do SOL em USD
        sol_price_usd = await self.get_sol_price_usd()
        usd_value = ""
        if sol_price_usd:
            usd_amount = sol_value * sol_price_usd
            usd_value = f"\n• <b>Valor (USD):</b> ${usd_amount:.2f}"
        
        # Cria um bloco para os detalhes da operação
        details = (
            f"• <b>Token:</b> {token}\n"
            f"• <b>Quantidade:</b> {formatted_amount} tokens\n"
            f"• <b>Preço:</b> {value_emoji} {formatted_price} SOL\n"
            f"• <b>Valor (SOL):</b> {sol_value:.6f} SOL{usd_value}\n"
            f"• <b>Data/Hora:</b> {now}"
        )
        
        # Adiciona tempo de execução para compras se disponível
        execution_time_info = ""
        if action == "COMPRA" and pool_data and "elapsed_time" in pool_data:
            elapsed_time = pool_data.get("elapsed_time", 0)
            execution_time_info = f"\n• <b>Tempo de execução:</b> {elapsed_time:.2f} segundos"
            details += execution_time_info
        
        # Adiciona dados da pool (apenas TVL e Reserva SOL que são mais relevantes)
        pool_info = ""
        if pool_data:
            tvl = pool_data.get("tvl", 0)
            sol_reserve = pool_data.get("sol_reserve", 0)
            
            pool_info = (
                f"\n\n📊 <b>DADOS DA POOL</b>\n"
                f"• <b>TVL:</b> {tvl:.2f} SOL\n"
                f"• <b>Reserva SOL:</b> {sol_reserve:.2f} SOL"
            )
        
        # Adiciona link para a transação se disponível
        tx_link = ""
        if signature:
            tx_link = (
                f"\n\n🔍 <a href='https://solscan.io/tx/{signature}'>Ver transação</a>"
            )
        
        message = f"{header}\n\n{details}{pool_info}{tx_link}"
        
        await self.send_message(message)
        
    async def send_profit_notification(self, token, profit_percentage, profit_amount, buy_price=None, sell_price=None, time_elapsed=None, trade_data=None):
        """
        Envia uma notificação de lucro
        
        Args:
            token (str): Símbolo do token
            profit_percentage (float): Porcentagem de lucro
            profit_amount (float): Valor do lucro em SOL
            buy_price (float, optional): Preço de compra
            sell_price (float, optional): Preço de venda
            time_elapsed (float, optional): Tempo total da operação em segundos
            trade_data (dict, optional): Dados adicionais da operação (quantidade, timestamp, etc)
        """
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        # Atualiza estatísticas internas
        self.total_profit += profit_amount
        if profit_percentage > 0:
            self.successful_trades += 1
        
        # Define emojis e cabeçalho com base no resultado (lucro ou prejuízo)
        if profit_percentage > 0:
            header_emoji = "💎"
            result_emoji = "📈"
            header = f"{header_emoji} <b>LUCRO REALIZADO</b> {header_emoji}"
        else:
            header_emoji = "📉"
            result_emoji = "⚠️"
            header = f"{header_emoji} <b>PREJUÍZO REGISTRADO</b> {header_emoji}"
        
        # Formata os valores numéricos
        formatted_profit_pct = f"{profit_percentage:.2f}%".replace(".", ",")
        formatted_profit_sol = f"{profit_amount:.6f}".replace(".", ",")
        
        # Tenta obter o preço do SOL em USD
        sol_price_usd = await self.get_sol_price_usd()
        usd_value = ""
        if sol_price_usd:
            usd_amount = profit_amount * sol_price_usd
            usd_value = f"\n• <b>Lucro (USD):</b> ${usd_amount:.2f}"
        
        # Obtém quantidades do trade se disponíveis
        quantity_info = ""
        if trade_data and "quantity" in trade_data:
            quantity = trade_data.get("quantity", 0)
            quantity_info = f"\n• <b>Quantidade negociada:</b> {quantity:,.4f} tokens"
        
        # Cria o bloco principal
        details = (
            f"• <b>Token:</b> {token}\n"
            f"• <b>Resultado:</b> {result_emoji} {formatted_profit_pct}\n"
            f"• <b>Lucro (SOL):</b> {formatted_profit_sol} SOL{usd_value}{quantity_info}\n"
            f"• <b>Data/Hora:</b> {now}"
        )
        
        # Adiciona informações de preço se disponíveis
        prices = ""
        if buy_price and sell_price:
            buy_price_fmt = f"{buy_price:.10f}".replace(".", ",")
            sell_price_fmt = f"{sell_price:.10f}".replace(".", ",")
            
            prices = (
                f"\n\n📊 <b>DETALHES DA OPERAÇÃO</b>\n"
                f"• <b>Preço de compra:</b> {buy_price_fmt} SOL\n"
                f"• <b>Preço de venda:</b> {sell_price_fmt} SOL"
            )
            
            # Adiciona tempo da operação completa se disponível
            if time_elapsed:
                # Converte para horas, minutos e segundos
                m, s = divmod(time_elapsed, 60)
                h, m = divmod(m, 60)
                time_str = f"{int(h)}h {int(m)}m {int(s)}s"
                prices += f"\n• <b>Tempo total do ciclo:</b> {time_str}"
                
            # Adiciona tempo até o envio da transação se disponível
            if trade_data and "submit_time" in trade_data:
                submit_time = trade_data.get("submit_time")
                prices += f"\n• <b>Tempo até envio da transação:</b> {submit_time:.2f} segundos"
                
            # Adiciona tempo de execução da compra se disponível
            if trade_data and "buy_execution_time" in trade_data:
                buy_execution_time = trade_data.get("buy_execution_time")
                prices += f"\n• <b>Tempo de finalização na blockchain:</b> {buy_execution_time} segundos"
        
        message = f"{header}\n\n{details}{prices}"
        
        await self.send_message(message)
    
    async def send_error_notification(self, error_message, error_type=None, suggestions=None):
        """
        Envia uma notificação de erro
        
        Args:
            error_message (str): Mensagem de erro
            error_type (str, optional): Tipo de erro (API, Blockchain, Configuração, etc)
            suggestions (list, optional): Lista de sugestões para resolver o problema
        """
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        # Define tipo de erro
        error_type_str = error_type or "Geral"
        
        # Escolhe emoji adequado ao tipo de erro
        error_emoji = {
            "API": "🔌",
            "Blockchain": "⛓️",
            "Configuração": "⚙️",
            "Conexão": "📡",
            "Transação": "💸",
            "Geral": "⚠️"
        }.get(error_type_str, "🚨")
        
        header = f"{error_emoji} <b>ERRO DETECTADO: {error_type_str}</b> {error_emoji}"
        
        # Formata a mensagem principal
        details = (
            f"• <b>Mensagem:</b> {error_message}\n"
            f"• <b>Data/Hora:</b> {now}\n"
            f"• <b>Uptime:</b> {str(datetime.now() - self.start_time).split('.')[0]}"
        )
        
        # Adiciona sugestões se disponíveis
        suggestions_block = ""
        if suggestions and len(suggestions) > 0:
            suggestions_block = "\n\n<b>🔧 POSSÍVEIS SOLUÇÕES:</b>"
            for i, suggestion in enumerate(suggestions, 1):
                suggestions_block += f"\n{i}. {suggestion}"
        
        message = f"{header}\n\n{details}{suggestions_block}\n\n⚠️ <i>Verifique os logs para mais detalhes</i>"
        
        await self.send_message(message)
    
    async def send_bot_status(self, status, pools_count=None, pools_info=None, trade_config=None):
        """
        Envia uma notificação sobre o status do bot
        
        Args:
            status (str): Status atual ('iniciado', 'parado', etc)
            pools_count (int, optional): Número de pools monitoradas
            pools_info (list, optional): Lista com informações das pools
            trade_config (dict, optional): Configurações de trading do bot
        """
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        uptime = datetime.now() - self.start_time
        
        if status.lower() == 'iniciado':
            emoji = "🚀"
            header = f"{emoji} <b>BOT DE TRADING INICIADO</b> {emoji}"
        elif status.lower() == 'parado':
            emoji = "🛑"
            header = f"{emoji} <b>BOT DE TRADING PARADO</b> {emoji}"
        elif status.lower() == 'monitorando':
            emoji = "👁️"
            header = f"{emoji} <b>BOT EM MONITORAMENTO ATIVO</b> {emoji}"
        else:
            emoji = "ℹ️"
            header = f"{emoji} <b>STATUS DO BOT: {status.upper()}</b> {emoji}"
        
        details = (
            f"• <b>Data/Hora:</b> {now}\n"
            f"• <b>Uptime:</b> {str(uptime).split('.')[0]}"
        )
        
        if pools_count:
            details += f"\n• <b>Pools monitoradas:</b> {pools_count}"
        
        # Adiciona estatísticas se existirem operações
        stats = ""
        if self.trades_count["compras"] > 0:
            success_rate = (self.successful_trades / self.trades_count["vendas"]) * 100 if self.trades_count["vendas"] > 0 else 0
            stats = (
                f"\n\n📊 <b>ESTATÍSTICAS DE TRADING</b>\n"
                f"• <b>Compras realizadas:</b> {self.trades_count['compras']}\n"
                f"• <b>Vendas realizadas:</b> {self.trades_count['vendas']}\n"
                f"• <b>Lucro acumulado:</b> {self.total_profit:.6f} SOL\n"
                f"• <b>Taxa de sucesso:</b> {success_rate:.1f}%"
            )
        
        # Adiciona configurações de trading se disponíveis
        config_info = ""
        if trade_config:
            config_info = (
                f"\n\n⚙️ <b>CONFIGURAÇÕES DE TRADING</b>\n"
                f"• <b>Queda mínima:</b> {trade_config.get('price_drop_percentage', 0):.2f}%\n"
                f"• <b>Queda máxima:</b> {trade_config.get('max_price_drop_percentage', 0):.2f}%\n"
                f"• <b>Meta de lucro:</b> {trade_config.get('profit_target_percentage', 0):.2f}%\n"
                f"• <b>Valor por trade:</b> {trade_config.get('trade_amount', 0):.4f} SOL\n"
                f"• <b>Slippage:</b> {trade_config.get('slippage', 0):.2f}%"
            )
        
        pools_list = ""
        if pools_info and len(pools_info) > 0:
            # Calcula o valor total em SOL das pools
            total_reserve = sum(pool.get('sol_reserve', 0) for pool in pools_info)
            
            pools_list = (
                f"\n\n💦 <b>TOP {min(5, len(pools_info))} POOLS (Total: {total_reserve:.2f} SOL)</b>"
            )
            
            for i, pool in enumerate(pools_info[:5], 1):
                pool_name = pool.get('token_pair', 'N/A')
                sol_reserve = pool.get('sol_reserve', 0)
                pools_list += f"\n{i}. {pool_name} - {sol_reserve:.2f} SOL"
        
        message = f"{header}\n\n{details}{stats}{config_info}{pools_list}"
        
        # Adiciona informações do sistema
        message += (
            f"\n\n💻 <b>INFORMAÇÕES DO SISTEMA</b>\n"
            f"• <b>Versão:</b> Bot Multi-Pool GRPC v1.1.0\n"
            f"• <b>Rede:</b> Solana Mainnet\n"
            f"• <b>Provider:</b> Helius GRPC"
        )
        
        await self.send_message(message)
    
    async def send_price_alert(self, token, price, drop_percentage, previous_price=None, pool_data=None):
        """
        Envia um alerta de queda de preço
        
        Args:
            token (str): Nome do token
            price (float): Preço atual
            drop_percentage (float): Percentual de queda
            previous_price (float, optional): Preço anterior
            pool_data (dict, optional): Dados adicionais da pool
        """
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        formatted_price = f"{price:.10f}".replace(".", ",")
        formatted_drop = f"{drop_percentage:.2f}%".replace(".", ",")
        
        # Cria mensagem simples com informações essenciais
        message = (
            f"⚠️ <b>QUEDA DE PREÇO DETECTADA</b> ⚠️\n\n"
            f"• <b>Token:</b> {token}\n"
            f"• <b>Queda:</b> 📉 {formatted_drop}\n"
            f"• <b>Preço atual:</b> {formatted_price} SOL"
        )
        
        if previous_price:
            formatted_prev = f"{previous_price:.10f}".replace(".", ",")
            message += f"\n• <b>Preço anterior:</b> {formatted_prev} SOL"
        
        # Adiciona apenas a reserva SOL da pool, que é o dado mais relevante
        if pool_data and "sol_reserve" in pool_data:
            sol_reserve = pool_data.get("sol_reserve", 0)
            message += f"\n• <b>Reserva SOL:</b> {sol_reserve:.2f} SOL"
        
        message += "\n\n🚀 <i>Preparando operação de compra...</i>"
        
        await self.send_message(message)
    
    async def send_daily_summary(self, pools_info=None, trading_stats=None):
        """
        Envia um resumo diário das atividades do bot
        
        Args:
            pools_info (list, optional): Lista com informações das pools
            trading_stats (dict, optional): Estatísticas de trading do dia
        """
        now = datetime.now()
        formatted_date = now.strftime("%d/%m/%Y")
        
        header = f"📅 <b>RESUMO DIÁRIO - {formatted_date}</b> 📅"
        
        # Estatísticas de trading
        trading_summary = "\n\n📊 <b>ESTATÍSTICAS DE TRADING</b>"
        
        if trading_stats:
            daily_trades = trading_stats.get("daily_trades", 0)
            daily_profit = trading_stats.get("daily_profit", 0)
            
            trading_summary += (
                f"\n• <b>Operações hoje:</b> {daily_trades}\n"
                f"• <b>Lucro hoje:</b> {daily_profit:.6f} SOL"
            )
        
        # Estatísticas simplificadas
        trading_summary += (
            f"\n\n<b>TOTAIS</b>\n"
            f"• <b>Compras:</b> {self.trades_count['compras']}\n"
            f"• <b>Vendas:</b> {self.trades_count['vendas']}\n"
            f"• <b>Lucro total:</b> {self.total_profit:.6f} SOL"
        )
        
        # Top pools (apenas as 3 principais)
        pools_list = ""
        if pools_info and len(pools_info) > 0:
            # Ordenar pools por reserva de SOL
            sorted_pools = sorted(pools_info, key=lambda x: x.get('sol_reserve', 0), reverse=True)
            
            pools_list = (
                f"\n\n💦 <b>TOP 3 POOLS</b>"
            )
            
            for i, pool in enumerate(sorted_pools[:3], 1):
                pool_name = pool.get('token_pair', 'N/A')
                sol_reserve = pool.get('sol_reserve', 0)
                pools_list += f"\n{i}. {pool_name} - {sol_reserve:.2f} SOL"
        
        message = f"{header}{trading_summary}{pools_list}"
        
        await self.send_message(message)
        

# Exemplo de uso como script independente
async def test_notification():
    notifier = TelegramNotifier()
    await notifier.send_message("🤖 Bot de trading iniciado!")
    
if __name__ == "__main__":
    asyncio.run(test_notification()) 