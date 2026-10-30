# US Pre-Earnings Dislocation Engine (`v4.1`)
**A Quantamental Mean-Reversion & Catalyst Run-Up Trading System for US Large-Cap Equities**

![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)
![Strategy](https://img.shields.io/badge/Strategy-Quantamental%20Event--Driven-emerald.svg)
![Universe](https://img.shields.io/badge/Universe-S%26P%20500%20%2B%20Nasdaq%20100-orange.svg)
![Cost](https://img.shields.io/badge/Data%20Cost-%240%20Open--Source-brightgreen.svg)

---

## 1. Executive Summary & Investment Thesis

The **US Pre-Earnings Dislocation Engine** is a systematic, hybrid **"Quantamental"** (Quantitative + Fundamental/LLM Audit) discovery and execution framework. It is designed to identify and exploit temporary, non-fundamental price dislocations in fundamentally elite US large-cap compounders (`S&P 500` and `Nasdaq-100`) during the **6-to-20 trading day window prior to quarterly earnings announcements**.

### The Structural Market Inefficiency
In institutional equity markets, high-growth "beat-and-raise" compounders frequently experience 6% to 20% technical pullbacks 2 to 4 weeks prior to their quarterly earnings release due to four non-fundamental market mechanics:
1. **Corporate Buyback Blackout Windows:** Roughly 4 to 5 weeks prior to earnings, US corporations enter mandatory share-repurchase blackout periods. The temporary removal of the corporate bid allows minor macro or sector rotation flows to push prices down to intermediate moving average support (50-day or 100-day SMA) on low volume.
2. **Pre-Earnings Short Covering ($T-12$ to $T-3$):** Short sellers who rode the technical pullback systematically cover positions ahead of the print rather than carry binary gap risk against management teams with a 75%–100% historical earnings-beat track record.
3. **Sell-Side Preview Notes & Channel Checks ($T-10$ to $T-4$):** Institutional research desks publish pre-earnings preview notes and price-target revisions 1 to 2 weeks before the print, triggering long-only institutional accumulation at the 50-day/100-day SMA.
4. **Options Dealer Gamma Hedging:** Pre-earnings call buying forces options market makers to accumulate underlying shares to remain delta-neutral as implied volatility (IV) expands into the catalyst.

### The Core Edge: Capturing the Run-Up Without Binary Earnings Gambling
Rather than holding through the binary earnings release—where even an EPS beat can gap down due to valuation compression or guidance nuances—this system enters at the point of **intraday seller exhaustion or Day-1 reversal** ($T-14$ to $T-6$ trading days) and enforces a strict **Hard Time-Stop at $T-3$ US Business Trading Days prior to the earnings announcement** (or an earlier **75% range-rebound profit target**, whichever triggers first). This isolates the pre-earnings institutional positioning drift while eliminating post-earnings gap risk and late pre-announcement leak risk.

---

## 2. System Architecture & 2-Stage Pipeline

Pure black-box machine learning models frequently overfit noisy daily equity returns, while pure LLM workflows suffer from numerical hallucination and scoring inconsistency. This engine solves both problems via a strict **70/30 Quantamental Split**:

```text
[S&P 500 + Nasdaq-100 Universe (~530 Liquid US Equities)]
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 1: DETERMINISTIC PYTHON ENGINE (scanner.py v4.1)          │
│ • Macro Regime Gate (SPY vs 50-SMA & ^VIX Volatility Check)     │
│ • Technical Pullback, Elasticity (ATR%), & SMA Support Filter   │
│ • Institutional Volume Footprint (10D Chaikin Money Flow)       │
│ • Earnings Beat Streak (>=3/4), EPS Revisions & Sales Growth    │
│ • 21-Day Analyst Upgrade/Downgrade & Price-Target Cut Parser    │
│ • Computes Deterministic 70-Point Setup Score (Setup_Score_70)  │
│ • Separates Setup Quality from Real-Time Trigger_Status         │
└─────────────────────────────────────────────────────────────────┘
                        │
                        ▼  Outputs: candidates_v4_1_YYYY-MM-DD.csv
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 2: FACT-CHECKED AI AUDITOR (SKILL.md Workflow)            │
│ • Python Ingestion: Verifies R:R Ratios & Summary Statistics    │
│ • Live 21-Day Web Audit (Mandatory Inline Citations)            │
│   ├─ Gate 4: Company & Sub-Sector News Purity (15 pts)          │
│   ├─ Gate 5: Customer/Supplier Bellwether Overlap (10 pts)      │
│   └─ Gate 6: Holding Window & BMO/AMC Timing Check (5 pts)      │
│ • Outputs Master 100-Point Scorecard & Bracket Execution Plan   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Quantitative Methodology & Mathematical Formulations

### 3.1 Stage 0: Macro Market Regime Filter (`SPY`, `QQQ`, `^VIX`)
Approximately 70% of short-term equity trajectory is governed by market and sector beta. Before scanning individual equities, `scanner.py` evaluates the S&P 500 (`SPY`) relative to its 50-day Simple Moving Average ($\text{SMA}_{50}$) alongside the CBOE Volatility Index (`^VIX`):
* **`GREEN (Risk-On)`:** $\text{VIX} < 20.0$ and $\text{Price}_{\text{SPY}} \ge \text{SMA}_{50,\text{SPY}}$. Normal capital deployment.
* **`YELLOW (Choppy / Selective)`:** $20.0 \le \text{VIX} < 24.0$ or $\text{Price}_{\text{SPY}} < \text{SMA}_{50,\text{SPY}}$. Restrict execution strictly to setups scoring $\ge 85/100$ with confirmed `Day1_Turn` triggers.
* **`RED (Risk-Off / High Volatility)`:** $\text{VIX} \ge 24.0$ or $\text{Price}_{\text{SPY}} < 0.985 \times \text{SMA}_{50,\text{SPY}}$. Institutional dip-buying is frozen; system shifts to cash preservation.

---

### 3.2 Stage 1: Technical Dislocation, Support Zone & Elasticity Filters
To qualify as a technical pullback candidate within a structural uptrend, a stock must satisfy six mathematical conditions:

1. **Structural Uptrend:**
   $$\text{Close}_t > \text{SMA}_{200, t}$$
2. **Intermediate Moving Average Support Zone (Anti-Parabolic & Anti-Breakdown Filter):**
   $$-10.0\% \le \left(\frac{\text{Close}_t}{\text{SMA}_{50, t}} - 1\right) \le +4.0\%$$
   *Rationale:* Eliminates both broken trends (slicing $>10\%$ below the 50-day SMA) and "fake dips" where a parabolic stock pulls back $-4\%$ while still floating $+15\%$ above its 50-day SMA.
3. **10-Day or 20-Day Pullback Window:**
   $$R_{10\text{d}} \in [-22\%, -4\%] \quad \lor \quad R_{20\text{d}} \in [-22\%, -4\%] \quad \lor \quad \left(R_{10\text{d}, t-1} \in [-22\%, -6\%] \land R_{10\text{d}, t} \le -2\%\right)$$
   *(Including $t-1$ ensures stocks that print a strong +3% to +4% `Day1_Turn` reversal candle today are still captured on the evening scan).*
4. **14-Day Wilder's Relative Strength Index ($\text{RSI}_{14}$):**
   $$\text{RSI}_{14} = 100 - \frac{100}{1 + \frac{\text{EMA}_{14}(\text{Gain})}{\text{EMA}_{14}(\text{Loss})}} \le 48.0$$
5. **Minimum Volatility Elasticity ($\text{ATR}_{14}\%$ Filter):**
   $$\text{TR}_t = \max\left(\text{High}_t - \text{Low}_t, \; \vert{}\text{High}_t - \text{Close}_{t-1}\vert{}, \; \vert{}\text{Low}_t - \text{Close}_{t-1}\vert{}\right)$$
   $$\text{ATR}_{14}\% = \left(\frac{\text{SMA}_{14}(\text{TR})}{\text{Close}_t}\right) \times 100 \ge 1.6\%$$
   *Rationale:* Eliminates low-beta "dead money" stocks incapable of generating an 8%–12% mean-reversion move within a 6-to-13 trading day holding window.
6. **Rebound Room to 20-Day High:**
   $$\text{Upside}_{20\text{d High}} = \left(\frac{\max_{i \in [t-20, t]}(\text{High}_i)}{\text{Close}_t} - 1\right) \times 100 \ge 6.0\%$$

---

### 3.3 Stage 2: Institutional Order Flow & Coupled Turn-Timing Tiers

Because institutional desk algorithms execute via Dark Pools and afternoon VWAP/TWAP schedules rather than displaying large limit orders on public books, `scanner.py` detects institutional accumulation vs. distribution using two price-volume signatures:

1. **5-Day vs. 20-Day Pullback Volume Ratio:**
   $$\text{Vol\_Ratio} = \frac{\frac{1}{5}\sum_{i=t-4}^{t} \text{Volume}_i}{\frac{1}{20}\sum_{j=t-24}^{t-5} \text{Volume}_j}$$
2. **10-Day Chaikin Money Flow ($\text{CMF}_{10\text{d}}$) & Intraday Money Flow Multiplier ($\text{MFM}_t$):**
   $$\text{MFM}_t = \frac{(\text{Close}_t - \text{Low}_t) - (\text{High}_t - \text{Close}_t)}{\text{High}_t - \text{Low}_t} \in [-1, +1]$$
   $$\text{CMF}_{10\text{d}} = \frac{\sum_{i=t-9}^{t} \left(\text{MFM}_i \times \text{Volume}_i\right)}{\sum_{i=t-9}^{t} \text{Volume}_i}$$

* **`Accumulating`:** $\text{CMF}_{10\text{d}} > +0.08$ (Institutions systematically buying intraday dips and pushing closes into the upper daily range).
* **`Quiet_DryUp`:** $\text{Vol\_Ratio} \le 0.92$ and $\text{CMF}_{10\text{d}} \ge -0.15$ (Pullback occurring on Below-Average Volume; absence of institutional liquidation).
* **`Neutral`:** Normal two-way institutional flow.
* **`Dumping`:** $\text{CMF}_{10\text{d}} < -0.18$ and $\text{Vol\_Ratio} \ge 1.25$ (Heavy institutional block liquidation closing near daily lows).

#### Decoupling `Setup_Score_70` from Real-Time `Trigger_Status`
A critical methodological principle of `v4.1` is **never penalizing a stock's setup quality score because it has not printed its reversal candle yet**. Instead, `Setup_Score_70` measures how coiled the spring is, while `Trigger_Status` independently classifies daily execution timing:
* **`Day1_Turn` (Immediate Execution):** $\text{Close}_t > \text{Open}_t$, $\text{Close}_t > \text{Close}_{t-1}$, and $\text{Inst\_Footprint} \neq \text{Dumping}$.
* **`Exhaustion_Buy` (Day-0 Bottom Execution):** Stock closes in the upper 52% of its daily range ($\frac{\text{Close}_t - \text{Low}_t}{\text{High}_t - \text{Low}_t} \ge 0.48$), $\text{MFM}_t > 0$, $\text{Inst\_Footprint} \neq \text{Dumping}$, and holds prior low or 50-SMA support.
* **`Stabilizing` (Watchlist — Set Alert):** $\text{Low}_t \ge \text{Low}_{t-1}$ (Inside bar / stopped making lower lows).
* **`Knife_Wait` (Watchlist — Do Not Buy Yet):** Making new lows and closing in the lower half of the daily range. Wait for `Stabilizing` or `Day1_Turn`.

---

### 3.4 Stage 3: Fundamental Catalyst, Revision Velocity & Trading-Day Window

1. **Strict US Business Trading Day Window ($T-3$ Exit Rule):**
   Using `numpy.busday_count` and `pandas.bdate_range`, the scanner requires the upcoming earnings date ($T_{\text{ER}}$) to sit between **6 and 20 US trading days** from today. The mandatory exit date is defined strictly in business days:
   $$T_{\text{Exit}} = T_{\text{ER}} - 3 \text{ US Trading Days}$$
   This guarantees $T_{\text{Exit}}$ never falls on a weekend and provides a clean **4 to 14 US trading day holding window** (`Hold_Days`).
2. **Historical Earnings Beat Track Record:**
   Evaluates the last 4 reported quarters (`Beats_4Q` $\ge 3/4$, with $4/4$ preferred, and average EPS surprise $< 200\%$ to exclude penny base-effect distortions).
3. **30-Day Consensus EPS Revision Gate (`eps_trend`):**
   $$\text{EPS}_{\text{Est, Current (0q)}} - \text{EPS}_{\text{Est, 30 Days Ago (0q)}} \ge -0.001$$
   Any stock suffering net downward analyst EPS revisions over the past 30 days is automatically eliminated.
4. **Top-Line Revenue Growth & Consensus Target Price Discount:**
   * Requires positive trailing YoY revenue growth ($\text{Rev\_Growth}\% > 0\%$) so shrinking companies that only beat EPS via cost-cutting are eliminated.
   * Requires the stock to trade at least **5.0% below** Wall Street's mean target price (`Target_Upside_%` $\ge 5.0\%$).

---

## 4. The 100-Point Quantamental Scoring Architecture

### Part A: The 70-Point Smooth Deterministic Scale (`Setup_Score_70` in `scanner.py`)
To avoid binary cliff effects, `scanner.py` grades every candidate on a graduated 70-point scale across three pillars, plus a 21-day analyst action modifier:

| Pillar | Component | Max Pts | Graduated Scoring Tiers |
| :--- | :--- | :---: | :--- |
| **1. Technical Structure & Elasticity (24 pts)** | **SMA Support Zone** | **12** | • **12 pts:** `Vs_50SMA >= -3.5%` & `Vs_100SMA >= -2.5%`<br>• **9 pts:** `Vs_100SMA >= -5.5%` & `Vs_50SMA >= -7.0%`<br>• **6 pts:** `Vs_100SMA >= -7.0%` or `Vs_50SMA >= -9.0%`<br>• **3 pts:** Deeper pullback toward 200-SMA |
| | **Rebound Room (`Upside_20D_High_%`)** | **12** | • **12 pts:** $\ge 18.0\%$<br>• **9 pts:** $12.0\%$ to $17.9\%$<br>• **6 pts:** $8.5\%$ to $11.9\%$<br>• **3 pts:** $6.0\%$ to $8.4\%$ |
| **2. Sub-Sector & Institutional Flow (22 pts)** | **Sub-Sector & Relative Resilience** | **12** | Compares stock to its exact GICS Sub-Industry ETF (`SMH`, `IGV`, `XLK`, `XBI`, `KBE`, `ITA`, `XLI`):<br>• **12 pts:** Healthy sub-sector (`SubETF_10D > -5%`) + clean relative pullback (`-7% <= Vs_SubETF <= -0.5%`)<br>• **10 pts (Leader Resilience):** Oversold sub-sector (`SubETF_10D <= -8%`), **but** stock holds its 50-SMA or 100-SMA<br>• **8 pts:** Moderate sector pullback (`SubETF_10D > -9%`)<br>• **5 pts:** Weak sector + heavy relative underperformance |
| | **Institutional Footprint** | **10** | • **10 pts:** `Accumulating`<br>• **8 pts:** `Quiet_DryUp`<br>• **5 pts:** `Neutral`<br>• **2 pts:** `Dumping` |
| **3. Earnings, Growth & Analyst Revisions (24 pts)** | **4Q Beat Consistency** | **8** | • **8 pts:** `4/4` beats<br>• **4 pts:** `3/4` beats (graduated -4 pt penalty) |
| | **Beat Magnitude (`Avg_Surp_%`)** | **4** | • **4 pts:** $\ge 10.0\%$<br>• **3 pts:** $5.0\%$ to $9.9\%$<br>• **2 pts:** $< 5.0\%$ |
| | **YoY Revenue Growth** | **6** | • **6 pts:** $\ge 25.0\%$<br>• **5 pts:** $15.0\%$ to $24.9\%$<br>• **3 pts:** $8.0\%$ to $14.9\%$<br>• **1 pt:** $< 8.0\%$ |
| | **Wall Street Target Upside** | **6** | • **6 pts:** $\ge 20.0\%$<br>• **4 pts:** $12.0\%$ to $19.9\%$<br>• **2 pts:** $5.0\%$ to $11.9\%$ |
| **Modifier** | **21-Day Analyst Action (`Analyst_21D`)** | **-7 to +3** | Parses `priorPriceTarget`, `currentPriceTarget`, and rating grades over the last 21 days:<br>• **+3 pts:** Price Target Hike or Rating Upgrade<br>• **0 pts:** Quiet / Maintained<br>• **-3 pts (Case A):** Price Target trimmed, **but** firm maintains `Buy/Outperform` AND new PT is $\ge 12\%$ above current price<br>• **-7 pts (Case B):** Rating downgrade OR Price Target cut on a `Hold/Neutral/Sell` rating OR $< 12\%$ upside remaining |

---

### Part B: The 30-Point Fact-Checked Live Web Audit (`SKILL.md`)
Once `scanner.py` outputs the top candidates, the **Pre-Earnings Dislocation Auditor Skill** executes a live web audit across three gates:
* **Gate 4 — Catalyst & Sub-Sector News Purity (15 pts):** Verifies the exact cause of the 10D/20D pullback over the last 21 days, checks for SEC 8-K filings or executive departures, and checks if direct sub-industry peers suffered downgrades or sold off on strong earnings.
* **Gate 5 — Bellwether & Customer Overlap Risk (10 pts):** Checks whether Mega-Cap Bellwethers (`MSFT`, `AAPL`, `NVDA`, `GOOGL`, `AMZN`, `META`, `TSLA`) or 10%+ revenue customers report *between Today and `Exit_Date`*. If a direct customer reports inside the window, outputs an **Adjusted Pre-Bellwether Exit Date**.
* **Gate 6 — Holding Window & BMO/AMC Efficiency (5 pts):** Verifies the official earnings press release date and **BMO (Before Market Open) vs. AMC (After Market Close)** timing, scoring the trade's Reward-to-Risk ratio ($\ge 1.85\text{x}$ ideal).

---

## 5. Risk Management & Bracket Execution Rules

Every candidate generated by `scanner.py` includes automated bracket order levels based on its 14-day Average True Range ($\text{ATR}_{14}$):

1. **Hard Stop-Loss Price (`Hard_Stop_Price`):**
   $$\text{Hard\_Stop\_Price} = \text{Close}_t - 1.5 \times \text{ATR}_{14}$$
   Protects capital against structural breakdowns if a pullback turns into a fundamental liquidation.
2. **Early Profit Target Price (`Early_Target_Price`):**
   $$\text{Early\_Target\_Price} = \text{Close}_t + 0.75 \times \left(\text{High}_{20\text{d}} - \text{Close}_t\right)$$
   Captures 75% of the mean-reversion move back to the 20-day high.
3. **Dual Exit Rule (Whichever Hits First):**
   Positions are closed immediately upon hitting **`Early_Target_Price`** OR on **`Exit_Date` ($T-3$ US Trading Days prior to earnings)**, whichever occurs first.
4. **Portfolio Allocation & FX Discipline:**
   * Capital is concentrated into **2 active slots** to prevent commission drag and dilution.
   * All trading capital is held in a dedicated **USD sub-account** (converting EUR $\rightarrow$ USD only once during weekday interbank market hours) to eliminate per-trade FX conversion spreads and weekend FX markups.

---

## 6. Installation & Daily Desk Workflow

### Step 1: Clone & Set Up Virtual Environment
```bash
git clone [https://github.com/](https://github.com/)<your-username>/us-pre-earnings-dislocation-engine.git
cd us-pre-earnings-dislocation-engine

# Create isolated Python virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install open-source dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 2: Run the Daily Quantitative Scanner
Run `scanner.py` after the US market close (22:00 CET / 16:00 EST) or 30 minutes prior to the US open:
```bash
python scanner.py
```
The script downloads daily OHLCV and fundamental catalyst data for ~530 US equities, evaluates the Macro Regime, and exports a ranked CSV (`candidates_v4_1_YYYY-MM-DD.csv`).

### Step 3: Execute the 100-Point Quantamental Audit (`SKILL.md`)
Upload the generated `candidates_v4_1_YYYY-MM-DD.csv` into Gemini with the **`pre-earnings-dislocation-auditor`** skill active:
> *"Run the Pre-Earnings Dislocation Auditor on this CSV."*

* **`EXECUTE NOW`:** Total Score $\ge 80/100$ AND `Trigger_Status` is `Day1_Turn` or `Exhaustion_Buy`.
* **`STALK FOR TURN`:** Total Score $\ge 75/100$ AND `Trigger_Status` is `Stabilizing` or `Knife_Wait` (set price alert for next session).
* **`PASS / VETO`:** Total Score $< 75/100$ or negative company-specific catalyst uncovered in Gate 4.

---

## 7. Disclaimer
*This repository and documentation are for quantitative research and educational purposes only. Nothing herein constitutes investment advice or a solicitation to buy or sell securities.*