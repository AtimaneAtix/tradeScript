"""Downloads the history the backtest needs into research/data/ (git-ignored).

- universe.csv : current S&P 500 (with GICS + "Date added") + Nasdaq-100-only names
- prices.pkl   : daily OHLCV since 2014 for every stock + all sector/sub ETFs + SPY + ^VIX
- earnings/T.csv : Yahoo earnings history (actual dates, EPS surprise) per ticker

Resumable: earnings files that already exist are skipped. Re-run to fill gaps.
Usage: .venv/bin/python research/fetch_data.py
"""

import io
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

import pandas as pd
import requests
import yfinance as yf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import scanner as S  # noqa: E402  (reuses the scanner's own ETF mapping)

DATA = os.path.join(ROOT, "research", "data")
EARN = os.path.join(DATA, "earnings")
START = "2014-01-01"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def build_universe():
  sp = pd.read_html(io.StringIO(
      requests.get(S.SP500_URL, headers=HEADERS, timeout=20).text))[0]
  sp["Symbol"] = sp["Symbol"].astype(str).str.replace(".", "-", regex=False)
  rows = []
  for _, r in sp.iterrows():
    sec, sub = str(r["GICS Sector"]), str(r["GICS Sub-Industry"])
    rows.append({"Symbol": r["Symbol"], "Sector": sec, "Sub_Industry": sub,
                 "Sub_ETF": S.map_subsector_etf(sec, sub),
                 "Date_Added": pd.to_datetime(r.get("Date added"), errors="coerce"),
                 "Source": "SP500"})
  have = set(sp["Symbol"])
  ndx = pd.read_html(io.StringIO(
      requests.get(S.NDX_URL, headers=HEADERS, timeout=20).text))
  tbl = next(t for t in ndx if "Ticker" in t.columns and len(t) >= 90)
  ind = next(c for c in tbl.columns if "Industry" in str(c))
  subc = next(c for c in tbl.columns if "Subsector" in str(c))
  for _, r in tbl.iterrows():
    sym = str(r["Ticker"]).replace(".", "-").upper()
    if sym in have:
      continue
    sec = S.ICB_TO_GICS_SECTOR.get(str(r[ind]), "Information Technology")
    rows.append({"Symbol": sym, "Sector": sec, "Sub_Industry": str(r[subc]),
                 "Sub_ETF": S.map_subsector_etf(sec, str(r[subc])),
                 "Date_Added": pd.NaT, "Source": "NDX"})
  u = pd.DataFrame(rows)
  u.to_csv(os.path.join(DATA, "universe.csv"), index=False)
  return u


def fetch_prices(u):
  path = os.path.join(DATA, "prices.pkl")
  if os.path.exists(path):
    print("prices.pkl exists, skipping (delete it to refresh)")
    return
  etfs = sorted(set(u["Sub_ETF"]) | set(S.SECTOR_ETF_MAP.values()) | {"SPY", "QQQ", "^VIX"})
  syms = sorted(set(u["Symbol"])) + etfs
  parts = []
  for i in range(0, len(syms), 100):
    chunk = syms[i:i + 100]
    for attempt in range(3):
      try:
        d = yf.download(chunk, start=START, group_by="ticker", progress=False,
                        auto_adjust=True, threads=True)
        parts.append(d)
        print(f"prices {i + len(chunk)}/{len(syms)}", flush=True)
        break
      except Exception as e:
        print(f"  retry chunk {i}: {e}", flush=True)
        time.sleep(5)
  px = pd.concat(parts, axis=1)
  px = px.loc[:, ~px.columns.duplicated()]
  px.to_pickle(path)
  print("prices saved:", px.shape, flush=True)


def fetch_earnings(u):
  os.makedirs(EARN, exist_ok=True)
  syms = sorted(set(u["Symbol"]))
  failed = []
  for k, t in enumerate(syms):
    out = os.path.join(EARN, f"{t}.csv")
    if os.path.exists(out):
      continue
    ok = False
    for attempt in range(3):
      try:
        ed = yf.Ticker(t).get_earnings_dates(limit=100)
        if ed is None or ed.empty:
          break
        ed = ed.copy()
        ed.index = S.normalize_ny_dates(ed.index)
        ed.index.name = "Date"
        ed[["EPS Estimate", "Reported EPS", "Surprise(%)"]].to_csv(out)
        ok = True
        break
      except Exception:
        time.sleep(3 * (attempt + 1))
    if not ok:
      failed.append(t)
    time.sleep(0.4)
    if k % 50 == 0:
      print(f"earnings {k}/{len(syms)}", flush=True)
  print(f"earnings done, failed={failed}", flush=True)


if __name__ == "__main__":
  os.makedirs(DATA, exist_ok=True)
  u = build_universe()
  print("universe:", len(u), u["Source"].value_counts().to_dict(), flush=True)
  fetch_prices(u)
  fetch_earnings(u)
