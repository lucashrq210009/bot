# Documentação Técnica - Bot de Trading Raydium Multi-Pool

## 📁 Estrutura de Arquivos

### Arquivos Principais

#### `config.json` - Configuração Central
```json
{
  "owner_address": "Endereço da wallet",
  "price_drop_percentage": "Percentual mínimo de queda para trigger",
  "max_price_drop_percentage": "Percentual máximo permitido",
  "profit_target_percentage": "Meta de lucro para venda",
  "profit_timeout_minutes": "Timeout para venda forçada",
  "trade_amount": "Quantidade de SOL por trade",
  "slippage": "Slippage máximo permitido",
  "min_sol_reserve": "Reserva mínima SOL nas pools",
  "mev_protection_pump_threshold": "Threshold para detecção MEV",
  "mev_protection_time_window": "Janela de proteção MEV",
  "buy_settings": "Configurações específicas de compra",
  "sell_settings": "Configurações específicas de venda",
  "tokens_to_monitor": "Array de tokens para monitorar"
}
```

**Características:**
- Configuração centralizada e flexível
- Suporte a configurações granulares por operação
- Proteções configuráveis contra MEV
- Lista dinâmica de tokens

---

#### `multi_pool_bot.py` - Orquestrador Principal
```python
async def central_manager():
    """
    Função principal que coordena todo o sistema:
    1. Carrega configurações
    2. Configura pools via API Raydium
    3. Inicializa monitoramento gRPC
    4. Coordena ciclos de trading
    5. Gerencia notificações
    """
```

**Funcionalidades Principais:**
- **Pool Discovery**: Busca automática de pools via API Raydium
- **Multi-threading**: Monitora até 200+ pools simultaneamente
- **Error Recovery**: Auto-restart em caso de falhas
- **State Management**: Gerencia estado de cada operação
- **Metrics Collection**: Coleta estatísticas de performance

**Fluxo Principal:**
```python
while True:
    # 1. Monitorar todas as pools em paralelo
    tasks = [monitor_pool(config) for config in pool_configs]
    
    # 2. Aguardar primeiro trigger
    done, pending = await asyncio.wait(tasks, return_when=FIRST_COMPLETED)
    
    # 3. Executar ciclo de trading
    selected_config = get_triggered_config(done)
    await execute_trading_cycle(selected_config)
    
    # 4. Reiniciar monitoramento
```

---

#### `monitor_grpc.py` - Monitor de Preços gRPC
```python
class PriceMonitorGRPC:
    """
    Monitor de preços em tempo real usando gRPC Helius
    """
    def __init__(self, config, rpc_fqdn, x_token):
        self.config = config
        self.rpc_fqdn = rpc_fqdn
        self.x_token = x_token
```

**Componentes:**

1. **Autenticação gRPC**:
```python
class TritonAuthMetadataPlugin(grpc.AuthMetadataPlugin):
    def __call__(self, context, callback):
        metadata = (("x-token", self.x_token),)
        callback(metadata, None)
```

2. **Decodificação de Liquidity State**:
```python
def decode_liquidity_state(self, data: bytes) -> dict:
    # Extrai decimais dos tokens
    base_decimal = int.from_bytes(decoded[32:40], 'little')
    quote_decimal = int.from_bytes(decoded[40:48], 'little')
    
    # Extrai endereços dos vaults
    base_vault_bytes = decoded[336:368]
    quote_vault_bytes = decoded[368:400]
```

3. **Stream de Preços**:
```python
async def stream_price(self) -> AsyncIterator[float]:
    # Calcula preço baseado em reserves
    price = self.quote_balance / self.base_balance
    yield price
```

**Características Técnicas:**
- **Conexão Persistente**: Mantém stream gRPC ativo
- **Binary Decoding**: Decodifica dados binários das pools
- **Real-time Processing**: Processamento sub-segundo
- **Automatic Vault Detection**: Identifica vaults automaticamente

---

#### `trader.py` - Executor de Trades
```python
class RaydiumTrader:
    """
    Executor de operações de compra e venda na Raydium
    """
    def __init__(self, api, config):
        self.api = api  # BX Solana API
        self.config = config
```

**Métodos Principais:**

1. **Execução de Compra**:
```python
async def execute_buy(self):
    # 1. Preparar parâmetros
    sol_amount = self.config['trade_amount']
    slippage = self.config['slippage']
    
    # 2. Calcular amounts
    quote_amount = self.calculate_quote_amount(sol_amount)
    
    # 3. Executar swap
    response = await self.api.raydium_swap(
        owner=self.owner,
        in_token=self.in_token,
        out_token=self.out_token,
        in_amount=quote_amount,
        slippage=slippage,
        **submit_params
    )
```

2. **Execução de Venda**:
```python
async def execute_sell(self):
    # 1. Obter saldo do token
    token_balance = await get_token_balance(self.owner, self.out_token)
    
    # 2. Calcular amount para venda
    sell_amount = self.calculate_sell_amount(token_balance)
    
    # 3. Executar swap reverso
    response = await self.api.raydium_swap(
        # Parâmetros invertidos para venda
    )
```

**Funcionalidades:**
- **Balance Verification**: Verifica saldos antes de operar
- **Amount Calculation**: Cálculos precisos de amounts
- **Retry Logic**: Sistema de retry para transações falhadas
- **Transaction Verification**: Verificação de confirmação

---

#### `telegram_notifier.py` - Sistema de Notificações
```python
class TelegramNotifier:
    """
    Sistema completo de notificações via Telegram
    """
    def __init__(self, token=None, chat_id=None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
```

**Tipos de Notificação:**

1. **Trade Notifications**:
```python
async def send_trade_notification(self, action, token, amount, price, ...):
    # Formata mensagem HTML
    # Calcula valores USD
    # Adiciona links para Solscan
    # Inclui dados da pool
```

2. **Profit Notifications**:
```python
async def send_profit_notification(self, token, profit_percentage, ...):
    # Calcula lucro/prejuízo
    # Converte para USD
    # Inclui métricas de tempo
    # Estatísticas de performance
```

3. **Error Notifications**:
```python
async def send_error_notification(self, error_message, error_type, ...):
    # Categoriza tipos de erro
    # Fornece sugestões de solução
    # Inclui informações de debug
```

**Características:**
- **Rich Formatting**: Mensagens HTML formatadas
- **USD Conversion**: Integração com CoinGecko
- **Performance Metrics**: Estatísticas em tempo real
- **Error Categorization**: Classificação inteligente de erros

---

#### `formatters.py` - Formatação de Interface
```python
# Formatadores coloridos para terminal
def format_success(message):
    return f"{Fore.GREEN}✅ {message}{Style.RESET_ALL}"

def format_price(price, precision=8):
    return f"{Fore.MAGENTA}{price:.{precision}f}{Style.RESET_ALL}"
```

**Funcionalidades:**
- **Colored Output**: Terminal colorido para melhor UX
- **Consistent Formatting**: Formatação padronizada
- **Timestamp Display**: Timestamps formatados
- **Status Indicators**: Indicadores visuais de status

---

### Arquivos gRPC (Auto-gerados)

#### `geyser_pb2.py` / `geyser_pb2_grpc.py`
- Arquivos gerados pelo Protocol Buffers
- Definem estruturas de dados para comunicação gRPC
- Interfaces para o serviço Geyser (Helius)

#### `solana_storage_pb2.py` / `solana_storage_pb2_grpc.py`
- Estruturas de dados específicas da Solana
- Definições de transações e blocos
- Metadados de transações

---

## 🔧 Configurações Técnicas

### Variáveis de Ambiente Requeridas
```bash
# API Keys
AUTH_HEADER=           # BX Solana Auth Header
PUBLIC_KEY=            # Wallet Public Key
PRIVATE_KEY=           # Wallet Private Key (Base58)
HELIUS_API_KEY=        # Helius API Key

# gRPC Configuration
GRPC_RPC_FQDN=         # Helius gRPC Endpoint
GRPC_X_TOKEN=          # gRPC Authentication Token

# Telegram
TELEGRAM_BOT_TOKEN=    # Bot Token
TELEGRAM_CHAT_ID=      # Chat ID para notificações
```

### Configurações de Performance
```json
{
  "mev_protection_pump_threshold": 6,    // % para detectar pump suspeito
  "mev_protection_time_window": 5,       // Segundos de proteção
  "profit_timeout_minutes": 1000,        // Timeout para venda forçada
  "min_sol_reserve": 500,                // Liquidez mínima
  "buy_settings": {
    "priority_fee_sol": 0.001,           // Priority fee em SOL
    "compute_price_sol": 0.001           // Compute price em SOL
  }
}
```

---

## ⚡ Fluxos de Dados

### 1. Inicialização do Sistema
```
config.json → multi_pool_bot.py → Raydium API → Pool Discovery
                ↓
telegram_notifier.py ← Status Notification
                ↓
monitor_grpc.py → Helius gRPC → Real-time Monitoring
```

### 2. Detecção de Oportunidade
```
Helius gRPC → monitor_grpc.py → Price Calculation
                ↓
Price Drop Detection → MEV Protection Check
                ↓
multi_pool_bot.py → Trading Trigger
```

### 3. Execução de Trade
```
multi_pool_bot.py → trader.py → BX Solana API
                ↓
Transaction Execution → Verification
                ↓
telegram_notifier.py ← Success/Failure Notification
```

### 4. Monitoramento de Lucro
```
monitor_grpc.py → Profit Monitoring → Threshold Check
                ↓
trader.py → Sell Execution → telegram_notifier.py
```

---

## 🛡️ Segurança e Proteções

### MEV Protection
```python
# Detecção de pump suspeito
if alta_repentina >= mev_threshold:
    recent_pump_detected = True
    pump_timestamp = current_time

# Proteção contra quedas após pump
if recent_pump_detected and (current_time - pump_timestamp <= time_window):
    if queda_detectada:
        print("MEV suspeito - ignorando operação")
        continue
```

### Transaction Verification
```python
async def verify_transaction_status(signature: str) -> bool:
    # 1. Verificação via Helius API
    # 2. Análise de erros específicos (IllegalOwner, etc)
    # 3. Confirmação de status
    # 4. Retry logic em caso de falha
```

### Error Handling
```python
try:
    # Operação crítica
except Exception as e:
    # Log detalhado
    # Notificação via Telegram
    # Recovery automático
    # Restart se necessário
```

---

## 📊 Métricas e Monitoramento

### Métricas Coletadas
- **Latência**: Tempo de detecção até execução
- **Success Rate**: Taxa de sucesso das operações
- **Profit/Loss**: Lucro acumulado e por operação
- **Uptime**: Tempo de operação contínua
- **Pool Statistics**: Dados de liquidez e volume

### Logging
```python
# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/bot.log"),
        # Console output via formatters.py
    ]
)
```

### Notificações Automáticas
- **Status Updates**: A cada 6 horas
- **Daily Summaries**: Resumo diário às 00:00
- **Error Alerts**: Imediatos
- **Trade Notifications**: Em tempo real

---

## 🔄 Ciclo de Vida das Operações

### Estado das Operações
1. **MONITORING**: Monitoramento ativo de preços
2. **TRIGGERED**: Oportunidade detectada
3. **BUYING**: Executando compra
4. **BOUGHT**: Compra confirmada
5. **PROFIT_MONITORING**: Monitorando lucro
6. **SELLING**: Executando venda
7. **COMPLETED**: Ciclo finalizado

### Transições de Estado
```python
# MONITORING → TRIGGERED
if price_drop >= min_drop and price_drop <= max_drop and not mev_detected:
    state = "TRIGGERED"

# TRIGGERED → BUYING
if execute_buy():
    state = "BUYING"

# BUYING → BOUGHT
if transaction_confirmed:
    state = "BOUGHT"

# BOUGHT → PROFIT_MONITORING
state = "PROFIT_MONITORING"

# PROFIT_MONITORING → SELLING
if profit >= target or timeout_reached:
    state = "SELLING"

# SELLING → COMPLETED
if sell_transaction_confirmed:
    state = "COMPLETED"
```

---

## 🚀 Otimizações e Performance

### Processamento Paralelo
- **Async/Await**: Operações não-bloqueantes
- **Concurrent Monitoring**: Monitora múltiplas pools simultaneamente
- **Queue-based Processing**: Filas assíncronas para eventos

### Memory Management
- **Connection Pooling**: Reutilização de conexões gRPC
- **Data Streaming**: Processamento em stream vs batch
- **Garbage Collection**: Limpeza automática de dados antigos

### Network Optimization
- **gRPC Streaming**: Conexões persistentes
- **Retry Logic**: Recovery inteligente de falhas
- **Rate Limiting**: Controle de requisições

---

Esta documentação técnica fornece uma visão completa da arquitetura, funcionamento interno e características técnicas do Bot de Trading Raydium Multi-Pool. 