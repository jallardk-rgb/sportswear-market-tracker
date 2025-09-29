import time
from datetime import datetime, timezone
from io import BytesIO

import pandas as pd
import yfinance as yf
import streamlit as st

st.set_page_config(page_title="Sportswear Market Tracker", layout="wide")

st.title("Sportswear Market Tracker")
st.caption("Market Cap (USD), Revenue TTM (USD), Daily % Change, and P/E (TTM). Data source: Yahoo Finance via yfinance.")

# --- Company list and config -------------------------------------------------
COMPANIES = [
    ("Nike", "NKE"),
    ("Adidas", "ADS.DE"),            # XETRA
    ("Anta Sports", "2020.HK"),      # HKEX
    ("Lululemon Athletica", "LULU"),
    ("Amer Sports", "AS"),           # NYSE
    ("ASICS", "7936.T"),             # Tokyo
    ("On Holding (On Running)", "ONON"),
    ("Deckers (HOKA, UGG)", "DECK"),
    ("Skechers", "SKX"),             # Corporate action may limit fresh quotes
    ("JD Sports Fashion", "JD.L"),   # London
    ("Li Ning", "2331.HK"),
    ("VF Corporation (Vans)", "VFC"),
    ("Puma", "PUM.DE"),
    ("Columbia Sportswear", "COLM"),
    ("Yonex", "7906.T"),
    ("Under Armour (Class A)", "UAA"),
    ("Fila Holdings", "081660.KS"),  # Korea
    ("361 Degrees", "1361.HK"),
    ("Mizuno", "8022.T"),
    ("BasicNet (Kappa)", "BAN.MI"),  # Borsa Italiana (BAN.MI on Yahoo)
]

FETCH_DELAY_SEC = 0.25  # polite delay between ticker calls

# --- Helpers -----------------------------------------------------------------
def clean_ticker(t: str) -> str:
    return t.strip().replace("$", "")

def safe(d, k, default=None):
    try:
        return d.get(k, default)
    except Exception:
        return default

def human_format(num):
    """Format large numbers with K/M/B/T suffixes and commas, suffixed by USD."""
    if pd.isna(num):
        return ""
    units = ["", "K", "M", "B", "T"]
    for unit in units:
        if abs(num) < 1000:
            return f"{num:,.0f} {unit} USD".strip()
        num /= 1000.0
    # Very large fallback
    return f"{num:.1f}P USD"

@st.cache_data(show_spinner=False, ttl=60*30)  # cache for 30 minutes
def get_fx_rates(codes):
    rates = {"USD": 1.0}
    for c in sorted({c for c in codes if c and c != "USD"}):
        try:
            fx = yf.Ticker(f"{c}USD=X").history(period="5d")["Close"]
            if len(fx) > 0:
                rates[c] = float(fx.iloc[-1])
        except Exception:
            pass
    return rates

def revenue_ttm(tkr: yf.Ticker):
    # Try sum of last 4 quarters; fallback to totalRevenue
    try:
        qf = tkr.quarterly_financials
        if qf is not None and not qf.empty:
            for key in ["Total Revenue", "TotalRevenue"]:
                if key in qf.index:
                    vals = qf.loc[key].dropna().astype(float)
                    if len(vals):
                        return float(vals.iloc[:4].sum())
    except Exception:
        pass
    try:
        return safe(tkr.info, "totalRevenue")
    except Exception:
        return None

def daily_pct_change(tkr: yf.Ticker):
    try:
        hist = tkr.history(period="2d")
        closes = hist["Close"].dropna()
        if len(closes) >= 2 and closes.iloc[-2] != 0:
            return float((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100.0)
        # fallback using previousClose/currentPrice
        info = tkr.info
        prev = safe(info, "previousClose")
        last = safe(info, "currentPrice")
        if prev and last and prev != 0:
            return float((last - prev) / prev * 100.0)
    except Exception:
        return None

@st.cache_data(show_spinner=True, ttl=60*30)  # cache for 30 minutes
def fetch_data():
    # Prefetch currencies for FX conversions
    currs = []
    tickers = [clean_ticker(t) for _, t in COMPANIES]
    for t in tickers:
        try:
            info = yf.Ticker(t).info
            currs.append((safe(info, "financialCurrency") or safe(info, "currency") or "USD").upper())
        except Exception:
            currs.append("USD")
    fx = get_fx_rates(currs)

    rows = []
    notes = []
    for (name, tkr_raw), cur in zip(COMPANIES, currs):
        tkr_sym = clean_ticker(tkr_raw)
        tkr = yf.Ticker(tkr_sym)

        info = {}
        try:
            info = tkr.info or {}
        except Exception:
            pass

        currency = (safe(info, "financialCurrency") or safe(info, "currency") or cur or "USD").upper()
        mktcap_nat = safe(info, "marketCap")
        rev_nat = revenue_ttm(tkr)
        pe = safe(info, "trailingPE")
        pct = daily_pct_change(tkr)

        rate = fx.get(currency, 1.0)
        mktcap_usd = float(mktcap_nat) * rate if mktcap_nat else None
        rev_usd = float(rev_nat) * rate if rev_nat else None

        last = safe(info, "currentPrice")
        if last is None:
            try:
                h = tkr.history(period="1d")
                if len(h):
                    last = float(h["Close"].iloc[-1])
            except Exception:
                last = None

        if name == "Skechers" and (pct is None or mktcap_usd is None):
            notes.append("SKX: corporate action/delisting risk may limit recent quotes; data may be incomplete.")

        rows.append({
            "Company": name,
            "Ticker": tkr_sym,
            "Native Currency": currency,
            "Last Price (native)": last,
            "Market Cap (USD)": mktcap_usd,
            "Revenue TTM (USD)": rev_usd,
            "P/E (TTM)": pe,
            "Daily % Change": pct,
            "Updated (UTC)": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        })
        time.sleep(FETCH_DELAY_SEC)

    df = pd.DataFrame(rows).sort_values("Market Cap (USD)", ascending=False, na_position="last")
    return df, notes

# --- Sidebar Controls --------------------------------------------------------
with st.sidebar:
    st.header("Controls")
    refresh = st.button("Refresh now")
    st.write("Data is cached for ~30 minutes. Use Refresh to force a new fetch.")
    st.divider()
    st.write("Download options will appear below the table.")

# --- Main content ------------------------------------------------------------
if refresh:
    # Clear caches to force fresh pull
    fetch_data.clear()
    get_fx_rates.clear()

df, notes = fetch_data()

# Apply human-readable formatting for display only
df_display = df.copy()
df_display["Market Cap (USD)"] = df_display["Market Cap (USD)"].apply(human_format)
df_display["Revenue TTM (USD)"] = df_display["Revenue TTM (USD)"].apply(human_format)

st.dataframe(
    df_display,
    use_container_width=True,
    hide_index=True
)

# Download buttons (CSV/Excel use the raw numeric values for analysis)
csv_bytes = df.to_csv(index=False).encode("utf-8")
xlsx_buf = BytesIO()
try:
    df.to_excel(xlsx_buf, index=False, engine="openpyxl")
    xlsx_buf.seek(0)
except Exception:
    xlsx_buf = None

st.download_button("Download CSV", data=csv_bytes, file_name="sportswear_market_tracker.csv", mime="text/csv")
if xlsx_buf is not None:
    st.download_button("Download Excel", data=xlsx_buf, file_name="sportswear_market_tracker.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

if notes:
    st.info("\\n".join(f"- {n}" for n in notes))

st.caption("Note: All monetary values are converted to USD using latest FX close prices from Yahoo Finance. 'Native Currency' shows the company listing currency for reference.")