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
    """Compute 1-day % change with robust checks and outlier filtering."""
    try:
        # Primary: last two closes
        hist = tkr.history(period="2d")
        closes = hist["Close"].dropna()
        if len(closes) >= 2:
            prev, last = float(closes.iloc[-2]), float(closes.iloc[-1])
            if prev and prev > 0:
                change = (last - prev) / prev * 100.0
                # Filter obvious data glitches (corporate actions, missing prev close, bad ticks)
                if abs(change) > 50:
                    return None
                return float(change)
        # Fallback: info.previousClose/currentPrice
        info = tkr.info or {}
        prev = info.get("previousClose")
        last = info.get("currentPrice")
        if prev and last and prev > 0:
            change = (float(last) - float(prev)) / float(prev) * 100.0
            if abs(change) > 50:
                return None
            return float(change)
    except Exception:
        return None
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

# Create display-friendly numeric columns in billions (keeps sorting numeric)
df_display = df.copy()
df_display["Market Cap (USD, B)"] = df_display["Market Cap (USD)"] / 1e9
df_display["Revenue TTM (USD, B)"] = df_display["Revenue TTM (USD)"] / 1e9

# Choose column order for display (keep raw USD for downloads and backend)
display_cols = [
    "Company",
    "Ticker",
    "Native Currency",
    "Last Price (native)",
    "Market Cap (USD, B)",
    "Revenue TTM (USD, B)",
    "P/E (TTM)",
    "Daily % Change",
    "Updated (UTC)",
]

st.dataframe(
    df_display[display_cols],
    use_container_width=True,
    hide_index=True,
    column_order=display_cols,
    column_config={
        "Market Cap (USD, B)": st.column_config.NumberColumn(
            "Market Cap (USD, B)",
            help="Billions of USD",
            format="%,.2f B USD"
        ),
        "Revenue TTM (USD, B)": st.column_config.NumberColumn(
            "Revenue TTM (USD, B)",
            help="Billions of USD",
            format="%,.2f B USD"
        ),
        "Last Price (native)": st.column_config.NumberColumn(
            "Last Price (native)",
            format="%,.2f"
        ),
        "P/E (TTM)": st.column_config.NumberColumn(
            "P/E (TTM)",
            format="%,.2f"
        ),
        "Daily % Change": st.column_config.NumberColumn(
            "Daily % Change",
            format="%,.2f%%"
        ),
    }
)

# Download buttons (CSV/Excel use the raw numeric values for analysis)
csv_bytes = df.to_csv(index=False).encode("utf-8")
xlsx_buf = BytesIO()
try:
    df.to_excel(xlsx_buf, index=False, engine="openpyxl")
    xlsx_buf.seek(0)
except Exception:
    xlsx_buf = None

st.download_button("Download CSV (raw USD)", data=csv_bytes, file_name="sportswear_market_tracker.csv", mime="text/csv")
if xlsx_buf is not None:
    st.download_button("Download Excel (raw USD)", data=xlsx_buf, file_name="sportswear_market_tracker.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

if notes:
    st.info("\\n".join(f"- {n}" for n in notes))

st.caption("All monetary values are converted to USD. Table displays billions (B USD) for readability while preserving numeric sorting. Downloads contain raw USD values.")