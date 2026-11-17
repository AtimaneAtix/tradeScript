"""Runs the fixed variant grid + baselines and writes research/output/report.txt.

The grid was fixed before looking at results (no tuning on the outcome):
  stops 1.5 / 2.5 / 3.0 ATR, target on/off, exit T-3 vs T-2, immediate vs confirmed
  entry, regime gate, one trade per earnings cycle vs re-entry.
In-sample 2016-2022, out-of-sample 2023-2026: a finding only counts if it holds in both.

Usage: .venv/bin/python research/analyze.py
"""

import io
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
pd.set_option("display.max_rows", 200)


def baseline_window(u, px, earn, mkt, exit_k=3):
  """Any stock (beats gate on/off), every entry day with Hold 4..21, held to exit."""
  rows = []
  for _, ur in u.iterrows():
    t = ur["Symbol"]
    b = B.bars_of(px, t)
    ed = earn.get(t)
    if b is None or ed is None or len(b) < 260:
      continue
    idx, o, c = b.index, b["Open"].values, b["Close"].values
    for er in sorted(set(ed.index.normalize())):
      if er < B.BT_START or er > idx[-1]:
        continue
      er_pos = idx.searchsorted(er)
      exit_pos = er_pos - exit_k
      first = exit_pos - 20
      if first < 200 or exit_pos >= len(idx):
        continue
      D = idx[first]
      if pd.notna(ur["Date_Added"]) and D < ur["Date_Added"]:
        continue
      q = B.S.get_distinct_past_4_quarters(ed, D, min_gap_days=35)
      beats_ok = len(q) == 4 and (q > 0).sum() >= 3 and q.mean() <= 200
      spy_out = mkt["spy_c"].asof(idx[exit_pos])
      for ep in range(first, exit_pos - 2):  # hold 21 .. 4
        ret = c[exit_pos] / o[ep] - 1
        spy = spy_out / mkt["spy_o"].asof(idx[ep]) - 1
        rows.append({"Ticker": t, "ER": er, "Hold": exit_pos - ep + 1,
                     "Ret": ret * 100, "Excess": (ret - spy) * 100,
                     "Beats_ok": beats_ok, "Year": idx[ep].year,
                     "Period": "2016-22" if idx[ep] <= B.IN_SAMPLE_END else "2023-26"})
  return pd.DataFrame(rows)


def baseline_pullback(sig_any, px, mkt, hold=10, cooldown=10):
  """Technical pullback filter only (no earnings window), fixed hold, no stop."""
  out = []
  for t, g in sig_any.sort_values("Signal_Date").groupby("Ticker"):
    b = B.bars_of(px, t)
    idx, o, c = b.index, b["Open"].values, b["Close"].values
    last = -10**9
    for _, r in g.iterrows():
      i = int(r["i"])
      if i - last < cooldown or i + hold >= len(idx):
        continue
      last = i
      ret = c[i + hold] / o[i + 1] - 1
      spy = mkt["spy_c"].asof(idx[i + hold]) / mkt["spy_o"].asof(idx[i + 1]) - 1
      out.append({"Ret": ret * 100, "Excess": (ret - spy) * 100,
                  "Period": "2016-22" if idx[i + 1] <= B.IN_SAMPLE_END else "2023-26"})
  return pd.DataFrame(out)


def simple(g):
  return pd.Series({"n": len(g), "win%": round((g.Ret > 0).mean() * 100, 1),
                    "avg%": round(g.Ret.mean(), 2), "med%": round(g.Ret.median(), 2),
                    "excess%": round(g.Excess.mean(), 2)})


def by_period(tr, fn=B.stats):
  t = tr.groupby("Period").apply(fn)
  t.loc["ALL"] = fn(tr)
  return t


def bucket(s, edges, labels):
  return pd.cut(s, edges, labels=labels)


def main():
  u, px, earn = B.load()
  mkt = B.market_context(px)
  print(f"universe {len(u)}, earnings files {len(earn)}", flush=True)

  sig = B.build_signals(u, px, earn)
  sig.to_pickle(os.path.join(B.DATA, "signals.pkl"))
  print("strategy signal rows:", len(sig), flush=True)
  sig_nobeats = B.build_signals(u, px, earn, require_beats=False)
  sig_any = B.build_signals(u, px, earn, require_window=False, require_beats=False)
  print("no-beats rows:", len(sig_nobeats), "pullback-only rows:", len(sig_any), flush=True)

  rep = io.StringIO()
  with redirect_stdout(rep):
    print("BACKTEST REPORT  (price + earnings window + beats only; see backtest.py header)")
    print(f"Signals since {B.BT_START.date()}; in-sample 2016-22, out-of-sample 2023-26\n")

    # ---------------- 1. Where is the edge? (hold to exit, no stop/target)
    raw = B.make_trades(sig, px, mkt, stop_atr=None, use_target=False)
    raw.to_pickle(os.path.join(B.DATA, "trades_raw.pkl"))
    raw_nb = B.make_trades(sig_nobeats, px, mkt, stop_atr=None, use_target=False)
    bw = baseline_window(u, px, earn, mkt)
    bp = baseline_pullback(sig_any, px, mkt)
    print("=" * 100)
    print("1. WHERE IS THE EDGE?  Hold to exit, no stop, no target. 'excess%' = minus SPY same days")
    print("=" * 100)
    print("\n[Strategy] pullback + ER window + beats>=3, first signal per ER cycle")
    print(by_period(raw))
    print("\n[Strategy without beats gate]")
    print(by_period(raw_nb))
    print("\n[Baseline A] ANY stock in the same pre-earnings window (beats>=3), every entry day")
    print(by_period(bw[bw.Beats_ok], simple))
    print("\n[Baseline A'] ANY stock in the window, no beats gate")
    print(by_period(bw, simple))
    print("\n[Baseline B] pullback filter only, no earnings window, 10-day hold")
    print(by_period(bp, simple))

    # ---------------- 2. Trade plan variants
    print("\n" + "=" * 100)
    print("2. TRADE PLAN VARIANTS (same signals). avgR = return in units of initial risk")
    print("=" * 100)
    variants = [
        ("Scanner plan: 1.5ATR stop + target, T-3", dict(stop_atr=1.5, use_target=True)),
        ("1.5ATR stop, no target", dict(stop_atr=1.5, use_target=False)),
        ("2.5ATR stop + target", dict(stop_atr=2.5, use_target=True)),
        ("2.5ATR stop, no target", dict(stop_atr=2.5, use_target=False)),
        ("3.0ATR stop + target", dict(stop_atr=3.0, use_target=True)),
        ("3.0ATR stop, no target", dict(stop_atr=3.0, use_target=False)),
        ("No stop, no target (raw)", dict(stop_atr=None, use_target=False)),
        ("Scanner plan, exit T-2", dict(stop_atr=1.5, use_target=True, exit_k=2)),
        ("Raw, exit T-2", dict(stop_atr=None, use_target=False, exit_k=2)),
        ("Scanner plan, confirmed entry", dict(stop_atr=1.5, use_target=True,
                                               entry_mode="confirmed")),
        ("Raw, confirmed entry", dict(stop_atr=None, use_target=False,
                                      entry_mode="confirmed")),
        ("Scanner plan, skip RED regime", dict(stop_atr=1.5, use_target=True,
                                               regime_skip=("RED",))),
        ("Scanner plan, GREEN only", dict(stop_atr=1.5, use_target=True,
                                          regime_skip=("RED", "YELLOW"))),
        ("Scanner plan, re-entry allowed", dict(stop_atr=1.5, use_target=True,
                                                one_per_cycle=False)),
    ]
    vt = {}
    for name, kw in variants:
      tr = B.make_trades(sig, px, mkt, **kw)
      st = tr.groupby("Period").apply(B.stats)
      vt[name] = pd.concat({"ALL": B.stats(tr), **{p: st.loc[p] for p in st.index}}, axis=0)
    print(pd.DataFrame(vt).T.to_string())

    # ---------------- 3. Which scanner components carry information? (raw trades)
    print("\n" + "=" * 100)
    print("3. COMPONENTS  (raw trades: hold to exit, no stop) -- does each label/bucket separate?")
    print("=" * 100)
    r = raw.copy()
    r["P1_b"] = bucket(r.P1, [0, 12, 17, 21, 24], ["6-12", "13-17", "18-21", "22-24"])
    r["P2_b"] = bucket(r.P2, [0, 12, 15, 18, 22], ["7-12", "13-15", "16-18", "19-22"])
    r["Score_b"] = bucket(r.Score_part, [0, 35, 40, 45, 60],
                          ["<=35", "36-40", "41-45", "46+"])
    r["ATR_b"] = bucket(r.ATR_pct, [0, 2, 3, 4, 100], ["1.6-2", "2-3", "3-4", "4+"])
    r["RSI_b"] = bucket(r.RSI, [0, 30, 38, 44, 48], ["<30", "30-38", "38-44", "44-48"])
    r["Hold_b"] = bucket(r.Hold, [3, 7, 14, 21], ["4-7", "8-14", "15-21"])
    r["Up_b"] = bucket(r.Upside, [0, 8.5, 12, 18, 100], ["6-8.5", "8.5-12", "12-18", "18+"])
    r["Beats_b"] = r.Beats.map({3: "3/4", 4: "4/4"})
    for col in ["Trigger", "Footprint", "Regime", "Beats_b", "P1_b", "P2_b", "Score_b",
                "ATR_b", "RSI_b", "Hold_b", "Up_b"]:
      t = r.groupby([col, "Period"]).apply(B.stats)[["n", "win%", "avg%", "excess%", "PF"]]
      print(f"\n--- {col}")
      print(t.unstack("Period").to_string())

    print("\n--- By year (raw)")
    print(r.groupby("Year").apply(B.stats)[["n", "win%", "avg%", "excess%", "PF"]].to_string())
    print("\n--- By sub-ETF (raw, n>=40)")
    s = r.groupby("Sub_ETF").apply(B.stats)
    print(s[s.n >= 40][["n", "win%", "avg%", "excess%", "PF"]].sort_values("excess%").to_string())

    # concentration: how many signals share the same entry week
    wk = raw.groupby(raw.Entry_Day.dt.to_period("W")).size()
    print(f"\nClustering: {len(raw)} trades over {len(wk)} active weeks; top-10 weeks hold "
          f"{wk.nlargest(10).sum()} trades ({wk.nlargest(10).sum() / len(raw) * 100:.0f}%)")

  text = rep.getvalue()
  os.makedirs(B.OUT, exist_ok=True)
  with open(os.path.join(B.OUT, "report.txt"), "w") as f:
    f.write(text)
  print(text)


if __name__ == "__main__":
  main()
