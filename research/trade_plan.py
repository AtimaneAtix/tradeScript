"""Trade-plan grid on the same historical signals (selection unchanged).

Grid fixed before running:
  initial stop : 1.5 / 2.0 / 2.5 / 3.0 ATR below the signal close
  target       : 75% of the way to the 20D high (current) / 100% / none
  management   : none / breakeven after +1R / trailing stop 2.5 ATR / trailing 3.0 ATR
  exit         : T-3 close (T-2 shown for the finalists)

Two views:
  avg%  = equal money per trade
  avgR  = equal RISK per trade (position = risk budget / stop distance) -> the fair way
          to compare stop widths. maxDD_R = worst peak-to-trough of cumulative R,
          trades ordered by exit day.

Usage: .venv/bin/python research/trade_plan.py
"""

import io
import itertools
import os
import sys
import warnings
from contextlib import redirect_stdout

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest as B  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 300)


def risk_stats(tr):
  if tr.empty:
    return pd.Series(dtype=float)
  t = tr.sort_values("Exit_Day")
  cum = t["R"].cumsum()
  dd = (cum - cum.cummax()).min()
  wins, losses = t.loc[t.Ret > 0, "Ret"].sum(), -t.loc[t.Ret <= 0, "Ret"].sum()
  years = (t["Exit_Day"].max() - t["Entry_Day"].min()).days / 365.25
  return pd.Series({
      "n": len(t),
      "win%": round((t.Ret > 0).mean() * 100, 1),
      "avg%": round(t.Ret.mean(), 2),
      "med%": round(t.Ret.median(), 2),
      "p5%": round(t.Ret.quantile(0.05), 2),
      "worst%": round(t.Ret.min(), 1),
      "PF": round(wins / losses, 2) if losses > 0 else np.nan,
      "avgR": round(t.R.mean(), 3),
      "R/sd": round(t.R.mean() / t.R.std(), 3),
      "worstR": round(t.R.min(), 2),
      "maxDD_R": round(dd, 1),
      "R/yr": round(t.R.sum() / years, 1),
      "stop%": round((t.Outcome == "STOP").mean() * 100, 1),
      "tgt%": round((t.Outcome == "TARGET").mean() * 100, 1),
      "days": round(t.Days.mean(), 1),
  })


def main():
  u, px, earn = B.load()
  mkt = B.market_context(px)
  sig_path = os.path.join(B.DATA, "signals.pkl")
  sig = pd.read_pickle(sig_path) if os.path.exists(sig_path) else B.build_signals(u, px, earn)

  stops = [1.5, 2.0, 2.5, 3.0]
  targets = [("tgt75", 0.75), ("tgt100", 1.0), ("noTgt", None)]
  mgmt = [("fixed", {}), ("BE@1R", {"be_r": 1.0}),
          ("trail2.5", {"trail_atr": 2.5}), ("trail3", {"trail_atr": 3.0})]

  rows, trades = [], {}
  for st, (tn, tf), (mn, mk) in itertools.product(stops, targets, mgmt):
    if mn.startswith("trail") and float(mn[5:]) < st:
      continue  # a trail tighter than the initial stop is just a tighter stop
    name = f"stop{st}_{tn}_{mn}"
    tr = B.make_trades(sig, px, mkt, stop_atr=st, use_target=tf is not None,
                       target_frac=tf or 0.75, **mk)
    trades[name] = tr
    for per, g in [("ALL", tr)] + list(tr.groupby("Period")):
      rows.append({"plan": name, "period": per, **risk_stats(g).to_dict()})
    print("done", name, flush=True)
  # reference: no stop at all (R measured as if risk were 3 ATR)
  ref = B.make_trades(sig, px, mkt, stop_atr=None, use_target=False, sizing_atr=3.0)
  trades["noStop_noTgt (R@3ATR)"] = ref
  for per, g in [("ALL", ref)] + list(ref.groupby("Period")):
    rows.append({"plan": "noStop_noTgt (R@3ATR)", "period": per, **risk_stats(g).to_dict()})

  res = pd.DataFrame(rows)
  res.to_csv(os.path.join(B.OUT, "trade_plan_grid.csv"), index=False)
  pd.to_pickle(trades, os.path.join(B.DATA, "trade_plan_trades.pkl"))

  rep = io.StringIO()
  with redirect_stdout(rep):
    piv = res.pivot(index="plan", columns="period")
    cols = ["avg%", "avgR", "R/sd", "maxDD_R", "worst%", "stop%", "tgt%"]
    show = piv[[(c, p) for c in cols for p in ["2016-22", "2023-26", "ALL"]]]
    print("TRADE PLAN GRID — same signals, sorted by avgR in the WEAKER of the two periods\n")
    weak = piv[("avgR", "2016-22")].combine(piv[("avgR", "2023-26")], min)
    print(show.loc[weak.sort_values(ascending=False).index].to_string())
    print("\nFull stats (ALL periods):")
    print(res[res.period == "ALL"].set_index("plan").sort_values("avgR", ascending=False)
          .drop(columns="period").to_string())
  text = rep.getvalue()
  with open(os.path.join(B.OUT, "trade_plan_report.txt"), "w") as f:
    f.write(text)
  print(text)


if __name__ == "__main__":
  main()
