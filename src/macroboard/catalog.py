"""Canonical series catalog — bottom-up.

Three declared layers, each derived only from the one below:

  RAW        L0  what a provider gives us, untouched
  DERIVED    L1  single-series transforms
  BREADTH    L1  aggregates built from a *panel* of many components
                 (trimmed mean, diffusion) — analytical, still one number
  COMPOSITES L2  weighted aggregates across L1/L0, defined in
                 `composite_input` so an aggregate is auditable

The board shows L2. L0/L1 exist so the aggregates can be rebuilt, drilled
into and argued with — and so that no single index has to occupy a whole row
of the dashboard on its own.

Only keyless, verified endpoints are used: DBnomics, Yahoo, the OECD SDMX
API. FRED and the BLS direct APIs refuse this host.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# L0 — raw series
# ---------------------------------------------------------------------------

RAW: list[dict] = [
    # ---------------- Policy and the nominal curve --------------------
    dict(series_id="us.rates.effr", title="Effective Federal Funds Rate", short_title="EFFR",
         layer="raw", group_id="rates", unit="pct", frequency="D", coverage="1954-07",
         source="dbnomics", provider="FED", dataset="H15", series_code="RIFSPFF_N.D",
         question="Where is the policy rate?",
         method_note="Overnight federal funds effective rate, H.15."),
    dict(series_id="us.rates.ust3m", title="3-Month Treasury", short_title="UST 3M",
         layer="raw", group_id="rates", unit="pct", frequency="D", coverage="1981-09",
         source="dbnomics", provider="FED", dataset="H15", series_code="RIFLGFCM03_N.B",
         question="What policy path is priced over one quarter?",
         method_note="Constant-maturity 3M bill, secondary market."),
    dict(series_id="us.rates.ust2y", title="2-Year Treasury", short_title="UST 2Y",
         layer="raw", group_id="rates", unit="pct", frequency="D", coverage="1976-06",
         source="dbnomics", provider="FED", dataset="H15", series_code="RIFLGFCY02_N.B",
         question="What policy path is priced over two years?",
         method_note="Constant-maturity 2Y note."),
    dict(series_id="us.rates.ust5y", title="5-Year Treasury", short_title="UST 5Y",
         layer="raw", group_id="rates", unit="pct", frequency="D", coverage="1962-01",
         source="dbnomics", provider="FED", dataset="H15", series_code="RIFLGFCY05_N.B",
         question="Where is the belly of the curve?",
         method_note="Constant-maturity 5Y note."),
    dict(series_id="us.rates.ust10y", title="10-Year Treasury", short_title="UST 10Y",
         layer="raw", group_id="rates", unit="pct", frequency="D", coverage="1962-01",
         source="dbnomics", provider="FED", dataset="H15", series_code="RIFLGFCY10_N.B",
         question="What growth and inflation path is priced?",
         method_note="Constant-maturity 10Y note."),
    dict(series_id="us.rates.ust30y", title="30-Year Treasury", short_title="UST 30Y",
         layer="raw", group_id="rates", unit="pct", frequency="D", coverage="1977-02",
         source="dbnomics", provider="FED", dataset="H15", series_code="RIFLGFCY30_N.B",
         question="What long-run term premium is priced?",
         method_note="Constant-maturity 30Y bond."),

    # ---------------- Real rates and inflation pricing ----------------
    dict(series_id="us.rates.real10y", title="10Y TIPS Real Yield", short_title="Real 10Y",
         layer="raw", group_id="real", unit="pct", frequency="D", coverage="2003-01",
         source="dbnomics", provider="FED", dataset="H15", series_code="RIFLGFCY10_XII_N.B",
         question="What is the real cost of capital?",
         method_note="10Y constant-maturity inflation-indexed Treasury."),
    dict(series_id="us.rates.tips10y", title="10Y TIPS Par Yield (GSW)", short_title="TIPS 10Y",
         layer="raw", group_id="real", unit="pct", frequency="D", coverage="1999-01",
         source="dbnomics", provider="FED", dataset="TIPS", series_code="TIPSPY10",
         question="What does the market pay for real duration?",
         method_note="GSW-fitted par real yield from the TIPS curve. Lags H.15 by ~4 business days."),
    dict(series_id="us.infl.be5y", title="5Y Breakeven Inflation", short_title="BE 5Y",
         layer="raw", group_id="real", unit="pct", frequency="D", coverage="1999-01",
         source="dbnomics", provider="FED", dataset="TIPS", series_code="BKEVEN05",
         question="What inflation is priced over five years?",
         method_note="Zero-coupon inflation compensation, 5Y."),
    dict(series_id="us.infl.be10y", title="10Y Breakeven Inflation", short_title="BE 10Y",
         layer="raw", group_id="real", unit="pct", frequency="D", coverage="1999-01",
         source="dbnomics", provider="FED", dataset="TIPS", series_code="BKEVEN10",
         question="What inflation is priced over ten years?",
         method_note="Zero-coupon inflation compensation, 10Y."),

    # ---------------- Prices -----------------------------------------
    dict(series_id="us.prices.pce_core", title="Core PCE Price Index", short_title="Core PCE",
         layer="raw", group_id="inflation", unit="idx", frequency="M", coverage="1959-01",
         source="dbnomics", provider="BEA", dataset="NIPA-T20804", series_code="DPCCRG-M",
         question="What inflation does the Fed actually target?",
         method_note="PCE excluding food and energy, index 2017=100."),
    dict(series_id="us.prices.pce", title="PCE Price Index", short_title="PCE",
         layer="raw", group_id="inflation", unit="idx", frequency="M", coverage="1959-01",
         source="dbnomics", provider="BEA", dataset="NIPA-T20804", series_code="DPCERG-M",
         question="What is headline consumer inflation?",
         method_note="PCE all items, index 2017=100."),
    dict(series_id="us.prices.cpi_yoy", title="CPI Inflation (YoY)", short_title="CPI YoY",
         layer="raw", group_id="inflation", unit="pct", frequency="M", coverage="1990-01",
         source="oecd", provider="OECD.SDD.TPS", dataset="DSD_PRICES@DF_PRICES_ALL",
         dataset_version="1.0", series_code="USA.M.N.CPI.PA._T.N.GY",
         question="What does the public actually experience as inflation?",
         method_note="OECD harmonised CPI, all items, year-on-year percent."),

    # ---------------- Activity ---------------------------------------
    dict(series_id="us.growth.gdp_level", title="Real GDP (chained 2017$)", short_title="GDP",
         layer="raw", group_id="growth", unit="usd_m", frequency="Q", coverage="1947-Q1",
         source="dbnomics", provider="BEA", dataset="NIPA-T10106", series_code="A191RX-Q",
         question="What is the level of output?",
         method_note="BEA real GDP, millions of chained 2017 dollars, SAAR."),
    dict(series_id="us.growth.ip", title="Industrial Production Index", short_title="IP",
         layer="raw", group_id="growth", unit="idx", frequency="M", coverage="1919-01",
         source="dbnomics", provider="FED", dataset="G17_IP_MAJOR_INDUSTRY_GROUPS",
         series_code="IP.B50001.S",
         question="Is the goods economy expanding?",
         method_note="Total industrial production, seasonally adjusted, index 2017=100."),
    dict(series_id="us.growth.cli", title="Composite Leading Indicator", short_title="CLI",
         layer="raw", group_id="growth", unit="idx", frequency="M", coverage="1960-01",
         source="oecd", provider="OECD.SDD.STES", dataset="DSD_STES@DF_CLI",
         dataset_version="4.1", series_code="USA.M.LI...AA...H",
         question="Is the cycle turning before it shows up in GDP?",
         method_note="OECD amplitude-adjusted CLI, long-term average = 100."),

    # ---------------- Labour -----------------------------------------
    dict(series_id="us.labor.unrate", title="Unemployment Rate", short_title="U-3",
         layer="raw", group_id="labor", unit="pct", frequency="M", coverage="1955-01",
         source="oecd", provider="OECD.SDD.TPS", dataset="DSD_LFS@DF_IALFS_UNE_M",
         dataset_version="1.0", series_code="USA..._Z.Y._T.Y_GE15..",
         question="How much slack is there in the labour market?",
         method_note="OECD harmonised unemployment rate, 15+, seasonally adjusted."),

    # ---------------- Market -----------------------------------------
    dict(series_id="us.market.spx", title="S&P 500", short_title="SPX",
         layer="raw", group_id="market", unit="idx", frequency="D", coverage="1996-10",
         source="yahoo", provider="YAHOO", dataset="chart", series_code="^GSPC",
         question="What is the market's read on the cycle?",
         method_note="S&P 500 daily close."),
    dict(series_id="us.market.vix", title="VIX", short_title="VIX",
         layer="raw", group_id="market", unit="idx", frequency="D", coverage="1996-10",
         source="yahoo", provider="YAHOO", dataset="chart", series_code="^VIX",
         question="How much macro uncertainty is priced?",
         method_note="CBOE 30-day implied volatility of the S&P 500."),
]

# ---------------------------------------------------------------------------
# L1a — single-series transforms
# ---------------------------------------------------------------------------

DERIVED: list[dict] = [
    dict(series_id="us.curve.10y2y", title="10Y - 2Y Spread", short_title="10Y-2Y",
         layer="derived", group_id="curve", unit="bp", frequency="D",
         question="Is the curve inverted, and for how long?",
         method_note="UST 10Y minus 2Y, basis points."),
    dict(series_id="us.curve.10y3m", title="10Y - 3M Spread", short_title="10Y-3M",
         layer="derived", group_id="curve", unit="bp", frequency="D",
         question="Is the near-term curve inverted?",
         method_note="UST 10Y minus 3M, basis points. The classic recession signal."),
    dict(series_id="us.curve.5y2y", title="5Y - 2Y Spread", short_title="5Y-2Y",
         layer="derived", group_id="curve", unit="bp", frequency="D",
         question="Is the market pricing a faster or slower path?",
         method_note="UST 5Y minus 2Y, basis points."),
    dict(series_id="us.rates.term_premium", title="10Y minus EFFR", short_title="10Y-EFFR",
         layer="derived", group_id="curve", unit="bp", frequency="D",
         question="What term premium is priced over the policy rate?",
         method_note="UST 10Y minus EFFR, basis points. A rough term-premium proxy."),
    dict(series_id="us.rates.real_policy", title="Real Policy Rate", short_title="Real FF",
         layer="derived", group_id="real", unit="pct", frequency="M",
         question="Is policy actually restrictive?",
         method_note="EFFR monthly average minus core PCE year-on-year."),
    dict(series_id="us.infl.pce_core_yoy", title="Core PCE YoY", short_title="PCE YoY",
         layer="derived", group_id="inflation", unit="pct", frequency="M",
         question="Are we at the Fed's 2% target?",
         method_note="12-month log change of the core PCE index."),
    dict(series_id="us.infl.pce_core_3m", title="Core PCE 3M Annualised", short_title="PCE 3M",
         layer="derived", group_id="inflation", unit="pct", frequency="M",
         question="What is the current inflation run-rate?",
         method_note="3-month log change annualised."),
    dict(series_id="us.infl.pce_yoy", title="Headline PCE YoY", short_title="PCE H YoY",
         layer="derived", group_id="inflation", unit="pct", frequency="M",
         question="How fast are consumer prices rising overall?",
         method_note="12-month log change of the PCE index."),
    dict(series_id="us.growth.gdp_yoy", title="Real GDP YoY", short_title="GDP YoY",
         layer="derived", group_id="growth", unit="pct", frequency="Q",
         question="Is the expansion accelerating or fading?",
         method_note="4-quarter log change of real GDP."),
    dict(series_id="us.growth.ip_yoy", title="Industrial Production YoY", short_title="IP YoY",
         layer="derived", group_id="growth", unit="pct", frequency="M",
         question="Is the goods cycle expanding?",
         method_note="12-month log change of the IP index."),
    dict(series_id="us.growth.cli_6m", title="CLI 6-Month Change", short_title="CLI 6M",
         layer="derived", group_id="growth", unit="pct", frequency="M",
         question="Is the leading indicator improving or deteriorating?",
         method_note="6-month change of the CLI, percent. OECD's own turning-point convention."),
    dict(series_id="us.labor.unrate_chg12", title="Unemployment 12M Change",
         short_title="dU-3", layer="derived", group_id="labor", unit="pct", frequency="M",
         question="Is the labour market deteriorating?",
         method_note="Unemployment rate now minus 12 months ago, percentage points."),
    dict(series_id="us.market.spx_dd", title="S&P 500 Drawdown", short_title="Drawdown",
         layer="derived", group_id="market", unit="pct", frequency="D",
         question="How much risk has been priced out of equities?",
         method_note="Distance from the trailing 252-day high, percent."),
    dict(series_id="us.market.vix_z", title="VIX z-score (1Y)", short_title="VIX z",
         layer="derived", group_id="market", unit="z", frequency="D",
         question="Is volatility unusual for this regime?",
         method_note="VIX standardised over the trailing 252 days."),
]

# ---------------------------------------------------------------------------
# L1b — panel aggregates: one number computed from many components.
# These are what "breadth" means, and they are the reason a single index does
# not need its own row on the board.
# ---------------------------------------------------------------------------

BREADTH: list[dict] = [
    dict(series_id="us.infl.trimmed_3m", title="Trimmed-Mean PCE 3M Annualised",
         short_title="Trimmed PCE", layer="derived", group_id="inflation",
         unit="pct", frequency="M", source="panel", provider="BEA", dataset="NIPA-T20804",
         question="What is inflation doing once outliers are removed?",
         method_note="From the 31 PCE price components: compute each component's 3M "
                     "annualised rate, drop the top and bottom 30% by weight of count, "
                     "average the rest. Robust to a handful of wild components."),
    dict(series_id="us.infl.pce_diffusion", title="PCE Component Diffusion (3M)",
         short_title="Breadth", layer="derived", group_id="inflation",
         unit="pct", frequency="M", source="panel", provider="BEA", dataset="NIPA-T20804",
         question="How broad is the inflation pressure?",
         method_note="Share of PCE price components with a positive 3M annualised rate, "
                     "percent. 50 = half the basket is rising."),
]

# ---------------------------------------------------------------------------
# L2 — composites
# ---------------------------------------------------------------------------

COMPOSITES: list[dict] = [
    dict(series_id="us.agg.growth", title="Growth Momentum", short_title="Growth",
         layer="composite", group_id="aggregate", unit="z", frequency="M",
         question="Is the expansion gaining or losing momentum?",
         method_note="Equal-weight mean of 5 standardised inputs: term spread, IP YoY, "
                     "GDP YoY, CLI 6M change, and the 12M change in unemployment (signed "
                     "negative). Zero means trend, not no growth.",
         inputs=[
             dict(input_id="us.curve.10y3m", weight=1.0, sign=+1, transform="z"),
             dict(input_id="us.growth.ip_yoy", weight=1.0, sign=+1, transform="z"),
             dict(input_id="us.growth.gdp_yoy", weight=1.0, sign=+1, transform="z"),
             dict(input_id="us.growth.cli_6m", weight=1.0, sign=+1, transform="z"),
             dict(input_id="us.labor.unrate_chg12", weight=1.0, sign=-1, transform="z"),
         ]),

    dict(series_id="us.agg.inflation", title="Inflation Momentum", short_title="Inflation",
         layer="composite", group_id="aggregate", unit="z", frequency="M",
         question="Is underlying inflation converging to target or stalling?",
         method_note="Weighted mean of 4 standardised inputs: core PCE 3M annualised (1.0), "
                     "trimmed-mean PCE 3M (1.0), CPI YoY (0.8), 5Y breakeven (0.5). "
                     "Realised and priced inflation disagree, and the gap is information.",
         inputs=[
             dict(input_id="us.infl.pce_core_3m", weight=1.0, sign=+1, transform="z"),
             dict(input_id="us.infl.trimmed_3m", weight=1.0, sign=+1, transform="z"),
             dict(input_id="us.prices.cpi_yoy", weight=0.8, sign=+1, transform="z"),
             dict(input_id="us.infl.be5y", weight=0.5, sign=+1, transform="z"),
         ]),

    dict(series_id="us.agg.financial", title="Financial Conditions", short_title="FCI",
         layer="composite", group_id="aggregate", unit="z", frequency="M",
         question="How tight is the financial channel?",
         method_note="Mean of 4 standardised inputs: real 10Y yield (+), VIX z (+), "
                     "S&P drawdown (-), 10Y-EFFR term spread (+). Higher = tighter.",
         inputs=[
             dict(input_id="us.rates.real10y", weight=1.0, sign=+1, transform="z"),
             dict(input_id="us.market.vix_z", weight=1.0, sign=+1, transform="z"),
             dict(input_id="us.market.spx_dd", weight=1.0, sign=-1, transform="z"),
             dict(input_id="us.rates.term_premium", weight=0.5, sign=+1, transform="z"),
         ]),

    dict(series_id="us.agg.policy", title="Policy Stance", short_title="Policy",
         layer="composite", group_id="aggregate", unit="z", frequency="M",
         question="How restrictive is policy relative to the economy?",
         method_note="Mean of two standardised inputs: the real policy rate and the "
                     "market-implied 2Y path. Higher = tighter than neutral.",
         inputs=[
             dict(input_id="us.rates.real_policy", weight=1.0, sign=+1, transform="z"),
             dict(input_id="us.rates.ust2y", weight=0.6, sign=+1, transform="z"),
         ]),

    dict(series_id="us.agg.risk", title="Cycle Risk", short_title="Risk",
         layer="composite", group_id="aggregate", unit="score", frequency="M",
         question="How close is the cycle to breaking?",
         method_note="0-100 percentile of a weighted z-sum: growth (-1.0), financial "
                     "(+0.8), policy (+0.4). No fitting and no backtest — a documented "
                     "rule you can argue with.",
         inputs=[
             dict(input_id="us.agg.growth", weight=1.0, sign=-1, transform="z"),
             dict(input_id="us.agg.financial", weight=0.8, sign=+1, transform="z"),
             dict(input_id="us.agg.policy", weight=0.4, sign=+1, transform="z"),
         ]),
]

# ---------------------------------------------------------------------------
# Trackers — providers that publish only a current value. We poll them and
# thereby build the history they do not hand out.
# ---------------------------------------------------------------------------

# Series whose provider publishes only a current value and no history. Anything
# added here is polled by `track.py` and slowly grows its own history.
# (Atlanta Fed GDPNow was tried and dropped: the number only exists inside a
# chart image, so there is nothing machine-readable to collect.)
TRACKED: list[dict] = []

# The tracker also runs over every catalogued series: once a day it records the
# latest print and its period, which over time becomes a first-print / revision
# log. That is history nobody publishes, built from what we already have.
TRACK_LATEST = True

GROUPS: list[dict] = [
    dict(group_id="aggregate", label="Aggregate indicators",
         blurb="Where the cycle actually is, once the single series are combined."),
    dict(group_id="rates", label="Policy and rates",
         blurb="What the Fed does, and what the curve prices next."),
    dict(group_id="curve", label="Term structure",
         blurb="Shape of the curve — the market's cycle forecast."),
    dict(group_id="real", label="Real rates and inflation pricing",
         blurb="The real cost of capital and priced inflation."),
    dict(group_id="inflation", label="Inflation",
         blurb="Realised prices, measured the way the Fed measures them."),
    dict(group_id="growth", label="Activity",
         blurb="Output and the leading indicators that turn first."),
    dict(group_id="labor", label="Labour", blurb="Slack in the labour market."),
    dict(group_id="market", label="Market state",
         blurb="What risk assets say about all of the above."),
]

QUESTIONS: dict[str, str] = {
    "regime": "Where are we in the cycle — accelerating or fading, and is inflation cooling?",
    "curve": "Is the curve still forecasting a slowdown?",
    "real": "Is the real cost of capital still restrictive?",
    "inflation": "Is inflation converging to target or stalling above it?",
    "growth": "Is the expansion holding up?",
    "labor": "Is the labour market loosening or breaking?",
    "market": "Is the market pricing the same cycle the data describes?",
}
