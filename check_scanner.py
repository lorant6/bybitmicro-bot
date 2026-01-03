import ccxt
from colorama import Fore, Style, init

# Initialize colors
init(autoreset=True)

print(f"{Fore.YELLOW}📡 Connecting to Bybit to scan the market...{Style.RESET_ALL}")

# Connect
exchange = ccxt.bybit()
tickers = exchange.fetch_tickers()

# Filter Logic (Same as Master Bot)
valid = []
for s, d in tickers.items():
    if "/USDT:USDT" not in s: continue
    if d['quoteVolume'] is None or d['quoteVolume'] < 5000000: continue
    valid.append({
        'symbol': s, 
        'vol': d['quoteVolume'], 
        'chg': abs(d['percentage'] or 0)
    })

# 1. SWING LIST (High Volume)
valid.sort(key=lambda x: x['vol'], reverse=True)
swing_watchlist = [x['symbol'] for x in valid[:20]]

# 2. SCALP LIST (High Volatility)
scalp_cands = [x for x in valid if x['symbol'] not in swing_watchlist]
scalp_cands.sort(key=lambda x: x['chg'], reverse=True)
scalp_watchlist = [x['symbol'] for x in scalp_cands[:20]]

# --- PRINT RESULTS ---
print(f"\n{Fore.CYAN}💎 SWING LIST (Top Volume):{Style.RESET_ALL}")
for i, coin in enumerate(swing_watchlist, 1):
    print(f"   {i}. {coin}")

print(f"\n{Fore.MAGENTA}🔥 SCALP LIST (Top Volatility):{Style.RESET_ALL}")
for i, coin in enumerate(scalp_watchlist, 1):
    print(f"   {i}. {coin}")

print("\n✅ These are the coins your bot is currently hunting.")
