import threading
import time
import random
import logging
import ccxt
import requests
import pandas as pd
import pandas_ta as ta
from tradingview_ta import TA_Handler, Interval
from colorama import Fore, Style, init
import config

# --- CONFIGURATION ---
API_KEY = config.API_KEY
API_SECRET = config.API_SECRET

# --- GOD MODE SETTINGS ---
ENABLE_NEWS_FILTER = False      
# "WAR" has been removed to prevent false alarms
PANIC_KEYWORDS = ['hack', 'banned', 'sec lawsuit', 'investigation', 'insolvent', 'arrested', 'collapse']

# EXPERT SETTINGS
RISK_PER_TRADE = 5.0        
MAX_POSITION_SIZE = 50.0    
ATR_MULTIPLIER_SL = 2.0     
ATR_MULTIPLIER_TP = 4.0     

# --- LOGGING SETUP (Now saves to file!) ---
init(autoreset=True)
# Create handlers
file_handler = logging.FileHandler('master_bot.log')
stream_handler = logging.StreamHandler()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[file_handler, stream_handler]
)
logger = logging.getLogger("GOD-MODE")

# --- SHARED GLOBAL STATE ---
swing_watchlist = []
scalp_watchlist = []
MARKET_LOCKDOWN = False

class NewsSentinel:
    """GOD MODE (RSS VERSION): Bypasses API blocks to read news"""
    def __init__(self):
        self.rss_url = "https://cryptopanic.com/news/rss/"
        
    def run(self):
        global MARKET_LOCKDOWN
        if not ENABLE_NEWS_FILTER:
            logger.warning("⚠️ God Mode News Filter is DISABLED.")
            return

        logger.info("👁️ NEWS SENTINEL: Watching RSS Feed for black swan events...")
        
        while True:
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                response = requests.get(self.rss_url, headers=headers, timeout=10)
                
                if response.status_code != 200:
                    logger.warning(f"News Feed Error: Status {response.status_code}")
                    time.sleep(300)
                    continue

                raw_data = response.text.lower()
                panic_detected = False
                trigger_word = ""

                for word in PANIC_KEYWORDS:
                    if word in raw_data:
                        if raw_data.find(word) < 4000: 
                            panic_detected = True
                            trigger_word = word
                            break
                
                if panic_detected:
                    if not MARKET_LOCKDOWN:
                        logger.error(f"🛑 GOD MODE ACTIVATED: '{trigger_word.upper()}' detected in news!")
                        logger.error("🛑 MARKET LOCKDOWN ENGAGED (Pausing Buys)")
                    MARKET_LOCKDOWN = True
                else:
                    if MARKET_LOCKDOWN:
                        logger.info(f"✅ News Clear. Lifting Lockdown.")
                    MARKET_LOCKDOWN = False
                    
            except Exception as e:
                logger.error(f"News Scan Error: {e}")
            time.sleep(300)

class MarketScanner:
    def __init__(self):
        self.exchange = ccxt.bybit()

    def run(self):
        global swing_watchlist, scalp_watchlist
        logger.info("📡 SCANNER: Initialized.")
        while True:
            try:
                tickers = self.exchange.fetch_tickers()
                valid = []
                for s, d in tickers.items():
                    if "/USDT:USDT" not in s: continue
                    if d['quoteVolume'] is None or d['quoteVolume'] < 5000000: continue
                    valid.append({'symbol': s, 'vol': d['quoteVolume'], 'chg': abs(d['percentage'] or 0)})
                
                valid.sort(key=lambda x: x['vol'], reverse=True)
                swing_watchlist = [x['symbol'] for x in valid[:12]]
                
                scalp_cands = [x for x in valid if x['symbol'] not in swing_watchlist]
                scalp_cands.sort(key=lambda x: x['chg'], reverse=True)
                scalp_watchlist = [x['symbol'] for x in scalp_cands[:12]]
                
                logger.info(f"💎 Lists Updated: {len(swing_watchlist)} Swing | {len(scalp_watchlist)} Scalp")
            except: pass
            time.sleep(3600)

class BotInstance:
    def __init__(self, name, interval):
        self.name = name
        self.interval = interval
        self.exchange = ccxt.bybit({
            'apiKey': API_KEY, 'secret': API_SECRET,
            'enableRateLimit': True, 'options': {'defaultType': 'swap'}
        })

    def get_atr(self, symbol, period=14):
        try:
            timeframe = '15m' if self.interval == Interval.INTERVAL_15_MINUTES else '5m'
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=period+5)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'vol'])
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=period)
            return df['atr'].iloc[-1]
        except: return None

    def manage_positions(self):
        try:
            positions = self.exchange.fetch_positions()
            for p in positions:
                if float(p.get('contracts', 0)) == 0: continue
                symbol = p['symbol']
                current_coins = swing_watchlist if self.name == "SWING" else scalp_watchlist
                if symbol.split('/')[0] + "/USDT:USDT" not in current_coins: continue

                entry = float(p['entryPrice'])
                curr_price = float(p['markPrice'])
                stop_loss = float(p.get('stopLoss', 0))
                side = p['side']
                
                if stop_loss == 0: continue
                atr = self.get_atr(symbol)
                if not atr: continue
                trail_dist = atr * ATR_MULTIPLIER_SL 
                
                if side == 'long':
                    new_sl = curr_price - trail_dist
                    if new_sl > stop_loss and new_sl > entry:
                        self.exchange.set_trading_stop(symbol, params={'stopLoss': str(new_sl)})
                        logger.info(f"🚀 {self.name} TRAILING SL UP: {symbol} -> {new_sl:.4f}")
                elif side == 'short':
                    new_sl = curr_price + trail_dist
                    if new_sl < stop_loss and new_sl < entry:
                        self.exchange.set_trading_stop(symbol, params={'stopLoss': str(new_sl)})
                        logger.info(f"📉 {self.name} TRAILING SL DOWN: {symbol} -> {new_sl:.4f}")
        except: pass

    def execute_trade(self, symbol, signal):
        if MARKET_LOCKDOWN and signal == 'BUY':
            logger.warning(f"🛡️ GOD MODE BLOCKED BUY on {symbol} (News Lockdown)")
            return

        try:
            positions = self.exchange.fetch_positions()
            for p in positions:
                if p['symbol'] == symbol and float(p['contracts']) > 0: return

            ticker = self.exchange.fetch_ticker(symbol)
            price = ticker['last']
            atr = self.get_atr(symbol)
            if not atr: return

            if signal == 'BUY':
                sl = price - (atr * ATR_MULTIPLIER_SL)
                tp = price + (atr * ATR_MULTIPLIER_TP)
                side = 'buy'
            else:
                sl = price + (atr * ATR_MULTIPLIER_SL)
                tp = price - (atr * ATR_MULTIPLIER_TP)
                side = 'sell'

            size = RISK_PER_TRADE / (atr * ATR_MULTIPLIER_SL)
            cost = size * price
            if cost > MAX_POSITION_SIZE: size = MAX_POSITION_SIZE / price

            params = {'stopLoss': str(self.exchange.price_to_precision(symbol, sl)), 'takeProfit': str(self.exchange.price_to_precision(symbol, tp))}
            if side == 'buy': self.exchange.create_market_buy_order(symbol, size, params=params)
            else: self.exchange.create_market_sell_order(symbol, size, params=params)
            logger.info(f"✅ ENTRY: {self.name} OPENED {symbol} {side.upper()}")
        except Exception as e:
            logger.error(f"❌ Exec Error: {e}")

    def run(self):
        logger.info(f"🟢 {self.name} Bot Started")
        while True:
            self.manage_positions()
            current_coins = swing_watchlist if self.name == "SWING" else scalp_watchlist
            if not current_coins:
                time.sleep(10)
                continue

            for symbol in current_coins:
                try:
                    tv_symbol = symbol.split('/')[0] + "USDT"
                    handler = TA_Handler(symbol=tv_symbol, exchange="BYBIT", screener="CRYPTO", interval=self.interval)
                    res = handler.get_analysis()
                    rec = res.summary['RECOMMENDATION']
                    rsi = res.indicators.get('RSI', 50)
                    macd = res.indicators.get('MACD.macd', 0)
                    sig = res.indicators.get('MACD.signal', 0)

                    if "BUY" in rec and rsi < 70 and macd > sig: self.execute_trade(symbol, 'BUY')
                    elif "SELL" in rec and rsi > 30 and macd < sig: self.execute_trade(symbol, 'SELL')
                    time.sleep(2)
                except: pass
            
            time.sleep(60 if self.name == "SCALP" else 300)

if __name__ == "__main__":
    scanner = MarketScanner()
    news = NewsSentinel() 
    swing = BotInstance("SWING", Interval.INTERVAL_15_MINUTES)
    scalp = BotInstance("SCALP", Interval.INTERVAL_5_MINUTES)

    threading.Thread(target=scanner.run, name="SCANNER").start()
    threading.Thread(target=news.run, name="NEWS").start()
    time.sleep(5)
    threading.Thread(target=swing.run, name="SWING").start()
    threading.Thread(target=scalp.run, name="SCALP").start()
