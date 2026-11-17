"""Downloads history for the parts of the score that the price backtest could not test.

- analyst/T.pkl  : Yahoo upgrades/downgrades history (dated events with price targets)
- splits/T.pkl   : Yahoo split history (to put old price targets on today's share basis)
- close_raw.pkl  : split-adjusted but NOT dividend-adjusted closes (as quoted at the time,
                   apart from splits) -> fair comparison with analyst price targets
- sec/T.csv      : SEC EDGAR XBRL revenue facts (value, period, FILED date) per company

SEC requires a contact in the User-Agent. It is read from the environment variable
SEC_USER_AGENT at runtime and never written to disk or printed. Without it, the SEC part
is skipped. Resumable: existing files are skipped.

Usage: SEC_USER_AGENT="name email" .venv/bin/python research/fetch_fundamentals.py
"""

import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

import pandas as pd
import requests
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
REV_TAGS = [
    ("us-gaap", "Revenues"),
    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
    ("us-gaap", "SalesRevenueNet"),
    ("us-gaap", "SalesRevenueGoodsNet"),
    ("us-gaap", "RevenuesNetOfInterestExpense"),
    ("ifrs-full", "Revenue"),
]


def fetch_yahoo(symbols):
  for sub in ("analyst", "splits"):
    os.makedirs(os.path.join(DATA, sub), exist_ok=True)
  for k, t in enumerate(symbols):
    pa, ps = (os.path.join(DATA, s, f"{t}.pkl") for s in ("analyst", "splits"))
    if os.path.exists(pa) and os.path.exists(ps):
      continue
    tk = yf.Ticker(t)
    for attempt in range(3):
      try:
        try:
          ud = tk.upgrades_downgrades
        except Exception as e:
          ud = pd.DataFrame() if "no upgrade" in str(e).lower() else None
          if ud is None:
            raise
        ud.to_pickle(pa)
        tk.splits.to_pickle(ps)
        break
      except Exception:
        time.sleep(3 * (attempt + 1))
    time.sleep(0.3)
    if k % 50 == 0:
      print(f"yahoo {k}/{len(symbols)}", flush=True)
  print("yahoo done", flush=True)


def fetch_close_raw(symbols):
  path = os.path.join(DATA, "close_raw.pkl")
  if os.path.exists(path):
    return
  parts = []
  for i in range(0, len(symbols), 100):
    d = yf.download(symbols[i:i + 100], start="2014-01-01", progress=False,
                    auto_adjust=False, group_by="ticker", threads=True)
    parts.append(d.xs("Close", axis=1, level=1))
  pd.concat(parts, axis=1).to_pickle(path)
  print("close_raw saved", flush=True)


def fetch_sec(symbols, ua):
  os.makedirs(os.path.join(DATA, "sec"), exist_ok=True)
  h = {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}
  r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=h, timeout=30)
  r.raise_for_status()
  cik = {v["ticker"].replace(".", "-"): int(v["cik_str"]) for v in r.json().values()}
  missing = []
  for k, t in enumerate(symbols):
    out = os.path.join(DATA, "sec", f"{t}.csv")
    if os.path.exists(out):
      continue
    c = cik.get(t)
    if c is None:
      missing.append(t)
      continue
    rows = []
    for tax, tag in REV_TAGS:
      url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{c:010d}/{tax}/{tag}.json"
      for attempt in range(3):
        try:
          resp = requests.get(url, headers=h, timeout=30)
          if resp.status_code == 404:
            break
          resp.raise_for_status()
          for unit, facts in resp.json().get("units", {}).items():
            for f in facts:
              rows.append({"tag": tag, "unit": unit, "start": f.get("start"),
                           "end": f.get("end"), "val": f.get("val"), "filed": f.get("filed"),
                           "form": f.get("form"), "fp": f.get("fp"), "fy": f.get("fy")})
          break
        except Exception:
          time.sleep(2 * (attempt + 1))
      time.sleep(0.12)  # SEC fair-access limit is 10 requests/second
    pd.DataFrame(rows).to_csv(out, index=False)
    if k % 50 == 0:
      print(f"sec {k}/{len(symbols)}", flush=True)
  print(f"sec done; no CIK for: {missing}", flush=True)


if __name__ == "__main__":
  u = pd.read_csv(os.path.join(DATA, "universe.csv"))
  syms = sorted(u.Symbol)
  sec_only = "--sec-only" in sys.argv
  if not sec_only:
    fetch_close_raw(syms)
  ua = os.environ.get("SEC_USER_AGENT")
  if ua:
    fetch_sec(syms, ua)
  else:
    print("SEC_USER_AGENT not set -> SEC revenue download skipped", flush=True)
  if not sec_only:
    fetch_yahoo(syms)
  print("FINISHED", flush=True)
