"""Historical backtest of the scanner's price + earnings-window + beats rules.

What it CAN test (point-in-time from Yahoo history): the technical filter, Inst_Footprint,
Trigger_Status, sub-ETF context (P2), the earnings window, beats/surprise, regime, and the
trade plan (stop / target / exit day). What it CANNOT test: the EPS-cut filter, revenue
growth, analyst target upside and the 21D analyst modifier (no history) -> no conclusions
about those, or about the full 70-point score.

Known biases: universe = today's S&P 500 + Nasdaq-100 (delisted names missing; S&P names
only count after their "Date added"), and earnings dates are the actual report dates
(live, the scanner sees Yahoo's estimate). Trust relative comparisons more than levels.

Usage: .venv/bin/python research/backtest.py [parity|run]
"""

import glob
import os
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import scanner as S  # noqa: E402

DATA = os.path.join(ROOT, "research", "data")
OUT = os.path.join(ROOT, "research", "output")
SLIP = 0.0005  # 5 bps per side
IN_SAMPLE_END = pd.Timestamp("2022-12-31")
BT_START = pd.Timestamp("2016-01-01")


# ----------------------------------------------------------------------------- data
def load():
  u = pd.read_csv(os.path.join(DATA, "universe.csv"), parse_dates=["Date_Added"])
  px = pd.read_pickle(os.path.join(DATA, "prices.pkl"))
  earn = {}
  for f in glob.glob(os.path.join(DATA, "earnings", "*.csv")):
    e = pd.read_csv(f, index_col=0, parse_dates=True)
    e = e[~e.index.isna()].sort_index()
    earn[os.path.basename(f)[:-4]] = e
  return u, px, earn


def bars_of(px, t):
  if t not in px.columns.get_level_values(0):
    return None
  b = px[t].dropna(subset=["Open", "High", "Low", "Close"]).copy()
  b["Volume"] = b["Volume"].fillna(0)
  return b


# ------------------------------------------------------------------ indicators (= scanner)
def indicators(b, high_window=20):
  c, o, h, l, v = b["Close"], b["Open"], b["High"], b["Low"], b["Volume"]
  d = pd.DataFrame(index=b.index)
  d["Close"], d["Open"], d["High"], d["Low"] = c, o, h, l
  d["sma50"] = c.rolling(50).mean()
  d["sma100"] = c.rolling(100).mean()
  d["sma200"] = c.rolling(200).mean()
  d["ret10"] = c / c.shift(10) - 1
  d["ret20"] = c / c.shift(20) - 1
  d["prev_ret10"] = c.shift(1) / c.shift(11) - 1
  d["high20"] = h.rolling(high_window).max()
  d["upside"] = (d["high20"] / c - 1) * 100
  tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
  d["atr"] = tr.rolling(14).mean()
  d["atr_pct"] = d["atr"] / c * 100
  delta = c.diff()
  gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
  loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean().replace(0, 1e-10)
  d["rsi"] = 100 - 100 / (1 + gain / loss)
  d["vs50"] = (c / d["sma50"] - 1) * 100
  d["vs100"] = (c / d["sma100"] - 1) * 100
  vol5 = v.rolling(5).mean()
  vol20 = v.shift(5).rolling(20).mean()
  d["vol_ratio"] = np.where(vol20 > 0, vol5 / vol20, 1.0)
  rng = (h - l).replace(0, np.nan)
  mfm = ((c - l) - (h - c)) / rng
  mfv = mfm.fillna(0) * v
  v10 = v.rolling(10).sum()
  d["cmf10"] = np.where(v10 > 0, mfv.rolling(10).sum() / v10, 0.0)
  d["footprint"] = np.select(
      [d["cmf10"] > 0.08,
       (d["vol_ratio"] <= 0.92) & (d["cmf10"] >= -0.15),
       (d["cmf10"] < -0.18) & (d["vol_ratio"] >= 1.25)],
      ["Accumulating", "Quiet_DryUp", "Dumping"], "Neutral")
  pos = np.where((h - l) > 0, (c - l) / (h - l), 0.5)
  mfm_t = mfm.fillna(0)
  dump = d["footprint"] == "Dumping"
  day1 = (c > o) & (c > c.shift()) & ~dump
  exh = (pos >= 0.48) & (mfm_t > 0) & ~dump & ((l >= l.shift() * 0.995) | (c >= d["sma50"] * 0.98))
  stab = l >= l.shift()
  d["trigger"] = np.select([day1, exh, stab], ["Day1_Turn", "Exhaustion_Buy", "Stabilizing"],
                           "Knife_Wait")
  in_pb = (d["ret20"].between(-0.22, -0.04) | d["ret10"].between(-0.22, -0.04)
           | (d["prev_ret10"].between(-0.22, -0.06) & (d["ret10"] <= -0.02)))
  d["tech_pass"] = ((c > d["sma200"]) & d["vs50"].between(-10, 4) & in_pb
                    & (d["rsi"] <= 48) & (d["upside"] >= 6) & (d["atr_pct"] >= 1.6)
                    & d["sma200"].notna())
  return d


def market_context(px):
  spy = bars_of(px, "SPY")
  vix = px["^VIX"]["Close"].dropna()
  m = pd.DataFrame(index=spy.index)
  m["spy_o"], m["spy_c"] = spy["Open"], spy["Close"]
  m["spy50"] = spy["Close"].rolling(50).mean()
  m["vix"] = vix.reindex(spy.index).ffill()
  m["regime"] = np.select(
      [(m["vix"] >= 24) | (m["spy_c"] < m["spy50"] * 0.985),
       (m["vix"] >= 20) | (m["spy_c"] < m["spy50"])], ["RED", "YELLOW"], "GREEN")
  return m


# ------------------------------------------------------------------------ signals
def build_signals(u, px, earn, high_window=20, exit_k=3, require_window=True,
                  require_beats=True):
  """One row per (ticker, signal bar) passing the technical filter (+ ER window/beats)."""
  mkt = market_context(px)
  etf_r10 = {}
  for etf in set(u["Sub_ETF"]):
    eb = bars_of(px, etf)
    etf_r10[etf] = (eb["Close"] / eb["Close"].shift(10) - 1) if eb is not None else None
  rows = []
  for _, ur in u.iterrows():
    t = ur["Symbol"]
    b = bars_of(px, t)
    if b is None or len(b) < 260:
      continue
    d = indicators(b, high_window)
    idx = d.index
    cand = np.where(d["tech_pass"].values)[0]
    cand = cand[(cand + 1 < len(idx))]
    if len(cand) == 0:
      continue
    ed = earn.get(t)
    er_dates = (np.array(sorted(set(ed.index.normalize())), dtype="datetime64[ns]")
                if ed is not None else np.array([], dtype="datetime64[ns]"))
    beats_cache = {}
    for i in cand:
      day = idx[i]
      D = idx[i + 1]  # scanner runs pre-market on D, buys D's open
      if day < BT_START - pd.Timedelta(days=5):
        continue
      if pd.notna(ur["Date_Added"]) and D < ur["Date_Added"]:
        continue
      row = {"Ticker": t, "Signal_Date": day, "Entry_Date": D, "i": i,
             "Sub_ETF": ur["Sub_ETF"], "Sector": ur["Sector"]}
      er_i = np.searchsorted(er_dates, np.datetime64(D)) if len(er_dates) else 0
      if er_i < len(er_dates):
        er = pd.Timestamp(er_dates[er_i])
        er_pos = idx.searchsorted(er)
        exit_pos = er_pos - exit_k
        hold = exit_pos - (i + 1) + 1
        row.update(ER=er, exit_pos=exit_pos, Hold=hold)
      else:
        row.update(ER=pd.NaT, exit_pos=-1, Hold=-99)
      in_window = 4 <= row["Hold"] <= 21 and row["exit_pos"] < len(idx)
      if require_window and not in_window:
        continue
      key = row["ER"]
      if key not in beats_cache:
        if ed is not None:
          q = S.get_distinct_past_4_quarters(ed, D, min_gap_days=35)
          beats_cache[key] = ((int((q > 0).sum()), round(float(q.mean()), 2))
                              if len(q) == 4 else (None, None))
        else:
          beats_cache[key] = (None, None)
      beats, surp = beats_cache[key]
      if require_beats and (beats is None or beats < 3 or surp > 200):
        continue
      r = d.iloc[i]
      e10 = etf_r10.get(ur["Sub_ETF"])
      sub10 = e10.get(day, np.nan) if e10 is not None else np.nan
      sub10 = 0.0 if pd.isna(sub10) else float(sub10)
      g = mkt.loc[day] if day in mkt.index else None
      score_in = {
          "Vs_50SMA_%": round(r["vs50"], 1), "Vs_100SMA_%": round(r["vs100"], 1),
          "Upside_20D_High_%": round(r["upside"], 1),
          "SubETF_10D_%": round(sub10 * 100, 2),
          "Vs_SubETF_10D_%": round((r["ret10"] - sub10) * 100, 2),
          "Inst_Footprint": r["footprint"],
          "Beats_4Q": f"{beats}/4" if beats is not None else "0/4",
          "Avg_Surp_%": surp if surp is not None else 0.0,
          "Rev_Growth_%": 0.0, "Target_Upside_%": 0.0,  # unknown historically -> fixed low
      }
      p1, p2, p3, _ = S.compute_setup_score_breakdown(score_in, 0)
      row.update(
          Close=r["Close"], ATR=r["atr"], ATR_pct=r["atr_pct"], RSI=r["rsi"],
          Vs50=r["vs50"], Vs100=r["vs100"], Upside=r["upside"], High20=r["high20"],
          Ret10=r["ret10"] * 100, Sub10=sub10 * 100, VolRatio=r["vol_ratio"],
          CMF=r["cmf10"], Footprint=r["footprint"], Trigger=r["trigger"],
          Beats=beats, AvgSurp=surp, P1=p1, P2=p2, P3_part=p3 - 3,  # minus fixed rev/pt pts
          Score_part=p1 + p2 + p3 - 3,
          Regime=g["regime"] if g is not None else "NA",
          VIX=g["vix"] if g is not None else np.nan,
      )
      rows.append(row)
  return pd.DataFrame(rows)


# ------------------------------------------------------------------------ trades
def simulate(o, h, l, c, entry_pos, exit_pos, stop, target, atr=None, trail_atr=None,
             be_r=None):
  """Day-by-day walk. Stop levels only move up (trailing / breakeven) after a bar closes."""
  entry = o[entry_pos] * (1 + SLIP)
  init_risk = entry - stop if stop is not None else None
  hi_close = entry
  for j in range(entry_pos, exit_pos + 1):
    if stop is not None:
      if j > entry_pos and o[j] <= stop:
        return o[j] * (1 - SLIP), "STOP", j, entry
      if l[j] <= stop:
        return min(stop, o[j]) * (1 - SLIP), "STOP", j, entry
    if target is not None and h[j] >= target:
      fill = max(o[j], target) if j > entry_pos else target
      return fill * (1 - SLIP), "TARGET", j, entry
    # end of bar: ratchet the stop
    hi_close = max(hi_close, c[j])
    if trail_atr and atr:
      trail = hi_close - trail_atr * atr
      stop = trail if stop is None else max(stop, trail)
    if be_r and init_risk and h[j] >= entry + be_r * init_risk:
      stop = max(stop, entry)
  return c[exit_pos] * (1 - SLIP), "EXIT", exit_pos, entry


def make_trades(sig, px, mkt, stop_atr=1.5, use_target=True, entry_mode="immediate",
                one_per_cycle=True, exit_k=3, regime_skip=(), target_frac=0.75,
                trail_atr=None, be_r=None, sizing_atr=None):
  """Turn signal rows into trades with the scanner's trade plan (or a variant)."""
  out = []
  cache = {}
  s = sig.sort_values(["Ticker", "Signal_Date"])
  if regime_skip:
    s = s[~s["Regime"].isin(regime_skip)]
  busy_until = {}
  for _, r in s.iterrows():
    t = r["Ticker"]
    if t not in cache:
      b = bars_of(px, t)
      cache[t] = (b.index, b["Open"].values, b["High"].values, b["Low"].values,
                  b["Close"].values)
    idx, o, h, l, c = cache[t]
    i = int(r["i"])
    exit_pos = int(r["exit_pos"]) + (3 - exit_k)
    if exit_pos >= len(idx):
      continue
    if one_per_cycle and (t, r["ER"]) in busy_until:
      continue
    if not one_per_cycle and busy_until.get(t, -1) >= i + 1:
      continue  # still in a trade
    entry_pos = i + 1
    if entry_mode == "confirmed":
      entry_pos = None
      for j in range(i, exit_pos):
        if c[j] > o[j] and l[j] >= l[j - 1]:
          entry_pos = j + 1
          break
      if entry_pos is None or entry_pos > exit_pos:
        if one_per_cycle:
          busy_until[(t, r["ER"])] = exit_pos
        continue
    stop = r["Close"] - stop_atr * r["ATR"] if stop_atr else None
    target = (r["Close"] + target_frac * (r["High20"] - r["Close"])) if use_target else None
    if stop is not None and o[entry_pos] <= stop:
      if one_per_cycle:
        busy_until[(t, r["ER"])] = exit_pos
      continue  # gapped below stop before entry -> no trade
    fill, outcome, xj, entry = simulate(o, h, l, c, entry_pos, exit_pos, stop, target,
                                        atr=r["ATR"], trail_atr=trail_atr, be_r=be_r)
    # R = return per unit of planned risk. sizing_atr overrides it (e.g. for no-stop plans)
    if sizing_atr:
      risk = r["Close"] * (1 + SLIP) - (r["Close"] - sizing_atr * r["ATR"])
    else:
      risk = entry - stop if stop is not None else r["ATR"] * 1.5
    ed, xd = idx[entry_pos], idx[xj]
    spy_ret = mkt["spy_c"].asof(xd) / mkt["spy_o"].asof(ed) - 1
    rec = r.to_dict()
    rec.update(Entry_Pos=entry_pos, Entry_Day=ed, Exit_Day=xd, Outcome=outcome,
               Days=xj - entry_pos + 1, Ret=(fill / entry - 1) * 100,
               R=(fill - entry) / risk, SPY=spy_ret * 100,
               Excess=(fill / entry - 1 - spy_ret) * 100)
    out.append(rec)
    if one_per_cycle:
      busy_until[(t, r["ER"])] = exit_pos
    else:
      busy_until[t] = xj
  tr = pd.DataFrame(out)
  if not tr.empty:
    tr["Year"] = tr["Entry_Day"].dt.year
    tr["Period"] = np.where(tr["Entry_Day"] <= IN_SAMPLE_END, "2016-22", "2023-26")
  return tr


def stats(g):
  if len(g) == 0:
    return pd.Series({"n": 0})
  wins, losses = g.loc[g.Ret > 0, "Ret"].sum(), -g.loc[g.Ret <= 0, "Ret"].sum()
  return pd.Series({
      "n": len(g),
      "win%": round((g.Ret > 0).mean() * 100, 1),
      "avg%": round(g.Ret.mean(), 2),
      "med%": round(g.Ret.median(), 2),
      "excess%": round(g.Excess.mean(), 2),
      "avgR": round(g.R.mean(), 2),
      "PF": round(wins / losses, 2) if losses > 0 else np.nan,
      "stop%": round((g.Outcome == "STOP").mean() * 100, 1),
      "tgt%": round((g.Outcome == "TARGET").mean() * 100, 1),
      "days": round(g.Days.mean(), 1),
  })


def table(tr, by):
  return tr.groupby(by).apply(stats)


# ------------------------------------------------------------------------ parity
def parity():
  """Recompute the stored v4.4 CSV rows from history; report differences."""
  u, px, earn = load()
  files = sorted(glob.glob(os.path.join(ROOT, "candidates_v4_4_*.csv")))
  res = []
  for f in files:
    D = pd.Timestamp(f[-14:-4])
    cs = pd.read_csv(f)
    for _, r in cs.iterrows():
      b = bars_of(px, r["Ticker"])
      if b is None:
        continue
      b1y = b[b.index > D - pd.DateOffset(years=1)]
      b1y = b1y[b1y.index < D]  # scanner ran pre-market on D: last bar = D-1
      d = indicators(b1y, high_window=21).iloc[-1]
      res.append({
          "file": D.date(), "T": r["Ticker"],
          "dPrice%": round((d["Close"] / r["Price"] - 1) * 100, 2),
          "dRSI": round(d["rsi"] - r["RSI_14"], 1),
          "dVs50": round(d["vs50"] - r["Vs_50SMA_%"], 1),
          "dVs100": round(d["vs100"] - r["Vs_100SMA_%"], 1),
          "dATR%": round(d["atr_pct"] - r["ATR_%"], 1),
          "dUpside": round(d["upside"] - r["Upside_20D_High_%"], 1),
          "foot_ok": d["footprint"] == r["Inst_Footprint"],
          "trig_ok": d["trigger"] == r["Trigger_Status"],
          "tech_pass": bool(d["tech_pass"]),
      })
  p = pd.DataFrame(res)
  pd.set_option("display.width", 250)
  print(p.to_string(index=False))
  num = ["dPrice%", "dRSI", "dVs50", "dVs100", "dATR%", "dUpside"]
  print("\nmax |diff|:", p[num].abs().max().to_dict())
  print("footprint match:", p.foot_ok.mean(), "trigger match:", p.trig_ok.mean(),
        "tech_pass:", p.tech_pass.mean())
  return p


if __name__ == "__main__":
  if len(sys.argv) > 1 and sys.argv[1] == "parity":
    parity()
