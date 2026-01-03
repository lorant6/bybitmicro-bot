import ccxt
from tradingview_ta import TA_Handler, Interval
from colorama import Fore, Style, init

init(autoreset=True)

# We will check these popular coins
COINS = ['SOL/USDT', 'ETH/USDT', 'BTC/USDT', 'DOGE/USDT', 'XRP/USDT']
INTERVAL = Interval.INTERVAL_15_MINUTES

print(f"\n{Fore.CYAN}🕵️‍♂️ DEBUGGING MARKET CONDITIONS (Why are we not buying?){Style.RESET_ALL}")
print(f"{'SYMBOL':<12} {'RSI':<8} {'MACD':<10} {'SIGNAL':<10} {'TV RATING':<15} {'VERDICT'}")
print("-" * 80)

for symbol in COINS:
    try:
        # 1. Get TradingView Data
        tv_symbol = symbol.split('/')[0] + "USDT"
        handler = TA_Handler(symbol=tv_symbol, exchange="BYBIT", screener="CRYPTO", interval=INTERVAL)
        res = handler.get_analysis()
        
        rec = res.summary['RECOMMENDATION']
        rsi = res.indicators.get('RSI', 50)
        macd = res.indicators.get('MACD.macd', 0)
        sig = res.indicators.get('MACD.signal', 0)

        # 2. Check Logic (Must match master_bot.py)
        # Condition: "BUY" in rec AND RSI < 70 AND MACD > SIGNAL
        
        is_buy_rating = "BUY" in rec
        is_rsi_safe = rsi < 70
        is_momentum_up = macd > sig
        
        # 3. Form Verdict
        verdict = ""
        if not is_buy_rating: verdict += "🚫 TV says Wait/Sell "
        if not is_rsi_safe: verdict += "🚫 RSI too high "
        if not is_momentum_up: verdict += "🚫 MACD Bearish "
        
        if verdict == "": 
            verdict = f"{Fore.GREEN}✅ BUY NOW!{Style.RESET_ALL}"
        else:
            verdict = f"{Fore.RED}{verdict}{Style.RESET_ALL}"

        # Print Row
        print(f"{symbol:<12} {rsi:<8.2f} {macd:<10.4f} {sig:<10.4f} {rec:<15} {verdict}")

    except Exception as e:
        print(f"{symbol:<12} ❌ Error: {e}")

print("-" * 80)
print(f"ℹ️  Your Logic requires: TV='BUY' + RSI < 70 + MACD > Signal")
