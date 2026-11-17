"""Portfolio test: the NEW workflow with and without the stage-2 revenue / target gates.

Same simulator as old_vs_new.py (S&P 500 point-in-time universe, max 5 positions, 2 new
per day, 2.5 ATR stop, no target, exit T-3, 1% risk sizing, ranking by the v4.9 score).
Only the gates differ:
  A  no revenue gate, no target gate   (what old_vs_new.py tested)
  B  + revenue growth > 0              (SEC filings known before entry)
  C  + target upside >= 5%             (analyst-history proxy, split-adjusted)
  D  + both                            (closest to the live scanner)
Missing data passes the gate (it is a data gap here, not a company signal).

Decision rule, written before running: drop the revenue gate if removing it (B -> A and
D -> C) does not lower Sharpe in either period (2016-22, 2023-26) and does not lower it
over the full period. Otherwise keep it.

Usage: .venv/bin/python research/revenue_gate_test.py
"""

import os
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest as B  # noqa: E402
import components_test as C  # noqa: E402
import old_vs_new as V  # noqa: E402

pd.set_option("display.width", 250)


def add_gate_data(sig, px):
  cache = os.path.join(B.DATA, "sig_newmap_hw20_gates.pkl")
  if os.path.exists(cache):
    return pd.read_pickle(cache)
  close_raw = pd.read_pickle(os.path.join(B.DATA, "close_raw.pkl"))
  rev, tgt = [], []
  for t, g in sig.groupby("Ticker"):
    sec = C.sec_series(t)
    ud = C.load_analyst(t)
    craw = close_raw[t] if t in close_raw.columns else None
    for k, r in g.iterrows():
      D = r.Entry_Date
      rev.append((k, C.rev_growth_at(sec, D) if sec else np.nan))
      up = np.nan
      if ud is not None and len(ud) and craw is not None:
        price = craw.get(r.Signal_Date, np.nan)
        t_mean, _ = C.target_proxy(ud[ud.index < D], D)
        if pd.notna(t_mean) and price > 0:
          up = (t_mean / price - 1) * 100
      tgt.append((k, up))
  sig = sig.copy()
  sig["RevG"] = pd.Series(dict(rev))
  sig["TgtUp"] = pd.Series(dict(tgt))
  sig.to_pickle(cache)
  return sig


def main():
  u, px, earn = B.load()
  _, sn = V.signals(u, px, earn)
  sn = V.add_scores(sn)
  sn = add_gate_data(sn[sn.Source == "SP500"], px)
  print(f"signal rows {len(sn)}; revenue known {sn.RevG.notna().mean():.0%}, "
        f"target known {sn.TgtUp.notna().mean():.0%}")
  rev_ok = sn.RevG.isna() | (sn.RevG > 0)
  tgt_ok = sn.TgtUp.isna() | (sn.TgtUp >= 5)
  print(f"rows removed by revenue gate {(~rev_ok).mean():.0%}, by target gate "
        f"{(~tgt_ok).mean():.0%}, by both {(~(rev_ok & tgt_ok)).mean():.0%}\n")

  spy = B.bars_of(px, "SPY")
  cal = spy.index[spy.index >= V.START]
  book = V.Book(px, cal)
  variants = {
      "A no gates": sn,
      "B revenue gate": sn[rev_ok],
      "C target gate": sn[tgt_ok],
      "D both gates (live)": sn[rev_ok & tgt_ok],
  }
  periods = [("ALL", cal[0], cal[-1]),
             ("2016-22", cal[0], pd.Timestamp("2022-12-31")),
             ("2023-26", pd.Timestamp("2023-01-01"), cal[-1])]
  res = {}
  for name, s in variants.items():
    eq, ex, tr = V.run_portfolio(book, s, "Score_new", "new", "new", "risk", cal)
    for p, a, b in periods:
      res[(p, name)] = V.metrics(eq, ex, tr, a, b)
  out = pd.DataFrame(res).T
  for p, _, _ in periods:
    print(f"=== {p} ===")
    print(out.loc[p][["CAGR%", "vol%", "Sharpe", "maxDD%", "CAGR/DD", "trades", "win%",
                      "avg_trade%", "avg_expo%"]].to_string(), "\n")

  sh = {k: out.loc[(p, k), "Sharpe"] for p, _, _ in periods for k in variants
        for _ in [0]} if False else None
  def sharpe(p, k):
    return out.loc[(p, k), "Sharpe"]
  ok = all(sharpe(p, "A no gates") >= sharpe(p, "B revenue gate")
           and sharpe(p, "C target gate") >= sharpe(p, "D both gates (live)")
           for p, _, _ in periods)
  print("Decision rule (drop revenue gate if removing it never lowers Sharpe):",
        "DROP" if ok else "KEEP")
  out.to_csv(os.path.join(B.OUT, "revenue_gate_test.csv"))


if __name__ == "__main__":
  main()
