# US Pre-Earnings Dislocation & Catalyst Run-Up Engine (v4.1)

**A Hybrid Quantamental Equity Discovery & Execution System for Capturing Pre-Earnings Mean Reversion in US Large-Cap Compounders**

![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Strategy: Quantamental Event-Driven](https://img.shields.io/badge/Strategy-Quantamental%20Event--Driven-orange.svg)
![Cost: Zero-Data-Spend](https://img.shields.io/badge/Data%20Stack-Open--Source%20%28yfinance%29-success.svg)

---

## 1. Executive Summary & Strategy Thesis

In institutional equity markets, fundamentally strong large-cap compounders frequently experience temporary, non-fundamental price dislocations (**-5% to -22% drawdowns**) in the **2 to 4 weeks preceding a quarterly earnings release**. 

As the earnings announcement approaches (typically between trading days $T-15$ and $T-3$), these dislocations systematically mean-revert as institutional capital repositions for the catalyst. However, holding *through* the binary earnings release exposes a portfolio to asymmetric overnight gap risk and implied volatility (IV) crush—where even an EPS beat can trigger a sell-off due to valuation compression.

This repository implements a **two-stage Quantamental Funnel** designed to capture the **pre-earnings anticipation drift** while eliminating binary announcement risk:
1. **`scanner.py` (70-Point Deterministic Quantitative Engine):** Scans the liquid US equity universe (S&P 500 + Nasdaq-100, ~$N \approx 530$ equities) daily to isolate oversold structural compounders with proven earnings beat streaks, positive analyst revision velocity, and dark-pool/VWAP institutional accumulation footprints.
2. **`SKILL.md` (30-Point Fact-Checked LLM Audit Protocol):** A deterministic, citation-enforced Large Language Model (LLM) audit specification that evaluates the top quantitative survivors for 21-day catalyst purity, sub-sector peer contagion, and supply-chain/customer bellwether overlap.

---

## 2. Market Microstructure: Why Pre-Earnings Dislocations Occur & Rebound

A naive technical screener buys any oversold stock before earnings, falling into value traps and informed institutional liquidations. This system is engineered around four specific institutional mechanics that govern pre-earnings price action:

### A. Why the Initial Dislocation Happens ($T-25$ to $T-12$)
* **Corporate Buyback Blackout Windows:** Roughly 4 to 5 weeks prior to quarterly earnings, US corporations enter mandatory share-repurchase blackout periods. Removing the largest price-insensitive daily buyer from the order book allows minor macro rate jitters or sector rotations to push high-beta compounders down 8%–15% on below-average volume.
* **Pre-Catalyst De-Risking:** Multi-manager pods and fast-money funds trim high-multiple winners ahead of macro prints or sector peer reports, creating temporary air pockets down to the 50-day or 100-day Simple Moving Average (SMA).

### B. Why the Pre-Earnings Rebound Fires ($T-14$ to $T-3$)
1. **Short Covering Before Proven "Beat-and-Raise" Management Teams:** Short sellers who rode a 10-day technical pullback systematically cover their positions 1 to 2 weeks prior to earnings when facing a management team that has beaten consensus EPS estimates in **4 of the last 4 quarters**.
2. **Sell-Side Preview Notes & Channel Checks:** Between $T-14$ and $T-5$, Wall Street research desks publish quarterly preview notes and supply-chain channel checks. Reiterations of *Buy/Outperform* ratings and price-target hikes trigger long-only institutional dip buying.
3. **Options Dealer Delta/Gamma Hedging:** As pre-earnings Call buying ramps up, options market makers selling those Calls must purchase the underlying equity to remain delta-neutral as implied volatility expands into the event.

### C. Why We Exit at $T-3$ US Trading Days (The Pre-Announcement Leak Buffer)
Rather than holding into the binary print ($T-0$) or exiting on the final afternoon ($T-1$), this system enforces a hard time-stop at **$T-3$ US Business Trading Days** prior to the earnings release. In final sessions ($T-2$ and $T-1$), late sell-side channel checks, whisper-number leaks, and institutional book-squaring frequently introduce erratic pre-print volatility. Exiting at $T-3$ (or earlier if the stock hits its **Early Profit Target** at 75% of its 20-day high range) locks in the mean-reversion alpha with zero binary gap exposure.

---

## 3. System Architecture & 4-Stage Pipeline

```text
[S&P 500 + Nasdaq-100 Universe (~530 Liquid US Equities)]
                        │
                        ▼
┌───────────────────────────────────────────────────────────────┐
│ STAGE 0: Macro Market Regime Filter (SPY, QQQ, ^VIX)          │
│ • Classifies tape as GREEN (Risk-On), YELLOW, or RED          │
└───────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────────────────┐
│ STAGE 1: Technical Pullback, Elasticity & Order-Flow Engine   │
│ • Structural Uptrend: Price > 200-SMA                         │
│ • Institutional Support Zone: -10.0% <= Vs_50SMA <= +4.0%     │
│ • Pullback & Momentum: 10D/20D Return -4% to -22%, RSI <= 48  │
│ • Elasticity Gate: 14D ATR% >= 1.6% & 20D High Upside >= 6%   │
│ • Institutional Footprint: 10D Chaikin Money Flow + Vol Ratio │
└───────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────────────────┐
│ STAGE 2: Fundamental Catalyst, Revision & Analyst Audit       │
│ • Holding Window: 4 to 14 US Trading Days until T-3 Exit      │
│ • Earnings Track Record: >= 3/4 Past Beats (Avg Surp < 200%)  │
│ • Revision Velocity: 30-Day Consensus EPS Revisions >= 0      │
│ • Top-Line & Valuation Guardrail: Rev Growth > 0%, PT >= +5%  │
│ • 21-Day Wall Street Upgrade / Downgrade / PT Cut Extraction  │
└───────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────────────────────┐
│ STAGE 3: 70/30 Quantamental Scorecard & Execution Brackets    │
│ • 70 Pts: Deterministic CSV Setup_Score_70 (Non-Polarized)    │
│ • Separate Trigger_Status (Day1_Turn / Exhaustion / Wait)     │
│ • 30 Pts: Fact-Checked LLM Web Audit (News, Peers, Customers) │
│ • Output: Hard_Stop (-1.5 ATR) & Early_Target (75% 20D High)  │
└───────────────────────────────────────────────────────────────┘
```

---

## 4. Quantitative Methodology & Mathematical Formulations

### 4.1 Granular Sub-Industry Relative Benchmarking
Comparing all technology stocks against a single broad index (`XLK`) masks critical sub-sector divergences (e.g., Semiconductors crashing while Systems Software holds steady). `scanner.py` parses each company's exact **GICS Sub-Industry** and maps it to a specialized liquid ETF benchmark:
* **Semiconductors:** `SMH` | **Software & IT Services:** `IGV` | **Hardware & Networking:** `XLK`
* **Biotech & Life Sciences:** `XBI` | **Banks, Custody & Brokerage:** `KBE` | **Aerospace & Defense:** `ITA`
* **Homebuilders:** `ITB` | **Oil & Gas E&P:** `XOP` | **Retail:** `XRT` | **Industrials:** `XLI`

Relative dislocation over a 10-trading-day window is defined as:

$$\text{Vs\_SubETF\_10D} = R_{i, 10d} - R_{\text{SubETF}, 10d}$$

### 4.2 Detecting Institutional Order Flow Using Daily OHLCV Data
Because institutional VWAP/TWAP accumulation algorithms execute heavily into the afternoon close while retail panic-selling clusters near the morning open, institutional footprints leave measurable signatures in daily price-volume bars. We combine two metrics:

1. **10-Day Chaikin Money Flow ($\text{CMF}_{10}$):**
   First, we compute the daily **Money Flow Multiplier ($\text{MFM}_t$)**, which measures where the stock closed within its intraday High-Low range:

   $$\text{MFM}_t = \frac{(C_t - L_t) - (H_t - C_t)}{H_t - L_t} \in [-1, +1]$$

   Multiplying $\text{MFM}_t$ by daily volume $V_t$ and normalizing over 10 sessions yields $\text{CMF}_{10}$:

   $$\text{CMF}_{10} = \frac{\sum_{t=1}^{10} \text{MFM}_t \cdot V_t}{\sum_{t=1}^{10} V_t}$$

2. **5-Day vs. 20-Day Pullback Volume Ratio ($\text{VolRatio}$):**

   $$\text{VolRatio} = \frac{\frac{1}{5}\sum_{t=-4}^{0} V_t}{\frac{1}{20}\sum_{t=-24}^{-5} V_t}$$

Using these two parameters, each stock's institutional footprint is classified into four states:
* **`Accumulating` ($\text{CMF}_{10} > +0.08$):** Institutions are systematically buying intraday dips and pushing closes into the upper half of the daily range on volume.
* **`Quiet_DryUp` ($\text{VolRatio} \le 0.92 \text{ and } \text{CMF}_{10} \ge -0.15$):** Pullback is occurring on below-average volume (buyback blackout / lack of buyers rather than active institutional liquidation).
* **`Neutral`:** Normal two-way institutional flow.
* **`Dumping` ($\text{CMF}_{10} < -0.18 \text{ and } \text{VolRatio} \ge 1.25$):** High-volume institutional distribution closing near intraday lows.

### 4.3 Decoupling Setup Quality (`Setup_Score_70`) from Trigger Timing (`Trigger_Status`)
A critical design principle of v4.1 is **separating how coiled the spring is (`Setup_Score_70`) from whether the reversal candle has printed yet (`Trigger_Status`)**. Penalizing a stock's quality score because it is still red on day $t-1$ hides the highest-upside candidates right before they turn on day $t$.

Instead, `Trigger_Status` is tracked as an independent execution signal coupled with institutional flow:
1. **`Day1_Turn` (Immediate Execution):** $C_t > O_t$ and $C_t > C_{t-1}$ and $\text{Inst\_Footprint} \neq \text{Dumping}$. (First confirmed green reversal session).
2. **`Exhaustion_Buy` (Day-0 Intraday Bottom):** Intraday range position $\frac{C_t - L_t}{H_t - L_t} \ge 0.48$, $\text{MFM}_t > 0$, $\text{Inst\_Footprint} \neq \text{Dumping}$, and price holds yesterday's low or sits within 2% of its 50-SMA. (Buyers absorbed morning selling and closed the bar in the upper half).
3. **`Stabilizing` (Watchlist — Inside Bar):** $L_t \ge L_{t-1}$ (seller momentum stalling; stopped making lower lows).
4. **`Knife_Wait` (Stalk Only — Do Not Catch Blindly):** Making new lows and closing in the bottom half of the daily range. Wait for `Stabilizing`, `Exhaustion_Buy`, or `Day1_Turn`.

### 4.4 Dynamic Volatility Brackets (`Hard_Stop_Price` & `Early_Target_Price`)
Using the 14-day Average True Range ($\text{ATR}_{14}$) and the 20-trading-day rolling high ($H_{20d}$), the scanner computes two hard price brackets for every candidate:

$$\text{Hard\_Stop\_Price} = C_t - 1.5 \times \text{ATR}_{14}$$

$$\text{Early\_Target\_Price} = C_t + 0.75 \times (H_{20d} - C_t)$$

* **Exit Rule:** Close the position at `Early_Target_Price` **OR** on `Exit_Date` ($T-3$ US trading days prior to earnings), **whichever comes first**.

---

## 5. The 100-Point Quantamental Scorecard Architecture

To eliminate LLM scoring drift and "hallucinated vibes," the 100-point rating system is split into **70 points of deterministic Python math** (using smooth, graduated tiers without 0-to-100 cliffs) and **30 points of fact-checked live web auditing**.

### Part A: The 70-Point Deterministic Scale (`Setup_Score_70` in `scanner.py`)

| Pillar | Component | Max Pts | Graduated Mathematical Tiers |
| :--- | :--- | :---: | :--- |
| **Pillar 1: Technical Structure & Elasticity (24 pts)** | **SMA Support Zone** | **12** | • **12 pts:** `Vs_50SMA >= -3.5%` & `Vs_100SMA >= -2.5%` (Holding both)<br>• **9 pts:** `Vs_100SMA >= -5.5%` & `Vs_50SMA >= -7.0%` (Testing 100-SMA)<br>• **6 pts:** `Vs_100SMA >= -7.0%` or `Vs_50SMA >= -9.0%`<br>• **3 pts:** Deeper pullback (`< -7.0%` vs 100-SMA) |
| | **Rebound Room (`Upside_20D_High_%`)** | **12** | • **12 pts:** `>= 18.0%` upside to 20D high<br>• **9 pts:** `12.0% to 17.9%`<br>• **6 pts:** `8.5% to 11.9%`<br>• **3 pts:** `6.0% to 8.4%` |
| **Pillar 2: Sub-Sector & Institutional Flow (22 pts)** | **Sector Context & Relative Resilience** | **12** | • **12 pts:** Healthy sub-sector (`SubETF_10D > -5%`) + clean dip (`-7% <= Vs_SubETF <= -0.5%`)<br>• **10 pts:** Oversold sub-sector (`SubETF_10D <= -8%`), **BUT** stock holds 50-SMA or 100-SMA (`Relative Leader Bonus`)<br>• **8 pts:** Moderate sector pullback (`SubETF_10D > -9%`)<br>• **5 pts:** Weak sector + heavy relative underperformance |
| | **Institutional Footprint** | **10** | • **10 pts:** `Accumulating`<br>• **8 pts:** `Quiet_DryUp`<br>• **5 pts:** `Neutral`<br>• **2 pts:** `Dumping` |
| **Pillar 3: Earnings, Growth & Revisions (24 pts)** | **4Q Beat Consistency** | **8** | • **8 pts:** `4/4` EPS beats<br>• **4 pts:** `3/4` EPS beats (Graduated -4 pt deduction) |
| | **Beat Magnitude (`Avg_Surp_%`)** | **4** | • **4 pts:** `>= 10.0%` avg surprise<br>• **3 pts:** `5.0% to 9.9%`<br>• **2 pts:** `< 5.0%` |
| | **YoY Revenue Growth** | **6** | • **6 pts:** `>= 25.0%` YoY top-line growth<br>• **5 pts:** `15.0% to 24.9%`<br>• **3 pts:** `8.0% to 14.9%`<br>• **1 pt:** `< 8.0%` (Eliminates shrinking cost-cutting traps) |
| | **Consensus Target Upside** | **6** | • **6 pts:** `>= 20.0%` discount to Wall Street mean target price<br>• **4 pts:** `12.0% to 19.9%`<br>• **2 pts:** `5.0% to 11.9%` |
| | **21-Day Analyst Action Modifier** | **-7 to +3** | • **+3 pts:** Analyst Upgrade or Price Target (PT) Hike in last 21 days<br>• **0 pts:** Quiet / Maintained<br>• **-3 pts (Case A):** PT trimmed, *but* bank maintains `Buy/Outperform` & new PT is `>= 12%` above current price<br>• **-7 pts (Case B):** Downgrade OR PT cut on a `Hold/Neutral/Sell` rating OR `< 12%` upside to new PT |

### Part B: The 30-Point Fact-Checked Web Audit (`SKILL.md`)

| Audit Gate | Max Pts | Verification Criteria (Requires Cited Web Sources from Last 21 Days) |
| :--- | :---: | :--- |
| **Gate 4: Catalyst & Sub-Sector News Purity** | **15** | • **13–15 pts:** Clean non-fundamental pullback; bullish analyst preview notes/upgrades.<br>• **9–12 pts:** Quiet news tape or minor Case-A PT trim.<br>• **4–8 pts:** Sub-sector peer contagion (peer sold off on good earnings or downgraded) or index-inclusion unwind.<br>• **0–3 pts:** Material negative company event (8-K warning, guidance cut, CFO exit, or Case-B PT cut). |
| **Gate 5: Bellwether & Customer Overlap Risk** | **10** | • **9–10 pts:** Zero direct 10%+ revenue customers or sub-sector bellwethers report before `Exit_Date`.<br>• **6–8 pts:** Unrelated macro bellwethers report inside the window.<br>• **3–5 pts:** Direct customer/hyperscaler (`MSFT`, `AMZN`, `GOOGL`, `META`) reports *before* `Exit_Date` (Requires an **Adjusted Pre-Bellwether Exit Date**). |
| **Gate 6: Holding Window & R:R Efficiency** | **5** | • **5 pts:** `Hold_Days` is 6–13 US trading days, `RR_Ratio >= 1.85x`, and confirmed BMO/AMC earnings date.<br>• **3–4 pts:** `Hold_Days` is 4–5 or 14 days, or `RR_Ratio` between `1.50x and 1.84x`.<br>• **1–2 pts:** `< 4 Hold_Days` remaining after BMO/calendar adjustment or `RR_Ratio < 1.50x`. |

---

## 6. Installation & Daily Operational Workflow

### Step 1: Clone & Set Up Virtual Environment
```bash
git clone [https://github.com/](https://github.com/)<your-username>/quantamental-pre-earnings-scanner.git
cd quantamental-pre-earnings-scanner

# Create and activate isolated virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows PowerShell

# Install dependencies
pip install --upgrade pip
pip install yfinance pandas numpy lxml requests urllib3
```

### Step 2: Run the Daily Quantitative Scan
Run `scanner.py` after the US market close (22:00 CET / 16:00 EST) or 30 minutes prior to the US open:
```bash
python scanner.py
```
The script will:
1. Check the **Macro Market Regime** (`SPY`, `QQQ`, `^VIX`).
2. Download 1-year daily OHLCV bars for ~530 US large-cap equities and 12 sub-industry ETFs.
3. Filter and score all candidates, printing the sorted table to the terminal and saving `candidates_v4_1_YYYY-MM-DD.csv`.

### Step 3: Run the 30-Point LLM Audit (`SKILL.md`)
Upload `candidates_v4_1_YYYY-MM-DD.csv` into an LLM workspace configured with `SKILL.md` (e.g., Gemini Custom Gem / Skill) with the prompt:
> `"Run the Pre-Earnings Dislocation Auditor on this CSV."`

### Step 4: Execution & Risk Management Rules
* **Minimum Conviction Threshold:** Only deploy capital into candidates scoring **$\ge 80 / 100$** with an active **`Day1_Turn`** or **`Exhaustion_Buy`** trigger.
* **Stalking Coiled Setups:** Candidates scoring **$\ge 75 / 100$** with a **`Stabilizing`** or **`Knife_Wait`** status are placed on the priority watchlist with price alerts set at the prior day's high; execute only when the turn trigger confirms.
* **Position Sizing & FX Discipline:** Maintain trading cash in a dedicated **USD sub-account** (converting EUR $\leftrightarrow$ USD only during weekday interbank market hours to avoid weekend FX markups). Concentrate capital into **2 to 3 uncorrelated slots** so commission quotas and FX spreads remain $0.00$.

---

## 7. CSV Output Schema Reference

| Column | Description |
| :--- | :--- |
| `Ticker` | Stock symbol (S&P 500 or Nasdaq-100 constituent) |
| `Sub_ETF` | Mapped GICS Sub-Industry benchmark ETF (`SMH`, `IGV`, `XLK`, `XBI`, `KBE`, `XLI`, etc.) |
| `Price` | Latest closing or live share price (USD) |
| `ATR_%` | 14-day Average True Range as a percentage of share price (measures daily elasticity) |
| `10D_Ret_%` | 10-trading-day price return (%) |
| `SubETF_10D_%` | 10-trading-day return of the mapped Sub-Industry ETF (%) |
| `Vs_SubETF_10D_%` | Excess 10-day drawdown of the stock relative to its Sub-Industry ETF (%) |
| `RSI_14` | 14-day Wilder Relative Strength Index |
| `Vs_50SMA_%` / `Vs_100SMA_%` | Distance (%) from the 50-day and 100-day Simple Moving Averages |
| `Upside_20D_High_%` | Percentage gain required to return to the 20-trading-day high |
| `Inst_Footprint` | Order-flow classification (`Accumulating`, `Quiet_DryUp`, `Neutral`, `Dumping`) |
| `Trigger_Status` | Reversal timing signal (`Day1_Turn`, `Exhaustion_Buy`, `Stabilizing`, `Knife_Wait`) |
| `Hard_Stop_Price` | Hard stop-loss level set at $1.5 \times \text{ATR}_{14}$ below current price |
| `Early_Target_Price` | Profit-taking target set at 75% of the distance back to the 20-day high |
| `Rev_Growth_%` | Trailing YoY quarterly revenue growth (%) |
| `Target_Upside_%` | Percentage upside to Wall Street consensus mean target price (`targetMeanPrice`) |
| `Analyst_21D` | Automated extraction of Wall Street upgrades, downgrades, and PT changes over the last 21 days |
| `Earnings_Date` | Next scheduled quarterly earnings release date |
| `Hold_Days` | Exact US Business Trading Days remaining between today and `Exit_Date` |
| `Exit_Date` | Mandatory pre-earnings time-stop date ($T-3$ US trading days prior to `Earnings_Date`) |
| `Beats_4Q` | Number of consensus EPS beats over the last 4 reported quarters (`4/4` or `3/4`) |
| `Avg_Surp_%` | Mean EPS surprise percentage across the last 4 quarters |
| `Setup_Score_70` | Deterministic 70-point setup quality score |

---

## Disclaimer
*This software and documentation are provided strictly for quantitative finance research and educational purposes. Nothing in this repository constitutes investment advice or a solicitation to buy or sell any security.*