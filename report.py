import ccxt
import pandas as pd
from datetime import datetime, timedelta
import config
from colorama import Fore, Style, init

# --- CONFIG ---
init(autoreset=True)
exchange = ccxt.bybit({
    'apiKey': config.API_KEY,
    'secret': config.API_SECRET,
    'options': {'defaultType': 'swap'}
})

def get_pnl(days=1):
    print(f"\n📊 {Fore.CYAN}SCANNING ACCOUNT PERFORMANCE (Last {days} Days)...{Style.RESET_ALL}")
    
    # Calculate timestamp for X days ago
    since_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
    
    try:
        # Fetch closed orders (Limit 50 to be fast)
        trades = exchange.fetch_closed_orders(limit=50, since=since_time)
        
        total_pnl = 0
        wins = 0
        losses = 0
        
        print(f"{'SYMBOL':<15} {'SIDE':<6} {'RESULT':<10} {'PnL ($)':<10}")
        print("-" * 45)
        
        for t in trades:
            symbol = t['symbol']
            side = t['side'].upper()
            
            # Not all trades have PnL info immediately, but Bybit usually provides trade data
            # For simplicity, we assume Bybit 'closed_orders' response includes filled value
            # Note: Accurate PnL often requires fetching 'my_trades', but let's try order cost diff
            
            # Fetch specific trade execution details for PnL
            my_trades = exchange.fetch_my_trades(symbol, since=t['timestamp'], limit=5)
            trade_pnl = 0
            
            for mt in my_trades:
                if mt['order'] == t['id']:
                    # Use realizedPnl if available (Bybit specific)
                    info = mt.get('info', {})
                    pnl = float(info.get('closedPnl', 0))
                    trade_pnl += pnl
            
            if trade_pnl == 0: continue # Skip open/partial orders

            total_pnl += trade_pnl
            
            # Determine Color
            if trade_pnl > 0:
                color = Fore.GREEN
                result = "WIN"
                wins += 1
            else:
                color = Fore.RED
                result = "LOSS"
                losses += 1
                
            print(f"{symbol:<15} {side:<6} {color}{result:<10} ${trade_pnl:.2f}{Style.RESET_ALL}")

        print("-" * 45)
        total_color = Fore.GREEN if total_pnl >= 0 else Fore.RED
        print(f"🏆 TOTAL PnL: {total_color}${total_pnl:.2f}{Style.RESET_ALL}")
        print(f"📈 WINS: {wins} | 📉 LOSSES: {losses}")
        
    except Exception as e:
        print(f"❌ Error fetching PnL: {e}")

if __name__ == "__main__":
    get_pnl(days=1) # Check last 24 hours
