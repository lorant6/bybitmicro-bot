import ccxt
print(f"CCXT Version: {ccxt.__version__}")
# We need at least version 4.0.0+
if hasattr(ccxt.bybit(), 'set_trading_stop'):
    print("✅ SUCCESS: set_trading_stop exists!")
else:
    print("❌ FAILURE: Still using old version.")
