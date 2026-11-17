"""Results tracker: replays every candidates_*.csv the scanner produced against real prices.

For each candidate row it simulates two entry styles:
  - "immediate": buy the open of the scan day (the scanner runs pre-market)
  - "confirmed": wait for the first green close with low >= prior low (on/after the
    scan day), then buy the next open. No confirmation before the exit -> no trade.
Then it walks day by day: gap through stop fills at the open, stop and target on the
same day counts as the stop, otherwise exit at the close of Exit_Date.
SPY is measured over each trade's actual holding days.

Usage (from the project folder):
  .venv/bin/python research/tracker.py
Writes research/output/tracker_trades.csv and prints a summary.
"""

import glob
import io
import os
import re
import subprocess
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "research", "output")
SLIPPAGE = 0.0005  # 5 bps per side


def load_candidate_files():
  """All candidate CSVs: those on disk plus ones that only exist in git history."""
  frames = {}
  for path in glob.glob(os.path.join(ROOT, "candidates_*.csv")):
    frames[os.path.basename(path)] = pd.read_csv(path)
  try:
    names = subprocess.run(
        ["git", "log", "--all", "--name-only", "--pretty=format:", "--",
         "candidates_*.csv"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    for name in sorted(set(names) - set(frames)):
      sha = subprocess.run(
          ["git", "log", "--all", "-n", "1", "--pretty=format:%H", "--", name],
          cwd=ROOT, capture_output=True, text=True,
      ).stdout.strip()
      blob = subprocess.run(
          ["git", "show", f"{sha}^:{name}"], cwd=ROOT, capture_output=True, text=True
      )
      if blob.returncode != 0:  # file still exists at that commit
        blob = subprocess.run(
            ["git", "show", f"{sha}:{name}"], cwd=ROOT, capture_output=True, text=True
        )
      if blob.returncode == 0 and blob.stdout.strip():
        frames[name] = pd.read_csv(io.StringIO(blob.stdout))
  except Exception as e:
    print(f"[!] git history not read: {e}")

  rows = []
  for name, df in frames.items():
    m = re.search(r"candidates_(v[\d_]+?)_?(\d{4}-\d{2}-\d{2})\.csv", name)
    if not m or "Exit_Date" not in df.columns:
      continue
    df = df.copy()
    df["Scan_Date"] = pd.Timestamp(m.group(2))
    df["Version"] = m.group(1).rstrip("_")
    if "Trigger_Status" not in df.columns:
      df["Trigger_Status"] = df.get("Entry_Timing", np.nan)
    if "Setup_Score_70" not in df.columns:
      df["Setup_Score_70"] = df.get("Math_Score_70", np.nan)
    rows.append(df)
  allc = pd.concat(rows, ignore_index=True)
  allc["Exit_Date"] = pd.to_datetime(allc["Exit_Date"])
  allc["Earnings_Date"] = pd.to_datetime(allc["Earnings_Date"])
  return allc.sort_values(["Scan_Date", "Ticker"]).reset_index(drop=True)


def simulate(bars, entry_idx, stop, target, exit_date):
  """Walk bars from entry_idx. Returns (exit_idx, fill_price, outcome)."""
  entry = bars["Open"].iloc[entry_idx] * (1 + SLIPPAGE)
  last_idx = bars.index.searchsorted(exit_date, side="right") - 1
  if last_idx < entry_idx:
    return None
  for j in range(entry_idx, last_idx + 1):
    o, h, l = bars["Open"].iloc[j], bars["High"].iloc[j], bars["Low"].iloc[j]
    if j > entry_idx and o <= stop:
      return j, o * (1 - SLIPPAGE), "STOP_GAP", entry
    if l <= stop:
      return j, stop * (1 - SLIPPAGE), "STOP", entry
    if pd.notna(target) and h >= target:
      fill = max(o, target) if j > entry_idx else target
      return j, fill * (1 - SLIPPAGE), "TARGET", entry
  return last_idx, bars["Close"].iloc[last_idx] * (1 - SLIPPAGE), "EXIT_DATE", entry


def run():
  cands = load_candidate_files()
  today = pd.Timestamp.now(tz="America/New_York").tz_localize(None).normalize()
  tickers = sorted(set(cands["Ticker"]) | {"SPY"})
  start = cands["Scan_Date"].min() - pd.Timedelta(days=10)
  px = yf.download(tickers, start=start, end=today + pd.Timedelta(days=1),
                   group_by="ticker", progress=False, auto_adjust=True)
  spy = px["SPY"].dropna(subset=["Close"])

  trades = []
  for _, r in cands.iterrows():
    t = r["Ticker"]
    if t not in px.columns.get_level_values(0):
      continue
    bars = px[t].dropna(subset=["Close"])
    scan = r["Scan_Date"]
    first_idx = bars.index.searchsorted(scan)  # first bar on/after scan date
    if first_idx >= len(bars):
      continue

    # Parity check: CSV Price should equal the last close before the scan date
    prev_close = bars["Close"].iloc[first_idx - 1] if first_idx > 0 else np.nan
    same_close = bars["Close"].iloc[first_idx]
    dev_prev = abs(r["Price"] / prev_close - 1) if prev_close else np.nan
    dev_same = abs(r["Price"] / same_close - 1)
    if dev_prev <= 0.01:
      parity = "ok"
    elif dev_same <= 0.01:
      parity = "ran_after_close"
      first_idx += 1  # scanner saw this bar already -> entry is the next open
    else:
      parity = f"MISMATCH({dev_prev*100:.1f}%)"
    is_open = r["Exit_Date"] > today - pd.Timedelta(days=1) and first_idx < len(bars)

    for mode in ("immediate", "confirmed"):
      entry_idx = first_idx
      if mode == "confirmed":
        entry_idx = None
        for j in range(max(first_idx - 1, 1), len(bars)):
          if bars.index[j] > r["Exit_Date"]:
            break
          if bars.index[j] < scan - pd.Timedelta(days=5):
            continue
          green = bars["Close"].iloc[j] > bars["Open"].iloc[j]
          higher_low = bars["Low"].iloc[j] >= bars["Low"].iloc[j - 1]
          if green and higher_low and j + 1 < len(bars) and j + 1 >= first_idx:
            entry_idx = j + 1
            break
        if entry_idx is None:
          trades.append({**_base(r, parity), "Mode": mode, "Outcome": "NO_ENTRY"})
          continue
      if entry_idx >= len(bars):
        continue
      res = simulate(bars, entry_idx, r["Hard_Stop_Price"],
                     r.get("Early_Target_Price"), r["Exit_Date"])
      if res is None:
        trades.append({**_base(r, parity), "Mode": mode, "Outcome": "NO_ENTRY"})
        continue
      exit_idx, fill, outcome, entry = res
      still_open = outcome == "EXIT_DATE" and is_open
      ent_d, ex_d = bars.index[entry_idx], bars.index[exit_idx]
      s_in = spy["Open"].asof(ent_d)
      s_out = spy["Close"].asof(ex_d)
      risk = entry - r["Hard_Stop_Price"]
      trades.append({
          **_base(r, parity),
          "Mode": mode,
          "Entry_Date": ent_d.date(),
          "Entry": round(entry, 2),
          "Exit_Fill_Date": ex_d.date(),
          "Exit": round(fill, 2),
          "Outcome": "OPEN" if still_open else outcome,
          "Ret_%": round((fill / entry - 1) * 100, 2),
          "R_Multiple": round((fill - entry) / risk, 2) if risk > 0 else np.nan,
          "SPY_%": round((s_out / s_in - 1) * 100, 2),
      })

  tr = pd.DataFrame(trades)
  os.makedirs(OUT_DIR, exist_ok=True)
  tr.to_csv(os.path.join(OUT_DIR, "tracker_trades.csv"), index=False)
  summarize(tr)
  return tr


def _base(r, parity):
  return {
      "Scan_Date": r["Scan_Date"].date(),
      "Version": r["Version"],
      "Ticker": r["Ticker"],
      "Earnings_Date": r["Earnings_Date"].date(),
      "Exit_Date": r["Exit_Date"].date(),
      "Trigger": r.get("Trigger_Status"),
      "Score": r.get("Setup_Score_70"),
      "Sub_ETF": r.get("Sub_ETF"),
      "Parity": parity,
  }


def _stats(g):
  g = g[g["Outcome"].isin(["STOP", "STOP_GAP", "TARGET", "EXIT_DATE"])]
  if g.empty:
    return "n=0"
  ex = g["Ret_%"] - g["SPY_%"]
  oc = g["Outcome"].value_counts().to_dict()
  return (f"n={len(g):3d} win={(g['Ret_%'] > 0).mean()*100:3.0f}% "
          f"avg={g['Ret_%'].mean():+6.2f}% med={g['Ret_%'].median():+6.2f}% "
          f"avgR={g['R_Multiple'].mean():+5.2f} vsSPY={ex.mean():+6.2f}% {oc}")


def summarize(tr):
  pd.set_option("display.width", 250)
  bad = tr[tr["Parity"].str.startswith("MISMATCH")].drop_duplicates(
      ["Scan_Date", "Ticker"])
  if not bad.empty:
    print("[!] Price parity mismatches (CSV Price vs real close):")
    print(bad[["Scan_Date", "Ticker", "Parity"]].to_string(index=False))
  # v2 files used different rules and had no stop levels -> only v4+ is evaluated
  tr = tr[~tr["Version"].str.startswith(("v2", "v3"))]
  closed = tr[tr["Outcome"] != "OPEN"]
  print(f"\nOpen trades (exit not reached): "
        f"{tr[(tr.Outcome == 'OPEN') & (tr.Mode == 'immediate')].Ticker.tolist()}")
  for mode in ("immediate", "confirmed"):
    m = closed[closed["Mode"] == mode]
    first = m.drop_duplicates(["Ticker", "Earnings_Date"], keep="first")
    print(f"\n== {mode} entry ==")
    print("  every row (overlapping):   ", _stats(m))
    print("  first signal per ER cycle: ", _stats(first))
    if mode == "confirmed":
      print(f"  no confirmation before exit: "
            f"{(first['Outcome'] == 'NO_ENTRY').sum()} of {len(first)} cycles")
    for trig, g in first.groupby("Trigger"):
      print(f"    trigger {str(trig):15s}", _stats(g))


if __name__ == "__main__":
  run()
