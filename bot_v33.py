import threading, time, json, logging, os, requests, pandas as pd, pandas_ta as ta, datetime, hmac, hashlib, sys, urllib.parse, csv
import config 

# --- CONFIG ---
API_KEY = config.API_KEY
API_SECRET = config.API_SECRET
TELEGRAM_TOKEN = config.TELEGRAM_TOKEN
TARGET_CHAT_ID = "1143478179"
BASE_DIR = os.getcwd()
SETTINGS_FILE = os.path.join(BASE_DIR, "live_settings.json")
LOG_FILE = os.path.join(BASE_DIR, "bot_v33.log")
DATA_FILE = os.path.join(BASE_DIR, "trade_history.csv")
PARDON_FILE = os.path.join(BASE_DIR, "pardoned.json")

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])

# --- SETTINGS & STATE ---
live_settings = {
    "GLOBAL_STOP": True,       
    "RISK_PER_TRADE": 4.0,     
    "MAX_OPEN_POSITIONS": 5,   
    "LEVERAGE": 5,             
    "ADX_THRESHOLD": 25.0,
    "DAILY_LOSS_LIMIT": -7.0,  
    "DAILY_PROFIT_GOAL": 15.0, 
    "MAX_FUNDING_RATE": 0.001, 
    "STALEMATE_HOURS": 4,      
    "GOD_MODE": True,
    "AUTO_SCALE": True,
    "PAUSE_UNTIL": 0 # New: For Circuit Breaker
}

# --- DYNAMIC LISTS & DATA ---
SCALP_TARGETS = []
SWING_TARGETS = []
fear_greed_index = {"value": 50, "label": "Neutral"} 
recent_losses_timestamps = [] # New: Track loss velocity

# --- STRATEGY CONFIG (FIXED FOR PROFIT TAKING) ---
# Hard Stop is WIDE (3.0), but Trailing Activates EARLY (0.5)
SCALP_CONF = {"interval": "15", "sl_atr": 3.0, "trail_active_atr": 0.5, "trail_cb_atr": 0.5}
SWING_CONF = {"interval": "60", "sl_atr": 5.0, "trail_active_atr": 1.5, "trail_cb_atr": 1.0}

COOLDOWN_MINUTES = 90 
scan_cache = {}
active_symbols = [] 
last_trade_time = {}      
last_entry_time = {}      
processed_trades = set()  
entry_data_log = {} 
global_btc_trend = "NEUTRAL"
last_market_update = 0
daily_pnl = 0.0
win_rate = 0.0
wins = 0
losses = 0

# --- MEMORY ---
loss_streak = {}     
blacklisted = {}
pardoned_coins = {}

def save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f: json.dump(live_settings, f, indent=4)
    except: pass

if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r") as f: live_settings.update(json.load(f))
    except: pass

# --- CIRCUIT BREAKER (STRIKE 3) ---
def check_loss_circuit_breaker():
    global recent_losses_timestamps, live_settings
    now = time.time()
    # Keep only losses from the last 60 minutes
    recent_losses_timestamps = [t for t in recent_losses_timestamps if now - t < 3600]
    
    if len(recent_losses_timestamps) >= 3:
        live_settings['PAUSE_UNTIL'] = now + 7200 # Pause for 2 hours
        save_settings()
        return True
    return False

# --- INTERNET SENSOR ---
def fetch_fear_and_greed():
    global fear_greed_index
    try:
        url = "https://api.alternative.me/fng/"
        r = requests.get(url, timeout=5).json()
        data = r['data'][0]
        fear_greed_index = {"value": int(data['value']), "label": data['value_classification']}
        logging.info(f"🌍 INTERNET SENSOR: {fear_greed_index['label']} ({fear_greed_index['value']})")
    except Exception as e:
        logging.error(f"Sensor Error: {e}")

# --- PARDON SYSTEM ---
def load_pardons():
    global pardoned_coins
    if os.path.exists(PARDON_FILE):
        try:
            with open(PARDON_FILE, "r") as f: pardoned_coins = json.load(f)
            now = time.time()
            pardoned_coins = {k:v for k,v in pardoned_coins.items() if now - v < 86400}
        except: pardoned_coins = {}

def save_pardon(symbol):
    pardoned_coins[symbol] = time.time()
    try:
        with open(PARDON_FILE, "w") as f: json.dump(pardoned_coins, f)
    except: pass

# --- BLACK BOX RECORDER ---
def init_csv():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Time", "Symbol", "Mode", "Side", "RSI", "ADX", "ATR", "Trend", "EntryPrice", "ExitPrice", "PnL", "Result"])

def log_trade_entry(symbol, mode, side, rsi, adx, atr, trend, price):
    entry_data_log[symbol] = {
        "Time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Mode": mode,
        "Side": side,
        "RSI": rsi,
        "ADX": adx,
        "ATR": atr,
        "Trend": trend,
        "EntryPrice": price
    }

def log_trade_exit(symbol, exit_price, pnl):
    if symbol in entry_data_log:
        d = entry_data_log[symbol]
        result = 1 if pnl > 0 else 0
        with open(DATA_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([d["Time"], symbol, d["Mode"], d["Side"], d["RSI"], d["ADX"], d["ATR"], d["Trend"], d["EntryPrice"], exit_price, pnl, result])
        del entry_data_log[symbol] 

# --- AUTO SCALER ---
def adjust_risk_based_on_performance(pnl):
    global wins, losses, win_rate, recent_losses_timestamps
    if pnl > 0: 
        wins += 1
    else: 
        losses += 1
        recent_losses_timestamps.append(time.time()) # Add timestamp of loss
        
    total = wins + losses
    if total < 5: return 

    win_rate = (wins / total) * 100
    if not live_settings['AUTO_SCALE']: return

    current_risk = live_settings['RISK_PER_TRADE']
    if win_rate > 60:
        new_risk = min(current_risk * 1.1, 10.0) 
        if new_risk != current_risk:
            live_settings['RISK_PER_TRADE'] = round(new_risk, 2)
            save_settings()
    elif win_rate < 40:
        new_risk = max(current_risk * 0.9, 1.0) 
        if new_risk != current_risk:
            live_settings['RISK_PER_TRADE'] = round(new_risk, 2)
            save_settings()

def smart_round(num):
    if num == 0: return "0"
    if num > 1000: return str(int(num))
    if num > 1: return f"{num:.2f}"
    if num > 0.01: return f"{num:.4f}"
    return f"{num:.8f}".rstrip("0")

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
    def get_closed_pnl_history():
        try:
            res = BybitPrivate.send_signed("GET", "/v5/position/closed-pnl", {"category": "linear", "limit": 50})
            data = res['result']['list']
            return data[::-1] if data else []
        except: return []

    @staticmethod
    def get_today_pnl():
        try:
            start_time = int((time.time() - 86400) * 1000)
            res = BybitPrivate.send_signed("GET", "/v5/position/closed-pnl", {"category": "linear", "limit": 50, "startTime": str(start_time)})
            total = 0.0
            for trade in res['result']['list']:
                total += float(trade['closedPnl'])
            return total
        except: return 0.0

    @staticmethod
    def get_open_positions_details():
        try:
            r = BybitPrivate.send_signed("GET", "/v5/position/list", {"category": "linear", "settleCoin": "USDT"})
            positions = {}
            for p in r['result']['list']:
                if float(p['size']) > 0:
                    positions[p['symbol']] = {
                        "size": p['size'], 
                        "pnl": float(p['unrealisedPnl']),
                        "created": int(p['createdTime'])
                    }
            return positions
        except: return {}
    
    @staticmethod
    def close_position(symbol):
        try:
            res = BybitPrivate.send_signed("GET", "/v5/position/list", {"category": "linear", "symbol": symbol})
            for p in res['result']['list']:
                if float(p['size']) > 0:
                    payload = {"category": "linear", "symbol": symbol, "side": "Buy" if p['side'] == "Sell" else "Sell", "orderType": "Market", "qty": p['size'], "reduceOnly": True}
                    BybitPrivate.send_signed("POST", "/v5/order/create", payload)
            return True
        except: return False

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
        
        payload_sl = {"category": "linear", "symbol": symbol, "stopLoss": smart_round(sl_price), "positionIdx": 0}
        payload_ts = {"category": "linear", "symbol": symbol, "activationPrice": smart_round(activation_price), "trailingStop": smart_round(trail_cb_dist), "positionIdx": 0}
        
        BybitPrivate.send_signed("POST", "/v5/position/trading-stop", payload_sl)
        time.sleep(0.2)
        BybitPrivate.send_signed("POST", "/v5/position/trading-stop", payload_ts)
        logging.info(f"🛡️ PROTECTED {symbol}")

    @staticmethod
    def place_order(symbol, side, price, atr_value, conf, multiplier=1.0, data_log=None):
        sentiment_mult = 1.0
        val = fear_greed_index['value']
        if val < 20: sentiment_mult = 1.25 
        elif val > 75: sentiment_mult = 0.75 
        
        final_risk = live_settings['RISK_PER_TRADE'] * multiplier * sentiment_mult
        qty_calc = (final_risk * live_settings['LEVERAGE']) / price
        
        if price > 100: qty = round(qty_calc, 3)
        elif price > 1: qty = round(qty_calc, 1)
        else: qty = int(qty_calc)

        BybitPrivate.send_signed("POST", "/v5/position/set-leverage", {"category":"linear","symbol":symbol,"buyLeverage":str(live_settings['LEVERAGE']),"sellLeverage":str(live_settings['LEVERAGE'])})
        payload = {"category": "linear", "symbol": symbol, "side": side, "orderType": "Market", "qty": str(qty)}
        res = BybitPrivate.send_signed("POST", "/v5/order/create", payload)
        
        if res and res.get('retCode') == 0:
            time.sleep(2) 
            BybitPrivate.set_trading_stop(symbol, price, side, atr_value, conf)
            if data_log:
                log_trade_entry(symbol, data_log['mode'], side, data_log['rsi'], data_log['adx'], data_log['atr'], data_log['trend'], price)
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

# --- MARKET SELECTOR ---
class MarketSelector:
    @staticmethod
    def refresh_lists():
        global SCALP_TARGETS, SWING_TARGETS
        logging.info("🧠 SMART ENGINE: Analyzing Market...")
        try:
            url = "https://api.bybit.com/v5/market/tickers?category=linear"
            res = requests.get(url, timeout=5).json()
            valid = [t for t in res['result']['list'] if t['symbol'].endswith('USDT') and 'USDC' not in t['symbol']]
            valid.sort(key=lambda x: float(x['turnover24h']), reverse=True)
            top_40 = valid[:40]
            
            scored_coins = []
            for t in top_40:
                funding = float(t.get('fundingRate', 0))
                if abs(funding) > live_settings['MAX_FUNDING_RATE']: continue 
                
                h = float(t['highPrice24h'])
                l = float(t['lowPrice24h'])
                volatility = (h - l) / l if l > 0 else 0
                scored_coins.append({'s': t['symbol'], 'v': volatility})
            
            scored_coins.sort(key=lambda x: x['v'], reverse=True)
            SCALP_TARGETS = [x['s'] for x in scored_coins[:20]]
            SWING_TARGETS = [x['s'] for x in scored_coins[20:]]
            return True
        except:
            if not SCALP_TARGETS: SCALP_TARGETS[:], SWING_TARGETS[:] = ["SOLUSDT"], ["BTCUSDT"]
            return False

# --- EXPERT ENGINE (GOD MODE) ---
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
    def get_trend_only(symbol, interval):
        try:
            url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit=50"
            res = requests.get(url, timeout=3).json()
            df = pd.DataFrame(res['result']['list'][::-1], columns=['ts','o','h','l','c','v','t'])
            df['c'] = pd.to_numeric(df['c'])
            ema = ta.ema(df['c'], length=50).iloc[-1]
            price = df['c'].iloc[-1]
            return "BULL" if price > ema else "BEAR"
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
            curr_vol = df['v'].iloc[-1]
            vol_multiplier = 1.0
            if curr_vol > (vol_ma * 2.0): vol_multiplier = 1.5 
            
            price = df['c'].iloc[-1]
            signal = "WAIT"

            if adx > live_settings['ADX_THRESHOLD'] and curr_vol > vol_ma:
                if (price > ema200) and (macd_h > 0) and (50 < rsi < 70) and global_btc_trend == "BULL":
                    signal = "LONG"
                elif (price < ema200) and (macd_h < 0) and (30 < rsi < 50) and global_btc_trend == "BEAR":
                    signal = "SHORT"
            
            return {"adx": adx, "slope": signal, "price": price, "atr": atr, "vol_mult": vol_multiplier, "rsi": rsi}
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
            {"command": "report", "description": "📈 Daily PnL"},
            {"command": "risk", "description": "🎲 Set Risk ($)"},
            {"command": "adx", "description": "📉 Set ADX"},
            {"command": "lev", "description": "⚙️ Set Leverage"},
            {"command": "black", "description": "☠️ Blacklist"},
            {"command": "unban", "description": "✨ Unban Coin"},
            {"command": "close", "description": "✂️ Close Coin"},
            {"command": "limit", "description": "🛑 Loss Limit"},
            {"command": "goal", "description": "🏆 Profit Goal"},
            {"command": "balance", "description": "💰 Balance"},
            {"command": "positions", "description": "📋 Trades"},
            {"command": "resume", "description": "🟢 START"},
            {"command": "pause", "description": "🛑 STOP"},
            {"command": "kill", "description": "⚠️ KILL ALL"}
        ]
        requests.post(f"{self.url}/setMyCommands", json={"commands": cmds})

    def send(self, msg):
        requests.post(f"{self.url}/sendMessage", json={"chat_id": TARGET_CHAT_ID, "text": msg, "parse_mode": "Markdown"})

    def handle(self, text):
        global live_settings, blacklisted, loss_streak
        args = text.split()
        cmd = args[0].lower() if args else ""
        
        if cmd == "/status":
            now = time.time()
            if live_settings.get('PAUSE_UNTIL', 0) > now:
                mins = int((live_settings['PAUSE_UNTIL'] - now) / 60)
                st = f"⛔ **CIRCUIT BREAKER ({mins}m left)**"
            else:
                st = '🛑 PAUSED' if live_settings['GLOBAL_STOP'] else '🟢 LIVE'
            
            self.send(f"🤖 **V60.00 SMART TRAIL + BREAKER**\nState: {st}\n🌍 BTC: **{global_btc_trend}**\n🧠 Mood: **{fear_greed_index['label']}** ({fear_greed_index['value']})\n📉 PnL: `${daily_pnl:.2f}`\n💰 Risk: `${live_settings['RISK_PER_TRADE']}`\n📈 WinRate: `{win_rate:.1f}%`")
        
        elif cmd == "/risk":
            if len(args) > 1:
                try: 
                    live_settings['RISK_PER_TRADE'] = float(args[1])
                    save_settings()
                    self.send(f"✅ Risk updated: `${live_settings['RISK_PER_TRADE']}`")
                except: pass
            else: self.send(f"Current Risk: `${live_settings['RISK_PER_TRADE']}`")

        elif cmd == "/adx":
            if len(args) > 1:
                try: 
                    live_settings['ADX_THRESHOLD'] = float(args[1])
                    save_settings()
                    self.send(f"✅ ADX Threshold: `{live_settings['ADX_THRESHOLD']}`")
                except: pass
            else: self.send(f"Current ADX: `{live_settings['ADX_THRESHOLD']}`")

        elif cmd == "/lev":
            if len(args) > 1:
                try: 
                    live_settings['LEVERAGE'] = int(args[1])
                    save_settings()
                    self.send(f"✅ Leverage: `{live_settings['LEVERAGE']}x`")
                except: pass
            else: self.send(f"Current Leverage: `{live_settings['LEVERAGE']}x`")

        elif cmd == "/close":
            if len(args) > 1:
                symbol_fragment = args[1].upper()
                found = None
                for s in active_symbols:
                    if symbol_fragment in s: found = s; break
                if found:
                    self.send(f"✂️ Closing **{found}**...")
                    BybitPrivate.close_position(found)
                    self.send(f"✅ {found} Closed.")
                else: self.send(f"❌ Not found: {symbol_fragment}")
            else: self.send("⚠️ Usage: `/close PEPE`")

        elif cmd == "/unban":
            if len(args) > 1:
                symbol_fragment = args[1].upper()
                target = None
                for b in blacklisted:
                    if symbol_fragment in b: target = b; break
                if not target: 
                    target = symbol_fragment if "USDT" in symbol_fragment else symbol_fragment + "USDT"

                if target in blacklisted: del blacklisted[target]
                loss_streak[target] = 0
                save_pardon(target) 
                self.send(f"✨ **{target}** unbanned (Permanent).")
            else: self.send("⚠️ Usage: `/unban PEPE`")

        elif cmd == "/black":
            if not blacklisted: self.send("✅ **No coins in Penalty Box.**")
            else:
                msg = "☠️ **BLACKLISTED:**\n"
                for s in blacklisted: msg += f"❌ {s}\n"
                self.send(msg)

        elif cmd == "/limit":
            if len(args) > 1:
                try: 
                    val = float(args[1])
                    if val > 0: val = -val 
                    live_settings['DAILY_LOSS_LIMIT'] = val
                    save_settings()
                    self.send(f"✅ Daily Loss Limit: `${live_settings['DAILY_LOSS_LIMIT']}`")
                except: pass
            else: self.send(f"Current Limit: `${live_settings['DAILY_LOSS_LIMIT']}`")

        elif cmd == "/goal":
            if len(args) > 1:
                try: 
                    val = float(args[1])
                    live_settings['DAILY_PROFIT_GOAL'] = val
                    save_settings()
                    self.send(f"✅ Profit Goal: `${live_settings['DAILY_PROFIT_GOAL']}`")
                except: pass
            else: self.send(f"Current Goal: `${live_settings['DAILY_PROFIT_GOAL']}`")

        elif cmd == "/report":
            color = "🟢" if daily_pnl >= 0 else "🔴"
            self.send(f"📅 **DAILY REPORT**\n\nRealized PnL: {color} `${daily_pnl:.2f}`\n\nTarget: `${live_settings['DAILY_PROFIT_GOAL']}`\nStop: `${live_settings['DAILY_LOSS_LIMIT']}`")

        elif cmd == "/scan":
            if not scan_cache: self.send("⏳ Syncing..."); return
            
            scalps = {k:v for k,v in scan_cache.items() if v['mode'] == 'SCALP'}
            swings = {k:v for k,v in scan_cache.items() if v['mode'] == 'SWING'}
            
            m = f"**🧗 MARKET: {global_btc_trend}**\n"
            m += "\n⚡ **SCALP (Top 8):**\n```\n"
            for s, d in list(scalps.items())[:8]: m += f"{s:<10} {d['slope']}\n"
            m += "```"
            m += "\n🐢 **SWING (Top 8):**\n```\n"
            for s, d in list(swings.items())[:8]: m += f"{s:<10} {d['slope']}\n"
            m += "```"
            self.send(m)

        elif cmd == "/positions":
            res = BybitPrivate.send_signed("GET", "/v5/position/list", {"category": "linear", "settleCoin": "USDT"})
            try:
                msg = "📋 **OPEN POSITIONS:**\n"
                has_pos = False
                for p in res['result']['list']:
                    if float(p['size']) > 0:
                        has_pos = True
                        pnl = float(p['unrealisedPnl'])
                        msg += f"{'🟢' if pnl>=0 else '🔴'} **{p['symbol']}** | PnL: `${pnl:.2f}`\n"
                if not has_pos: self.send("🤷 **No open positions.**")
                else: self.send(msg)
            except: self.send("❌ Error")

        elif cmd == "/balance":
            bal = BybitPrivate.get_balance()
            self.send(f"💰 Balance: `${bal:.2f}`\nTrades: {len(active_symbols)}/{live_settings['MAX_OPEN_POSITIONS']}")

        elif cmd == "/pause":
            live_settings['GLOBAL_STOP'] = True; save_settings(); self.send("🛑 **PAUSED**")
        
        elif cmd == "/resume":
            live_settings['GLOBAL_STOP'] = False; live_settings['PAUSE_UNTIL'] = 0; save_settings(); self.send("🟢 **LIVE**")

        elif cmd == "/kill":
            self.send("⚠️ **KILLING ALL...**"); BybitPrivate.kill_all(); self.send("✅ Done.")

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
    global scan_cache, active_symbols, global_btc_trend, last_trade_time, last_entry_time, last_market_update, daily_pnl, processed_trades
    init_csv()
    load_pardons() 
    bot_ui = TelegramBot()
    
    # Init Data
    MarketSelector.refresh_lists()
    fetch_fear_and_greed() 
    last_market_update = time.time()
    last_fng_update = time.time()
    
    # Init History
    history = BybitPrivate.get_closed_pnl_history()
    for trade in history:
        oid = trade['orderId']
        processed_trades.add(oid) 
        s = trade['symbol']
        pnl = float(trade['closedPnl'])
        ts = int(trade['updatedTime']) / 1000.0
        
        if pnl < 0: loss_streak[s] = loss_streak.get(s, 0) + 1
        else: loss_streak[s] = 0
        
        if loss_streak[s] >= 2:
            if s in pardoned_coins and (time.time() - pardoned_coins[s] < 86400):
                pass 
            else:
                blacklisted[s] = time.time() + 86400
        
        adjust_risk_based_on_performance(pnl) 

    while True:
        daily_pnl = BybitPrivate.get_today_pnl()
        now = time.time()

        # CHECK CIRCUIT BREAKER STATUS
        if live_settings.get('PAUSE_UNTIL', 0) > now:
            # We are in Circuit Breaker mode
            time.sleep(30); continue

        if not live_settings['GLOBAL_STOP']:
            if daily_pnl <= live_settings['DAILY_LOSS_LIMIT']:
                live_settings['GLOBAL_STOP'] = True; save_settings(); bot_ui.send(f"⛔ **CIRCUIT BREAKER**\nDaily Loss: `${daily_pnl:.2f}`")
            if daily_pnl >= live_settings['DAILY_PROFIT_GOAL']:
                live_settings['GLOBAL_STOP'] = True; save_settings(); bot_ui.send(f"🏆 **TARGET HIT**\nDaily Profit: `${daily_pnl:.2f}`")

        # 4H: Refresh Market List
        if now - last_market_update > 14400:
            MarketSelector.refresh_lists()
            last_market_update = now

        # 4H: Refresh Internet Sentiment (Fear & Greed)
        if now - last_fng_update > 14400:
            fetch_fear_and_greed()
            last_fng_update = now

        global_btc_trend = ExpertEngine.check_btc_trend()
        
        # 1. UPDATE POSITIONS
        current_positions = BybitPrivate.get_open_positions_details()
        new_active = list(current_positions.keys())
        
        for s in active_symbols:
            if s not in new_active:
                last_trade_time[s] = now
        
        active_symbols = new_active
        
        # 2. DETECT CLOSED TRADES
        time.sleep(2)
        res = BybitPrivate.send_signed("GET", "/v5/position/closed-pnl", {"category": "linear", "limit": 10})
        if res and res.get('result'):
            for last_trade in res['result']['list']:
                oid = last_trade['orderId']
                if oid in processed_trades: continue 

                processed_trades.add(oid) 
                
                s = last_trade['symbol']
                pnl = float(last_trade['closedPnl'])
                exit_price = float(last_trade['avgExitPrice'])
                ts = int(last_trade['updatedTime']) / 1000.0
                
                log_trade_exit(s, exit_price, pnl)
                adjust_risk_based_on_performance(pnl)
                
                if now - ts < 900: 
                    msg = f"💰 **PROFIT:** {s} (+${pnl:.2f})" if pnl > 0 else f"☠️ **BLACKLISTED {s}**\nReason: Stop Loss."
                    bot_ui.send(f"{msg}")

                if s not in active_symbols: 
                    if pnl < 0:
                        loss_streak[s] = loss_streak.get(s, 0) + 1
                        if loss_streak[s] >= 2:
                            if s in pardoned_coins and (now - pardoned_coins[s] < 86400):
                                bot_ui.send(f"🛡️ **PARDON SHIELD:** {s} had a loss, but is protected.")
                            else:
                                blacklisted[s] = now + 86400
                        
                        # CHECK FOR CIRCUIT BREAKER TRIGGER
                        if check_loss_circuit_breaker():
                            bot_ui.send("⚡ **CIRCUIT BREAKER TRIGGERED**\n3 Losses in 60m. Pausing buys for 2 hours.")
                    else:
                        loss_streak[s] = 0

        # 3. ZOMBIE KILLER
        now_ms = now * 1000
        for s, details in current_positions.items():
            if s in last_entry_time and (now - last_entry_time[s] < 3600):
                continue
            duration_hours = (now_ms - details['created']) / 3600000.0
            if s in SCALP_TARGETS and duration_hours > live_settings['STALEMATE_HOURS']:
                if details['pnl'] < 0.2:
                    bot_ui.send(f"🧟 **ZOMBIE KILLED:** {s}\nOpen for {duration_hours:.1f}h. Freed up slot.")
                    BybitPrivate.close_position(s)

        if live_settings['GLOBAL_STOP']: time.sleep(5); continue
            
        try:
            tmp = {}
            for symbol in SCALP_TARGETS:
                if symbol in active_symbols: continue
                if symbol in blacklisted and now < blacklisted[symbol]: continue
                if now - last_trade_time.get(symbol, 0) < (COOLDOWN_MINUTES * 60): continue
                if len(active_symbols) >= live_settings['MAX_OPEN_POSITIONS']: continue

                data = ExpertEngine.get_market_info(symbol, SCALP_CONF['interval'])
                if data:
                    tmp[symbol] = {**data, "mode": "SCALP"}
                    if data['slope'] != "WAIT":
                        htf_trend = ExpertEngine.get_trend_only(symbol, "60") 
                        if data['slope'] == "LONG" and htf_trend == "BEAR": continue 
                        if data['slope'] == "SHORT" and htf_trend == "BULL": continue 

                        size_mult = data['vol_mult']
                        
                        trade_log = {"mode": "SCALP", "rsi": data['rsi'], "adx": data['adx'], "atr": data['atr'], "trend": htf_trend}
                        
                        if BybitPrivate.place_order(symbol, "Buy" if data['slope']=="LONG" else "Sell", data['price'], data['atr'], SCALP_CONF, size_mult, trade_log):
                            last_entry_time[symbol] = now
                            active_symbols.append(symbol) 
                            boost_msg = "🔥 **GOD HAND (1.5x)**" if size_mult > 1 else ""
                            bot_ui.send(f"⚡ **SCALP ENTRY:** {symbol}\nSig: {data['slope']} | {boost_msg}")

            for symbol in SWING_TARGETS:
                if symbol in active_symbols: continue
                if symbol in blacklisted and now < blacklisted[symbol]: continue
                if now - last_trade_time.get(symbol, 0) < (COOLDOWN_MINUTES * 60): continue
                if len(active_symbols) >= live_settings['MAX_OPEN_POSITIONS']: continue

                data = ExpertEngine.get_market_info(symbol, SWING_CONF['interval'])
                if data:
                    tmp[symbol] = {**data, "mode": "SWING"}
                    if data['slope'] != "WAIT":
                        trade_log = {"mode": "SWING", "rsi": data['rsi'], "adx": data['adx'], "atr": data['atr'], "trend": "SWING"}
                        
                        if BybitPrivate.place_order(symbol, "Buy" if data['slope']=="LONG" else "Sell", data['price'], data['atr'], SWING_CONF, 1.0, trade_log):
                            last_entry_time[symbol] = now
                            active_symbols.append(symbol) 
                            bot_ui.send(f"🐢 **SWING ENTRY: {symbol}**\nSig: {data['slope']}")

            scan_cache = tmp
            logging.info(f"Scan Done. Active: {len(active_symbols)}")
            time.sleep(60)
        except Exception as e: logging.error(f"Scan Error: {e}"); time.sleep(10)

if __name__ == "__main__":
    print("🚀 BOT V60.00 SMART TRAIL + BREAKER STARTING...")
    t_bot = TelegramBot()
    threading.Thread(target=t_bot.poll, daemon=True).start()
    threading.Thread(target=scanner_loop, daemon=True).start()
    while True: time.sleep(1)