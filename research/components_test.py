"""Tests the score parts the price backtest could not: Analyst_Mod, target upside, revenue
growth (SEC, if downloaded), plus the mechanical web-audit parts (bellwether overlap,
Hold_Days tiers). EPS-cut has no history -> verified live in a separate check only.

Point-in-time rules:
  - analyst events strictly before the entry day; scanner's own evaluate_analyst_21d()
  - price targets split-adjusted (Yahoo stores them as issued) and compared with
    split-adjusted, NOT dividend-adjusted closes (as quoted at the time)
  - target proxy = mean of each firm's latest target within the prior 120 days
  - SEC revenue known only from its FILED date (conservative: filings come after earnings)

Pre-registered decisions (written before running):
  - Coverage: a trade is "covered" if >= 5 analyst events in the prior 365 days.
    Years where >= 60% of trades are covered are used; the last 40% of those years are
    the TEST years, the rest FIT years.
  - Default = leave unchanged. A gate is flagged for removal only if trades it REJECTS do
    better than trades it keeps by > 2 SE in both fit and test. A points component is
    set to zero only if its IC < -0.03 in both fit and test. A modification is adopted
    only if it improves top-2-per-week in both fit and test.

Usage: .venv/bin/python research/components_test.py
"""

import glob
import os
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest as B  # noqa: E402

S = B.S
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 200)
TARGET_WINDOW = 120
COVER_MIN = 5


# ------------------------------------------------------------------- analyst data
def load_analyst(t):
  p = os.path.join(B.DATA, "analyst", f"{t}.pkl")
  if not os.path.exists(p):
    return None
  ud = pd.read_pickle(p)
  if ud is None or len(ud) == 0:
    return pd.DataFrame()
  ud = ud.sort_index()
  sp = os.path.join(B.DATA, "splits", f"{t}.pkl")
  splits = pd.read_pickle(sp) if os.path.exists(sp) else pd.Series(dtype=float)
  if len(splits):
    sidx = splits.index.tz_localize(None) if splits.index.tz is not None else splits.index
    for d, ratio in zip(sidx, splits.values):
      if ratio and ratio > 0:
        before = ud.index < d
        for col in ("currentPriceTarget", "priorPriceTarget"):
          if col in ud:
            ud.loc[before, col] = ud.loc[before, col] / ratio
  return ud


class FakeTicker:
  def __init__(self, ud):
    self.upgrades_downgrades = ud


def target_proxy(ud_past, day):
  w = ud_past[(ud_past.index >= day - pd.Timedelta(days=TARGET_WINDOW))]
  w = w[w.get("currentPriceTarget", pd.Series(dtype=float)) > 0]
  if w.empty:
    return np.nan, 0
  last = w.groupby(w["Firm"].str.lower())["currentPriceTarget"].last()
  return float(last.mean()), len(last)


# ------------------------------------------------------------------- SEC revenue
def sec_series(t):
  p = os.path.join(B.DATA, "sec", f"{t}.csv")
  if not os.path.exists(p):
    return None
  try:
    f = pd.read_csv(p)
  except pd.errors.EmptyDataError:  # company files no revenue tag we query (e.g. SYF, TFC)
    return {}
  if f.empty:
    return {}
  f = f.dropna(subset=["end", "val", "filed"])
  f["start"] = pd.to_datetime(f["start"], errors="coerce")
  f["end"] = pd.to_datetime(f["end"])
  f["filed"] = pd.to_datetime(f["filed"])
  f["dur"] = (f["end"] - f["start"]).dt.days
  out = {}
  for tag, g in f.groupby("tag"):
    g = g.sort_values("filed")
    q = g[g.dur.between(80, 100)].drop_duplicates(["end"], keep="first")
    rows = [(r.end, r.val, r.filed) for r in q.itertuples()]
    fy = g[g.dur.between(350, 380)].drop_duplicates(["end"], keep="first")
    ytd9 = g[g.dur.between(260, 285)].drop_duplicates(["end"], keep="first")
    have = set(q.end)
    for r in fy.itertuples():
      if r.end in have:
        continue
      nine = ytd9[(ytd9.start - r.start).abs().dt.days <= 5]
      if len(nine):
        val = r.val - nine.iloc[-1].val
      else:
        three = q[(q.start >= r.start - pd.Timedelta(days=5)) & (q.end < r.end)]
        if len(three) != 3:
          continue
        val = r.val - three.val.sum()
      rows.append((r.end, val, r.filed))
    s = pd.DataFrame(rows, columns=["end", "val", "known"]).sort_values("end")
    if len(s):
      out[tag] = s
  return out


TAG_PRIORITY = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                "SalesRevenueGoodsNet", "RevenuesNetOfInterestExpense", "Revenue"]


def rev_growth_at(series, day):
  if not series:
    return np.nan
  best = None
  for tag in TAG_PRIORITY:
    s = series.get(tag)
    if s is None:
      continue
    k = s[s.known < day]
    if k.empty:
      continue
    cur = k.iloc[-1]
    prev = k[(k.end - (cur.end - pd.Timedelta(days=365))).abs().dt.days <= 25]
    if prev.empty or prev.iloc[-1].val <= 0:
      continue
    cand = (cur.end, cur.val / prev.iloc[-1].val - 1)
    if best is None or cand[0] > best[0]:
      best = cand  # most recent quarter across tags; priority breaks ties
  return best[1] * 100 if best else np.nan


# ------------------------------------------------------------------- build table
def build():
  u, px, earn = B.load()
  mkt = B.market_context(px)
  sig = pd.read_pickle(os.path.join(B.DATA, "sig_newmap_hw20.pkl"))
  tr = B.make_trades(sig, px, mkt, stop_atr=2.5, use_target=False)
  tr["Week"] = tr.Entry_Day.dt.to_period("W")
  tr["R_dm"] = tr.R - tr.groupby("Week").R.transform("mean")
  close_raw = pd.read_pickle(os.path.join(B.DATA, "close_raw.pkl"))
  bw_dates = {bw: sorted(set(earn[bw].index.normalize())) for bw in S.BELLWETHERS if bw in earn}
  rows = []
  for t, g in tr.groupby("Ticker"):
    ud = load_analyst(t)
    sec = sec_series(t)
    craw = close_raw[t] if t in close_raw.columns else None
    bidx = B.bars_of(px, t).index
    for k, r in g.iterrows():
      D = r.Entry_Date
      price = craw.get(r.Signal_Date, np.nan) if craw is not None else np.nan
      rec = {"_k": k, "PriceRaw": price}
      if ud is not None and len(ud):
        past = ud[ud.index < D]
        rec["Cover365"] = int((past.index >= D - pd.Timedelta(days=365)).sum())
        tgt, nfirms = target_proxy(past, D)
        rec["TgtFirms"] = nfirms
        rec["TgtUp"] = (tgt / price - 1) * 100 if pd.notna(tgt) and price > 0 else np.nan
        mod, note = S.evaluate_analyst_21d(FakeTicker(past), D, price,
                                           rec["TgtUp"] if pd.notna(rec["TgtUp"]) else 0.0)
        rec["AnMod"], rec["AnNote"] = mod, note
      else:
        rec.update(Cover365=0, TgtFirms=0, TgtUp=np.nan, AnMod=0, AnNote="NoData")
      rec["RevG"] = rev_growth_at(sec, D) if sec is not None else np.nan
      # PLANNED exit (known at entry), not the actual exit: a stop-out must not shrink it
      exit_day = bidx[min(int(r.exit_pos), len(bidx) - 1)]
      rec["BW"] = int(any(any(D <= d <= exit_day for d in ds) for bw, ds in bw_dates.items()
                          if bw != t))
      rows.append(rec)
  e = pd.DataFrame(rows).set_index("_k")
  tr = tr.join(e)
  tr["PT_pts"] = np.select([tr.TgtUp >= 20, tr.TgtUp >= 12], [6, 4], 2)
  tr["Rev_pts"] = np.select([tr.RevG >= 25, tr.RevG >= 15, tr.RevG >= 8], [6, 5, 3], 1)
  tr.loc[tr.RevG.isna(), "Rev_pts"] = np.nan
  tr.loc[tr.TgtUp.isna(), "PT_pts"] = np.nan
  tr.to_pickle(os.path.join(B.DATA, "components_trades.pkl"))
  return tr


# ------------------------------------------------------------------- tests
def ic(a, b):
  ok = pd.concat([a, b], axis=1).dropna()
  return ok.iloc[:, 0].rank().corr(ok.iloc[:, 1].rank()) if len(ok) > 30 else np.nan


def gate_test(df, mask_pass, label):
  p, f = df[mask_pass], df[~mask_pass]
  def ms(x):
    return f"{x.R_dm.mean():+.3f} (se {x.R_dm.std() / np.sqrt(max(len(x), 1)):.3f}, n={len(x)})"
  return f"  {label:38s} kept {ms(p)} | rejected {ms(f)}"


def top2(df, col):
  out = []
  for w, g in df.groupby("Week"):
    if len(g) < 2 or g[col].isna().all():
      continue
    g = g.sample(frac=1, random_state=0).sort_values(col, ascending=False, kind="stable")
    k = min(2, len(g) - 1)
    out.append(g.head(k).R.mean() - g.iloc[k:].R.mean())
  o = pd.Series(out)
  return f"{o.mean():+.3f}R (se {o.std() / np.sqrt(len(o)):.3f}, weeks={len(o)})"


def main():
  path = os.path.join(B.DATA, "components_trades.pkl")
  tr = build() if not os.path.exists(path) or "--rebuild" in sys.argv else pd.read_pickle(path)
  sec_ok = tr.RevG.notna().mean()
  print(f"trades: {len(tr)} | SEC revenue available for {sec_ok:.0%} of trades\n")

  cov = tr.groupby("Year").apply(lambda g: (g.Cover365 >= COVER_MIN).mean()).round(2)
  print("Share of trades with analyst coverage >= 5 events/yr, by year:")
  print(cov.to_dict())
  years = sorted(y for y, v in cov.items() if v >= 0.6)
  n_test = max(1, round(len(years) * 0.4))
  fit_years, test_years = years[:-n_test], years[-n_test:]
  print(f"-> analyst/target analysis years: fit {fit_years}, test {test_years}\n")
  covered = tr[(tr.Cover365 >= COVER_MIN) & tr.Year.isin(years)]
  sets = {"FIT": covered[covered.Year.isin(fit_years)],
          "TEST": covered[covered.Year.isin(test_years)]}

  print("=== Target proxy sanity ===")
  print(f"  firms behind each proxy target: median {covered.TgtFirms.median():.0f}; "
        f"proxy upside median {covered.TgtUp.median():.1f}%")

  print("\n=== Gates (week-demeaned R; kept vs rejected) ===")
  for name, d in sets.items():
    print(f" [{name}]")
    print(gate_test(d, d.TgtUp >= 5.0, "Target upside >= 5%"))
    severe = d.AnMod <= -3
    print(gate_test(d, ~severe, "Analyst_Mod > -3 (no severe bear)"))
  if sec_ok > 0.3:
    rv = tr[tr.RevG.notna() & (tr.Year >= 2016)]
    for name, d in [("2016-22", rv[rv.Year <= 2022]), ("2023-26", rv[rv.Year >= 2023])]:
      print(f" [{name}]")
      print(gate_test(d, d.RevG > 0, "Revenue growth > 0"))

  print("\n=== Points components: rank IC vs week-demeaned R ===")
  comp = ["AnMod", "PT_pts", "TgtUp"]
  for c in comp:
    print(f"  {c:8s} " + "  ".join(f"{n}: {ic(d[c], d.R_dm):+.3f}" for n, d in sets.items()))
  if sec_ok > 0.3:
    rv = tr[tr.RevG.notna() & (tr.Year >= 2016)]
    for c in ["Rev_pts", "RevG"]:
      print(f"  {c:8s} 2016-22: {ic(rv[rv.Year <= 2022][c], rv[rv.Year <= 2022].R_dm):+.3f}  "
            f"2023-26: {ic(rv[rv.Year >= 2023][c], rv[rv.Year >= 2023].R_dm):+.3f}")
  print("\n  Analyst_Mod buckets (mean R_dm, n):")
  for name, d in sets.items():
    b = d.groupby(pd.cut(d.AnMod, [-8, -3.5, -0.5, 0.5, 3.5], labels=["-7..-4", "-3..-1", "0", "+1..+3"]))
    print(f"   {name}: " + "  ".join(f"{k}: {v.R_dm.mean():+.3f} ({len(v)})" for k, v in b))

  print("\n=== Top-2 per week vs rest (R): does adding the parts help the v4.9 ranking? ===")
  for name, d in sets.items():
    d = d.copy()
    d["S_base"] = d.P1 + d.P2
    d["S_plus_an"] = d.S_base + d.AnMod
    d["S_plus_pt"] = d.S_base + d.PT_pts.fillna(2)
    d["S_full"] = d.S_base + d.AnMod + d.PT_pts.fillna(2) + d.P3_part
    for col in ["S_base", "S_plus_an", "S_plus_pt", "S_full"]:
      print(f"  [{name}] {col:10s} {top2(d, col)}")

  if sec_ok > 0.3:
    print("\n=== Revenue: does it add to the v4.9 ranking? (top-2 per week vs rest) ===")
    rv = tr[tr.RevG.notna() & (tr.Year >= 2016)].copy()
    rv["S_base"] = rv.P1 + rv.P2
    rv["S_rev"] = rv.S_base + rv.Rev_pts
    for name, d in [("2016-22", rv[rv.Year <= 2022]), ("2023-26", rv[rv.Year >= 2023])]:
      for col in ["S_base", "S_rev"]:
        print(f"  [{name}] {col:7s} {top2(d, col)}")
    print("\n  Revenue growth buckets (mean R_dm, n):")
    for name, d in [("2016-22", rv[rv.Year <= 2022]), ("2023-26", rv[rv.Year >= 2023])]:
      bk = d.groupby(pd.cut(d.RevG, [-1e9, 0, 8, 15, 25, 1e9],
                            labels=["<=0", "0-8", "8-15", "15-25", "25+"]))
      print(f"   {name}: " + "  ".join(f"{k}: {v.R_dm.mean():+.3f} ({len(v)})" for k, v in bk))

  print("\n=== Web-audit mechanics (all trades 2016-26) ===")
  for name, d in [("2016-22", tr[tr.Year <= 2022]), ("2023-26", tr[tr.Year >= 2023])]:
    print(f" [{name}]")
    print(gate_test(d, d.BW == 0, "No bellwether report in window"))
    tech = d[d.Sub_ETF.isin(["IGV", "SMH", "XLK", "XLC"])]
    print(gate_test(tech, tech.BW == 0, "  tech names only: no bellwether"))
    for lo, hi in [(4, 7), (8, 14), (15, 21)]:
      g = d[d.Hold.between(lo, hi)]
      print(f"  Hold {lo:2d}-{hi:2d}: n={len(g):4d} R/trade {g.R.mean():+.3f}  "
            f"R/day {(g.R / g.Days).mean():+.4f}  R_dm {g.R_dm.mean():+.3f}")


if __name__ == "__main__":
  main()
