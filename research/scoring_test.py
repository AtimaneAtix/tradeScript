"""Step 2 of the scoring work: a frozen, in-sample-only rule and one out-of-sample test.

Rules written BEFORE running this file:
  Outcome   : R of the v4.8 plan, demeaned within entry week (R_dm). This strips market
              timing (VIX, regime, beta), which is the same for every candidate that week
              and cannot rank a daily list.
  Candidates: stock-level features only (no VIX, no Hold -> Hold is scored in Window_8).
  Selection : 2016-22 data only. |IC| >= 0.03 on R_dm AND same sign in >= 5 of 7 years.
              Max 4 features; skip a feature whose |rank corr| > 0.6 with one already chosen.
  Points    : direction from in-sample IC; cutoffs = in-sample terciles (frozen absolute
              values); 0/1/2 points per feature; equal weights; no fitted coefficients.
  Test      : weeks with >= 2 candidates. Pick top-1 and top-2 by score, compare their
              mean R with the rest of that week. Run for the current score (Score_part) and
              the new composite, per period and per year. Leave-one-year-out as 2nd check.
  Pass bar  : new composite top-2-vs-rest >= +0.05R in 2023-26, beats the current score
              there, and is positive in >= 3 of the 4 years 2023-26.
              If it fails, the honest result is "the score does not rank".

Usage: .venv/bin/python research/scoring_test.py
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

STOCK_FEATURES = [
    "Vs50", "Vs100", "Upside", "Sub10", "VsSub", "CMF", "VolRatio", "AvgSurp", "Beats",
    "ATR_pct", "RSI", "Ret10", "Trig_num", "Mom126", "Vs200", "Ret20",
]
CURRENT_PARTS = ["SMA_pts", "Up_pts", "Sec_pts", "Flow_pts", "Beats_pts", "Surp_pts",
                 "P1", "P2", "Score_part"]


def rank_ic(a, b):
  ok = pd.concat([a, b], axis=1).dropna()
  return ok.iloc[:, 0].rank().corr(ok.iloc[:, 1].rank())


def main():
  tr = pd.read_pickle(os.path.join(B.DATA, "scoring_trades.pkl"))
  tr["Week"] = tr["Entry_Day"].dt.to_period("W")
  tr["R_dm"] = tr["R"] - tr.groupby("Week")["R"].transform("mean")
  tr["Ex_dm"] = tr["RawExcess"] - tr.groupby("Week")["RawExcess"].transform("mean")
  ins = tr[tr.Period == "2016-22"]
  oos = tr[tr.Period == "2023-26"]
  years_in = sorted(ins.Year.unique())
  years_in = [y for y in years_in if y >= 2016]

  # ---------------- 1. in-sample ICs on week-demeaned R, with per-year sign counts
  rows = []
  for f in STOCK_FEATURES + CURRENT_PARTS:
    ic = rank_ic(ins[f], ins["R_dm"])
    yr = [rank_ic(g[f], g["R_dm"]) for y, g in ins.groupby("Year") if y in years_in]
    same = sum(np.sign(v) == np.sign(ic) for v in yr if pd.notna(v))
    rows.append({"feature": f, "IC_in": round(ic, 3), "years_same_sign": f"{same}/{len(yr)}",
                 "IC_in_RawEx_dm": round(rank_ic(ins[f], ins["Ex_dm"]), 3),
                 "is_current_part": f in CURRENT_PARTS})
  ict = pd.DataFrame(rows).set_index("feature").sort_values("IC_in", key=abs, ascending=False)
  print("=== 1. IN-SAMPLE (2016-22) rank IC vs week-demeaned R ===")
  print(ict.to_string(), "\n")

  # ---------------- 2. frozen selection rule (in-sample only)
  chosen = []
  for f, r in ict[~ict.is_current_part].iterrows():
    same = int(r.years_same_sign.split("/")[0])
    if abs(r.IC_in) < 0.03 or same < 5:
      continue
    if any(abs(ins[f].rank().corr(ins[c].rank())) > 0.6 for c, _ in chosen):
      continue
    chosen.append((f, 1 if r.IC_in > 0 else -1))
    if len(chosen) == 4:
      break
  cut = {f: ins[f].quantile([1 / 3, 2 / 3]).values for f, _ in chosen}
  print("=== 2. FROZEN RULE (from 2016-22 only) ===")
  if not chosen:
    print("No stock-level feature passed the rule. Stop here.\n")
  for f, d in chosen:
    lo, hi = cut[f]
    better = "higher" if d > 0 else "lower"
    print(f"  {f:8s} {better} is better; tercile cutoffs {lo:.2f} / {hi:.2f}")

  def composite(df):
    s = pd.Series(0.0, index=df.index)
    for f, d in chosen:
      lo, hi = cut[f]
      pts = np.select([df[f] <= lo, df[f] <= hi], [0, 1], 2).astype(float)
      s += pts if d > 0 else (2 - pts)
    return s

  tr["New"] = composite(tr) if chosen else np.nan
  print()

  # ---------------- 3. decisive test: top picks within each week vs the rest
  def pick_test(df, score, k):
    out = []
    for w, g in df.groupby("Week"):
      if len(g) < 2 or g[score].isna().all():
        continue
      g = g.sample(frac=1, random_state=0).sort_values(score, ascending=False, kind="stable")
      top, rest = g.head(min(k, len(g) - 1)), g.iloc[min(k, len(g) - 1):]
      out.append({"Year": g.Year.iloc[0], "Period": g.Period.iloc[0],
                  "diff": top.R.mean() - rest.R.mean()})
    return pd.DataFrame(out)

  print("=== 3. TOP-k PER WEEK minus REST OF WEEK (mean R), weeks with >= 2 candidates ===")
  res = {}
  for score in ["Score_part", "New"]:
    if tr[score].isna().all():
      continue
    for k in (1, 2):
      p = pick_test(tr, score, k)
      res[(score, k)] = p
      by_p = p.groupby("Period")["diff"].agg(["count", "mean", "sem"]).round(3)
      by_y = p.groupby("Year")["diff"].mean().round(3)
      print(f"\n[{score}] top-{k}:")
      print(by_p.to_string())
      print("  by year:", by_y.to_dict())

  # ---------------- 4. pass bar
  print("\n=== 4. PASS BAR ===")
  if ("New", 2) in res:
    p_new = res[("New", 2)]
    p_cur = res[("Score_part", 2)]
    o_new = p_new[p_new.Period == "2023-26"]
    o_cur = p_cur[p_cur.Period == "2023-26"]
    yrs = o_new.groupby("Year")["diff"].mean()
    c1 = o_new["diff"].mean() >= 0.05
    c2 = o_new["diff"].mean() > o_cur["diff"].mean()
    c3 = (yrs > 0).sum() >= 3
    print(f"  new top-2 vs rest 2023-26 = {o_new['diff'].mean():+.3f}R (need >= +0.05): {c1}")
    print(f"  beats current ({o_cur['diff'].mean():+.3f}R): {c2}")
    print(f"  positive years 2023-26: {(yrs > 0).sum()}/{len(yrs)} (need >= 3): {c3}")
    print("  RESULT:", "PASS" if (c1 and c2 and c3) else "FAIL")

    # leave-one-year-out on in-sample years (rule re-derived without that year)
    print("\n  Leave-one-year-out check (rule features fixed, cutoffs re-derived):")
    for y in years_in:
      fit = ins[ins.Year != y]
      test = tr[tr.Year == y].copy()
      s = pd.Series(0.0, index=test.index)
      for f, d in chosen:
        lo, hi = fit[f].quantile([1 / 3, 2 / 3]).values
        pts = np.select([test[f] <= lo, test[f] <= hi], [0, 1], 2).astype(float)
        s += pts if d > 0 else (2 - pts)
      test["L"] = s
      p = pick_test(test, "L", 2)
      print(f"    {y}: top-2 vs rest {p['diff'].mean():+.3f}R over {len(p)} weeks")

  # ---------------- 5. score distribution for the 70-point tiers
  print("\n=== 5. CURRENT Score_part distribution (for tier compatibility) ===")
  print(tr["Score_part"].describe().round(1).to_dict())
  tr.to_pickle(os.path.join(B.DATA, "scoring_trades_scored.pkl"))


if __name__ == "__main__":
  main()
