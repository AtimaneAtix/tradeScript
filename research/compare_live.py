"""Old workflow vs new workflow, replayed on the scanner's real past candidate CSVs.

OLD (v4.4 code + old SKILL.md):
  - ranking by the stored Setup_Score_70 (old P1/P2)
  - stop/target as written in the CSV (1.5 ATR stop, 75%-to-20D-high target)
  - Knife_Wait: wait for a green close with low >= prior low, buy the next open
    (old SKILL Turn-2 rule); other triggers: buy the scan-day open
NEW (v4.9 code + new SKILL.md):
  - ranking by the v4.9 score: new P1 + new P2 + stored P3 + stored Analyst_Mod
  - stop = signal close - 2.5 ATR, no target
  - every trigger: buy the scan-day open
Both exit at the Exit_Date close (T-3) at the latest. 5 bps slippage per side.

NOT covered: the 30-point web audit (no record of past audit scores), and the v4.7
universe/mapping changes (stocks the new code would have added are not in old CSVs).

Usage: .venv/bin/python research/compare_live.py
"""

import os
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest as B  # noqa: E402
import tracker as T  # noqa: E402

pd.set_option("display.width", 250)
SLIP = 0.0005
LAST_BAR = None


def tier(x, a, b, pts):
  return pts[0] if x <= a else (pts[1] if x <= b else pts[2])


def prepare(px):
  c = T.load_candidate_files()
  c = c[~c.Version.str.startswith("v2")].copy()
  rows = []
  for _, r in c.iterrows():
    b = B.bars_of(px, r.Ticker)
    if b is None:
      continue
    first = b.index.searchsorted(r.Scan_Date)  # first bar on/after scan date
    prev_close = b.Close.iloc[first - 1]
    if abs(r.Price / prev_close - 1) <= 0.01:
      sig_i = first - 1  # ran pre-market: signal bar = previous day
    elif first < len(b) and abs(r.Price / b.Close.iloc[first] - 1) <= 0.01:
      sig_i = first  # ran after the close
    else:
      print(f"[!] price mismatch {r.Ticker} {r.Scan_Date.date()} -> skipped")
      continue
    d = B.indicators(b.iloc[: sig_i + 1])
    atr, close = d.atr.iloc[-1], d.Close.iloc[-1]
    mom = (b.Close.iloc[sig_i - 21] / b.Close.iloc[sig_i - 126] - 1) * 100
    p1n = tier(r.RSI_14, 38.75, 43.10, (12, 8, 4)) + tier(mom, 11.81, 22.96, (12, 8, 4))
    p2n = tier(r["SubETF_10D_%"], -4.12, -1.20, (11, 7, 3)) + (
        11 if r.Trigger_Status == "Knife_Wait" else 3)
    has_p3 = pd.notna(r.get("P3_Fund_24")) and pd.notna(r.get("Analyst_Mod"))
    new_score = (min(70, max(0, p1n + p2n + r.P3_Fund_24 + r.Analyst_Mod))
                 if has_p3 else np.nan)
    rows.append({**r.to_dict(), "sig_i": sig_i, "ATR_calc": atr, "SigClose": close,
                 "Mom_6M": round(mom, 1), "Old_Score": r.Setup_Score_70,
                 "New_Score": new_score, "New_Stop": close - 2.5 * atr})
  return pd.DataFrame(rows)


def run_trade(px, spy, r, plan):
  b = B.bars_of(px, r.Ticker)
  o, h, l, c = b.Open.values, b.High.values, b.Low.values, b.Close.values
  idx = b.index
  i = int(r.sig_i)
  exit_pos = idx.searchsorted(r.Exit_Date, side="right") - 1
  entry_pos = i + 1
  if plan == "old" and r.Trigger_Status == "Knife_Wait":
    entry_pos = None
    for j in range(i + 1, exit_pos):
      if c[j] > o[j] and l[j] >= l[j - 1]:
        entry_pos = j + 1
        break
    if entry_pos is None:
      return {"Outcome": "NO_ENTRY"}
  if entry_pos >= len(idx):
    return {"Outcome": "NOT_YET"}
  stop = r.Hard_Stop_Price if plan == "old" else r.New_Stop
  target = r.Early_Target_Price if plan == "old" else None
  entry = o[entry_pos] * (1 + SLIP)
  if o[entry_pos] <= stop:
    return {"Outcome": "GAP_BELOW_STOP"}
  last = min(exit_pos, len(idx) - 1)
  out, fill, xj = None, None, None
  for j in range(entry_pos, last + 1):
    if j > entry_pos and o[j] <= stop:
      out, fill, xj = "STOP", o[j], j
      break
    if l[j] <= stop:
      out, fill, xj = "STOP", stop, j
      break
    if target is not None and h[j] >= target:
      out, fill, xj = "TARGET", (max(o[j], target) if j > entry_pos else target), j
      break
  if out is None:
    xj = last
    fill = c[last]
    out = "EXIT" if exit_pos <= len(idx) - 1 and idx[last] >= r.Exit_Date - pd.Timedelta(days=0) \
        and last == exit_pos else "OPEN"
  fill *= (1 - SLIP)
  spy_r = spy.Close.asof(idx[xj]) / spy.Open.asof(idx[entry_pos]) - 1
  return {"Outcome": out, "Entry_Day": idx[entry_pos].date(), "Exit_Day": idx[xj].date(),
          "Ret": (fill / entry - 1) * 100, "SPY": spy_r * 100,
          "Excess": (fill / entry - 1 - spy_r) * 100}


def picks(cands, score_col, k):
  """Each scan day, take the k best-scored names not already held.

  A ticker counts as held until its planned Exit_Date, even if Yahoo later moved the
  earnings date (that happened with PANW), so one stock is never held twice at once.
  """
  held, out = {}, []
  for d, g in cands.sort_values("Scan_Date").groupby("Scan_Date"):
    g = g.sort_values([score_col, "Ticker"], ascending=[False, True])
    n = 0
    for _, r in g.iterrows():
      if r.Ticker in held and r.Scan_Date <= held[r.Ticker]:
        continue
      if k is not None and n >= k:
        break
      held[r.Ticker] = r.Exit_Date
      out.append(r)
      n += 1
  return pd.DataFrame(out)


def summarize(tr):
  closed = tr[tr.Outcome.isin(["STOP", "TARGET", "EXIT"])]
  skipped = tr[tr.Outcome.isin(["NO_ENTRY", "GAP_BELOW_STOP"])]
  opn = tr[tr.Outcome == "OPEN"]
  s = {"closed_n": len(closed), "skipped": len(skipped)}
  if len(closed):
    s.update({
        "win%": round((closed.Ret > 0).mean() * 100),
        "avg%": round(closed.Ret.mean(), 2), "med%": round(closed.Ret.median(), 2),
        "sum%": round(closed.Ret.sum(), 1), "worst%": round(closed.Ret.min(), 1),
        "vsSPY%": round(closed.Excess.mean(), 2),
        "stops": int((closed.Outcome == "STOP").sum()),
        "targets": int((closed.Outcome == "TARGET").sum()),
    })
  s.update({"open_n": len(opn), "open_avg%": round(opn.Ret.mean(), 2) if len(opn) else np.nan})
  return s


def main():
  u, px, earn = B.load()
  spy = B.bars_of(px, "SPY")
  print(f"Price data through {spy.index[-1].date()} (open trades marked at that close)\n")
  c = prepare(px)
  c.to_csv(os.path.join(B.OUT, "compare_live_candidates.csv"), index=False)

  sets = {
      "All candidates (one position per stock at a time), files 10-20..11-17":
          (c, None, None),
      "Top-1 per scan day, files 10-22..11-17 (both scores available)":
          (c[c.New_Score.notna()], 1, True),
      "Top-2 per scan day, files 10-22..11-17":
          (c[c.New_Score.notna()], 2, True),
  }
  all_rows = []
  for title, (cand, k, ranked) in sets.items():
    print("=" * 110)
    print(title)
    print("=" * 110)
    res = {}
    combos = [("OLD  (old rank, old plan)", "Old_Score", "old"),
              ("     old rank, NEW plan", "Old_Score", "new"),
              ("     NEW rank, old plan", "New_Score", "old"),
              ("NEW  (new rank, new plan)", "New_Score", "new")]
    if not ranked:
      combos = [("OLD plan", "Old_Score", "old"), ("NEW plan", "Old_Score", "new")]
    for name, sc, plan in combos:
      pk = picks(cand, sc, k)
      trades = pd.DataFrame([{**{"Scan_Date": r.Scan_Date.date(), "Ticker": r.Ticker,
                                 "Trigger": r.Trigger_Status, "Old_Score": r.Old_Score,
                                 "New_Score": r.New_Score, "Exit_Date": r.Exit_Date.date()},
                              **run_trade(px, spy, r, plan)} for _, r in pk.iterrows()])
      trades["Set"], trades["System"] = title.split(",")[0], name.strip()
      all_rows.append(trades)
      res[name] = summarize(trades)
    print(pd.DataFrame(res).T.to_string(), "\n")

  allt = pd.concat(all_rows, ignore_index=True)
  allt.to_csv(os.path.join(B.OUT, "compare_live_trades.csv"), index=False)
  print("Per-trade detail (all candidates, closed or open):")
  a = allt[allt.Set == "All candidates (one position per stock at a time)"]
  piv = a.pivot_table(index=["Scan_Date", "Ticker", "Trigger", "Exit_Date"],
                      columns="System", values="Ret", aggfunc="first").round(2)
  oc = a.pivot_table(index=["Scan_Date", "Ticker", "Trigger", "Exit_Date"],
                     columns="System", values="Outcome", aggfunc="first")
  print(piv.join(oc, rsuffix=" outcome").to_string())


if __name__ == "__main__":
  main()
