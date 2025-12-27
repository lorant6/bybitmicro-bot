import ccxt
import time
import config
from colorama import Fore, Style, init

# --- SETUP ---
init(autoreset=True)
exchange = ccxt.bybit({
    'apiKey': config.API_KEY,
    'secret': config.API_SECRET,
    'options': {'defaultType': 'swap'}
})

def get_dashboard():
    print(f"\n📡 {Fore.CYAN}CONNECTING TO LIVE MARKET...{Style.RESET_ALL}")
    try:
        # Fetch all raw positions
        positions = exchange.fetch_positions()

        # Filter for active trades (Size > 0)
        active = [p for p in positions if float(p['contracts']) > 0]

        if not active:
            print(f"{Fore.YELLOW}💤 No active trades. Scanning for targets...{Style.RESET_ALL}")
            return

        print(f"\n💰 {Fore.GREEN}LIVE POSITIONS ({len(active)}){Style.RESET_ALL}")
        print(f"{'SYMBOL':<15} {'SIDE':<6} {'SIZE ($)':<10} {'ENTRY':<10} {'PRICE':<10} {'PnL ($)':<10}")
        print("-" * 65)

        total_unrealized = 0

        for p in active:
            symbol = p['symbol']
            side = p['side'].upper()
            size = float(p['contracts']) * float(p['markPrice'])
            entry = float(p['entryPrice'])
            current = float(p['markPrice'])
            pnl = float(p['unrealizedPnl'])

            total_unrealized += pnl

            # Color logic
            pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED

            print(f"{symbol:<15} {side:<6} ${size:<9.2f} ${entry:<9.4f} ${current:<9.4f} {pnl_color}${pnl:.2f}{Style.RESET_ALL}")

        print("-" * 65)
        print(f"💵 TOTAL UNREALIZED PnL: {Fore.GREEN if total_unrealized >= 0 else Fore.RED}${total_unrealized:.2f}{Style.RESET_ALL}")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    while True:
        get_dashboard()
        print(f"\n... Refreshing in 10s (Press Ctrl+C to exit) ...")
        time.sleep(10)
