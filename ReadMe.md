# US Pre-Earnings Dislocation Engine (`v4.10`)
**A Quantamental Mean-Reversion & Pre-Earnings Run-Up Scanner for US Large-Cap Equities**

![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)
![Strategy](https://img.shields.io/badge/Strategy-Quantamental%20Event--Driven-emerald.svg)
![Universe](https://img.shields.io/badge/Universe-S%26P%20500%20%2B%20Nasdaq%20100-orange.svg)
![Cost](https://img.shields.io/badge/Data%20Cost-%240%20Open--Source-brightgreen.svg)

---

## 1. Thesis

The engine looks for quality US large caps (S&P 500 + Nasdaq-100) that have pulled back
4–22% inside a long-term uptrend shortly before their quarterly report, buys the
dislocation, and **exits before the binary earnings event** (`T-3` business days before the
report). The idea combines two documented effects: short-term reversal after 1–4 week
losses, and the drift of stocks into their earnings date (buyback blackouts ending,
pre-earnings short covering, sell-side preview notes, options hedging flows).

It is a **70/30 Quantamental split**: a deterministic Python scanner produces a 70-point
score; a live web audit (`SKILL.md`, run in an LLM) adds 30 points for catalyst purity,
bellwether risk and earnings-date verification.

---

## 2. Pipeline

```text
[S&P 500 + Nasdaq-100 universe (~518 stocks, Wikipedia, cached in universe_cache.csv)]
                        │
                        ▼
┌───────────────────────────────────────────────────────────────────┐
│ STAGE 1: scanner.py — technical filter (1 year of daily bars)     │
│ • price > 200-SMA, within -10%..+4% of the 50-SMA                 │
│ • 10D or 20D return between -22% and -4% (pullback)               │
│ • RSI14 <= 48, ATR14 >= 1.6% of price, >= 6% below 20-day high    │
├───────────────────────────────────────────────────────────────────┤
│ STAGE 2: scanner.py — earnings & fundamentals (per stock)         │
│ • next earnings 4–21 trading days away (exit = T-3)               │
│ • >= 3 of last 4 quarters beat EPS estimates                      │
│ • no >= 1% cut to this quarter's EPS estimate in 30 days          │
│ • revenue growth > 0, analyst target >= 5% above price            │
│ • 21-day analyst actions -> Analyst_Mod [-7, +3]                  │
│ • Setup_Score_70 = P1 + P2 + P3 + Analyst_Mod                     │
└───────────────────────────────────────────────────────────────────┘
        │ candidates_v4_10_YYYY-MM-DD.csv   (passed)
        │ rejects_v4_10_YYYY-MM-DD.csv      (dropped in stage 2, with reason)
        ▼
┌───────────────────────────────────────────────────────────────────┐
│ STAGE 3: SKILL.md — live web audit (30 pts)                       │
│ • Catalyst_14: why did it fall? (veto on thesis-breaking news)     │
│ • Bellwether_8: direct customer/competitor reporting in window    │
│ • Window_8: confirmed earnings date and holding runway            │
│ • -> Quantamental_Score_100, tiers, audit_YYYY-MM-DD.csv log      │
└───────────────────────────────────────────────────────────────────┘
```

The market regime (SPY vs 50-SMA, VIX) is printed for information only. It is not a filter:
in the backtest, signals in RED regimes did not do worse.

---

## 3. Scoring (`Setup_Score_70`)

| Pillar | Max | Inputs (v4.9+) |
|---|---|---|
| **P1 Pullback depth** (`P1_Tech_24`) | 24 | `RSI_14` (lower = more points) 12/8/4 · `Mom_6M_%` prior run-up, t-126→t-21 (smaller = more) 12/8/4 |
| **P2 Sector dislocation & entry state** (`P2_SecFlow_22`) | 22 | `SubETF_10D_%` (weaker sector = more) 11/7/3 · `Trigger_Status` Knife_Wait 11, else 3 |
| **P3 Fundamentals** (`P3_Fund_24`) | 24 | beats 4/4 = 8, 3/4 = 4 · avg surprise 4/3/2 · revenue growth 6/5/3/1 · target upside 6/4/2 |
| **Analyst_Mod** | -7..+3 | 21-day upgrades, downgrades and target changes, magnitude-weighted |

P1/P2 cut-offs were derived mechanically on 2016–22 data and validated once on 2023–26
(`research/scoring_test.py`). Inputs that did not rank trades (SMA distance, upside to the
20-day high, Inst_Footprint/CMF) stay in the CSV as context but carry no points.

---

## 4. Trade Plan (v4.8+)

* **Entry:** next open after the scan (any `Trigger_Status`; waiting for a green
  confirmation day did not improve results in the backtest).
* **Hard stop:** signal close − 2.5 × ATR14 (`Hard_Stop_Price`, `Risk_%`).
* **No fixed profit target:** hold to the `Exit_Date` close (T-3) unless stopped.
  (The old 75%-to-20D-high target capped winners and lowered returns in every test.)
* **Sizing:** `Pos_%_per_1%_Risk` = position size, as % of the account, when risking 1% of
  the account on the trade. The wider stop only works with these smaller positions.
* **Exit day:** `EXIT_BDAYS_BEFORE_ER` in `scanner.py` (3 = T-3; 2 = T-2 is the closest
  allowed). Exit dates skip weekends only; check exchange holidays yourself.

---

## 5. Daily Workflow

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scanner.py          # best pre-market or after the US close
```

1. The scanner writes `candidates_v4_10_<date>.csv` and `rejects_v4_10_<date>.csv`.
2. Run the `SKILL.md` auditor on the candidates file (two-turn web audit).
3. Save the CSV block the auditor prints as `audit_<date>.csv` in this folder.
4. Periodically run `python research/tracker.py` to see how past candidates, rejected
   stocks and audit tiers actually performed.

---

## 6. Research Toolkit (`research/`)

| Script | Purpose |
|---|---|
| `fetch_data.py` | Prices since 2014 + Yahoo earnings history → `research/data/` (git-ignored) |
| `fetch_fundamentals.py` | Analyst history, splits, raw closes; SEC revenue with `SEC_USER_AGENT="name email"` and `--sec-only` |
| `backtest.py` | Point-in-time replication of the scanner rules (parity-checked against real CSVs) |
| `analyze.py` | Baselines, plan variants and component breakdowns |
| `trade_plan.py` | Stop / target / trailing grid |
| `scoring.py`, `scoring_test.py` | Feature tests and the frozen in-sample → out-of-sample scoring rule |
| `components_test.py` | Analyst, target, revenue, bellwether and hold-window tests |
| `old_vs_new.py` | Portfolio simulation: original v4.4/4.6 workflow vs current |
| `compare_live.py`, `tracker.py` | Replays the real daily CSVs (and rejects/audit logs) against prices |

---

## 7. What the Evidence Says (2016–2026 backtest, read with the limits below)

* Portfolio (max 5 positions, 2 new per day, 1% risk sizing): current workflow
  **CAGR 9.0%, Sharpe 0.74, max DD −26.6%** vs the original workflow 4.3% / 0.36 / −30.4%.
  2023–26 (out-of-sample for the scoring): 11.7% / 0.96 / −15.5% vs 0.1% / 0.08 / −23.9%.
* The biggest single gain came from the v4.9 scoring; next from entering Knife_Wait setups
  without waiting, and from the wider stop without a target.
* **It does not beat simply holding SPY:** at the same average exposure (~56%) SPY had a
  similar CAGR with a higher Sharpe (0.86) and a smaller drawdown. Stock selection still
  largely tracks the market; bad market years (2018, 2022) lose money.
* Revenue growth, beats/surprise and a bellwether merely reporting in the window showed no
  measurable effect. Analyst modifier and target upside were weakly positive.

**Limits:** the universe is today's index members (delisted losers missing), the backtest
uses actual earnings dates (live uses estimates), the EPS-cut filter and the web audit
cannot be replayed historically, and the trade plan was chosen on the full period. The
rejects and audit logs exist so these parts can be judged on live data over time.

---

## 8. Version History

See the changelog comments at the bottom of `scanner.py` (v4.6 → v4.10).

---

## 9. Disclaimer
*For quantitative research and educational purposes only. Nothing here is investment advice
or a solicitation to buy or sell securities. See `DISCLAIMER.md`.*
