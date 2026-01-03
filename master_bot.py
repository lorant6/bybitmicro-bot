import threading, time, json, logging, os, requests, pandas as pd, pandas_ta as ta, datetime, hmac, hashlib, sys, urllib.parse
import config 

# --- CONFIG ---
API_KEY = config.API_KEY
API_SECRET = config.API_SECRET
TELEGRAM_TOKEN = config.TELEGRAM_TOKEN
TARGET_CHAT_ID = "1143478179"
BASE_DIR = os.getcwd()
SETTINGS_FILE = os.path.join(BASE_DIR, "live_settings.json")
LOG_FILE = os.path.join(BASE_DIR, "bot_v33.log")

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])

# --- SETTINGS & STATE ---
live_settings = {
    "GLOBAL_STOP": True,       # Safety: Start PAUSED
    "RISK_PER_TRADE": 2.0,     # USDT Margin per trade
    "MAX_OPEN_POSITIONS": 5,   # PRO FEATURE: Max concurrent trades
    "LEVERAGE": 10,
    "ADX_THRESHOLD": 25.0
}

# --- PRO PARAMETERS ---
SCALP_TARGETS = ["SOLUSDT", "DOGEUSDT", "PEPEUSDT", "SUIUSDT", "WIFUSDT", "AVAXUSDT", "OPUSDT", "1000BONKUSDT"]
# Scalp: Tight stops, fast activation
SCALP_CONF = {"interval": "15", "sl_atr": 2.0, "trail_active_atr": 1.0, "trail_cb_atr": 0.3}

SWING_TARGETS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "LTCUSDT"]
# Swing: Wide stops, slow activation
SWING_CONF = {"interval": "60", "sl_atr": 3.0, "trail_active_atr": 2.0, "trail_cb_atr": 1.0}

# Anti-Chop Cooldown (Minutes)
COOLDOWN_MINUTES = 90 

scan_cache = {}
active_symbols = []
last_trade_time = {} # Tracks when a coin was last traded
wallet_snapshot_24h = 0.0 
global_btc_trend = "NEUTRAL" 

def save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f: json.dump(live_settings, f, indent=4)
    except: pass

if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r") as f: live_settings.update(json.load(f))
    except: pass

# --- BYBIT API ---
class BybitPrivate:
    BASE_URL = "https://api.bybit.com"
    
    @staticmethod
    def send_signed(method, endpoint, payload={}):
        try:
            ts = str(int(time.time() * 1000)); recv_window = "5000"
            if method == "GET": param_str = urllib.parse.urlencode(payload); sign_str = ts+API_KEY+recv_window+param_str
            else: param_str = json.dumps(payload); sign_str = ts+API_KEY+recv_window+param_str
            signature = hmac.new(bytes(API_SECRET, "utf-8"), sign_str.encode("utf-8"), hashlib.sha256).hexdigest()
            headers = {"X-BAPI-API-KEY": API_KEY, "X-BAPI-SIGN": signature, "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": recv_window, "Content-Type": "application/json"}
            url = f"{BybitPrivate.BASE_URL}{endpoint}"
            if method == "GET": return requests.get(url, headers=headers, params=payload, timeout=5).json()
            else: return requests.post(url, headers=headers, data=param_str, timeout=5).json()
        except Exception as e: logging.error(f"API Error: {e}"); return None

    @staticmethod
    def get_balance():
        try:
            r = BybitPrivate.send_signed("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED", "coin": "USDT"})
            return float(r['result']['list'][0]['coin'][0]['walletBalance'])
        except: return 0.0
    
    @staticmethod
    def get_open_positions():
        try:
            r = BybitPrivate.send_signed("GET", "/v5/position/list", {"category": "linear", "settleCoin": "USDT"})
            return [p['symbol'] for p in r['result']['list'] if float(p['size']) > 0]
        except: return []

    @staticmethod
    def set_trading_stop(symbol, entry_price, side, atr_value, conf):
        sl_dist = atr_value * conf['sl_atr']
        trail_active_dist = atr_value * conf['trail_active_atr']
        trail_cb_dist = atr_value * conf['trail_cb_atr']

        if side == "Buy":
            sl_price = entry_price - sl_dist
            activation_price = entry_price + trail_active_dist
        else: 
            sl_price = entry_price + sl_dist
            activation_price = entry_price - trail_active_dist
        
        BybitPrivate.send_signed("POST", "/v5/position/trading-stop", {"category": "linear", "symbol": symbol, "stopLoss": str(round(sl_price, 4)), "positionIdx": 0})
        BybitPrivate.send_signed("POST", "/v5/position/trading-stop", {"category": "linear", "symbol": symbol, "activationPrice": str(round(activation_price, 4)), "trailingStop": str(round(trail_cb_dist, 4)), "positionIdx": 0})
        logging.info(f"🛡️ PROTECTED {symbol}")

    @staticmethod
    def place_order(symbol, side, price, atr_value, conf):
        qty_calc = (live_settings['RISK_PER_TRADE'] * live_settings['LEVERAGE']) / price
        if price > 100: qty = round(qty_calc, 3)
        elif price > 1: qty = round(qty_calc, 1)
        else: qty = int(qty_calc)

        BybitPrivate.send_signed("POST", "/v5/position/set-leverage", {"category":"linear","symbol":symbol,"buyLeverage":str(live_settings['LEVERAGE']),"sellLeverage":str(live_settings['LEVERAGE'])})
        payload = {"category": "linear", "symbol": symbol, "side": side, "orderType": "Market", "qty": str(qty)}
        res = BybitPrivate.send_signed("POST", "/v5/order/create", payload)
        
        if res and res.get('retCode') == 0:
            time.sleep(2) 
            BybitPrivate.set_trading_stop(symbol, price, side, atr_value, conf)
            return True
        return False

    @staticmethod
    def kill_all():
        BybitPrivate.send_signed("POST", "/v5/order/cancel-all", {"category": "linear", "settleCoin": "USDT"})
        res = BybitPrivate.send_signed("GET", "/v5/position/list", {"category": "linear", "settleCoin": "USDT"})
        for p in res['result']['list']:
            if float(p['size']) > 0:
                payload = {"category": "linear", "symbol": p['symbol'], "side": "Buy" if p['side'] == "Sell" else "Sell", "orderType": "Market", "qty": p['size'], "reduceOnly": True}
                BybitPrivate.send_signed("POST", "/v5/order/create", payload)
        return True

# --- EXPERT ENGINE ---
class ExpertEngine:
    @staticmethod
    def check_btc_trend():
        try:
            url = "https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=60&limit=200"
            res = requests.get(url, timeout=3).json()
            df = pd.DataFrame(res['result']['list'][::-1], columns=['ts','o','h','l','c','v','t'])
            df['c'] = pd.to_numeric(df['c'])
            return "BULL" if df['c'].iloc[-1] > ta.ema(df['c'], length=200).iloc[-1] else "BEAR"
        except: return "NEUTRAL"

    @staticmethod
    def get_market_info(symbol, interval):
        try:
            url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit=200"
            res = requests.get(url, timeout=3).json()
            df = pd.DataFrame(res['result']['list'][::-1], columns=['ts','o','h','l','c','v','t'])
            df[['h','l','c','v']] = df[['h','l','c','v']].apply(pd.to_numeric)
            
            adx = ta.adx(df['h'], df['l'], df['c'])['ADX_14'].iloc[-1]
            rsi = ta.rsi(df['c'], length=14).iloc[-1]
            ema200 = ta.ema(df['c'], length=200).iloc[-1]
            macd = ta.macd(df['c'])
            macd_h = macd['MACDh_12_26_9'].iloc[-1]
            atr = ta.atr(df['h'], df['l'], df['c'], length=14).iloc[-1]
            vol_ma = ta.sma(df['v'], length=20).iloc[-1]
            
            price = df['c'].iloc[-1]
            curr_vol = df['v'].iloc[-1]
            signal = "WAIT"

            # FILTER 1: Vol & Trend
            if adx > live_settings['ADX_THRESHOLD'] and curr_vol > vol_ma:
                # FILTER 2: Global Trend & RSI Check
                if (price > ema200) and (macd_h > 0) and (50 < rsi < 70) and global_btc_trend == "BULL":
                    signal = "LONG"
                elif (price < ema200) and (macd_h < 0) and (30 < rsi < 50) and global_btc_trend == "BEAR":
                    signal = "SHORT"
            
            return {"adx": adx, "slope": signal, "price": price, "atr": atr}
        except: return None

# --- TELEGRAM BOT ---
class TelegramBot:
    def __init__(self):
        self.url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
        self.offset = 0
        self.refresh_ui()

    def refresh_ui(self):
        requests.post(f"{self.url}/deleteMyCommands")
        time.sleep(1)
        cmds = [
            {"command": "status", "description": "📊 Status"},
            {"command": "scan", "description": "🔍 Market Heatmap"},
            {"command": "balance", "description": "💰 Balance"},
            {"command": "risk", "description": "⚙️ Set Risk ($)"},
            {"command": "adx", "description": "🛡️ Set ADX"},
            {"command": "resume", "description": "🟢 START"},
            {"command": "pause", "description": "🛑 STOP"},
            {"command": "kill", "description": "⚠️ KILL POSITIONS"},
            {"command": "reboot", "description": "♻️ Reboot"}
        ]
        requests.post(f"{self.url}/setMyCommands", json={"commands": cmds})

    def send(self, msg):
        requests.post(f"{self.url}/sendMessage", json={"chat_id": TARGET_CHAT_ID, "text": msg, "parse_mode": "Markdown"})

    def handle(self, text):
        global live_settings
        args = text.split()
        cmd = args[0].lower() if args else ""
        
        if cmd == "/status":
            st = '🛑 PAUSED' if live_settings['GLOBAL_STOP'] else '🟢 LIVE'
            self.send(f"📊 **V35.00 PORTFOLIO MANAGER**\nState: {st}\n🌍 BTC Trend: **{global_btc_trend}**\n🔒 Max Pos: `{live_settings['MAX_OPEN_POSITIONS']}`\n💰 Risk: `${live_settings['RISK_PER_TRADE']}`")
        
        elif cmd == "/scan":
            if not scan_cache: self.send("⏳ Syncing..."); return
            m = f"**🧗 MARKET: {global_btc_trend}**\n```\nSym          Mode   Sig\n" + "-"*26 + "\n"
            for s, d in list(scan_cache.items())[:15]: m += f"{s:<12} {d['mode'][:5]}  {d['slope']}\n"
            self.send(m + "```")

        elif cmd == "/balance":
            bal = BybitPrivate.get_balance()
            self.send(f"💰 Balance: `${bal:.2f}`\nTrades: {len(active_symbols)}/{live_settings['MAX_OPEN_POSITIONS']}")

        elif cmd == "/risk":
            if len(args) > 1:
                try: live_settings['RISK_PER_TRADE'] = float(args[1]); save_settings(); self.send(f"✅ Risk: `${live_settings['RISK_PER_TRADE']}`")
                except: pass
            else: self.send(f"Current Risk: `${live_settings['RISK_PER_TRADE']}`")

        elif cmd == "/adx":
            if len(args) > 1:
                try: live_settings['ADX_THRESHOLD'] = float(args[1]); save_settings(); self.send(f"✅ ADX: `{live_settings['ADX_THRESHOLD']}`")
                except: pass

        elif cmd == "/pause":
            live_settings['GLOBAL_STOP'] = True; save_settings(); self.send("🛑 **PAUSED**")
        
        elif cmd == "/resume":
            live_settings['GLOBAL_STOP'] = False; save_settings(); self.send("🟢 **LIVE**")

        elif cmd == "/kill":
            self.send("⚠️ **KILLING ALL...**"); BybitPrivate.kill_all(); self.send("✅ Done.")

        elif cmd == "/reboot":
            self.send("♻️ Rebooting..."); time.sleep(1); sys.exit(0)

    def poll(self):
        while True:
            try:
                r = requests.get(f"{self.url}/getUpdates?offset={self.offset}&timeout=10", timeout=15).json()
                for u in r.get("result", []):
                    self.offset = u["update_id"] + 1
                    if "message" in u and "text" in u["message"]: self.handle(u["message"]["text"])
            except: time.sleep(2)

# --- PORTFOLIO LOOP ---
def scanner_loop():
    global scan_cache, active_symbols, global_btc_trend, last_trade_time
    bot_ui = TelegramBot()
    
    while True:
        global_btc_trend = ExpertEngine.check_btc_trend()
        previous_symbols = set(active_symbols)
        active_symbols = BybitPrivate.get_open_positions()
        
        # Detect Closed Trades -> Start Cooldown
        for s in previous_symbols:
            if s not in active_symbols:
                last_trade_time[s] = time.time()
                logging.info(f"COOLDOWN STARTED: {s}")

        if live_settings['GLOBAL_STOP']: time.sleep(5); continue
            
        try:
            tmp = {}
            # --- SCALP SCAN ---
            for symbol in SCALP_TARGETS:
                # 1. Check if already open
                if symbol in active_symbols: continue
                # 2. Check Cooldown (Anti-Chop)
                if time.time() - last_trade_time.get(symbol, 0) < (COOLDOWN_MINUTES * 60): continue
                # 3. Check Max Positions
                if len(active_symbols) >= live_settings['MAX_OPEN_POSITIONS']: continue

                data = ExpertEngine.get_market_info(symbol, SCALP_CONF['interval'])
                if data:
                    tmp[symbol] = {**data, "mode": "SCALP"}
                    if data['slope'] != "WAIT":
                        if BybitPrivate.place_order(symbol, "Buy" if data['slope']=="LONG" else "Sell", data['price'], data['atr'], SCALP_CONF):
                            bot_ui.send(f"⚡ **SCALP ENTRY: {symbol}**\nSig: {data['slope']} | ATR: {data['atr']:.4f}")
                            active_symbols.append(symbol)

            # --- SWING SCAN ---
            for symbol in SWING_TARGETS:
                if symbol in active_symbols: continue
                if time.time() - last_trade_time.get(symbol, 0) < (COOLDOWN_MINUTES * 60): continue
                if len(active_symbols) >= live_settings['MAX_OPEN_POSITIONS']: continue

                data = ExpertEngine.get_market_info(symbol, SWING_CONF['interval'])
                if data:
                    tmp[symbol] = {**data, "mode": "SWING"}
                    if data['slope'] != "WAIT":
                        if BybitPrivate.place_order(symbol, "Buy" if data['slope']=="LONG" else "Sell", data['price'], data['atr'], SWING_CONF):
                            bot_ui.send(f"🐢 **SWING ENTRY: {symbol}**\nSig: {data['slope']} | ATR: {data['atr']:.4f}")
                            active_symbols.append(symbol)

            scan_cache = tmp
            logging.info(f"Scan Done. BTC: {global_btc_trend} | Active: {len(active_symbols)}")
            time.sleep(60)
        except Exception as e: logging.error(f"Scan Error: {e}"); time.sleep(10)

if __name__ == "__main__":
    print("🚀 BOT V35.00 PORTFOLIO MANAGER STARTING...")
    t_bot = TelegramBot()
    threading.Thread(target=t_bot.poll, daemon=True).start()
    threading.Thread(target=scanner_loop, daemon=True).start()
    while True: time.sleep(1)