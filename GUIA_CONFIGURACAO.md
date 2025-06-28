# Guia de Configuração e Uso - Bot de Trading Raydium Multi-Pool

## 🚀 Configuração Inicial

### 1. Pré-requisitos

#### Sistema Operacional
- **Windows 10/11**, **Linux**, ou **macOS**
- **Python 3.8+** instalado
- **Git** para clonar o repositório

#### Contas e APIs Necessárias
1. **Wallet Solana** com SOL para trading
2. **Conta Helius** (node privado) + (RPC plano gratuito)
3. **API BloxRoute** - Para execução de trades
4. **Bot Telegram** (opcional) - Para notificações

### 2. Instalação Passo a Passo

#### Clone do Repositório
```bash
git clone <repository-url>
cd Bot_GRPC_raydium
```

#### Instalação de Dependências
```bash
# Instalar dependências Python
pip install -r requirements.txt

# Ou usando ambiente virtual (recomendado)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

#### Verificação da Instalação
```bash
python -c "import bxsolana_trader; print('BX Solana OK')"
python -c "import grpc; print('gRPC OK')"
python -c "import telegram; print('Telegram OK')"
```

---

## 🔧 Configuração de APIs

### 1. Configuração Helius

#### Configuração gRPC
```bash
# Endpoint gRPC da Helius
GRPC_RPC_FQDN=api_helius_plano_free_ou_pago

# Token de autenticação (mesmo que API Key)
GRPC_X_TOKEN=api_node_privado 
```

### 2. Configuração BloxRoute Solana

#### Obter Credenciais
1. Acesse a plataforma BX Solana
2. Configure sua wallet
3. Obtenha o **AUTH_HEADER**

#### Formato das Chaves
```bash
# Header de autenticação BX
AUTH_HEADER=Bearer_seu_token_aqui

# Chaves da wallet
PUBLIC_KEY=sua_public_key_base58
PRIVATE_KEY=sua_private_key_base58
```

### 3. Configuração Telegram (Opcional)

#### Criar Bot
1. Abra o Telegram e procure por **@BotFather**
2. Digite `/newbot` e siga as instruções
3. Copie o **Token** fornecido

#### Obter Chat ID
```bash
# Envie uma mensagem para seu bot, depois acesse:
https://api.telegram.org/bot<SEU_TOKEN>/getUpdates

# Procure pelo campo "chat" -> "id"
```

---

## ⚙️ Arquivo de Configuração

### Criar arquivo .env
```bash
# Copie o exemplo e edite
cp .env.example .env
nano .env  # ou seu editor preferido
```

### Exemplo de .env completo
```bash
# ===== BX SOLANA CONFIGURATION =====
AUTH_HEADER=Bearer_seu_token_bx_solana
PUBLIC_KEY=11111111111111111111111111111111
PRIVATE_KEY=base58_encoded_private_key_here

# ===== HELIUS CONFIGURATION =====
HELIUS_API_KEY=sua_helius_api_key
GRPC_RPC_FQDN=mainnet.helius-rpc.com:443
GRPC_X_TOKEN=sua_helius_api_key

# ===== TELEGRAM CONFIGURATION =====
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhiJklMnoPqrsTuvWxYz
TELEGRAM_CHAT_ID=123456789
```

### Configuração do config.json

#### Configuração Básica
```json
{
  "owner_address": "SUA_WALLET_PUBLIC_KEY_AQUI",
  "price_drop_percentage": 5.0,
  "max_price_drop_percentage": 25.0,
  "profit_target_percentage": 10.0,
  "profit_timeout_minutes": 60,
  "trade_amount": 0.01,
  "slippage": 15,
  "min_sol_reserve": 100,
  "mev_protection_pump_threshold": 8,
  "mev_protection_time_window": 10
}
```

#### Configuração Avançada
```json
{
  "owner_address": "SUA_WALLET_AQUI",
  
  // Configurações de Trading
  "price_drop_percentage": 3.0,        // Queda mínima para compra (3%)
  "max_price_drop_percentage": 30.0,   // Queda máxima permitida (30%)
  "profit_target_percentage": 8.0,     // Meta de lucro (8%)
  "profit_timeout_minutes": 120,       // Timeout para venda (2 horas)
  "trade_amount": 0.005,               // 0.005 SOL por trade
  "slippage": 20,                      // Slippage máximo (20%)
  "min_sol_reserve": 250,              // Reserva mínima (250 SOL)
  
  // Proteção MEV
  "mev_protection_pump_threshold": 6,  // Pump suspeito (6%)
  "mev_protection_time_window": 15,    // Janela de proteção (15s)
  
  // Configurações de Compra
  "buy_settings": {
    "priority_fee_sol": 0.0015,        // Priority fee (0.0015 SOL)
    "compute_price_sol": 0.0005        // Compute price (0.0005 SOL)
  },
  
  // Configurações de Venda
  "sell_settings": {
    "priority_fee_sol": 0.002,         // Priority fee maior para venda
    "compute_price_sol": 0.001         // Compute price maior para venda
  },
  
  // Tokens para Monitorar
  "tokens_to_monitor": [
    {
      "out_token": "TOKEN_ADDRESS_1"
    },
    {
      "out_token": "TOKEN_ADDRESS_2",
      "sol_in_quote": true               // Configuração específica
    }
  ]
}
```

---

## 🚀 Execução e Monitoramento

### 1. Primeira Execução

#### Teste de Configuração
```bash
# Verificar configurações
python -c "
import json
with open('config.json') as f:
    config = json.load(f)
    print(f'Tokens: {len(config.get(\"tokens_to_monitor\", []))}')
    print(f'Trade amount: {config.get(\"trade_amount\")} SOL')
"
```

#### Execução do Bot
```bash
# Executar em primeiro plano
python multi_pool_bot.py

# Executar em background (Linux/Mac)
nohup python multi_pool_bot.py > bot.log 2>&1 &

# Windows (PowerShell)
Start-Process python -ArgumentList "multi_pool_bot.py" -WindowStyle Hidden
```

### 2. Monitoramento

#### Logs em Tempo Real
```bash
# Visualizar logs
tail -f logs/bot.log

# Filtrar apenas erros
tail -f logs/bot.log | grep ERROR

# Filtrar trades
tail -f logs/bot.log | grep -E "(COMPRA|VENDA)"
```

#### Verificação de Status
```bash
# Verificar se está rodando
ps aux | grep multi_pool_bot.py

# Verificar uso de CPU/memória
top -p $(pgrep -f multi_pool_bot.py)
```

---

## 📊 Métricas e Análise

### 1. Estatísticas do Terminal

Durante a execução, o bot exibe:
```
🚀 BOT DE TRADING RAYDIUM - MULTI-POOL 🚀
════════════════════════════════════════════════════════════════════════════════

⚙️ CONFIGURAÇÕES DO BOT
  • Queda mínima de preço: 5.00%
  • Queda máxima de preço: 25.00%
  • Meta de lucro: 10.00%
  • Valor de cada trade: 0.0100 SOL
  • Slippage: 15.00%
  • Reserva mínima de SOL: 100.00 SOL

💦 POOLS CONFIGURADAS PARA MONITORAMENTO (3)
   1. TOKEN1/WSOL | Reserva: 245.67 SOL
   2. TOKEN2/WSOL | Reserva: 189.34 SOL
   3. TOKEN3/WSOL | Reserva: 156.78 SOL

ℹ️ Monitorando 3 pools simultaneamente...
```

### 2. Notificações Telegram

#### Exemplo de Notificação de Compra
```
🟢 COMPRA REALIZADA 🟢

• Token: BONK
• Quantidade: 15,234.5678 tokens
• Preço: 💸 0,0000045623 SOL
• Valor (SOL): 0.069456 SOL
• Valor (USD): $4.23
• Data/Hora: 15/01/2024 14:32:15
• Tempo de execução: 2.34 segundos

📊 DADOS DA POOL
• TVL: 2,456.78 SOL
• Reserva SOL: 1,234.56 SOL

🔍 Ver transação
```

#### Exemplo de Notificação de Lucro
```
💎 LUCRO REALIZADO 💎

• Token: BONK
• Resultado: 📈 +12,45%
• Lucro (SOL): 0.008634 SOL
• Lucro (USD): $0.52
• Quantidade negociada: 15,234.5678 tokens
• Data/Hora: 15/01/2024 14:45:33

📊 DETALHES DA OPERAÇÃO
• Preço de compra: 0,0000045623 SOL
• Preço de venda: 0,0000051301 SOL
• Tempo total do ciclo: 0h 13m 18s
• Tempo até envio da transação: 1.87 segundos
• Tempo de finalização na blockchain: 3 segundos
```

---

## 🛠️ Solução de Problemas

### 1. Problemas Comuns

#### Bot não inicia
```bash
# Verificar dependências
pip install -r requirements.txt --force-reinstall

# Verificar arquivo .env
cat .env | grep -v "^#"

# Verificar permissões
ls -la *.py
```

#### Erro de conexão gRPC
```bash
# Testar conectividade
python -c "
import grpc
import os
channel = grpc.secure_channel(
    os.getenv('GRPC_RPC_FQDN', 'mainnet.helius-rpc.com:443'),
    grpc.ssl_channel_credentials()
)
print('Conexão gRPC OK')
"
```

#### Erro de autenticação
```bash
# Verificar chaves
python -c "
import os
print('AUTH_HEADER:', bool(os.getenv('AUTH_HEADER')))
print('PRIVATE_KEY:', bool(os.getenv('PRIVATE_KEY')))
print('PUBLIC_KEY:', bool(os.getenv('PUBLIC_KEY')))
"
```

### 2. Logs de Debug

#### Ativar logs detalhados
```python
# Editar multi_pool_bot.py
logging.basicConfig(level=logging.DEBUG)
```

#### Verificar transações falhadas
```bash
# Procurar por erros específicos
grep -n "IllegalOwner\|InsufficientBalance\|SlippageExceeded" logs/bot.log
```

---

## 🔄 Manutenção e Atualizações

### 1. Atualizações de Dependências
```bash
# Atualizar dependências
pip install -r requirements.txt --upgrade

# Verificar versões
pip list | grep -E "(bxsolana|grpc|telegram)"
```

### 2. Backup de Configurações
```bash
# Backup automático
mkdir backups
cp config.json backups/config_$(date +%Y%m%d).json
cp .env backups/env_$(date +%Y%m%d).backup
```

### 3. Monitoramento de Performance
```bash
# Script de monitoramento
#!/bin/bash
while true; do
    echo "$(date): CPU $(ps -o %cpu -p $(pgrep -f multi_pool_bot.py) | tail -1)%"
    sleep 60
done
```

---

## 📈 Otimização de Performance

### 1. Configurações para Performance
```json
{
  "tokens_to_monitor": [],              // Máximo 50-100 tokens
  "profit_timeout_minutes": 60,         // Timeouts razoáveis
  "min_sol_reserve": 200,               // Liquidez adequada
  "buy_settings": {
    "priority_fee_sol": 0.002,          // Fees maiores = execução mais rápida
    "compute_price_sol": 0.001
  }
}
```

### 2. Recursos do Sistema
```bash
# Requisitos mínimos
CPU: 2 cores
RAM: 4GB
Rede: 10Mbps estável
Armazenamento: 1GB livre

# Requisitos recomendados
CPU: 4+ cores
RAM: 8GB+
Rede: 50Mbps+
SSD: 5GB+ livre
```

---

### Recursos Úteis
- **Solscan**: Verificar transações
- **Raydium**: Interface da DEX
- **Helius**: Dashboard da API
- **CoinGecko**: Preços de referência
