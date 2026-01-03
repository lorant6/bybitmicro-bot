import ccxt
import config
from datetime import datetime

# Connect to Bybit
exchange = ccxt.bybit({
    'apiKey': config.API_KEY,
    'secret': config.API_SECRET,
})

print("🔍 DEEP SEARCH: Fetching last 10 CLOSED orders...")
print("-" * 75)
print(f"{'TIME':<16} {'SYMBOL':<10} {'SIDE':<5} {'STATUS':<10} {'PRICE':<10} {'FILLED'}")
print("-" * 75)

try:
    # UTA Accounts must use fetch_closed_orders
    orders = exchange.fetch_closed_orders(limit=10)
    
    # Sort by time (newest first)
    orders.sort(key=lambda x: x['timestamp'], reverse=True)

    if not orders:
        print("❌ No closed orders found. (If you just started, this is normal!)")

    for o in orders:
        # Format the time
        dt = datetime.fromtimestamp(o['timestamp'] / 1000).strftime('%m-%d %H:%M')
        symbol = o['symbol'].replace("/USDT:USDT", "")
        side = o['side'].upper()
        status = o['status'].upper()
        price = o.get('average') or o.get('price') or 0
        filled = o.get('filled', 0)
        
        # Color coding
        if status == 'CLOSED': status_str = f"✅ {status}"
        elif status == 'CANCELED': status_str = f"🚫 {status}"
        else: status_str = status

        print(f"{dt:<16} {symbol:<10} {side:<5} {status_str:<10} ${price:<9.4f} {filled}")

    print("-" * 75)
    print("ℹ️  INTERPRETATION:")
    print("   ✅ CLOSED   = Trade finished (Hit TP or SL).")
    print("   🚫 CANCELED = Bot tried to buy, but exchange rejected it (Check logs!).")

except Exception as e:
    print(f"❌ Error: {e}")
