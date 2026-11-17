"""Step 1 of the scoring work: which features actually predict trade results?

Outcome = the v4.8 trade plan (2.5 ATR stop, no target, exit T-3), in R units, plus the
held-to-exit return in excess of SPY. Information coefficient (IC) = Spearman rank
correlation between a feature and the outcome, measured separately in 2016-22 and
2023-26. A feature only counts if its sign agrees in both periods.

Features were declared before looking: everything the scanner scores today, plus three
well-known ones it doesn't use (6-month momentum, distance above the 200-day average,
20-day return).

Usage: .venv/bin/python research/scoring.py
"""

import os
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest as B  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 200)


def load_trades():
  T = pd.read_pickle(os.path.join(B.DATA, "trade_plan_trades.pkl"))
  tr = T["stop2.5_noTgt_fixed"].copy()
  raw = pd.read_pickle(os.path.join(B.DATA, "trades_raw.pkl"))[["Ticker", "ER", "Excess", "Ret"]]
  tr = tr.merge(raw.rename(columns={"Excess": "RawExcess", "Ret": "RawRet"}),
                on=["Ticker", "ER"], how="left")
  return tr


def add_features(tr, px):
  extra = []
  for t, g in tr.groupby("Ticker"):
    b = B.bars_of(px, t)
    c = b["Close"].values
    sma200 = b["Close"].rolling(200).mean().values
    for k, r in g.iterrows():
      i = int(r["i"])
      extra.append({
          "_k": k,
          "Mom126": (c[i - 21] / c[i - 126] - 1) * 100 if i >= 126 else np.nan,
          "Vs200": (c[i] / sma200[i] - 1) * 100,
          "Ret20": (c[i] / c[i - 20] - 1) * 100,
      })
  e = pd.DataFrame(extra).set_index("_k")
  tr = tr.join(e)
  tr["VsSub"] = tr["Ret10"] - tr["Sub10"]
  # current scanner sub-scores, split out of P1 / P2
  tr["SMA_pts"] = np.select(
      [(tr.Vs50 >= -3.5) & (tr.Vs100 >= -2.5), (tr.Vs100 >= -5.5) & (tr.Vs50 >= -7),
       (tr.Vs100 >= -7) | (tr.Vs50 >= -9)], [12, 9, 6], 3)
  tr["Up_pts"] = np.select([tr.Upside >= 18, tr.Upside >= 12, tr.Upside >= 8.5], [12, 9, 6], 3)
  tr["Sec_pts"] = tr["P2"] - tr["Footprint"].map(
      {"Accumulating": 10, "Quiet_DryUp": 8, "Neutral": 5, "Dumping": 2})
  tr["Flow_pts"] = tr["P2"] - tr["Sec_pts"]
  tr["Beats_pts"] = np.where(tr.Beats == 4, 8, 4)
  tr["Surp_pts"] = np.select([tr.AvgSurp >= 10, tr.AvgSurp >= 5], [4, 3], 2)
  tr["Trig_num"] = tr["Trigger"].map(
      {"Knife_Wait": 0, "Stabilizing": 1, "Exhaustion_Buy": 2, "Day1_Turn": 3})
  return tr


FEATURES = [
    # current score inputs
    "Vs50", "Vs100", "Upside", "Sub10", "VsSub", "CMF", "VolRatio", "AvgSurp", "Beats",
    # current sub-scores
    "SMA_pts", "Up_pts", "Sec_pts", "Flow_pts", "Beats_pts", "Surp_pts", "P1", "P2",
    "Score_part",
    # other scanner fields
    "ATR_pct", "RSI", "Ret10", "Hold", "VIX", "Trig_num",
    # new, declared up front
    "Mom126", "Vs200", "Ret20",
]


def spearman(a, b):
  """Rank correlation without scipy."""
  return a.rank().corr(b.rank())


def ic_table(tr, outcome):
  rows = []
  for f in FEATURES:
    row = {"feature": f}
    for per, g in tr.groupby("Period"):
      ok = g[[f, outcome]].dropna()
      row[f"IC {per}"] = round(spearman(ok[f], ok[outcome]), 3)
    ok = tr[[f, outcome]].dropna()
    row["IC ALL"] = round(spearman(ok[f], ok[outcome]), 3)
    # quintile spread (top 20% minus bottom 20%) on all data
    q = pd.qcut(ok[f].rank(method="first"), 5, labels=False)
    row["Q5-Q1"] = round(ok[outcome][q == 4].mean() - ok[outcome][q == 0].mean(), 3)
    a, b = row.get("IC 2016-22", np.nan), row.get("IC 2023-26", np.nan)
    row["same_sign"] = bool(np.sign(a) == np.sign(b)) and min(abs(a), abs(b)) >= 0.02
    rows.append(row)
  return pd.DataFrame(rows).set_index("feature")


def main():
  u, px, earn = B.load()
  tr = add_features(load_trades(), px)
  tr.to_pickle(os.path.join(B.DATA, "scoring_trades.pkl"))
  print(f"trades: {len(tr)} (2016-22: {(tr.Period == '2016-22').sum()}, "
        f"2023-26: {(tr.Period == '2023-26').sum()}); IC noise level ~ +/-{1/np.sqrt(1700):.3f}\n")
  for outcome in ["R", "RawExcess"]:
    t = ic_table(tr, outcome)
    print(f"=== Outcome: {outcome} ===")
    print(t.sort_values("IC ALL", key=abs, ascending=False).to_string(), "\n")
  print("=== Categorical: Footprint / Trigger, mean R by period ===")
  for col in ["Footprint", "Trigger"]:
    print(tr.groupby([col, "Period"]).R.agg(["count", "mean"]).round(3).unstack().to_string(), "\n")
  print("=== Feature correlations (Spearman) among the main candidates ===")
  cand = ["ATR_pct", "Upside", "Vs50", "Vs100", "CMF", "RSI", "Mom126", "Vs200", "Ret20", "Hold"]
  print(tr[cand].rank().corr().round(2).to_string())


if __name__ == "__main__":
  main()
