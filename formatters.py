from colorama import Fore, Back, Style
from datetime import datetime

# Formatadores para saída no terminal
def format_success(message):
    return f"{Fore.GREEN}✅ {message}{Style.RESET_ALL}"

def format_error(message):
    return f"{Fore.RED}❌ {message}{Style.RESET_ALL}"

def format_warning(message):
    return f"{Fore.YELLOW}⚠️ {message}{Style.RESET_ALL}"

def format_info(message):
    return f"{Fore.CYAN}ℹ️ {message}{Style.RESET_ALL}"

def format_price(price, precision=8):
    return f"{Fore.MAGENTA}{price:.{precision}f}{Style.RESET_ALL}"

def format_percent(percent, is_positive=None):
    # Se is_positive não for especificado, determina com base no valor
    if is_positive is None:
        is_positive = percent >= 0
    
    color = Fore.GREEN if is_positive else Fore.RED
    symbol = "+" if is_positive and percent > 0 else ""
    return f"{color}{symbol}{percent:.2f}%{Style.RESET_ALL}"

def format_header(message):
    return f"\n{Fore.WHITE}{Back.BLUE}{message.center(78)}{Style.RESET_ALL}"

def format_subheader(message):
    return f"{Fore.BLACK}{Back.CYAN}{message.center(78)}{Style.RESET_ALL}"

def format_pool(pool_name):
    return f"{Fore.YELLOW}[{pool_name}]{Style.RESET_ALL}"

def format_sol(amount):
    return f"{Fore.YELLOW}{amount:.4f} SOL{Style.RESET_ALL}"

def format_timestamp():
    current_time_str = datetime.now().strftime("%H:%M:%S")
    return f"{Fore.BLACK}{Back.WHITE} {current_time_str} {Style.RESET_ALL}" 