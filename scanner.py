import io
import os
import re
import time
import warnings

warnings.filterwarnings("ignore")

import urllib3

urllib3.disable_warnings()

import numpy as np
import pandas as pd
import requests
import yfinance as yf

SECTOR_ETF_MAP = {
    "Information Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
}

# Nasdaq-100 Wikipedia sayfası ICB sınıflandırması kullanır -> GICS ana sektörüne çeviri
ICB_TO_GICS_SECTOR = {
    "Technology": "Information Technology",
    "Telecommunications": "Communication Services",
    "Health Care": "Health Care",
    "Financials": "Financials",
    "Real Estate": "Real Estate",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Industrials": "Industrials",
    "Basic Materials": "Materials",
    "Energy": "Energy",
    "Utilities": "Utilities",
}

SCANNER_VERSION = "v4.7"
BELLWETHERS = ["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]
CACHE_FILE = "universe_cache.csv"
CUSTOM_TICKERS_FILE = "custom_tickers.txt"
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NDX_URL = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"


def clean_str(val):
  """NaN, None veya 'nan' metinlerini güvenli şekilde boş stringe çevirir."""
  if pd.isna(val) or val is None:
    return ""
  s = str(val).strip().lower()
  return "" if s in ["nan", "none", "null"] else s


def _has_word(text, words):
  """Kelime başında eşleşme: 'it' -> 'credit' içinde, 'gas' -> 'las vegas' içinde yakalanmaz."""
  return any(re.search(r"\b" + re.escape(w), text) for w in words)


def infer_sector_from_sub(sub_industry):
  """ICB sektörü bulunamayan Nasdaq-100 / özel hisseler için ana GICS sektörünü tahmin eder (yedek)."""
  sub = str(sub_industry).lower()
  # Önce çakışmaya açık özel ifadeler (sıra önemli)
  if _has_word(sub, ["reit", "real estate"]):
    return "Real Estate"
  if _has_word(sub, ["industrial gas", "chemical", "material", "mining", "metal"]):
    return "Materials"
  if _has_word(sub, ["gas utilit", "multi-utilit", "utilit", "water utilit"]):
    return "Utilities"
  if re.search(r"\bit\b", sub) or _has_word(
      sub, ["tech", "software", "semiconductor", "computer", "electronic", "hardware"]
  ):
    return "Information Technology"
  if _has_word(sub, ["health", "biotech", "pharma", "medical", "life sciences"]):
    return "Health Care"
  if _has_word(
      sub,
      ["bank", "financ", "insurance", "investment", "credit", "payment",
       "capital market", "exchange", "asset management"],
  ):
    return "Financials"
  if _has_word(
      sub,
      ["retail", "auto", "travel", "apparel", "restaurant", "hotel", "casino",
       "gaming", "leisure", "consumer discretionary", "e-commerce"],
  ):
    return "Consumer Discretionary"
  if _has_word(sub, ["food", "beverage", "soft drink", "household", "staple", "personal"]):
    return "Consumer Staples"
  if _has_word(
      sub,
      ["industrial", "aerospace", "defense", "machinery", "transport", "rail",
       "electrical"],
  ):
    return "Industrials"
  if _has_word(sub, ["energy", "oil", "gas"]):
    return "Energy"
  if _has_word(sub, ["electric"]):
    return "Utilities"
  return "Communication Services"


def map_subsector_etf(sector, sub_industry):
  sub = str(sub_industry).lower()
  if "semiconductor" in sub:
    return "SMH"
  if (
      "software" in sub
      or "it consulting" in sub
      or "internet services" in sub
      or "data processing" in sub
  ):
    return "IGV"
  if "biotechnology" in sub:
    return "XBI"
  if "bank" in sub or "brokerage" in sub:
    return "KBE"
  if "aerospace" in sub or "defense" in sub:
    return "ITA"
  if "homebuilding" in sub or "building products" in sub:
    return "ITB"
  if sector == "Energy" and ("oil" in sub or "gas" in sub):
    return "XOP"
  if "retail" in sub and sector != "Real Estate":
    return "XRT"
  return SECTOR_ETF_MAP.get(sector, "SPY")


def get_us_universe():
  """3 Katmanlı Evren Yükleyici: Canlı Wikipedia (StringIO) -> Otomatik Cache -> Yerel Yedek."""
  headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
  meta = {}

  # Katman 1: Wikipedia'dan io.StringIO ile güvenli çekim
  try:
    resp = requests.get(SP500_URL, headers=headers, timeout=15)
    sp_df = pd.read_html(io.StringIO(resp.text))[0]
    sp_df["Symbol"] = (
        sp_df["Symbol"].astype(str).str.replace(".", "-", regex=False)
    )
    for _, row in sp_df.iterrows():
      sym = str(row["Symbol"]).strip()
      sec = str(row["GICS Sector"]).strip()
      sub = str(row["GICS Sub-Industry"]).strip()
      meta[sym] = {
          "Sector": sec,
          "Sub_Industry": sub,
          "Sub_ETF": map_subsector_etf(sec, sub),
      }
  except Exception as e:
    print(f"      [!] Wikipedia S&P 500 okuma uyarısı: {e}")

  # Nasdaq-100: bileşen tablosu artık ayrı "List of NASDAQ-100 companies" sayfasında (ICB sınıflandırmalı)
  ndx_added = 0
  try:
    resp_ndx = requests.get(NDX_URL, headers=headers, timeout=15)
    tables = pd.read_html(io.StringIO(resp_ndx.text))
    tbl = next(
        (
            t
            for t in tables
            if ("Ticker" in t.columns or "Symbol" in t.columns) and len(t) >= 90
        ),
        None,
    )
    if tbl is None:
      raise ValueError("bileşen tablosu (Ticker/Symbol, ~100 satır) bulunamadı")
    col = "Ticker" if "Ticker" in tbl.columns else "Symbol"
    ind_col = next((c for c in tbl.columns if "Industry" in str(c)), None)
    sub_col = next(
        (c for c in tbl.columns if "Subsector" in str(c) or "Sub-Industry" in str(c)),
        None,
    )
    for _, row in tbl.iterrows():
      sym = str(row[col]).replace(".", "-").strip().upper()
      if sym in meta or not sym.replace("-", "").isalpha():
        continue
      industry = str(row[ind_col]).strip() if ind_col and pd.notna(row[ind_col]) else ""
      sub = str(row[sub_col]).strip() if sub_col and pd.notna(row[sub_col]) else industry
      sec = ICB_TO_GICS_SECTOR.get(industry) or infer_sector_from_sub(sub)
      meta[sym] = {
          "Sector": sec,
          "Sub_Industry": sub,
          "Sub_ETF": map_subsector_etf(sec, sub),
      }
      ndx_added += 1
  except Exception as e:
    print(f"      [!] Wikipedia Nasdaq-100 okuma uyarısı: {e}")
  if ndx_added == 0:
    print(
        "      [!] Nasdaq-100 listesinden hiç ek hisse eklenmedi (sayfa yapısı"
        " değişmiş olabilir)."
    )

  # Katman 2: Başarılıysa yerel önbelleği (universe_cache.csv) güncelle; başarısızsa önbellekten oku
  if len(meta) >= 400:
    try:
      cache_df = pd.DataFrame.from_dict(meta, orient="index").reset_index()
      cache_df.rename(columns={"index": "Symbol"}, inplace=True)
      cache_df.to_csv(CACHE_FILE, index=False)
    except Exception:
      pass
  elif os.path.exists(CACHE_FILE):
    print(f"      [i] Canlı liste eksik; yerel önbellek ({CACHE_FILE}) yükleniyor...")
    try:
      cache_df = pd.read_csv(CACHE_FILE)
      for _, row in cache_df.iterrows():
        sym = str(row["Symbol"]).strip()
        sec, sub = str(row["Sector"]), str(row["Sub_Industry"])
        meta[sym] = {
            "Sector": sec,
            "Sub_Industry": sub,
            # Eski önbellekteki ETF eşlemesi güncel kurallarla yeniden hesaplanır
            "Sub_ETF": map_subsector_etf(sec, sub),
        }
    except Exception as e:
      print(f"      [!] Önbellek okuma hatası: {e}")

  # Katman 3: İsteğe bağlı custom_tickers.txt varsa ekle
  if os.path.exists(CUSTOM_TICKERS_FILE):
    try:
      with open(CUSTOM_TICKERS_FILE, "r", encoding="utf-8") as f:
        for line in f:
          sym = line.strip().upper().replace(".", "-")
          if sym and sym not in meta and sym.replace("-", "").isalpha():
            meta[sym] = {
                "Sector": "Information Technology",
                "Sub_Industry": "Custom",
                "Sub_ETF": "SPY",
            }
    except Exception:
      pass

  return meta


def drop_phantom_bar(df):
  """Pre-market'te Yahoo'nun eklediği Volume=0 boş günlük mumu atar (VIX gibi hacimsiz seriler hariç)."""
  if "Volume" in df.columns and len(df) > 1:
    v = df["Volume"].fillna(0)
    if float(v.iloc[-1]) == 0 and float(v.iloc[-2]) > 0:
      return df.iloc[:-1]
  return df


def get_market_regime(data):
  try:
    spy_c = drop_phantom_bar(data["SPY"].dropna(subset=["Close"]))["Close"]
    vix_c = data["^VIX"]["Close"].dropna()
    spy_price = float(spy_c.iloc[-1])
    spy_50 = float(spy_c.rolling(50).mean().iloc[-1])
    vix_val = float(vix_c.iloc[-1])

    regime = "GREEN (Risk-On)"
    if vix_val >= 24.0 or spy_price < spy_50 * 0.985:
      regime = "RED (Risk-Off / High Volatility)"
    elif vix_val >= 20.0 or spy_price < spy_50:
      regime = "YELLOW (Choppy / Selective)"
    return regime, vix_val
  except Exception as e:
    print(f"      [!] Piyasa rejimi hesaplanamadı (SPY/^VIX verisi yok): {e}")
    return "UNKNOWN (SPY/VIX data unavailable)", float("nan")


def normalize_ny_dates(idx):
  """DatetimeIndex'i America/New_York zaman dilimine göre normalize edip tz-naive (00:00:00) yapar."""
  dt_idx = pd.to_datetime(idx)
  if dt_idx.tz is None:
    dt_idx = dt_idx.tz_localize(
        "America/New_York", ambiguous="NaT", nonexistent="NaT"
    )
  else:
    dt_idx = dt_idx.tz_convert("America/New_York")
  return dt_idx.tz_localize(None).normalize()


def get_distinct_past_4_quarters(ed_df, today_naive, min_gap_days=35):
  """Aynı çeyreğe ait mükerrer/yakın tarihli satırları filtreleyerek gerçek son 4 çeyreği döndürür."""
  past = (
      ed_df[ed_df.index < today_naive]
      .sort_index(ascending=False)
      .dropna(subset=["Surprise(%)"])
  )
  if past.empty:
    return pd.Series(dtype=float)

  distinct_surprises = []
  last_accepted_date = None
  for dt_idx, row in past.iterrows():
    if (
        last_accepted_date is None
        or (last_accepted_date - dt_idx).days >= min_gap_days
    ):
      distinct_surprises.append(float(row["Surprise(%)"]))
      last_accepted_date = dt_idx
      if len(distinct_surprises) == 4:
        break
  return pd.Series(distinct_surprises)


def fetch_verified_fundamentals(tk, curr_price):
  """tk.info eksik dönerse yedek tablolardan gerçek büyüme ve hedef fiyat verisini çeker."""
  info_dict = {}
  try:
    info_dict = tk.info or {}
  except Exception:
    info_dict = {}

  # 1. Revenue Growth (Önce info, yoksa quarterly_income_stmt üzerinden YoY hesap)
  rev_growth = info_dict.get("revenueGrowth", None)
  if rev_growth is None or pd.isna(rev_growth):
    try:
      q_inc = tk.quarterly_income_stmt
      if q_inc is not None and not q_inc.empty and "Total Revenue" in q_inc.index:
        revs = q_inc.loc["Total Revenue"].dropna()
        if len(revs) >= 5 and float(revs.iloc[4]) > 0:
          rev_growth = (float(revs.iloc[0]) / float(revs.iloc[4])) - 1.0
    except Exception:
      rev_growth = None

  # 2. Target Mean Price (Önce info, yoksa analyst_price_targets)
  target_price = info_dict.get("targetMeanPrice", None)
  if target_price is None or pd.isna(target_price) or float(target_price) <= 0:
    try:
      apt = tk.analyst_price_targets
      if isinstance(apt, dict) and apt.get("mean"):
        target_price = float(apt.get("mean"))
    except Exception:
      target_price = None

  if rev_growth is None or pd.isna(rev_growth):
    return None, None
  if target_price is None or pd.isna(target_price) or float(target_price) <= 0:
    return None, None

  rev_growth_pct = round(float(rev_growth) * 100, 1)
  target_upside_pct = round(((float(target_price) / curr_price) - 1.0) * 100, 1)
  return rev_growth_pct, target_upside_pct


def get_bellwether_earnings(today_naive):
  bw_dates = {}
  for bw in BELLWETHERS:
    try:
      ed = yf.Ticker(bw).get_earnings_dates(limit=8)
      if ed is not None and not ed.empty:
        ed = ed.copy()
        ed.index = normalize_ny_dates(ed.index)
        future = ed[ed.index >= today_naive].sort_index(ascending=True)
        if not future.empty:
          bw_dates[bw] = future.index[0]
    except Exception:
      continue
  return bw_dates


def evaluate_analyst_21d(tk, today_naive, curr_price, target_upside_pct):
  """Büyüklüğe duyarlı (Magnitude-Weighted) ve kurum bazında netleştirilmiş 21D analist puanlaması."""
  try:
    try:
      ud = tk.upgrades_downgrades
    except Exception as e:
      # yfinance hiç geçmiş olmayan hisse için istisna fırlatır -> bu bir hata değil, sessizlik
      if "no upgrade/downgrade history" in str(e).lower():
        return 0, "Quiet"
      raise
    if ud is None or ud.empty:
      return 0, "Quiet"

    ud = ud.copy()
    ud.index = pd.to_datetime(ud.index)
    # yfinance GradeDate'i tz-naive UTC verir -> New York gününe çevir
    if ud.index.tz is None:
      ud.index = ud.index.tz_localize("UTC")
    ud.index = ud.index.tz_convert("America/New_York").tz_localize(None)
    cutoff = today_naive - pd.Timedelta(days=21)
    recent = ud[ud.index >= cutoff].sort_index(ascending=False)
    if recent.empty:
      return 0, "Quiet"

    buy_words = [
        "buy",
        "outperform",
        "overweight",
        "strong",
        "positive",
        "add",
        "accumulate",
        "top pick",
    ]
    sell_words = [
        "sell",
        "underperform",
        "underweight",
        "reduce",
        "negative",
    ]
    hold_words = [
        "neutral",
        "hold",
        "equal-weight",
        "equal weight",
        "market perform",
        "sector perform",
        "in-line",
        "inline",
        "peer perform",
        "sector weight",
        "market weight",
    ]
    # Alt-string olarak aranamayacak notlar ("perform" -> "outperform" içinde de geçer)
    hold_exact = {"perform", "mixed"}

    seen_firms = set()
    net_score = 0
    has_severe_bear = False
    events = []  # (event_pts, note)

    for i, (_, r) in enumerate(recent.iterrows()):
      firm_raw = clean_str(r.get("Firm"))
      firm = firm_raw.title()[:10].strip() if firm_raw else "Firm"
      # Tekilleştirme tam kurum adıyla; isimsiz satırlar birbirini ezmez
      firm_key = firm_raw if firm_raw else f"_unnamed_{i}"
      if firm_key in seen_firms:
        continue
      seen_firms.add(firm_key)

      act = clean_str(r.get("Action"))
      to_g = clean_str(r.get("ToGrade"))
      from_g = clean_str(r.get("FromGrade"))
      cur_pt = pd.to_numeric(r.get("currentPriceTarget", np.nan), errors="coerce")
      pri_pt = pd.to_numeric(r.get("priorPriceTarget", np.nan), errors="coerce")
      # Yahoo hedef verilmeyen satırlarda 0 yazar -> eksik veri say (sahte -%100 kesinti olmasın)
      if pd.notna(cur_pt) and cur_pt <= 0:
        cur_pt = np.nan

      active_grade = to_g if to_g else from_g
      is_hold = active_grade in hold_exact or any(
          w in active_grade for w in hold_words
      )
      is_buy = (not is_hold) and (
          any(w in active_grade for w in buy_words)
          or (act == "main" and active_grade == "" and target_upside_pct >= 15.0)
      )
      is_sell = any(w in active_grade for w in sell_words)

      event_pts = 0
      note = None
      if "down" in act or is_sell:
        event_pts = -7
        has_severe_bear = True
        # Gerçek not düşürme ile mevcut Sell/Underweight notunun teyidi ayrı etiketlenir
        note = f"Downgrade({firm})" if "down" in act else f"Sell_Rating({firm})"
      elif pd.notna(cur_pt) and pd.notna(pri_pt) and pri_pt > 0:
        pt_chg_pct = ((cur_pt - pri_pt) / pri_pt) * 100.0
        if cur_pt < pri_pt:
          if is_buy and (cur_pt >= curr_price * 1.10):
            if pt_chg_pct >= -5.0:
              event_pts = -1
            elif pt_chg_pct >= -12.0:
              event_pts = -3
            else:
              event_pts = -5
            note = f"PT_Trim_Buy({firm}:${int(pri_pt)}->${int(cur_pt)}[{pt_chg_pct:.0f}%])"
          else:
            event_pts = -7 if pt_chg_pct <= -10.0 else -5
            has_severe_bear = True
            note = f"PT_Cut_Hold({firm}:${int(pri_pt)}->${int(cur_pt)}[{pt_chg_pct:.0f}%])"
        elif cur_pt > pri_pt:
          if pt_chg_pct >= 10.0:
            event_pts = 4
          elif pt_chg_pct >= 3.0:
            event_pts = 3
          else:
            event_pts = 1
          note = f"PT_Hike({firm}:${int(pri_pt)}->${int(cur_pt)}[+{pt_chg_pct:.0f}%])"
      elif "up" in act or ("init" in act and is_buy):
        event_pts = 3
        note = f"Upgrade({firm})" if "up" in act else f"Init_Buy({firm})"

      net_score += event_pts
      if note:
        events.append((event_pts, note))

    if not events:
      return 0, "Maintained"

    if has_severe_bear:
      final_mod = max(-7, min(-3, net_score))
    else:
      final_mod = max(-7, min(3, net_score))

    # Önce olumsuz olaylar (en sert önce), sonra olumlu olaylar -> skoru düşüren olay asla gizlenmez
    negatives = sorted([e for e in events if e[0] < 0], key=lambda e: e[0])
    positives = sorted([e for e in events if e[0] >= 0], key=lambda e: -e[0])
    ordered = [n for _, n in negatives + positives]
    shown = ordered[:3]
    if len(ordered) > 3:
      shown.append(f"+{len(ordered) - 3} more")
    return final_mod, "; ".join(shown)
  except Exception as e:
    return 0, f"Error({type(e).__name__})"


def compute_setup_score_breakdown(row, analyst_mod):
  """Returns (P1_Tech_24, P2_SecFlow_22, P3_Fund_24, Setup_Score_70)."""
  v50, v100 = row["Vs_50SMA_%"], row["Vs_100SMA_%"]
  if v50 >= -3.5 and v100 >= -2.5:
    sma_pts = 12
  elif v100 >= -5.5 and v50 >= -7.0:
    sma_pts = 9
  elif v100 >= -7.0 or v50 >= -9.0:
    sma_pts = 6
  else:
    sma_pts = 3

  up = row["Upside_20D_High_%"]
  if up >= 18.0:
    up_pts = 12
  elif up >= 12.0:
    up_pts = 9
  elif up >= 8.5:
    up_pts = 6
  else:
    up_pts = 3
  p1_tech = sma_pts + up_pts

  sub_ret, vs_sub = row["SubETF_10D_%"], row["Vs_SubETF_10D_%"]
  if sub_ret > -5.0 and -7.0 <= vs_sub <= -0.5:
    sec_pts = 12
  elif sub_ret <= -8.0 and (v50 >= -3.5 or v100 >= -2.5):
    sec_pts = 10
  elif sub_ret > -9.0 and -9.0 <= vs_sub <= 1.0:
    sec_pts = 8
  else:
    sec_pts = 5

  flow = row["Inst_Footprint"]
  flow_pts = (
      10
      if flow == "Accumulating"
      else (8 if flow == "Quiet_DryUp" else (5 if flow == "Neutral" else 2))
  )
  p2_secflow = sec_pts + flow_pts

  beats_pts = 8 if row["Beats_4Q"] == "4/4" else 4
  surp_pts = (
      4
      if row["Avg_Surp_%"] >= 10.0
      else (3 if row["Avg_Surp_%"] >= 5.0 else 2)
  )

  rg = row["Rev_Growth_%"]
  rev_pts = (
      6
      if rg >= 25.0
      else (5 if rg >= 15.0 else (3 if rg >= 8.0 else 1))
  )

  tu = row["Target_Upside_%"]
  pt_pts = 6 if tu >= 20.0 else (4 if tu >= 12.0 else 2)
  p3_fund_base = beats_pts + surp_pts + rev_pts + pt_pts

  total_70 = min(70, max(0, p1_tech + p2_secflow + p3_fund_base + analyst_mod))
  return p1_tech, p2_secflow, p3_fund_base, total_70


def run_scanner(
    min_drop=-0.22,
    max_drop=-0.04,
    max_rsi=48,
    min_beats=3,
):
  today_naive = (
      pd.Timestamp.now(tz="America/New_York").tz_localize(None).normalize()
  )
  today_str = today_naive.strftime("%Y-%m-%d")
  print(
      f"=== US PRE-EARNINGS DISLOCATION SCANNER {SCANNER_VERSION} ({today_str}) ==="
  )

  now_ny = pd.Timestamp.now(tz="America/New_York")
  ny_minutes = now_ny.hour * 60 + now_ny.minute
  if now_ny.weekday() < 5 and 570 <= ny_minutes < 960:
    print(
        "      [!] Piyasa şu an açık (09:30-16:00 ET): bugünün mumu henüz"
        " tamamlanmadı; RSI/Trigger/CMF kısmi gün verisiyle hesaplanır."
        " En temiz sonuç için pre-market veya kapanış sonrası çalıştırın."
    )

  universe = get_us_universe()
  tickers = list(universe.keys())
  sub_etfs = list(set(info["Sub_ETF"] for info in universe.values()))
  all_etfs = list(
      set(sub_etfs + list(SECTOR_ETF_MAP.values()) + ["SPY", "QQQ", "^VIX"])
  )
  all_symbols = list(set(tickers + all_etfs))

  print(
      f"[1/3] Downloading price data & macro indicators for {len(tickers)}"
      " stocks..."
  )
  data = yf.download(
      all_symbols,
      period="1y",
      interval="1d",
      group_by="ticker",
      progress=False,
      threads=True,
  )

  # --- FAILED TICKERS SEQUENTIAL RETRY ---
  failed_tickers = list(getattr(yf.shared, "_ERRORS", {}).keys())
  if failed_tickers:
    print(
        f"      -> {len(failed_tickers)} hisse ilk denemede düşmedi, tek tek"
        f" tekrar çekiliyor: {failed_tickers}"
    )
    time.sleep(2)
    retry_data = yf.download(
        failed_tickers,
        period="1y",
        interval="1d",
        group_by="ticker",
        threads=False,
        progress=False,
    )
    recovered = []
    if retry_data is not None and not retry_data.empty:
      # yfinance 1.x tek hisse için de (Ticker, Price) MultiIndex döndürür
      is_multi = isinstance(retry_data.columns, pd.MultiIndex)
      for t in failed_tickers:
        try:
          if is_multi:
            if t not in retry_data.columns.get_level_values(0):
              continue
            sub = retry_data[t]
          else:
            sub = retry_data
          sub = sub.reindex(data.index)
          if "Close" not in sub.columns or sub["Close"].notna().sum() == 0:
            continue
          # Kolon kolon yaz: hem mevcut (NaN) hem de hiç olmayan ticker için çalışır
          for col in sub.columns:
            data[(t, col)] = sub[col]
          recovered.append(t)
        except Exception as e:
          print(f"      [!] {t} tekrar verisi yazılamadı: {e}")
    print(
        f"      -> Tekrar denemede kurtarılan: {len(recovered)}/{len(failed_tickers)}"
        + (f" {recovered}" if recovered else "")
    )

  market_regime, vix_val = get_market_regime(data)
  print(f"      Macro Market Regime: {market_regime} (^VIX: {vix_val:.1f})")

  etf_10d_ret = {}
  for etf in all_etfs:
    try:
      # Hisse tarafındaki pre-market boş mum temizliğinin aynısı (10G getiriler aynı güne bitsin)
      c = drop_phantom_bar(data[etf].dropna(subset=["Close"]))["Close"]
      etf_10d_ret[etf] = (float(c.iloc[-1]) / float(c.iloc[-11])) - 1.0
    except Exception:
      etf_10d_ret[etf] = 0.0

  pullbacks = []
  tech_errors = []
  for t in tickers:
    try:
      if t not in data:
        continue
      df = data[t].dropna(subset=["Close", "High", "Low", "Open"]).copy()
      if len(df) < 200:
        continue
      df["Volume"] = df["Volume"].fillna(0)

      if float(df["Volume"].iloc[-1]) == 0 and len(df) > 201:
        df = df.iloc[:-1]

      close, open_p, high, low, vol = (
          df["Close"],
          df["Open"],
          df["High"],
          df["Low"],
          df["Volume"],
      )
      curr_price = float(close.iloc[-1])
      prev_price = float(close.iloc[-2])

      sma_50 = float(close.rolling(50).mean().iloc[-1])
      sma_100 = float(close.rolling(100).mean().iloc[-1])
      sma_200 = float(close.rolling(200).mean().iloc[-1])

      ret_10d = (curr_price / float(close.iloc[-11])) - 1.0
      ret_20d = (curr_price / float(close.iloc[-21])) - 1.0
      prev_ret_10d = (prev_price / float(close.iloc[-12])) - 1.0
      high_20d = float(high.iloc[-20:].max())
      upside_to_high = ((high_20d / curr_price) - 1.0) * 100

      tr = pd.concat(
          [
              high - low,
              (high - close.shift()).abs(),
              (low - close.shift()).abs(),
          ],
          axis=1,
      ).max(axis=1)
      atr_14 = float(tr.rolling(14).mean().iloc[-1])
      atr_pct = (atr_14 / curr_price) * 100
      if atr_pct < 1.6:
        continue

      delta = close.diff()
      gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
      loss = (
          (-delta.clip(upper=0))
          .ewm(alpha=1 / 14, adjust=False)
          .mean()
          .replace(0, 1e-10)
      )
      rs = gain / loss
      rsi_14 = float(100 - (100 / (1 + rs.iloc[-1])))

      vs_50 = ((curr_price / sma_50) - 1.0) * 100
      in_pullback = (
          (min_drop <= ret_20d <= max_drop)
          or (min_drop <= ret_10d <= max_drop)
          or (min_drop <= prev_ret_10d <= -0.06 and ret_10d <= -0.02)
      )
      if not (
          (curr_price > sma_200)
          and (-10.0 <= vs_50 <= 4.0)
          and in_pullback
          and (rsi_14 <= max_rsi)
          and (upside_to_high >= 6.0)
      ):
        continue

      vol_5d = float(vol.iloc[-5:].mean())
      vol_20d = (
          float(vol.iloc[-25:-5].mean()) if len(vol) >= 25 else float(vol.mean())
      )
      vol_ratio = vol_5d / vol_20d if vol_20d > 0 else 1.0

      hl_range = (high - low).replace(0, np.nan)
      mfm = ((close - low) - (high - close)) / hl_range
      mfv = mfm.fillna(0) * vol
      vol_10d_sum = float(vol.iloc[-10:].sum())
      cmf_10d = (
          float(mfv.iloc[-10:].sum() / vol_10d_sum) if vol_10d_sum > 0 else 0.0
      )

      if cmf_10d > 0.08:
        inst_footprint = "Accumulating"
      elif vol_ratio <= 0.92 and cmf_10d >= -0.15:
        inst_footprint = "Quiet_DryUp"
      elif cmf_10d < -0.18 and vol_ratio >= 1.25:
        inst_footprint = "Dumping"
      else:
        inst_footprint = "Neutral"

      c_today, o_today, h_today, l_today = (
          float(close.iloc[-1]),
          float(open_p.iloc[-1]),
          float(high.iloc[-1]),
          float(low.iloc[-1]),
      )
      c_prev, l_prev = float(close.iloc[-2]), float(low.iloc[-2])
      day_range_pos = (
          (c_today - l_today) / (h_today - l_today)
          if (h_today - l_today) > 0
          else 0.5
      )
      mfm_today = float(mfm.iloc[-1]) if pd.notna(mfm.iloc[-1]) else 0.0

      if (
          c_today > o_today
          and c_today > c_prev
          and inst_footprint != "Dumping"
      ):
        trigger_status = "Day1_Turn"
      elif (
          day_range_pos >= 0.48
          and mfm_today > 0
          and inst_footprint != "Dumping"
          and (l_today >= l_prev * 0.995 or c_today >= sma_50 * 0.98)
      ):
        trigger_status = "Exhaustion_Buy"
      elif l_today >= l_prev:
        trigger_status = "Stabilizing"
      else:
        trigger_status = "Knife_Wait"

      hard_stop = round(curr_price - (1.5 * atr_14), 2)
      early_target = round(curr_price + (0.75 * (high_20d - curr_price)), 2)
      risk_pct = round(((curr_price - hard_stop) / curr_price) * 100, 2)
      reward_pct = round(((early_target - curr_price) / curr_price) * 100, 2)
      rr_ratio = round(reward_pct / risk_pct, 2) if risk_pct > 0 else 0.0

      info = universe[t]
      sub_etf = info["Sub_ETF"]
      sub_10d = etf_10d_ret.get(sub_etf, 0.0)

      pullbacks.append({
          "Ticker": t,
          "Sub_ETF": sub_etf,
          "Price": round(curr_price, 2),
          "ATR_%": round(atr_pct, 1),
          "10D_Ret_%": round(ret_10d * 100, 2),
          "SubETF_10D_%": round(sub_10d * 100, 2),
          "Vs_SubETF_10D_%": round((ret_10d - sub_10d) * 100, 2),
          "RSI_14": round(rsi_14, 1),
          "Vs_50SMA_%": round(vs_50, 1),
          "Vs_100SMA_%": round(((curr_price / sma_100) - 1.0) * 100, 1),
          "Upside_20D_High_%": round(upside_to_high, 1),
          "Vol_Ratio_5D": round(vol_ratio, 2),
          "CMF_10D": round(cmf_10d, 2),
          "Inst_Footprint": inst_footprint,
          "Trigger_Status": trigger_status,
          "Hard_Stop_Price": hard_stop,
          "Early_Target_Price": early_target,
          "Risk_%": risk_pct,
          "Reward_%": reward_pct,
          "RR_Ratio": rr_ratio,
      })
    except Exception as e:
      tech_errors.append(f"{t}({type(e).__name__})")
      continue

  if tech_errors:
    print(
        f"      [!] Teknik hesaplamada hata veren {len(tech_errors)} hisse"
        f" atlandı: {', '.join(tech_errors[:15])}"
        + (" ..." if len(tech_errors) > 15 else "")
    )
  print(
      f"[2/3] {len(pullbacks)} passed technicals. Auditing Earnings, Revenue"
      " Growth, Bellwethers & 21D Analyst Actions..."
  )
  bw_dates = get_bellwether_earnings(today_naive)
  bw_missing = [bw for bw in BELLWETHERS if bw not in bw_dates]
  if bw_missing:
    print(
        "      [!] Bellwether bilanço tarihi alınamadı: "
        f"{', '.join(bw_missing)} -> çakışma yoksa BW_Overlap 'Unverified' yazılır."
    )
  candidates = []

  drop_stats = {
      "er_window": 0,
      "beats_surp": 0,
      "eps_cut": 0,
      "fund_target": 0,
      "api_err": 0,
  }
  er_debug_notes = []

  for row in pullbacks:
    t = row["Ticker"]
    try:
      tk = yf.Ticker(t)
      time.sleep(0.15)  # Yahoo rate-limit koruması

      # AŞAMA 2A: Bilanço penceresi ve 4 ayrı çeyrek beat kontrolü
      ed = tk.get_earnings_dates(limit=16)
      if ed is None or ed.empty:
        drop_stats["er_window"] += 1
        er_debug_notes.append(f"{t}(NoData)")
        continue

      ed = ed.copy()
      ed.index = normalize_ny_dates(ed.index)

      future_er = ed[ed.index >= today_naive].sort_index(ascending=True)
      if future_er.empty:
        drop_stats["er_window"] += 1
        er_debug_notes.append(f"{t}(NoFutureER)")
        continue
      next_er = future_er.index[0]
      next_er_str = next_er.strftime("%Y-%m-%d")

      # Sadece hafta sonlarını düşen standart iş günü hesabı (Bilançodan 3 iş günü önce çıkış: T-3)
      planned_exit_bday = pd.bdate_range(end=next_er, periods=4, freq="B")[
          0
      ].normalize()
      exit_str = planned_exit_bday.strftime("%Y-%m-%d")

      # Çıkış günü kapanışına kadar elde tutulan toplam işlem günü (bugün/giriş günü dahil +1)
      hold_trading_days = int(np.busday_count(today_str, exit_str)) + 1
      if not (4 <= hold_trading_days <= 21):
        drop_stats["er_window"] += 1
        er_debug_notes.append(f"{t}(ER:{next_er_str},Hold:{hold_trading_days}d)")
        continue

      # En az 35 gün aralıklı gerçek son 4 çeyreği seç (Duplicate date korumalı)
      last_4 = get_distinct_past_4_quarters(ed, today_naive, min_gap_days=35)
      if len(last_4) < 4:
        drop_stats["beats_surp"] += 1
        continue
      beats = int((last_4 > 0).sum())
      avg_surp = round(float(last_4.mean()), 2)
      if beats < min_beats or avg_surp > 200.0:
        drop_stats["beats_surp"] += 1
        continue

      # AŞAMA 2B: Derin temel veri & analist revizyon kontrolü
      time.sleep(0.15)

      eps_cut = False
      try:
        trend = tk.eps_trend
        if trend is not None and not trend.empty and "0q" in trend.index:
          diff = trend.loc["0q", "current"] - trend.loc["0q", "30daysAgo"]
          if pd.notna(diff) and diff < -0.001:
            eps_cut = True
      except Exception:
        pass
      if eps_cut:
        drop_stats["eps_cut"] += 1
        continue

      rev_growth_pct, target_upside = fetch_verified_fundamentals(
          tk, row["Price"]
      )
      if rev_growth_pct is None or target_upside is None:
        drop_stats["fund_target"] += 1
        continue
      if rev_growth_pct <= 0.0 or target_upside < 5.0:
        drop_stats["fund_target"] += 1
        continue

      analyst_mod, analyst_note = evaluate_analyst_21d(
          tk, today_naive, row["Price"], target_upside
      )

      bw_overlap = [
          f"{bw}({dt_bw.strftime('%m/%d')})"
          for bw, dt_bw in bw_dates.items()
          if today_naive <= dt_bw <= planned_exit_bday and bw != t
      ]

      row["Rev_Growth_%"] = rev_growth_pct
      row["Target_Upside_%"] = target_upside
      row["Analyst_21D"] = analyst_note
      row["Earnings_Date"] = next_er_str
      row["Hold_Days"] = hold_trading_days
      row["Exit_Date"] = exit_str
      if bw_overlap:
        row["BW_Overlap"] = ", ".join(bw_overlap[:3])
      elif bw_missing:
        row["BW_Overlap"] = f"Unverified(no data: {'/'.join(bw_missing)})"
      else:
        row["BW_Overlap"] = "Clear"
      row["Beats_4Q"] = f"{beats}/4"
      row["Avg_Surp_%"] = avg_surp

      p1, p2, p3, total_70 = compute_setup_score_breakdown(row, analyst_mod)
      row["P1_Tech_24"] = p1
      row["P2_SecFlow_22"] = p2
      row["P3_Fund_24"] = p3
      row["Analyst_Mod"] = analyst_mod
      row["Setup_Score_70"] = total_70

      candidates.append(row)
    except Exception:
      drop_stats["api_err"] += 1
      continue

  print(
      "      Filter Breakdown -> ER Window:"
      f" -{drop_stats['er_window']} | Beats/Surp: -{drop_stats['beats_surp']} |"
      f" EPS Cut: -{drop_stats['eps_cut']} | Growth/Target:"
      f" -{drop_stats['fund_target']} | API Err: -{drop_stats['api_err']}"
  )
  if er_debug_notes:
    print(f"      [i] ER Window Drops: {', '.join(er_debug_notes)}")

  res_df = pd.DataFrame(candidates)
  if not res_df.empty:
    res_df = res_df.sort_values(
        by=["Setup_Score_70", "Hold_Days"], ascending=[False, True]
    )
    filename = (
        f"candidates_{SCANNER_VERSION.replace('.', '_')}_{today_str}.csv"
    )
    res_df.to_csv(filename, index=False)
    print(
        f"[3/3] Saved {len(res_df)} institutional-grade setups to {filename}\n"
    )
    display_cols = [
        "Ticker",
        "Sub_ETF",
        "Price",
        "10D_Ret_%",
        "RSI_14",
        "Inst_Footprint",
        "Trigger_Status",
        "Hold_Days",
        "Exit_Date",
        "BW_Overlap",
        "RR_Ratio",
        "Analyst_21D",
        "Setup_Score_70",
    ]
    print(res_df[display_cols].to_string(index=False))
    if not market_regime.startswith("GREEN"):
      print(
          f"\n[!] Macro Regime: {market_regime} — rejim filtrelemeye/puana"
          " dahil değildir; pozisyon boyutunu buna göre ayarlayın."
      )
  else:
    print(
        f"\nNo candidates passed the {SCANNER_VERSION} filters today (Macro"
        f" Regime: {market_regime})."
    )


if __name__ == "__main__":
  run_scanner()

# scanner v4.6 - Latest: 14 days to 21 days update.
# scanner v4.7 - Stress-test fixes:
#   - Nasdaq-100 source moved to "List of NASDAQ-100 companies" (ICB -> GICS); the old
#     page had no constituent table, so ARM/ASML/MELI/PDD/SHOP etc. were never scanned.
#   - Sub-ETF mapping: gas/oil -> XOP only for Energy (Industrial Gases -> XLB, Gas
#     Utilities -> XLU); Retail REITs -> XLRE; Financial Exchanges -> XLF; Pharma and
#     Life Sciences Tools -> XLV (only Biotechnology -> XBI). Cached Sub_ETF recomputed.
#   - infer_sector_from_sub uses word-start matching ("credit" no longer = IT).
#   - Failed-ticker retry now actually writes data back (single ticker was a silent no-op).
#   - Analyst_21D: negative events listed first (+N more), standing Sell/Underweight
#     labelled Sell_Rating instead of Downgrade, PT=0 treated as missing, firm dedupe on
#     full name, added Accumulate/Top Pick/Sector Weight/Market Weight/Perform/Mixed,
#     grade dates converted UTC -> New York, fetch errors shown as "Error" not "Quiet".
#   - Silent failures now visible: regime UNKNOWN instead of fake GREEN/16, BW_Overlap
#     "Unverified" when bellwether dates missing, technical-loop errors listed.
#   - ETF/SPY 10D returns drop the same pre-market zero-volume candle as stocks.
#   - Warning when run during market hours (partial daily candle).
#   - 20D high now uses 20 bars (was 21). Version in banner/filename/messages = v4.7.
#   - Not changed by design: exit dates skip weekends only (holidays handled manually).