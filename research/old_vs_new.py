"""OLD workflow vs NEW workflow on 2016-2026 history, as a day-by-day portfolio.

OLD = v4.4/v4.6 script (research/legacy_scanner_v4_4.py: old ETF mapping, old score,
      21-bar "20D" high) + old SKILL execution (Knife_Wait: wait for a green close with
      low >= prior low, then buy the next open) + old trade plan (1.5 ATR stop,
      75%-to-20D-high target) + equal money per position.
NEW = v4.9 script (scanner.py) + new SKILL execution (buy the next open, any trigger)
      + v4.8 plan (2.5 ATR stop, no target) + risk sizing (1% of equity per trade,
      i.e. the Pos_%_per_1%_Risk column).

Same for both: S&P 500 universe (point-in-time by "Date added"), technical filter,
earnings window 4-21 days, beats >= 3/4, exit at T-3 close, 5 bps slippage per side.
Portfolio: max 5 positions, at most 2 new per day, picked by each system's own score,
one position per stock at a time, no leverage.

What cannot be replayed historically (identical in both, so excluded): EPS-cut filter,
revenue growth, analyst target upside, Analyst_Mod, and the 30-point web audit.

Bias notes (read before the numbers):
  - The v4.9 score cut-offs were derived on 2016-22 -> NEW's 2016-22 result is partly
    in-sample. 2023-26 is the fair comparison for scoring.
  - The v4.8 trade plan was picked from a grid over all years -> mild bias in both periods.
  - Universe = today's index members (survivorship) -> absolute returns are flattered;
    the OLD-vs-NEW gap is more trustworthy than either level.
  - The 15 Nasdaq-100-only names added in v4.7 are today's survivors; they are shown in
    a separate, clearly biased line and are NOT in the main comparison.

Usage: .venv/bin/python research/old_vs_new.py
"""

import importlib.util
import io
import os
import sys
import warnings
from contextlib import redirect_stdout

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest as B  # noqa: E402

S = B.S  # current scanner.py (v4.9)
_spec = importlib.util.spec_from_file_location(
    "legacy_scanner", os.path.join(HERE, "legacy_scanner_v4_4.py"))
OLD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(OLD)

pd.set_option("display.width", 250)
MAX_POS, MAX_NEW, RISK_FRAC, POS_CAP = 5, 2, 0.01, 0.25
START = pd.Timestamp("2016-01-04")


# --------------------------------------------------------------------------- signals
def signals(u, px, earn):
  cache_old = os.path.join(B.DATA, "sig_oldmap_hw21.pkl")
  cache_new = os.path.join(B.DATA, "sig_newmap_hw20.pkl")
  if os.path.exists(cache_old) and os.path.exists(cache_new):
    return pd.read_pickle(cache_old), pd.read_pickle(cache_new)
  u_old = u.copy()
  u_old["Sub_ETF"] = [OLD.map_subsector_etf(s, sub)
                      for s, sub in zip(u_old.Sector, u_old.Sub_Industry)]
  print("building signals (old mapping, 21-bar high)...", flush=True)
  so = B.build_signals(u_old, px, earn, high_window=21)
  print("building signals (new mapping, 20-bar high)...", flush=True)
  sn = B.build_signals(u, px, earn, high_window=20)
  for s in (so, sn):
    s["Source"] = s.Ticker.map(dict(zip(u.Symbol, u.Source)))
  so.to_pickle(cache_old)
  sn.to_pickle(cache_new)
  return so, sn


def add_scores(sig):
  old, new = [], []
  for _, r in sig.iterrows():
    base = {
        "Vs_50SMA_%": round(r.Vs50, 1), "Vs_100SMA_%": round(r.Vs100, 1),
        "Upside_20D_High_%": round(r.Upside, 1), "SubETF_10D_%": round(r.Sub10, 2),
        "Vs_SubETF_10D_%": round(r.Ret10 - r.Sub10, 2), "Inst_Footprint": r.Footprint,
        "Beats_4Q": f"{int(r.Beats)}/4", "Avg_Surp_%": r.AvgSurp,
        # untestable inputs: same constants for both systems (do not affect ranking)
        "Rev_Growth_%": 15.0, "Target_Upside_%": 15.0,
        "RSI_14": round(r.RSI, 1), "Mom_6M_%": round(r.Mom126, 1),
        "Trigger_Status": r.Trigger,
    }
    old.append(OLD.compute_setup_score_breakdown(base, 0)[3])
    new.append(S.compute_setup_score_breakdown(base, 0)[3])
  sig = sig.copy()
  sig["Score_old"], sig["Score_new"] = old, new
  return sig


# --------------------------------------------------------------------------- portfolio
class Book:
  def __init__(self, px, cal):
    self.px, self.cal, self.cache, self.close_cache = px, cal, {}, {}

  def arrays(self, t):
    if t not in self.cache:
      b = B.bars_of(self.px, t)
      self.cache[t] = (b.index, b.Open.values, b.High.values, b.Low.values, b.Close.values)
    return self.cache[t]

  def close_on(self, t, day):
    if t not in self.close_cache:
      b = B.bars_of(self.px, t)
      self.close_cache[t] = b.Close.reindex(self.cal).ffill()
    return self.close_cache[t].get(day, np.nan)


def plan_trade(book, r, plan, execution):
  idx, o, h, l, c = book.arrays(r.Ticker)
  i, exit_pos = int(r.i), int(r.exit_pos)
  if exit_pos >= len(idx):
    return None
  entry_pos = i + 1
  if execution == "old" and r.Trigger == "Knife_Wait":
    entry_pos = None
    for j in range(i, exit_pos):
      if c[j] > o[j] and l[j] >= l[j - 1]:
        entry_pos = j + 1
        break
    if entry_pos is None or entry_pos > exit_pos:
      return {"reserve_until": idx[exit_pos]}
  if plan == "old":
    stop = r.Close - 1.5 * r.ATR
    target = r.Close + 0.75 * (r.High20 - r.Close)
  else:
    stop, target = r.Close - 2.5 * r.ATR, None
  if o[entry_pos] <= stop:
    return None
  fill, outcome, xj, entry = B.simulate(o, h, l, c, entry_pos, exit_pos, stop, target)
  return {"entry_day": idx[entry_pos], "exit_day": idx[xj], "entry": entry, "fill": fill,
          "stop": stop, "outcome": outcome, "reserve_until": idx[xj]}


def run_portfolio(book, sig, score_col, plan, execution, sizing, cal):
  by_day = {d: g for d, g in sig.groupby("Entry_Date")}
  cash, equity_prev = 1.0, 1.0
  scheduled, open_pos, slots = [], [], []  # slots: (ticker, reserve_until)
  eq, expo, trades = [], [], []
  for day in cal:
    # 1. decisions for today's open
    slots = [s for s in slots if s[1] >= day]
    held = {s[0] for s in slots}
    free = MAX_POS - len(slots)
    if free > 0 and day in by_day:
      g = by_day[day].sort_values([score_col, "Ticker"], ascending=[False, True])
      n_new = 0
      for _, r in g.iterrows():
        if n_new >= min(MAX_NEW, free):
          break
        if r.Ticker in held:
          continue
        tp = plan_trade(book, r, plan, execution)
        if tp is None:
          continue
        slots.append((r.Ticker, tp["reserve_until"]))
        held.add(r.Ticker)
        n_new += 1
        if "entry_day" in tp:
          scheduled.append({**tp, "ticker": r.Ticker, "score": r[score_col],
                            "trigger": r.Trigger})
    # 2. entries at today's open
    still = []
    for tp in scheduled:
      if tp["entry_day"] != day:
        still.append(tp)
        continue
      if sizing == "equal":
        value = equity_prev / MAX_POS
      else:
        risk_ps = tp["entry"] - tp["stop"]
        value = min(RISK_FRAC * equity_prev / risk_ps * tp["entry"], POS_CAP * equity_prev)
      value = min(value, cash)
      if value <= 1e-9:
        continue
      cash -= value
      open_pos.append({**tp, "shares": value / tp["entry"], "value_in": value})
    scheduled = still
    # 3. exits during / at end of today
    keep = []
    for p in open_pos:
      if p["exit_day"] == day:
        cash += p["shares"] * p["fill"]
        trades.append({"ticker": p["ticker"], "entry_day": p["entry_day"], "exit_day": day,
                       "ret": (p["fill"] / p["entry"] - 1) * 100, "outcome": p["outcome"],
                       "pnl": p["shares"] * p["fill"] - p["value_in"],
                       "weight": p["value_in"] / equity_prev, "trigger": p["trigger"]})
      else:
        keep.append(p)
    open_pos = keep
    # 4. mark to market
    invested = sum(p["shares"] * book.close_on(p["ticker"], day) for p in open_pos)
    equity = cash + invested
    eq.append(equity)
    expo.append(invested / equity if equity > 0 else 0)
    equity_prev = equity
  return pd.Series(eq, index=cal), pd.Series(expo, index=cal), pd.DataFrame(trades)


def metrics(eq, expo, trades, a, b):
  e = eq[(eq.index >= a) & (eq.index <= b)]
  e = e / e.iloc[0]
  rets = e.pct_change().dropna()
  yrs = (e.index[-1] - e.index[0]).days / 365.25
  dd = (e / e.cummax() - 1).min()
  cagr = e.iloc[-1] ** (1 / yrs) - 1
  t = trades[(trades.exit_day >= a) & (trades.exit_day <= b)] if len(trades) else trades
  return {
      "CAGR%": round(cagr * 100, 1),
      "vol%": round(rets.std() * np.sqrt(252) * 100, 1),
      "Sharpe": round(rets.mean() / rets.std() * np.sqrt(252), 2) if rets.std() > 0 else np.nan,
      "maxDD%": round(dd * 100, 1),
      "CAGR/DD": round(cagr / -dd, 2) if dd < 0 else np.nan,
      "trades": len(t),
      "win%": round((t.ret > 0).mean() * 100, 1) if len(t) else np.nan,
      "avg_trade%": round(t.ret.mean(), 2) if len(t) else np.nan,
      "avg_expo%": round(expo[(expo.index >= a) & (expo.index <= b)].mean() * 100),
  }


def main():
  u, px, earn = B.load()
  so, sn = signals(u, px, earn)
  so, sn = add_scores(so), add_scores(sn)
  spy = B.bars_of(px, "SPY")
  cal = spy.index[spy.index >= START]
  book = Book(px, cal)
  sp_old, sp_new = so[so.Source == "SP500"], sn[sn.Source == "SP500"]

  steps = [
      ("0 OLD (v4.6 script + old SKILL, equal money)", sp_old, "Score_old", "old", "old", "equal"),
      ("1 + v4.7 fixes (ETF map, 20-bar high)", sp_new, "Score_old", "old", "old", "equal"),
      ("2 + v4.9 scoring", sp_new, "Score_new", "old", "old", "equal"),
      ("3 + v4.8 trade plan (2.5ATR, no target)", sp_new, "Score_new", "new", "old", "equal"),
      ("4 + new SKILL execution (no Knife wait)", sp_new, "Score_new", "new", "new", "equal"),
      ("5 NEW: + 1% risk sizing", sp_new, "Score_new", "new", "new", "risk"),
      ("x OLD with 1% risk sizing (sizing-matched)", sp_old, "Score_old", "old", "old", "risk"),
      ("y NEW + NDX-only names (SURVIVORSHIP-BIASED)", sn, "Score_new", "new", "new", "risk"),
  ]
  periods = [("ALL 2016-26", cal[0], cal[-1]),
             ("2016-22 (scoring in-sample)", cal[0], pd.Timestamp("2022-12-31")),
             ("2023-26 (scoring out-of-sample)", pd.Timestamp("2023-01-01"), cal[-1])]
  results, curves = {}, {}
  for name, sig, sc, plan, ex, sz in steps:
    print("running", name, flush=True)
    eq, expo, tr = run_portfolio(book, sig, sc, plan, ex, sz, cal)
    curves[name] = eq
    tr.to_csv(os.path.join(B.OUT, f"old_vs_new_trades_{name[0]}.csv"), index=False)
    for pname, a, b in periods:
      results[(pname, name)] = metrics(eq, expo, tr, a, b)
  spy_eq = spy.Close.reindex(cal)
  for pname, a, b in periods:
    results[(pname, "SPY buy & hold")] = metrics(
        spy_eq, pd.Series(1.0, index=cal), pd.DataFrame(columns=["exit_day", "ret"]), a, b)

  rep = io.StringIO()
  with redirect_stdout(rep):
    print(__doc__)
    res = pd.DataFrame(results).T
    for pname, _, _ in periods:
      print("=" * 120)
      print(pname)
      print("=" * 120)
      print(res.loc[pname].to_string(), "\n")
    yr = pd.DataFrame({k: v.resample("YE").last().pct_change().mul(100).round(1)
                       for k, v in list(curves.items())[:6]})
    first = pd.DataFrame({k: [round((v.resample("YE").last().iloc[0] - 1) * 100, 1)]
                          for k, v in list(curves.items())[:6]},
                         index=[yr.index[0]])
    yr.iloc[0] = first.iloc[0]
    yr["SPY"] = (spy_eq.resample("YE").last().pct_change().mul(100).round(1))
    yr.index = yr.index.year
    yr.columns = [c[:2].strip() if c != "SPY" else c for c in yr.columns]
    print("Calendar-year returns % (columns = step numbers above)")
    print(yr.to_string())
  text = rep.getvalue()
  with open(os.path.join(B.OUT, "old_vs_new_report.txt"), "w") as f:
    f.write(text)
  pd.DataFrame(curves).to_csv(os.path.join(B.OUT, "old_vs_new_equity.csv"))
  print(text)


if __name__ == "__main__":
  main()
