#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║         SWING HUNTER v7.0 — 2-Scan + Telegram Bot               ║
║                                                              ║
║  SCAN 1 @ 8:00 PM IST → Full scan after market close║
║  SCAN 2 @ 9:30 AM IST → Final verdict before market open        ║
║  BOT MODE  → Control via Telegram commands ║
║                                                              ║
║  All alerts → Telegram                                       ║
╚══════════════════════════════════════════════════════════════╝

COMMANDS:
  python swing_hunter.py            → Start auto 3-scan scheduler
  python swing_hunter.py scan1      → Run Scan 1 manually (6 PM full scan)
  python swing_hunter.py scan2      → Run Scan 2 manually (8 PM recheck)
  python swing_hunter.py scan3      → Run Scan 3 manually (9:15 AM verdict)
  python swing_hunter.py test       → Test all data sources
  python swing_hunter.py telegram   → Test Telegram alert

PYTHONANYWHERE (run without laptop — FREE):
  1. pythonanywhere.com → Sign up free
  2. Files → Upload this script
  3. Bash console: pip install --user yfinance pandas requests
  4. Tasks → Add 3 daily tasks:
       Task 1: 12:30 UTC = 6:00 PM IST  → python /home/USER/swing_hunter.py scan1
       Task 2: 14:30 UTC = 8:00 PM IST  → python /home/USER/swing_hunter.py scan2
       Task 3: 03:45 UTC = 9:15 AM IST  → python /home/USER/swing_hunter.py scan3  # 9:30 AM IST = 04:00 UTC
  NOTE: Free account only allows 1 task. Upgrade to $5/month for 3 tasks.
  OR: Use your laptop with the auto scheduler (keeps all 3 scans)

INSTALL:
  pip install yfinance pandas requests schedule
"""

import time, datetime, sys, json, smtplib, os, logging, random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def install_if_missing():
    import subprocess
    # schedule only needed for local laptop mode, not GitHub Actions
    pkgs = ['yfinance','pandas','requests']
    if len(sys.argv) <= 1:  # no args = scheduler mode = need schedule
        pkgs.append('schedule')
    for pkg in pkgs:
        try: __import__(pkg)
        except ImportError:
            print(f"  Installing {pkg}...")
            subprocess.check_call([sys.executable,'-m','pip','install','--user',pkg],
                                  stdout=subprocess.DEVNULL)
install_if_missing()

import yfinance as yf
import pandas as pd
import requests

# schedule only imported in local mode
try:
    import schedule
    HAS_SCHEDULE = True
except ImportError:
    HAS_SCHEDULE = False

# ══════════════════════════════════════════════════════════════
#  ⚙️  CONFIG
# ══════════════════════════════════════════════════════════════
CONFIG = {
    # Telegram — get token from @BotFather, chat_id from getUpdates
    # Edit these directly OR set as environment variables (for GitHub Actions)
    # GitHub Actions: Settings → Secrets → TELEGRAM_TOKEN and TELEGRAM_CHAT_ID
    "TELEGRAM_TOKEN"  : os.environ.get("TELEGRAM_TOKEN", ""),
    "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID", ""),

    # Gmail (optional)
    "GMAIL_FROM"    : "",
    "GMAIL_PASSWORD": "",
    "GMAIL_TO"      : "",

    # Scan times (IST)
    "EVENING_TIME"  : "20:00",   # 8:00 PM IST — full universe scan
    "MORNING_TIME"  : "09:30",   # 9:30 AM IST — recheck shortlist
    # scan3 removed - now just 2 scans   # 9:15 AM next morning — final verdict

    # Capital
    "TOTAL_CAPITAL" : 5000,
}

# ══════════════════════════════════════════════════════════════
#  📊 SCREENER RULES
# ══════════════════════════════════════════════════════════════
RULES = {
    "MIN_PRICE"         : 80,    # Rs.80+ for better quantity
    "MAX_PRICE"         : 1500,  # Rs.1500 max — more shares for Rs.5K
    "RSI_MIN"           : 52,    # slightly above 50 filters weak stocks
    "RSI_MAX"           : 75,    # 75 not 78 — 78+ is overbought
    "ADX_MIN"           : 16,    # catch momentum earlier
    "VOLUME_MULT"       : 1.6,    # raised — momentum needs volume
    "BREAKOUT_DAYS"     : 10,
    "BREAKOUT_MIN_PCT"  : 0.3,    # small raise — NOT 3.0
    "CANDLE_MIN_PCT"    : 0.3,
    "EMA20_MAX_STRETCH" : 1.12,  # slightly more room
    "REQUIRE_EMA_STACK" : True,
    "REQUIRE_SMA200"    : False,
    "USE_DELIVERY"      : True,
    "MIN_DELIVERY_PCT"  : 35,    # real buying confirmation
    "USE_ANTI_GAP"      : True,
    "MAX_GAP_PCT"       : 4.0,    # 4% gap ok if volume confirms
    "USE_FUND_FILTER"   : True,
    "MIN_ROE"           : 5,     # light filter — momentum stocks ok
    "MAX_DEBT_EQUITY"   : 2.5,   # loosened for infra/utility stocks
    "MIN_PROFIT_MARGIN" : 2,     # loosened — allow growth-stage
    "MIN_REV_GROWTH"    : -8,    # loosened — slight dip allowed
    "BULL_THRESHOLD"    : 1.5,
    "BEAR_THRESHOLD"    : -3.0,

    # ── Scan Mode ─────────────────────────────────────────────
    # STRICT = fewer but higher quality stocks (default)
    # RELAXED = more stocks, useful when market is in early recovery
    # Change to "RELAXED" if you keep getting 0 results
    "SCAN_MODE"         : "STRICT",
}

# ══════════════════════════════════════════════════════════════
#  📋 STOCK UNIVERSE
# ══════════════════════════════════════════════════════════════
STOCKS_CACHE_FILE  = "stocks_cache.json"
FUND_CACHE_FILE    = "fundamentals_cache.json"
SHORTLIST_FILE     = "shortlist.json"
TRADES_FILE        = "active_trades.json"      # ← ADD THIS LINE
LOG_FILE           = f"swing_hunter_{datetime.datetime.now().strftime('%Y%m%d')}.log"

FALLBACK_STOCKS = sorted(set([
    "ADANIENT","ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK","BAJAJ-AUTO",
    "BAJFINANCE","BAJAJFINSV","BPCL","BHARTIARTL","BRITANNIA","CIPLA","COALINDIA",
    "DIVISLAB","DRREDDY","EICHERMOT","GRASIM","HCLTECH","HDFCBANK","HDFCLIFE",
    "HEROMOTOCO","HINDALCO","HINDUNILVR","ICICIBANK","ITC","INDUSINDBK","INFY",
    "JSWSTEEL","KOTAKBANK","LT","LTIM","M&M","MARUTI","NESTLEIND","NTPC","ONGC",
    "POWERGRID","RELIANCE","SBILIFE","SBIN","SUNPHARMA","TATACONSUM","TATAMOTORS",
    "TATASTEEL","TCS","TECHM","TITAN","ULTRACEMCO","WIPRO","ZOMATO",
    "ABB","ADANIENSOL","ADANIGREEN","AMBUJACEM","BAJAJHLDNG","BANKBARODA",
    "BERGEPAINT","BEL","BOSCHLTD","CANBK","CHOLAFIN","COLPAL","DLF","DMART",
    "GAIL","GODREJCP","GODREJPROP","HAVELLS","HINDZINC","ICICIPRULI","ICICIGI",
    "IOC","IRCTC","JIOFIN","JSWENERGY","LICI","LODHA","LUPIN","MARICO",
    "MCDOWELL-N","MOTHERSON","MUTHOOTFIN","NAUKRI","NMDC","OFSS","PAGEIND",
    "PIDILITIND","PFC","RECLTD","SAIL","SHRIRAMFIN","SIEMENS","TATAPOWER",
    "TORNTPHARM","TRENT","TVSMOTOR","VBL","VEDL","ZYDUSLIFE",
    "AARTIIND","ABCAPITAL","ACC","AIAENG","ALKEM","AMARAJABAT","APOLLOTYRE",
    "ASTRAL","ATUL","AUBANK","AUROPHARMA","BALKRISIND","BANDHANBNK","BATAINDIA",
    "BHARATFORG","BHEL","BIOCON","CAMS","CANFINHOME","CEATLTD","COFORGE",
    "CONCOR","COROMANDEL","CROMPTON","CUMMINSIND","CYIENT","DALBHARAT","DEEPAKNTR",
    "DIXON","ELGIEQUIP","EMAMILTD","ESCORTS","EXIDEIND","FEDERALBNK","FORTIS",
    "GLAND","GMRINFRA","GUJGASLTD","HAL","HFCL","HINDPETRO","IDFCFIRSTB",
    "IEX","IGL","INDHOTEL","INDUSTOWER","IPCALAB","IRFC","JINDALSTEL","JUBLFOOD",
    "KAJARIACER","KEC","KPITTECH","LALPATHLAB","LAURUSLABS","LICHSGFIN","LTTS",
    "MANAPPURAM","METROPOLIS","MFSL","MGL","MPHASIS","MRF","NAVINFLUOR","NBCC",
    "OBEROIRLTY","OIL","PERSISTENT","PETRONET","PFIZER","PHOENIXLTD","PIIND",
    "POLYCAB","POONAWALLA","RADICO","RAMCOCEM","RELAXO","RITES","SCHAEFFLER",
    "SKFINDIA","SOBHA","SOLARINDS","SPANDANA","STARHEALTH","SUNDARMFIN",
    "SUPREMEIND","SUNTV","SYNGENE","TATACOMM","TATAELXSI","TEAMLEASE","THERMAX",
    "TIINDIA","TIMKEN","TORNTPOWER","TRIDENT","TTKPRESTIG","UNIONBANK","UPL",
    "VOLTAS","WELCORP","WHIRLPOOL","ZEEL",
    "AAVAS","ACE","AFFLE","AJANTPHARM","AMBER","ANGELONE","APTUS","BALAMINES",
    "BALUFORGE","BLUEDART","BRIGADE","CDSL","CENTURYPLY","CERA","CRAFTSMAN",
    "CSBBANK","DBREALTY","DCBBANK","DEVYANI","DODLA","EPIGRAL","EQUITASBNK",
    "FLUOROCHEM","GHCL","GLENMARK","GRANULES","GRSE","HAPPSTMNDS","HEG","HGINFRA",
    "HINDCOPPER","HOMEFIRST","HONASA","HUDCO","INDIAMART","INDIASHLTR","IREDA",
    "JBMA","JINDALSAW","JKLAKSHMI","JKPAPER","JUBLINGREA","JUSTDIAL","KALPATPOWR",
    "KARURVYSYA","KAYNES","KFINTECH","KNRCON","KOLTEPATIL","KRBL","KTKBANK",
    "LAXMIMACH","LEMONTREE","MANINFRA","MAXHEALTH","MEDANTA","MEDPLUS","MIDHANI",
    "MOLDTKPAC","MONTECARLO","MSTCLTD","MTARTECH","NEWGEN","NUVAMA","ONWARDTEC",
    "PAISALO","PCBL","PENIND","PGHH","PNBHOUSING","POLYMED","PRESTIGE","PRINCEPIPE",
    "PRUDENT","PSPPROJECT","PVRINOX","RAILTEL","RAINBOW","RATNAMANI","RAYMOND",
    "REDINGTON","RVNL","SAFARI","SAREGAMA","SBICARD","SHANKARA","SHILPAMED",
    "SIGACHI","SKIPPER","STLTECH","SUBROS","SUDARSCHEM","SUPRIYA","SUZLON",
    "SWSOLAR","SYMPHONY","TANLA","TATATECH","TEJASNET","THYROCARE","TITAGARH",
    "TRIVENI","UGROCAP","UJJIVANSFB","UNIPARTS","UTIAMC","VAIBHAVGBL","VENKEYS",
    "VGUARD","VINATI","VINATIORGA","VMART","VOLTAMP","VRLLOG","WABAG",
    "WELSPUNLIV","WINDLAS","WONDERLA","YATHARTH","ZENSARTECH","ZYDUSWELL",
    "NTPCGREEN","SONACOMS","TATAPOWER","RVNL","IREDA","HUDCO","RAILTEL",
]))

# ══════════════════════════════════════════════════════════════
#  📝 LOGGING
# ══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger()

# ══════════════════════════════════════════════════════════════
#  📋 DYNAMIC STOCK LIST
# ══════════════════════════════════════════════════════════════
def get_stock_list():
    # Use cache if < 7 days old
    if os.path.exists(STOCKS_CACHE_FILE):
        try:
            with open(STOCKS_CACHE_FILE) as f:
                c = json.load(f)
            age = (datetime.datetime.now() - datetime.datetime.fromisoformat(c['updated'])).days
            if age < 7:
                return c['stocks']
        except: pass

    # Try NSE API
    try:
        s = requests.Session()
        hdrs = {'User-Agent':'Mozilla/5.0','Accept':'application/json',
                'Referer':'https://www.nseindia.com/'}
        s.get('https://www.nseindia.com/', headers=hdrs, timeout=10)
        time.sleep(1)
        for idx in ['NIFTY 500','NIFTY 200','NIFTY 100']:
            r = s.get(f'https://www.nseindia.com/api/equity-stockIndices?index={idx}',
                      headers=hdrs, timeout=15)
            if r.status_code == 200:
                stocks = [d['symbol'] for d in r.json().get('data',[])
                         if d.get('symbol') and 'NIFTY' not in d['symbol']]
                if len(stocks) > 50:
                    with open(STOCKS_CACHE_FILE,'w') as f:
                        json.dump({'updated':datetime.datetime.now().isoformat(),
                                  'stocks':stocks}, f)
                    log.info(f"  ✅ NSE API: {len(stocks)} stocks loaded")
                    return stocks
    except Exception as e:
        log.warning(f"  ⚠️  NSE API failed: {e}")

    log.warning("  Using fallback stock list")
    return list(FALLBACK_STOCKS)

# ══════════════════════════════════════════════════════════════
#  🏦 FUNDAMENTALS via yfinance
# ══════════════════════════════════════════════════════════════
def load_fund_cache():
    if not os.path.exists(FUND_CACHE_FILE): return {}
    try:
        with open(FUND_CACHE_FILE) as f: return json.load(f)
    except: return {}

def save_fund_cache(c):
    with open(FUND_CACHE_FILE,'w') as f: json.dump(c, f, indent=2)

def is_fund_fresh(cache, sym):
    if sym not in cache: return False
    try:
        age = (datetime.datetime.now() -
               datetime.datetime.fromisoformat(cache[sym].get('_ts','2000-01-01'))).total_seconds()/3600
        return age < 24
    except: return False

def fetch_fund(symbol):
    try:
        info = yf.Ticker(f"{symbol}.NS").info
        if not info or not info.get('regularMarketPrice'): return None
        roe = info.get('returnOnEquity')
        de  = info.get('debtToEquity')
        pm  = info.get('profitMargins')
        rg  = info.get('revenueGrowth')
        return {
            '_ts'        : datetime.datetime.now().isoformat(),
            'roe'        : round(roe*100,1) if roe else None,
            'debt_eq'    : round(de/100,2)  if de  else None,
            'profit_m'   : round(pm*100,1)  if pm  else None,
            'rev_growth' : round(rg*100,1)  if rg  else None,
            'pe'         : info.get('trailingPE'),
            'sector'     : info.get('sector',''),
        }
    except: return None

# ══════════════════════════════════════════════════════════════
#  📦 NSE BHAVCOPY
# ══════════════════════════════════════════════════════════════
def fetch_bhavcopy():
    log.info("📦 Fetching NSE Bhavcopy...")
    now   = datetime.datetime.now()
    dates = []
    for i in range(10):
        d = now - datetime.timedelta(days=i)
        if d.weekday() < 5: dates.append(d.strftime('%d%m%Y'))
        if len(dates) >= 5: break
    hdrs = {'User-Agent':'Mozilla/5.0','Referer':'https://www.nseindia.com/'}
    for ds in dates:
        url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ds}.csv"
        try:
            r = requests.get(url, headers=hdrs, timeout=15)
            if r.status_code != 200: continue
            lines = r.text.strip().split('\n')
            dm = {}
            for line in lines[1:]:
                c = line.split(',')
                if len(c) >= 15 and c[1].strip() == 'EQ':
                    try: dm[c[0].strip()] = float(c[14].strip())
                    except: pass
            if len(dm) > 100:
                log.info(f"  ✅ Bhavcopy: {ds} — {len(dm)} stocks")
                return dm, ds
        except: continue
    log.warning("  ⚠️  Bhavcopy unavailable")
    return {}, None

# ══════════════════════════════════════════════════════════════
#  📐 INDICATORS
# ══════════════════════════════════════════════════════════════
def ema(s,n):  return s.ewm(span=n,adjust=False).mean().iloc[-1]
def sma(s,n):  return s.tail(min(n,len(s))).mean()

def rsi(s,n=14):
    if len(s)<n+1: return 50.0
    d = s.diff().dropna()
    g = d.where(d>0,0).tail(n).mean()
    l = (-d.where(d<0,0)).tail(n).mean()
    return round(100-100/(1+g/l),1) if l!=0 else 100.0

def adx(df,n=14):
    if len(df)<n+1: return 0
    h,l,c = df['High'],df['Low'],df['Close']
    tr  = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    pdm = (h-h.shift()).where((h-h.shift())>(l.shift()-l),0).clip(lower=0)
    ndm = (l.shift()-l).where((l.shift()-l)>(h-h.shift()),0).clip(lower=0)
    atr = tr.ewm(span=n,adjust=False).mean()
    pdi = 100*pdm.ewm(span=n,adjust=False).mean()/atr.replace(0,1)
    ndi = 100*ndm.ewm(span=n,adjust=False).mean()/atr.replace(0,1)
    dx  = 100*(pdi-ndi).abs()/(pdi+ndi).replace(0,1)
    return round(min(100,dx.ewm(span=n,adjust=False).mean().iloc[-1]),1)

# ══════════════════════════════════════════════════════════════
#  🏆 SCORING
# ══════════════════════════════════════════════════════════════
def tech_score(rsi_v, adx_v, vr, bp, p52, last3=0):
    s  = max(0, 30-abs(rsi_v-62)*2)         # RSI sweet spot    max 30
    s += min(25, max(0,(adx_v-18)*1.1))      # ADX strength      max 25
    s += min(20, max(0,(vr-1.4)*9))          # Volume surge      max 20
    s += min(15, bp*4)                        # Breakout %        max 15
    s += 10 if p52<5 else 6 if p52<15 else 3 if p52<30 else 0  # 52W proximity
    # Momentum bonus — fast movers get extra points
    s += min(10, max(0, last3 * 1.5))        # 3-day momentum    max 10
    return round(min(100,max(0,s)),1)

def fund_score(roe,de,pm,rg):
    s  = min(30,max(0,roe*1.5)) if roe else 15
    s += min(20,max(0,pm*0.8))  if pm  else 10
    s += min(20,max(0,rg*0.6))  if rg  else 10
    if de is not None:
        s += 15 if de<0.3 else 12 if de<0.5 else 8 if de<1.0 else 4 if de<1.5 else 2 if de<2.0 else 0
    else: s += 7
    return round(min(100,max(0,s)),1)

def sm_score(delivery,vr):
    s  = 60 if delivery and delivery>=60 else 50 if delivery and delivery>=50 else \
         35 if delivery and delivery>=40 else 20 if delivery and delivery>=30 else \
         5  if delivery else 30
    s += 40 if vr>=3 else 30 if vr>=2 else 20 if vr>=1.5 else 10
    return round(min(100,max(0,s)),1)

def final_score(t,f,sm): return round(t*0.60+f*0.30+sm*0.10,1)

# ══════════════════════════════════════════════════════════════
#  🔍 CHECK ONE STOCK
# ══════════════════════════════════════════════════════════════
def check_stock(symbol, delivery_map, fund_cache, nifty_ret=0, market_mode="NEUTRAL"):
    try:
        df = yf.Ticker(f"{symbol}.NS").history(period="65d", interval="1d")
        if df is None or len(df)<22: return None
        c   = float(df['Close'].iloc[-1])
        o   = float(df['Open'].iloc[-1])
        v   = float(df['Volume'].iloc[-1])
        pc  = float(df['Close'].iloc[-2])
        if c<=0 or c<RULES['MIN_PRICE'] or c>RULES['MAX_PRICE']: return None

        closes  = df['Close']
        volumes = df['Volume']
        highs   = df['High']

        e20  = ema(closes,20); e50 = ema(closes,50)
        s200 = sma(closes,min(200,len(closes)))
        rv   = rsi(closes);    av  = adx(df)
        ve20 = ema(volumes,20)
        vr   = round(v/ve20,2) if ve20>0 else 0
        n    = min(RULES['BREAKOUT_DAYS']+1,len(highs))
        hin  = float(highs.iloc[-n:-1].max())
        bp   = round(((c-hin)/hin)*100,2) if hin>0 else 0
        cp   = round(((c-o)/o)*100,2)     if o>0   else 0
        w52h = float(highs.max())
        p52  = round(((w52h-c)/w52h)*100,1) if w52h>0 else 0
        gap  = round(((o-pc)/pc)*100,2)     if pc>0   else 0
        deliv = delivery_map.get(symbol, None)

        # Fetch fundamentals if not cached
        if not is_fund_fresh(fund_cache, symbol):
            fd = fetch_fund(symbol)
            if fd: fund_cache[symbol] = fd
        fund = fund_cache.get(symbol, {}) or {}
        roe  = fund.get('roe'); de   = fund.get('debt_eq')
        pm   = fund.get('profit_m'); rg = fund.get('rev_growth')
        sect = fund.get('sector','')

        # Hard filters
        if RULES['USE_FUND_FILTER']:
            if roe is not None and roe  < RULES['MIN_ROE']:                    return None
            if de  is not None and de   > RULES['MAX_DEBT_EQUITY']:            return None
            if pm  is not None and pm   < RULES['MIN_PROFIT_MARGIN']:          return None
            if rg  is not None and rg   < RULES.get('MIN_REV_GROWTH', -20):   return None
        if RULES['USE_ANTI_GAP'] and gap > RULES['MAX_GAP_PCT']:      return None
        if market_mode == "BEAR":
            if len(df)>=5:
                s5d = ((c-float(df['Close'].iloc[-5]))/float(df['Close'].iloc[-5]))*100
                if s5d < 0: return None

        # Dynamic thresholds — BULL market gets relaxed filters to catch more winners
        # STRICT mode or BEAR = tight filters
        scan_mode = RULES.get('SCAN_MODE', 'STRICT')
        is_bull   = market_mode == "BULL"

        if is_bull and scan_mode == 'STRICT':
            # Bull market — auto-loosen slightly
            rsi_max_eff = min(RULES['RSI_MAX'] + 2, 77)   # 75 → 77
            adx_min_eff = max(RULES['ADX_MIN'] - 2, 12)   # 16 → 14
            vol_min_eff = max(RULES['VOLUME_MULT'] - 0.2, 1.2)  # 1.6 → 1.4
            del_min_eff = max(RULES['MIN_DELIVERY_PCT'] - 5, 28) # 35 → 28
        elif scan_mode == 'RELAXED':
            # /relax command — most stocks pass
            rsi_max_eff = 78
            adx_min_eff = 12
            vol_min_eff = 1.2
            del_min_eff = 25
        else:
            # STRICT default
            rsi_max_eff = RULES['RSI_MAX']
            adx_min_eff = RULES['ADX_MIN']
            vol_min_eff = RULES['VOLUME_MULT']
            del_min_eff = RULES['MIN_DELIVERY_PCT']

        # Technical filters
        if c<=e20: return None
        if c<=e50: return None
        if RULES['REQUIRE_EMA_STACK'] and e20<=e50:        return None
        if RULES['REQUIRE_SMA200']    and c<=s200:         return None
        if rv<=RULES['RSI_MIN']:                            return None
        if rv>=rsi_max_eff:                                 return None
        if vr <vol_min_eff:                                 return None
        if c <=hin:                                         return None
        if bp <RULES['BREAKOUT_MIN_PCT']:                   return None
        if av <adx_min_eff:                                 return None
        if cp <RULES['CANDLE_MIN_PCT']:                     return None

        # Candle strength — close must be in upper 80% of candle range
        # Filters out shooting star / doji / weak breakout candles
        try:
            day_high = float(df['High'].iloc[-1])
            day_low  = float(df['Low'].iloc[-1])
            candle_range = day_high - day_low
            if candle_range > 0:
                close_position = (c - day_low) / candle_range
                if close_position < 0.5:  # closing in lower half = rejection candle
                    return None
        except: pass
        if c >=RULES['EMA20_MAX_STRETCH']*e20:              return None
        if RULES['USE_DELIVERY'] and deliv is not None:
            if deliv<del_min_eff:                           return None

        # Momentum boost — only fast movers (up 2%+ in last 3 days)
        try:
            last3_ret = ((c - float(df['Close'].iloc[-4])) / float(df['Close'].iloc[-4])) * 100
        except: last3_ret = 0

        # Smart money trap filter — high RSI with low volume = retail trap
        if rv > 68 and vr < 1.8:
            return None  # RSI pumped by low volume = retail trap, skip

        ts  = tech_score(rv,av,vr,bp,p52,last3_ret)
        fs  = fund_score(roe,de,pm,rg)
        sms = sm_score(deliv,vr)
        fs_ = final_score(ts,fs,sms)

        sl  = round(c*0.95,2)
        t1  = round(c*1.08,2)   # +8%  T1 — sell half
        t2  = round(c*1.12,2)   # +12% T2 — realistic 1-week target
        rr  = round((t2-c)/(c-sl),1)
        # Risk 5% of capital — allows meaningful Rs.300+ profit
        risk_per_trade = CONFIG['TOTAL_CAPITAL']*0.05  # Rs.250 risk
        sl_gap = c-sl
        pos = max(2,int(risk_per_trade/sl_gap)) if sl_gap>0 else 2
        inv = round(pos*c, 0)
        if inv > CONFIG['TOTAL_CAPITAL']:
            pos = max(2, int(CONFIG['TOTAL_CAPITAL']/c))
            inv = round(pos*c, 0)
        profit_t2 = round((t2-c)*pos, 0)  # Expected profit at T2
        pos = max(1,int(inv/c))

        return {
            'symbol':symbol,'close':round(c,2),'open':round(o,2),
            'prev_close':round(pc,2),'rsi':rv,'adx':av,'vol_ratio':vr,
            'bo_pct':bp,'cdl_pct':cp,'gap_pct':gap,'p52wh':p52,
            'ema20':round(e20,2),'sma200':round(s200,2),
            'delivery':round(deliv,1) if deliv else None,
            'roe':roe,'debt_eq':de,'profit_m':pm,'rev_growth':rg,'sector':sect,
            'tech_score':ts,'fund_score':fs,'sm_score':sms,'score':fs_,
            'sl':sl,'target1':t1,'target2':t2,'rr':rr,
            'pos_size':pos,'invest_amt':inv,'profit_t2':profit_t2,
        }
    except: return None

# ══════════════════════════════════════════════════════════════
#  📤 TELEGRAM
# ══════════════════════════════════════════════════════════════
def send_telegram(msg):
    tok = CONFIG['TELEGRAM_TOKEN']
    cid = CONFIG['TELEGRAM_CHAT_ID']
    if not tok or not cid:
        log.warning("⚠️  Telegram not configured")
        return False
    # Split long messages (Telegram limit 4096 chars)
    chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
    for chunk in chunks:
        try:
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                              json={'chat_id':cid,'text':chunk,'parse_mode':'HTML'},
                              timeout=10)
            if not r.json().get('ok'):
                log.error(f"Telegram error: {r.json().get('description')}")
                return False
            time.sleep(0.5)
        except Exception as e:
            log.error(f"Telegram failed: {e}")
            return False
    log.info("✅ Telegram sent!")
    return True

# ══════════════════════════════════════════════════════════════
#  🛒 PRE-BUY CHECKLIST — Generate BUY/WAIT/SKIP verdict
# ══════════════════════════════════════════════════════════════
def get_verdict(stock, scan_type="scan1"):
    """
    Returns verdict + reasons based on current data
    scan1/scan2: preliminary verdict
    scan3: final morning verdict (most strict)
    """
    r      = stock
    issues = []
    green  = []

    # RSI check
    if r['rsi'] >= 68:
        issues.append(f"RSI {r['rsi']} — dangerously close to overbought (70)")
    elif r['rsi'] >= 63:
        issues.append(f"RSI {r['rsi']} — slightly elevated, watch closely")
    else:
        green.append(f"RSI {r['rsi']} ✅ ideal zone")

    # Gap check (only relevant in scan3 — pre-market)
    if scan_type == "scan3":
        if r['gap_pct'] > 3.0:
            issues.append(f"Gapped up +{r['gap_pct']}% — too late to chase!")
        elif r['gap_pct'] > 1.5:
            issues.append(f"Gapped up +{r['gap_pct']}% — enter only if RSI still ok")
        elif r['gap_pct'] < -2.0:
            issues.append(f"Gapped down {r['gap_pct']}% — check if SL breached")
        else:
            green.append(f"Gap {r['gap_pct']}% ✅ acceptable")

    # Delivery check
    if r['delivery'] is not None:
        if r['delivery'] >= 50:
            green.append(f"Delivery {r['delivery']}% ✅ strong institutional buying")
        elif r['delivery'] >= 40:
            green.append(f"Delivery {r['delivery']}% ✅ real buying confirmed")
        else:
            issues.append(f"Delivery {r['delivery']}% — mostly intraday, not institutions")

    # Volume
    if r['vol_ratio'] >= 2.0:
        green.append(f"Volume {r['vol_ratio']}x ✅ strong surge")
    elif r['vol_ratio'] >= 1.5:
        green.append(f"Volume {r['vol_ratio']}x ✅ above average")

    # Fundamental quick check
    if r['debt_eq'] is not None and r['debt_eq'] < 0.5:
        green.append(f"Debt/Equity {r['debt_eq']} ✅ almost debt-free")
    elif r['debt_eq'] is not None and r['debt_eq'] > 1.5:
        issues.append(f"Debt/Equity {r['debt_eq']} ⚠️ high debt company")

    if r['rev_growth'] is not None:
        if r['rev_growth'] >= 15:
            green.append(f"Revenue growth {r['rev_growth']}% ✅ strong")
        elif r['rev_growth'] < 0:
            issues.append(f"Revenue growth {r['rev_growth']}% ❌ declining revenue!")

    # Score
    if r['score'] >= 70:
        green.append(f"Score {r['score']}/100 ✅ high confidence")
    elif r['score'] >= 50:
        green.append(f"Score {r['score']}/100 — moderate confidence")
    else:
        issues.append(f"Score {r['score']}/100 — low confidence")

    # Final verdict logic
    # Critical = actual deal breakers (declining revenue, gap-up trap, overbought at open)
    # RSI near 70 in scan1/2 is just a WARNING, not a deal breaker — will be re-evaluated in scan3
    hard_fails  = [i for i in issues if '❌' in i or 'too late' in i]
    rsi_warning = any('RSI' in i for i in issues)

    if scan_type == "scan3":
        # Strictest — morning verdict. RSI still high at open = skip
        if hard_fails or (rsi_warning and len(issues) >= 2):
            verdict = "🔴 SKIP"
            action  = "Do NOT buy today — setup degraded"
        elif len(issues) >= 2:
            verdict = "🟡 WAIT"
            action  = "Watch 9:20-9:25 AM — buy only if stable and RSI not rising"
        else:
            verdict = "🟢 BUY"
            action  = f"Buy between 9:35-9:45 AM near Rs.{r['close']}"
    else:
        # Scan 1 & 2 — informational, not final
        # Only flag LIKELY SKIP if there are hard fundamental/revenue fails
        if hard_fails:
            verdict = "🔴 LIKELY SKIP"
            action  = "Fundamental concern — monitor only"
        elif rsi_warning and len(issues) >= 2:
            verdict = "🟡 WATCHLIST (RSI high)"
            action  = "RSI elevated — confirm RSI cools by 9 AM tomorrow"
        elif len(issues) >= 1:
            verdict = "🟡 WATCHLIST"
            action  = "Promising — confirm in next scan"
        else:
            verdict = "🟢 STRONG CANDIDATE"
            action  = "Looking great — confirm in scan 2 and 3"

    return verdict, action, green, issues


# ══════════════════════════════════════════════════════════════
#  📈 ACTIVE TRADE TRACKER — Hold/Sell advice for open trades
# ══════════════════════════════════════════════════════════════
def load_trades():
    if not os.path.exists(TRADES_FILE): return []
    try:
        with open(TRADES_FILE) as f: return json.load(f)
    except: return []

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f: json.dump(trades, f, indent=2)

def save_results_as_trades(results, scan_time):
    trades = load_trades()
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=9)).isoformat()
    trades = [t for t in trades if t.get('date','') > cutoff]
    existing = {t['symbol'] for t in trades}
    for r in results:
        if r['symbol'] not in existing:
            trades.append({
                'symbol'     : r['symbol'],
                'entry_price': r['close'],
                'date'       : scan_time,
                'sl'         : r['sl'],         # 5% SL
                'target1'    : r['target1'],     # +8%
                'target2'    : r['target2'],     # +12%
                'score'      : r['score'],
                'pos_size'   : r.get('pos_size', 2),
                'profit_t2'  : r.get('profit_t2', 0),
            })
    save_trades(trades)

def check_active_trades():
    trades = load_trades()
    if not trades: return []
    report = []
    for t in trades:
        try:
            df   = yf.Ticker(f"{t['symbol']}.NS").history(period="2d", interval="1d")
            if df is None or len(df) == 0: continue
            curr = round(float(df['Close'].iloc[-1]), 2)
            ep   = t['entry_price']
            sl   = t['sl']
            t1   = t['target1']
            t2   = t['target2']
            pnl  = round(((curr - ep) / ep) * 100, 2)
            try:
                days = (datetime.datetime.now() -
                        datetime.datetime.fromisoformat(t['date'])).days
            except: days = 1

            if curr <= sl:
                action = "🔴 SL HIT — EXIT NOW. Don't wait!"
                emoji  = "🔴"
            elif curr >= t2:
                action = "🟢 T2 HIT — EXIT ALL. Full profit!"
                emoji  = "🟢"
            elif curr >= t1:
                action = "🟡 T1 HIT — Sell half. Move SL to cost."
                emoji  = "🟡"
            elif days >= 7:
                action = "⏰ DAY 7 — Exit today. Rule is rule!"
                emoji  = "⏰"
            elif pnl >= 10:
                action = "🟢 HOLD — Move SL to EMA20 (lock profits)"
                emoji  = "🟢"
            elif pnl >= 5:
                action = "🟢 HOLD — Move SL to cost price (free trade!)"
                emoji  = "🟢"
            elif pnl >= 0:
                action = "🟢 HOLD — In profit. Maintain original SL."
                emoji  = "🟢"
            elif pnl >= -3:
                action = "🟡 HOLD — Near SL. Watch closely today."
                emoji  = "🟡"
            else:
                action = "🔴 WARNING — Deep in loss. Check if SL hit."
                emoji  = "🔴"

            report.append({
                'symbol'   : t['symbol'],
                'entry'    : ep,
                'current'  : curr,
                'pnl_pct'  : pnl,
                'sl'       : sl,
                'target1'  : t1,
                'target2'  : t2,
                'days_held': days,
                'action'   : action,
                'emoji'    : emoji,
            })
        except: continue
    return report

def build_trades_msg(report):
    if not report:
        return ("📋 NO ACTIVE TRADES\n\n"
                "Trades appear here automatically after evening scan.\n"
                "Run /scan to find stocks.")
    now = datetime.datetime.now().strftime('%d %b %Y %I:%M %p')
    msg = f"📋 ACTIVE TRADES — {now}\n{'─'*32}\n\n"
    for t in report:
        pnl = f"{'+' if t['pnl_pct']>=0 else ''}{t['pnl_pct']}%"
        msg += (f"{t['emoji']} <b>{t['symbol']}</b> Day {t['days_held']}\n"
                f"   Entry Rs.{t['entry']} → Now Rs.{t['current']} ({pnl})\n"
                f"   {t['action']}\n\n")
    return msg

# ══════════════════════════════════════════════════════════════
#  💬 MESSAGE BUILDERS
# ══════════════════════════════════════════════════════════════
def msg_scan1(results, scanned, nse_date, nifty_ret, banknifty_ret, market_mode):
    now  = datetime.datetime.now().strftime('%d %b %Y')
    mood = {'BULL':'🟢 BULL','NEUTRAL':'🟡 NEUTRAL','BEAR':'🔴 BEAR'}.get(market_mode,'🟡 NEUTRAL')
    nse  = f"✅ NSE Delivery: {nse_date}" if nse_date else "⚠️ No delivery data yet"

    mode_tag = f" | Mode: {RULES.get('SCAN_MODE','STRICT')}"
    msg  = (f"🔍 SWING HUNTER — SCAN 1 (6 PM){mode_tag}\n"
            f"📅 {now} | Market: {mood}\n"
            f"Nifty5D:{'+ ' if nifty_ret>=0 else ''}{nifty_ret}% | BankNifty5D:{'+ ' if banknifty_ret>=0 else ''}{banknifty_ret}%\n"
            f"{nse}\n"
            f"Scanned: {scanned} stocks\n\n")

    # Show active trades status if any
    trade_report = check_active_trades()
    if trade_report:
        msg += "📋 OPEN TRADES STATUS:\n"
        for t in trade_report:
            pnl = f"{chr(43) if t['pnl_pct']>=0 else ''}{t['pnl_pct']}%"
            msg += f"  {t['emoji']} {t['symbol']} {pnl} Day{t['days_held']} — {t['action']}\n"
        msg += "\n"

    if not results:
        return msg + ("❌ No stocks passed today's filters.\n\n"
                      "Reasons could be:\n"
                      "• Market just recovered — stocks may be overextended\n"
                      "• Wait for a pullback and fresh breakout\n\n"
                      "Next scan at 8:00 PM IST\nNot SEBI advice")

    msg += f"✅ {len(results)} stocks found — PRELIMINARY SHORTLIST\n"
    msg += f"(Delivery data final — Bhavcopy fully loaded)\n"
    msg += "─"*35 + "\n\n"

    for i, r in enumerate(results, 1):
        verdict, action, green, issues = get_verdict(r, "scan1")
        sect = f" [{r['sector'][:12]}]" if r['sector'] else ""
        msg += f"{i}. <b>{r['symbol']}</b>{sect}\n"
        msg += f"   {verdict} | Score: {r['score']}/100\n"
        msg += f"   Rs.{r['close']} | RSI:{r['rsi']} | ADX:{r['adx']} | Vol:{r['vol_ratio']}x\n"
        last3_str = f" | 3D Momentum:+{r.get('last3_ret',0)}%" if r.get('last3_ret',0) > 0 else ""
        msg += f"   Breakout: +{r['bo_pct']}%{last3_str}"
        if r['delivery']: msg += f" | Delivery: {r['delivery']}%"
        msg += f" | 52WH: -{r['p52wh']}%\n"
        fund_parts = []
        if r['roe']:                     fund_parts.append(f"ROE:{r['roe']}%")
        if r['debt_eq'] is not None:     fund_parts.append(f"D/E:{r['debt_eq']}")
        if r['rev_growth']:              fund_parts.append(f"RevG:{r['rev_growth']}%")
        if fund_parts: msg += f"   {' | '.join(fund_parts)}\n"
        msg += f"   SL: Rs.{r['sl']} (-5%) | T1: Rs.{r['target1']} (+8%) | T2: Rs.{r['target2']} (+12%)\n"
        msg += f"   R:R=1:{r['rr']} | {r['pos_size']} shares≈Rs.{r['invest_amt']} | Est.profit Rs.{r.get('profit_t2',0):.0f}\n\n"
        for iss in issues[:1]: msg += f"   ⚠️ {iss}\n"
        msg += "\n"

    msg += ("─"*35 + "\n"
            "⏰ Next: SCAN 2 at 8:00 PM IST\n"
            "Will recheck these stocks with updated data\n\n"
            "Not SEBI registered advice")
    return msg

def msg_scan2(results, prev_results, nse_date, nifty_ret, banknifty_ret, market_mode):
    now  = datetime.datetime.now().strftime('%d %b %Y')
    mood = {'BULL':'🟢 BULL','NEUTRAL':'🟡 NEUTRAL','BEAR':'🔴 BEAR'}.get(market_mode,'🟡 NEUTRAL')

    msg  = (f"🔄 SWING HUNTER — SCAN 2 (8 PM RECHECK)\n"
            f"📅 {now} | Market: {mood}\n"
            f"Nifty 5D: {'+' if nifty_ret>=0 else ''}{nifty_ret}%\n\n")

    prev_syms = {r['symbol'] for r in prev_results}
    curr_syms = {r['symbol'] for r in results}

    # Stocks that dropped out
    dropped = prev_syms - curr_syms
    if dropped:
        msg += f"❌ DROPPED OUT (no longer valid):\n"
        for s in dropped:
            msg += f"   • {s} — failed recheck filters\n"
        msg += "\n"

    # New stocks added
    new_syms = curr_syms - prev_syms
    if new_syms:
        msg += f"🆕 NEW ADDITIONS:\n"
        for s in new_syms:
            msg += f"   • {s} — newly qualified\n"
        msg += "\n"

    if not results:
        msg += ("❌ No stocks remain after recheck.\n"
                "All candidates dropped out — sit on cash today.\n\n"
                "⏰ Next: SCAN 3 at 9:15 AM IST tomorrow\nNot SEBI advice")
        return msg

    msg += f"✅ {len(results)} stocks confirmed — UPDATED SHORTLIST\n"
    msg += "─"*35 + "\n\n"

    for i, r in enumerate(results, 1):
        verdict, action, green, issues = get_verdict(r, "scan2")
        sect = f" [{r['sector'][:12]}]" if r['sector'] else ""

        # Check if score changed vs scan1
        prev = next((p for p in prev_results if p['symbol']==r['symbol']), None)
        score_change = ""
        if prev:
            diff = round(r['score'] - prev['score'], 1)
            score_change = f" ({'+' if diff>=0 else ''}{diff} vs 6PM)"

        msg += f"{i}. <b>{r['symbol']}</b>{sect}\n"
        msg += f"   {verdict} | Score: {r['score']}/100{score_change}\n"
        msg += f"   Rs.{r['close']} | RSI:{r['rsi']} | ADX:{r['adx']} | Vol:{r['vol_ratio']}x\n"
        msg += f"   Breakout: +{r['bo_pct']}%"
        if r['delivery']: msg += f" | Delivery: {r['delivery']}%"
        msg += f" | 52WH: -{r['p52wh']}%\n"
        msg += f"   SL: Rs.{r['sl']} (-5%) | T1: Rs.{r['target1']} (+8%) | T2: Rs.{r['target2']} (+12%)\n"
        msg += f"   R:R=1:{r['rr']} | {r['pos_size']} shares≈Rs.{r['invest_amt']} | Est.profit Rs.{r.get('profit_t2',0):.0f}\n"

        # Green flags
        for g in green[:2]: msg += f"   ✅ {g}\n"
        # Issues
        for iss in issues[:1]: msg += f"   ⚠️ {iss}\n"
        msg += "\n"

    # Capital allocation
    cap = CONFIG['TOTAL_CAPITAL']
    msg += "─"*35 + f"\nCAPITAL PLAN (Rs.{cap:,}):\n"
    if len(results)>=3:
        msg += f"  {results[0]['symbol']}: Rs.{round(cap*0.40):,} (40%)\n"
        msg += f"  {results[1]['symbol']}: Rs.{round(cap*0.35):,} (35%)\n"
        msg += f"  {results[2]['symbol']}: Rs.{round(cap*0.25):,} (25%)\n"
    elif len(results)==2:
        msg += f"  {results[0]['symbol']}: Rs.{round(cap*0.55):,} | {results[1]['symbol']}: Rs.{round(cap*0.45):,}\n"
    else:
        msg += f"  All Rs.{cap:,} in {results[0]['symbol']}\n"

    msg += ("\n⏰ Next: SCAN 3 at 9:15 AM IST tomorrow\n"
            "Final verdict before market opens!\n\n"
            "Not SEBI registered advice")
    return msg

def msg_scan3(results, prev_results, nifty_ret, banknifty_ret, market_mode):
    now  = datetime.datetime.now().strftime('%d %b %Y')
    mood = {'BULL':'🟢 BULL','NEUTRAL':'🟡 NEUTRAL','BEAR':'🔴 BEAR'}.get(market_mode,'🟡 NEUTRAL')

    msg  = (f"🚀 SWING HUNTER — SCAN 3 (9:15 AM FINAL VERDICT)\n"
            f"📅 {now} | Market: {mood}\n"
            f"Nifty 5D: {'+' if nifty_ret>=0 else ''}{nifty_ret}%\n\n"
            f"⏰ Market opens at 9:15 AM — act by 9:30 AM!\n"
            "─"*35 + "\n\n")

    if not results:
        msg += ("🔴 NO TRADES TODAY\n\n"
                "All candidates from last night failed morning check.\n"
                "Possible reasons:\n"
                "• Pre-market gap up too much\n"
                "• RSI overbought at open\n"
                "• Market weakness overnight\n\n"
                "✅ Correct action: Sit on cash. Next opportunity tomorrow.\n\n"
                "Not SEBI advice")
        return msg

    buy_stocks  = []
    wait_stocks = []
    skip_stocks = []

    for r in results:
        verdict, action, green, issues = get_verdict(r, "scan3")
        if "BUY" in verdict:    buy_stocks.append((r, verdict, action, green, issues))
        elif "WAIT" in verdict: wait_stocks.append((r, verdict, action, green, issues))
        else:                    skip_stocks.append((r, verdict, action, green, issues))

    # BUY stocks
    if buy_stocks:
        msg += f"🟢 BUY NOW ({len(buy_stocks)} stocks):\n\n"
        for r, verdict, action, green, issues in buy_stocks:
            sect = f" [{r['sector'][:12]}]" if r['sector'] else ""
            msg += f"<b>{r['symbol']}</b>{sect} — Score:{r['score']}/100\n"
            msg += f"   {action}\n"
            msg += f"   Price: Rs.{r['close']}\n"
            msg += f"   RSI:{r['rsi']} | ADX:{r['adx']} | Vol:{r['vol_ratio']}x\n"
            if r['delivery']: msg += f"   Delivery: {r['delivery']}% ✅\n"
            msg += f"\n   📌 TRADE PLAN:\n"
            msg += f"   Entry  : Rs.{r['close']} (buy between 9:35-9:45 AM)\n"
            msg += f"   SL     : Rs.{r['sl']} (-5%) ← GTT order immediately!\n"
            msg += f"   Target1: Rs.{r['target1']} (+8%) ← sell half here\n"
            msg += f"   Target2: Rs.{r['target2']} (+15%) ← sell rest here\n"
            msg += f"   Shares : {r['pos_size']} shares = Rs.{r['invest_amt']} | Est.profit Rs.{r.get('profit_t2',0):.0f}\n"
            msg += f"   R:R    : 1:{r['rr']}\n"
            msg += f"   Exit   : Day 7 max — no exceptions!\n\n"
            for g in green[:3]: msg += f"   ✅ {g}\n"
            msg += "\n"

    # WAIT stocks
    if wait_stocks:
        msg += f"🟡 WAIT & WATCH ({len(wait_stocks)} stocks):\n\n"
        for r, verdict, action, green, issues in wait_stocks:
            msg += f"<b>{r['symbol']}</b> — {action}\n"
            msg += f"   Rs.{r['close']} | RSI:{r['rsi']} | Score:{r['score']}\n"
            msg += f"   SL: Rs.{r['sl']} | T2: Rs.{r['target2']}\n"
            for iss in issues[:2]: msg += f"   ⚠️ {iss}\n"
            msg += "\n"

    # SKIP stocks
    if skip_stocks:
        msg += f"🔴 SKIP TODAY ({len(skip_stocks)} stocks):\n"
        for r, verdict, action, green, issues in skip_stocks:
            msg += f"   • {r['symbol']}: {issues[0] if issues else 'Failed morning check'}\n"
        msg += "\n"

    # Final rules reminder
    msg += ("─"*35 + "\n"
            "📋 GOLDEN RULES:\n"
            "✅ Buy 9:35-9:45 AM (NOT at open)\n"
            "✅ Check: price above breakout + RSI<70 + vol strong\n"
            "✅ Set GTT SL the moment you buy\n"
            "⬆️  TRAILING SL:\n"
            "   +5% hit  → move SL to your cost (free trade!)\n"
            "   +10% hit → move SL to EMA20 (lock profits)\n"
            "✅ +8% hit  → sell HALF, let rest run to T2\n"
            "✅ Exit ALL on Day 7 — no emotions\n"
            "❌ Never buy if already +4-5% from yesterday close\n"
            "❌ Never average down if SL hits\n\n"
            "Not SEBI registered advice")
    return msg

# ══════════════════════════════════════════════════════════════
#  🚀 THE 3 SCANS
# ══════════════════════════════════════════════════════════════
def get_market_data():
    """Nifty + Bank Nifty confirmation for stronger regime signal"""
    nifty_ret = 0
    banknifty_ret = 0
    try:
        df_n = yf.Ticker("^NSEI").history(period="20d", interval="1d")
        nifty_ret = round(((float(df_n['Close'].iloc[-1]) -
                           float(df_n['Close'].iloc[-5])) /
                           float(df_n['Close'].iloc[-5])) * 100, 2)
    except: pass
    try:
        df_b = yf.Ticker("^NSEBANK").history(period="20d", interval="1d")
        banknifty_ret = round(((float(df_b['Close'].iloc[-1]) -
                               float(df_b['Close'].iloc[-5])) /
                               float(df_b['Close'].iloc[-5])) * 100, 2)
    except: pass

    # Both Nifty AND BankNifty must confirm for BULL
    # Either one going BEAR = cautious
    if nifty_ret > RULES['BULL_THRESHOLD'] and banknifty_ret > RULES['BULL_THRESHOLD']:
        mode = "BULL"
    elif nifty_ret < RULES['BEAR_THRESHOLD'] or banknifty_ret < RULES['BEAR_THRESHOLD']:
        mode = "BEAR"
    else:
        mode = "NEUTRAL"

    return nifty_ret, banknifty_ret, mode

def run_evening_scan():
    """6:00 PM — Full universe scan with final bhavcopy data"""
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        log.info(f"⏭️  {now.strftime('%A')} — no scan"); return

    log.info("="*60)
    log.info(f"SCAN 1 (6 PM) — {now.strftime('%d %b %Y %I:%M %p')}")
    log.info("="*60)

    stocks       = get_stock_list()
    delivery_map, nse_date = fetch_bhavcopy()
    fund_cache   = load_fund_cache()
    nifty_ret, banknifty_ret, market_mode = get_market_data()

    log.info(f"Universe: {len(stocks)} | Market: {market_mode} | Nifty5D:{nifty_ret}% BankNifty5D:{banknifty_ret}%")

    results = []
    for i, sym in enumerate(stocks):
        try:
            r = check_stock(sym, delivery_map, fund_cache, nifty_ret, market_mode)
            if r:
                results.append(r)
                log.info(f"  ✅ {sym} Rs.{r['close']} Score:{r['score']} Del:{r['delivery']}")
        except: pass
        if (i+1) % 50 == 0:
            log.info(f"  {i+1}/{len(stocks)} scanned | {len(results)} found")
        time.sleep(0.8)

    save_fund_cache(fund_cache)
    results.sort(key=lambda x: x['score'], reverse=True)

    # Save shortlist for Scan 2 & 3 to use
    with open(SHORTLIST_FILE, 'w') as f:
        json.dump({'time':now.isoformat(),'scan':'scan1',
                   'results':results,'nifty_ret':nifty_ret,
                   'market_mode':market_mode,'nse_date':nse_date}, f, indent=2)

    log.info(f"\nSCAN 1 DONE: {len(results)} stocks found from {len(stocks)}")
    msg = msg_scan1(results, len(stocks), nse_date, nifty_ret, banknifty_ret, market_mode)
    send_telegram(msg)

def run_morning_scan_recheck():
    """8:00 PM — Recheck only shortlisted stocks"""
    now = datetime.datetime.now()
    if now.weekday() >= 5: return

    log.info("="*60)
    log.info(f"SCAN 2 (8 PM RECHECK) — {now.strftime('%d %b %Y %I:%M %p')}")
    log.info("="*60)

    # Load scan1 shortlist
    if not os.path.exists(SHORTLIST_FILE):
        log.warning("No Scan 1 shortlist found — running full scan")
        run_evening_scan(); return

    with open(SHORTLIST_FILE) as f:
        prev_data = json.load(f)
    prev_results = prev_data.get('results', [])

    if not prev_results:
        send_telegram("🔄 SCAN 2 (8 PM)\n\nNo stocks from Scan 1 to recheck.\n\nNot SEBI advice")
        return

    shortlist_syms = [r['symbol'] for r in prev_results]
    log.info(f"Rechecking {len(shortlist_syms)} stocks from Scan 1: {shortlist_syms}")

    delivery_map, nse_date = fetch_bhavcopy()
    fund_cache   = load_fund_cache()
    nifty_ret, banknifty_ret, market_mode = get_market_data()

    results = []
    for sym in shortlist_syms:
        try:
            r = check_stock(sym, delivery_map, fund_cache, nifty_ret, market_mode)
            if r:
                results.append(r)
                log.info(f"  ✅ {sym} still valid | Score:{r['score']} Del:{r['delivery']}")
            else:
                log.info(f"  ❌ {sym} dropped out")
        except: pass
        time.sleep(0.8)

    save_fund_cache(fund_cache)
    results.sort(key=lambda x: x['score'], reverse=True)

    # Update shortlist file with scan2 results
    with open(SHORTLIST_FILE, 'w') as f:
        json.dump({'time':now.isoformat(),'scan':'scan2',
                   'results':results,'nifty_ret':nifty_ret,
                   'market_mode':market_mode,'nse_date':nse_date}, f, indent=2)
    save_results_as_trades(results, now.isoformat())
    log.info(f"\nSCAN 2 DONE: {len(results)} stocks confirmed")
    msg = msg_scan2(results, prev_results, nse_date, nifty_ret, banknifty_ret, market_mode)
    send_telegram(msg)

def run_morning_scan():
    """9:15 AM — Pre-market final verdict"""
    now = datetime.datetime.now()
    if now.weekday() >= 5: return

    log.info("="*60)
    log.info(f"SCAN 3 (9:15 AM FINAL) — {now.strftime('%d %b %Y %I:%M %p')}")
    log.info("="*60)

    # Load scan2 shortlist
    if not os.path.exists(SHORTLIST_FILE):
        send_telegram("🚀 SCAN 3 (9:15 AM)\n\nNo shortlist from previous scans.\nNo trades today.\n\nNot SEBI advice")
        return

    with open(SHORTLIST_FILE) as f:
        prev_data = json.load(f)
    prev_results = prev_data.get('results', [])

    if not prev_results:
        send_telegram("🚀 SCAN 3 (9:15 AM)\n\nNo stocks in shortlist.\nSit on cash today.\n\nNot SEBI advice")
        return

    shortlist_syms = [r['symbol'] for r in prev_results]
    log.info(f"Final check on {len(shortlist_syms)} stocks: {shortlist_syms}")

    delivery_map, _ = fetch_bhavcopy()
    fund_cache       = load_fund_cache()
    nifty_ret, banknifty_ret, market_mode = get_market_data()

    if market_mode == "BEAR":
        send_telegram(f"🚀 SCAN 3 (9:15 AM FINAL)\n\n🔴 MARKET IS BEARISH (Nifty 5D: {nifty_ret}%)\n\nRecommendation: SIT ON CASH TODAY\nDo not trade in a falling market — wait for recovery!\n\nNot SEBI advice")
        return

    results = []
    for sym in shortlist_syms:
        try:
            r = check_stock(sym, delivery_map, fund_cache, nifty_ret, market_mode)
            if r:
                results.append(r)
                log.info(f"  ✅ {sym} cleared final check | Score:{r['score']}")
            else:
                log.info(f"  ❌ {sym} failed final check")
        except: pass
        time.sleep(0.8)

    save_fund_cache(fund_cache)
    results.sort(key=lambda x: x['score'], reverse=True)
    save_results_as_trades(results, now.isoformat())
    log.info(f"\nSCAN 3 DONE: {len(results)} stocks cleared final check")
    msg = msg_scan3(results, prev_results, nifty_ret, banknifty_ret, market_mode)
    send_telegram(msg)

# ══════════════════════════════════════════════════════════════
#  🔬 TEST
# ══════════════════════════════════════════════════════════════
def run_test():
    print("\n" + "="*60)
    print("  SWING HUNTER v6 — LIVE DATA TEST")
    print("="*60)

    print("\n📈 Yahoo Finance — RELIANCE.NS")
    try:
        df = yf.Ticker("RELIANCE.NS").history(period="5d")
        lc = round(float(df['Close'].iloc[-1]),2)
        dt = df.index[-1].strftime('%d %b %Y')
        print(f"   ✅ Rs.{lc} | Date: {dt}")
    except Exception as e: print(f"   ❌ {e}")

    print("\n🏦 yfinance Fundamentals — INFY.NS")
    try:
        info = yf.Ticker("INFY.NS").info
        roe  = info.get('returnOnEquity')
        de   = info.get('debtToEquity')
        print(f"   ✅ ROE:{round(roe*100,1) if roe else 'N/A'}% | D/E:{round(de/100,2) if de else 'N/A'}")
        print(f"   Sector: {info.get('sector','N/A')}")
    except Exception as e: print(f"   ❌ {e}")

    print("\n📦 NSE Bhavcopy")
    dm, ds = fetch_bhavcopy()
    if dm: print(f"   ✅ {ds} | {len(dm)} stocks | RELIANCE:{dm.get('RELIANCE','N/A')}% TCS:{dm.get('TCS','N/A')}%")
    else:  print(f"   ⚠️  Unavailable ({datetime.datetime.now().strftime('%A')})")

    print("\n📊 Nifty Market Regime")
    nifty_ret, mode = get_market_data()
    print(f"   ✅ 5D Return: {'+' if nifty_ret>=0 else ''}{nifty_ret}% — {mode}")

    print("\n📱 Telegram")
    tok = CONFIG['TELEGRAM_TOKEN']
    cid = CONFIG['TELEGRAM_CHAT_ID']
    if not tok: print("   ⚠️  TOKEN empty — edit CONFIG above")
    elif not cid: print(f"   ⚠️  CHAT_ID empty | Get from: api.telegram.org/bot{tok}/getUpdates")
    else:
        try:
            r = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=10)
            d = r.json()
            if d.get('ok'): print(f"   ✅ Bot: {d['result']['first_name']}")
            else:           print(f"   ❌ {d.get('description')}")
        except Exception as e: print(f"   ❌ {e}")

    print("\n📋 Stock List")
    stocks = get_stock_list()
    print(f"   {len(stocks)} stocks | Source: {'NSE cache' if os.path.exists(STOCKS_CACHE_FILE) else 'Fallback'}")
    print("="*60 + "\n")

def test_telegram():
    tok = CONFIG['TELEGRAM_TOKEN']
    cid = CONFIG['TELEGRAM_CHAT_ID']
    if not tok: print("TOKEN empty — edit CONFIG"); return
    if not cid:
        print(f"CHAT_ID empty — open: api.telegram.org/bot{tok}/getUpdates"); return
    msg = (f"✅ Swing Hunter v6 — TEST\n\n"
           f"3-Scan system active!\n"
           f"Scan 1: 6:00 PM IST — full universe\n"
           f"Scan 2: 8:00 PM IST — recheck shortlist\n"
           f"Scan 3: 9:15 AM IST — final BUY/WAIT/SKIP\n\n"
           f"Time now: {datetime.datetime.now().strftime('%d %b %Y %I:%M %p')}\n"
           f"Stocks: {len(get_stock_list())} NSE stocks\n\n"
           f"Not SEBI advice")
    ok = send_telegram(msg)
    print("SUCCESS! Check Telegram!" if ok else "FAILED! Check TOKEN/CHAT_ID")


# ══════════════════════════════════════════════════════════════
#  🤖 TELEGRAM BOT — Full command controller
# ══════════════════════════════════════════════════════════════
def get_tg_updates(offset=0):
    tok = CONFIG['TELEGRAM_TOKEN']
    if not tok: return [], 0
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{tok}/getUpdates",
            params={'offset': offset, 'timeout': 30, 'allowed_updates': ['message']},
            timeout=35
        )
        data = r.json()
        if not data.get('ok'): return [], offset
        updates = data.get('result', [])
        return updates, (updates[-1]['update_id'] + 1 if updates else offset)
    except: return [], offset

def tg_authorized(chat_id):
    return str(chat_id) == str(CONFIG['TELEGRAM_CHAT_ID'])

def handle_tg_command(text, chat_id):
    if not tg_authorized(chat_id):
        return "Unauthorized"
    cmd = text.strip().lower().split()[0]

    if cmd in ['/scan', '/evening', '/scan1']:
        send_telegram("Starting evening scan... (~8 min)")
        run_evening_scan()
        return None

    elif cmd in ['/morning', '/scan2', '/scan3']:
        send_telegram("Starting morning scan...")
        run_morning_scan()
        return None

    elif cmd == '/relax':
        RULES['SCAN_MODE'] = 'RELAXED'
        return ("RELAXED mode ON\n\nRSI max:76 ADX min:14 Vol:1.1x\n"
                "More stocks will appear.\nSend /scan to scan.")

    elif cmd == '/strict':
        RULES['SCAN_MODE'] = 'STRICT'
        return ("STRICT mode ON\n\nRSI max:72 ADX min:18 Vol:1.4x\n"
                "Quality stocks only.\nSend /scan to scan.")

    elif cmd == '/relax_scan':
        RULES['SCAN_MODE'] = 'RELAXED'
        send_telegram("Relaxed mode. Scanning...")
        run_evening_scan()
        return None

    elif cmd == '/strict_scan':
        RULES['SCAN_MODE'] = 'STRICT'
        send_telegram("Strict mode. Scanning...")
        run_evening_scan()
        return None

    elif cmd == '/trades':
        return build_trades_msg(check_active_trades())

    elif cmd == '/status':
        shortlist = []
        last_time = "No scan yet"
        if os.path.exists(SHORTLIST_FILE):
            try:
                with open(SHORTLIST_FILE) as f: d = json.load(f)
                shortlist = d.get('results', [])
                last_time = d.get('time','')[:16].replace('T',' ')
            except: pass
        trades = load_trades()
        sl_str = ', '.join([r['symbol'] for r in shortlist[:5]]) or "None"
        return (f"STATUS\n{'─'*25}\n"
                f"Mode    : {RULES.get('SCAN_MODE','STRICT')}\n"
                f"Capital : Rs.{CONFIG['TOTAL_CAPITAL']:,}\n"
                f"Last scan: {last_time}\n"
                f"Shortlist: {sl_str}\n"
                f"Trades  : {len(trades)} active\n"
                f"Auto: 8PM evening + 9:30AM morning")

    elif cmd == '/capital':
        shortlist = []
        if os.path.exists(SHORTLIST_FILE):
            try:
                with open(SHORTLIST_FILE) as f:
                    shortlist = json.load(f).get('results', [])
            except: pass
        if not shortlist: return "No shortlist. Run /scan first."
        cap = CONFIG['TOTAL_CAPITAL']
        alloc = [0.40,0.35,0.25] if len(shortlist)>=3 else [0.55,0.45] if len(shortlist)==2 else [1.0]
        msg = f"CAPITAL PLAN (Rs.{cap:,})\n"
        for r, a in zip(shortlist, alloc):
            amt = round(cap*a)
            sh  = max(1, int(amt/r['close']))
            msg += f"{r['symbol']}: Rs.{amt:,} ({int(a*100)}%) — {sh} shares\n"
            msg += f"  SL:Rs.{r['sl']} T2:Rs.{r['target2']}\n"
        return msg

    elif cmd == '/help':
        return ("SWING HUNTER COMMANDS\n" + "─"*25 + "\n"
                "/scan         Evening scan now\n"
                "/morning      Morning verdict\n"
                "/relax        Relaxed filters\n"
                "/strict       Strict filters\n"
                "/relax_scan   Relax + scan now\n"
                "/strict_scan  Strict + scan now\n"
                "/trades       Hold/sell advice\n"
                "/status       Config + shortlist\n"
                "/capital      Capital allocation\n"
                "/help         This message")

    elif cmd == '/stop':
        RUNTIME['bot_active'] = False
        return "Bot stopped."

    else:
        return "Unknown. Send /help"

def run_bot():
    tok = CONFIG['TELEGRAM_TOKEN']
    cid = CONFIG['TELEGRAM_CHAT_ID']
    if not tok or not cid:
        print("Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in CONFIG")
        return

    log.info("BOT STARTED — listening for Telegram commands")
    send_telegram(("Swing Hunter Bot ONLINE!\n\n"
                   f"Mode: {RULES.get('SCAN_MODE','STRICT')}\n"
                   "Auto: 8:00 PM + 9:30 AM IST\n\n"
                   "Send /help to see all commands"))

    if HAS_SCHEDULE:
        schedule.every().day.at(CONFIG['EVENING_TIME']).do(run_evening_scan)
        schedule.every().day.at(CONFIG['MORNING_TIME']).do(run_morning_scan)
        log.info(f"Scheduled: {CONFIG['EVENING_TIME']} + {CONFIG['MORNING_TIME']} IST")

    offset = 0
    while RUNTIME['bot_active']:
        try:
            if HAS_SCHEDULE: schedule.run_pending()
            updates, offset = get_tg_updates(offset)
            for upd in updates:
                msg_data = upd.get('message', {})
                text     = msg_data.get('text', '').strip()
                chat_id  = msg_data.get('chat', {}).get('id', '')
                name     = msg_data.get('from', {}).get('first_name', 'User')
                if text and text.startswith('/'):
                    log.info(f"Command [{name}]: {text}")
                    resp = handle_tg_command(text, chat_id)
                    if resp: send_telegram(resp)
        except KeyboardInterrupt:
            log.info("Bot stopped.")
            send_telegram("Bot stopped.")
            break
        except Exception as e:
            log.error(f"Bot error: {e}")
            time.sleep(5)
        time.sleep(1)

# ══════════════════════════════════════════════════════════════
#  ▶  ENTRY POINT
# ══════════════════════════════════════════════════════════════
def main():
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    if cmd == "scan1":    run_evening_scan();    return
    if cmd == "scan2":    run_morning_scan();    return
    if cmd == "scan3":    run_morning_scan();    return
    if cmd == "test":     run_test();     return
    if cmd == "telegram": test_telegram();return
    if cmd == "bot":      run_bot();      return

    stocks = get_stock_list()
    fund_cache  = load_fund_cache()
    fund_loaded = sum(1 for s in stocks if is_fund_fresh(fund_cache,s))

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║         SWING HUNTER v6.0 — 3-Scan System                   ║
╠══════════════════════════════════════════════════════════════╣
║  Stocks     : {len(stocks):<46} ║
║  Fund cache : {f"{fund_loaded}/{len(stocks)} stocks (yfinance live)":<46} ║
║  Telegram   : {'Configured ✅' if CONFIG['TELEGRAM_TOKEN'] else 'NOT CONFIGURED — edit CONFIG above':<46} ║
║  Capital    : {'Rs.'+str(CONFIG['TOTAL_CAPITAL']):<46} ║
╠══════════════════════════════════════════════════════════════╣
║  3-SCAN SCHEDULE:                                            ║
║  Scan 1 @ 6:00 PM → Full scan (Bhavcopy fully loaded)       ║
║  Scan 2 @ 8:00 PM → Recheck shortlist only                  ║
║  Scan 3 @ 9:15 AM → Final BUY/WAIT/SKIP verdict             ║
╠══════════════════════════════════════════════════════════════╣
║  COMMANDS:                                                   ║
║    python swing_hunter.py         Auto 3-scan scheduler      ║
║    python swing_hunter.py scan1   Run Scan 1 now             ║
║    python swing_hunter.py scan2   Run Scan 2 now             ║
║    python swing_hunter.py scan3   Run Scan 3 now             ║
║    python swing_hunter.py test    Test data sources          ║
║    python swing_hunter.py telegram Test Telegram             ║
╚══════════════════════════════════════════════════════════════╝""")

    if not CONFIG['TELEGRAM_TOKEN']:
        print("\n  ⚠️  Edit CONFIG at top of file — add TELEGRAM_TOKEN and CHAT_ID\n")

    if not HAS_SCHEDULE:
        print("  ⚠️  Install schedule: pip install schedule")
        print("  Then re-run without arguments for auto scheduler")
        return
    schedule.every().day.at(CONFIG['EVENING_TIME']).do(run_evening_scan)
    schedule.every().day.at(CONFIG['MORNING_TIME']).do(run_morning_scan)

    print(f"  ⏰ Scan 1 scheduled: {CONFIG['EVENING_TIME']} IST (full scan)")
    print(f"  ⏰ Scan 2 scheduled: {CONFIG['MORNING_TIME']} IST (recheck)")
    print(f"  ⏰ Scan 3 scheduled: {CONFIG['MORNING_TIME']} IST (final verdict)")
    print("  Keep window open. Ctrl+C to stop.\n")

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
