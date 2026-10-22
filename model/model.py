"""
Who should buy Just Salad: Chipotle or Qdoba?

A hypothetical M&A case study model. Neither company has announced or
reportedly explored a deal for Just Salad. Market and company figures come
from data/inputs.csv (each row cites its source); everything in ASSUMPTIONS
below is a modeling choice, not a reported fact.

Run:  python model/model.py
Output: printed tables + PNG charts in charts/
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CHARTS = ROOT / "charts"
CHARTS.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
inputs = pd.read_csv(ROOT / "data" / "inputs.csv").set_index("key")["value"]

ASSUMPTIONS = {
    "ask_price": 1.25e9,           # 25% premium to the Feb 2025 $1.0B round
    "js_units_end_2026": 150,      # ~120 at end-2025 + ~30 planned openings
    "rev_per_unit_2025": 1.80e6,   # $195M / ~110 average open units
    "rev_per_unit_growth": 0.02,
    "js_revenue_2026e": 248e6,
    "js_ebitda_margin_2026e": 0.10,
    "da_pct_revenue": 0.05,
    "tax_rate": 0.25,
    "capex_per_new_unit": 1.2e6,
    "maintenance_capex_pct": 0.02,
    "exit_multiples": [12, 15, 18],  # x 2031 EBITDA; 15x is the base case
    "chipotle_hurdle": 0.09,         # unlevered cost of capital
    "qdoba_hurdle": 0.20,            # private-equity equity return target
    "qdoba_debt": 150e6,             # ~6x 2026E EBITDA
    "qdoba_debt_rate": 0.07,
    "cmg_debt_rate": 0.055,
    "cmg_cash_yield": 0.04,
}
A = ASSUMPTIONS
B = 1e9

# Openings per year (2027-2031) and EBITDA margins by owner
SCENARIOS = {
    "Standalone": ([32, 35, 38, 40, 42], [0.105, 0.11, 0.115, 0.12, 0.125]),
    "Qdoba-owned": ([40, 50, 60, 70, 75], [0.11, 0.12, 0.13, 0.135, 0.14]),
    "Chipotle-owned": ([50, 70, 90, 110, 120], [0.115, 0.13, 0.145, 0.16, 0.165]),
}


# ---------------------------------------------------------------------------
# 1. Trading comps and implied value for Just Salad
# ---------------------------------------------------------------------------
def comps_table():
    rows = [
        ("CAVA", inputs.cava_market_cap * B, inputs.cava_revenue_ttm * B, inputs.cava_restaurants),
        ("Chipotle", inputs.cmg_market_cap * B, inputs.cmg_revenue_ttm * B, inputs.cmg_restaurants),
        ("Sweetgreen", inputs.sg_market_cap * B, inputs.sg_revenue_q2_2026 * 4 * B, inputs.sg_restaurants),
    ]
    df = pd.DataFrame(rows, columns=["company", "market_cap", "sales", "restaurants"])
    df["price_to_sales"] = df.market_cap / df.sales
    df["value_per_unit"] = df.market_cap / df.restaurants
    # Implied Just Salad value: low = sales multiple, high = per-restaurant value
    df["js_low"] = df.price_to_sales * A["js_revenue_2026e"]
    df["js_high"] = df.value_per_unit * inputs.js_restaurants
    lo = df[["js_low", "js_high"]].min(axis=1)
    hi = df[["js_low", "js_high"]].max(axis=1)
    df["js_low"], df["js_high"] = lo, hi
    return df


# ---------------------------------------------------------------------------
# 2. Unit growth and earnings by owner
# ---------------------------------------------------------------------------
def project(adds, margins):
    start = A["js_units_end_2026"]
    rpu = A["rev_per_unit_2025"] * (1 + A["rev_per_unit_growth"])  # 2026 level
    out = []
    for i, (new, margin) in enumerate(zip(adds, margins)):
        end = start + new
        revenue = (start + end) / 2 * rpu * (1 + A["rev_per_unit_growth"]) ** (i + 1)
        ebitda = revenue * margin
        ebit = ebitda - revenue * A["da_pct_revenue"]
        tax = max(ebit, 0) * A["tax_rate"]
        capex = new * A["capex_per_new_unit"] + revenue * A["maintenance_capex_pct"]
        out.append(dict(year=2027 + i, units=end, revenue=revenue, ebitda=ebitda,
                        net_income=ebit - tax, fcf=ebitda - tax - capex))
        start = end
    return pd.DataFrame(out)


PATHS = {name: project(*spec) for name, spec in SCENARIOS.items()}


# ---------------------------------------------------------------------------
# 3. What each bidder can pay (walk-away price at its required return)
# ---------------------------------------------------------------------------
def irr(cash_flows):
    lo, hi = -0.99, 2.0
    for _ in range(200):
        mid = (lo + hi) / 2
        npv = sum(cf / (1 + mid) ** t for t, cf in enumerate(cash_flows))
        lo, hi = (mid, hi) if npv > 0 else (lo, mid)
    return mid


def deal_irr(path, price, exit_multiple, debt=0.0, rate=0.0):
    after_tax_interest = debt * rate * (1 - A["tax_rate"])
    flows = [-(price - debt)] + [f - after_tax_interest for f in path.fcf]
    flows[-1] += path.ebitda.iloc[-1] * exit_multiple - debt
    return irr(flows)


def max_price(path, hurdle, exit_multiple, debt=0.0, rate=0.0):
    lo, hi = 1e8, 5e9
    for _ in range(100):
        mid = (lo + hi) / 2
        if deal_irr(path, mid, exit_multiple, debt, rate) > hurdle:
            lo = mid
        else:
            hi = mid
    return mid


def bidder_prices():
    q = dict(debt=A["qdoba_debt"], rate=A["qdoba_debt_rate"])
    cases = [
        ("Chipotle", PATHS["Chipotle-owned"], A["chipotle_hurdle"], {}),
        ("Chipotle, no growth boost", PATHS["Standalone"], A["chipotle_hurdle"], {}),
        ("Qdoba, Chipotle-level growth", PATHS["Chipotle-owned"], A["qdoba_hurdle"], q),
        ("Qdoba", PATHS["Qdoba-owned"], A["qdoba_hurdle"], q),
    ]
    rows = []
    for name, path, hurdle, fin in cases:
        low, mid, high = (max_price(path, hurdle, m, **fin) for m in A["exit_multiples"])
        rows.append(dict(bidder=name, low=low, mid=mid, high=high))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 4. Chipotle EPS test: acquisition vs. an equal-size buyback
# ---------------------------------------------------------------------------
def eps_impact(rate):
    shares, eps = inputs.cmg_diluted_shares * B, inputs.cmg_eps_ttm
    cost = A["ask_price"] * rate * (1 - A["tax_rate"])
    out = {}
    for name in ["Chipotle-owned", "Standalone"]:
        out[name] = [(ni - cost) / shares / eps for ni in PATHS[name].net_income]
    bought = A["ask_price"] / inputs.cmg_share_price
    base_ni = shares * eps
    buyback = ((base_ni - cost) / (shares - bought)) / eps - 1
    return out, buyback


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
BLUE, GREY = "#2a78d6", "#b9b8ad"


def style(ax, title, subtitle):
    ax.set_title(f"{title}\n", loc="left", fontsize=13, fontweight="bold")
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color="#555")
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)


def chart_bidders(df):
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for i, r in enumerate(df.itertuples()):
        c = BLUE if r.bidder == "Chipotle" else GREY
        y = len(df) - i
        ax.plot([r.low / 1e6, r.high / 1e6], [y, y], color=c, lw=2)
        ax.plot(r.mid / 1e6, y, "o", color=c, ms=9)
        ax.text(r.high / 1e6 + 25, y, f"${r.mid / 1e6:,.0f}M", va="center", fontweight="bold")
    ax.axvline(A["ask_price"] / 1e6, color="#333", lw=1.2)
    ax.axvline(inputs.js_valuation_2025 * 1000, color="#999", ls="--", lw=1)
    ax.text(A["ask_price"] / 1e6, 0.45, " Asking price $1.25B", fontsize=9)
    ax.text(inputs.js_valuation_2025 * 1000, 0.45, "Last round $1.0B ", fontsize=9, ha="right", color="#777")
    ax.set_ylim(0.3, len(df) + 0.5)
    ax.set_yticks(range(len(df), 0, -1), df.bidder)
    ax.set_xlim(0, 2100)
    ax.set_xlabel("Walk-away price, $M (dot = 15x exit, line = 12x to 18x)")
    style(ax, "Only Chipotle can clear the $1.25B ask",
          "Highest price each bidder can pay and still hit its required return")
    fig.tight_layout()
    fig.savefig(CHARTS / "walk_away_prices.png", dpi=160)


def chart_units():
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for name, path in PATHS.items():
        years = [2025, 2026] + list(path.year)
        units = [120, A["js_units_end_2026"]] + list(path.units)
        c = BLUE if name.startswith("Chipotle") else GREY
        ls = "--" if name == "Standalone" else "-"
        ax.plot(years, units, ls, color=c, lw=2.5, marker="o", ms=4)
        ax.text(2031.1, units[-1], f"{name}: {units[-1]}", va="center", fontsize=9)
    ax.axvline(2026, color="#999", ls=":", lw=1)
    ax.set_xlim(2025, 2032.4)
    ax.set_ylim(0, 650)
    style(ax, "Under Chipotle, Just Salad reaches 590 restaurants by 2031",
          "Year-end restaurants; actual and planned through 2026, modeled after")
    fig.tight_layout()
    fig.savefig(CHARTS / "unit_growth.png", dpi=160)


def chart_eps(impacts, buyback):
    fig, ax = plt.subplots(figsize=(10, 4.5))
    years = list(PATHS["Standalone"].year)
    w = 0.38
    for k, (name, c) in enumerate([("Chipotle-owned", BLUE), ("Standalone", GREY)]):
        vals = [v * 100 for v in impacts[name]]
        ax.bar([y + (k - 0.5) * w for y in years], vals, w, color=c, label=f"Acquisition, {name} growth")
    ax.axhline(0, color="#333", lw=0.8)
    ax.axhline(buyback * 100, color="#777", ls="--", lw=1.2, label=f"Same $1.25B in buybacks ({buyback * 100:+.1f}%)")
    ax.set_ylabel("Change in Chipotle EPS, %")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    style(ax, "Debt-funded, the deal beats an equal-size buyback only from 2030",
          "Both options pay 5.5% interest on $1.25B")
    fig.tight_layout()
    fig.savefig(CHARTS / "eps_vs_buyback.png", dpi=160)


def chart_valuation(comps):
    fig, ax = plt.subplots(figsize=(10, 4))
    rows = list(comps.itertuples())
    labels = []
    for i, r in enumerate(rows):
        ax.barh(i, (r.js_high - r.js_low) / 1e6, left=r.js_low / 1e6, color=GREY, height=0.5)
        labels.append(f"{r.company} multiples")
    i = len(rows)
    ax.barh(i, 250, left=1000, color=GREY, height=0.5)
    labels.append("Last private round + premium")
    ax.axvline(A["ask_price"] / 1e6, color=BLUE, lw=2)
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("Implied Just Salad equity value, $M")
    style(ax, "A $1.25B offer prices Just Salad above Chipotle's own multiples",
          "Each bar spans a sales-multiple and a per-restaurant valuation")
    fig.tight_layout()
    fig.savefig(CHARTS / "valuation_range.png", dpi=160)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    pd.options.display.float_format = "{:,.2f}".format

    comps = comps_table()
    print("\nTrading comps (implied Just Salad value in $M)")
    print(comps.assign(js_low=comps.js_low / 1e6, js_high=comps.js_high / 1e6,
                       value_per_unit=comps.value_per_unit / 1e6)
          [["company", "price_to_sales", "value_per_unit", "js_low", "js_high"]].to_string(index=False))

    print("\nProjections by owner ($M)")
    for name, p in PATHS.items():
        print(f"\n{name}")
        print((p.assign(revenue=p.revenue / 1e6, ebitda=p.ebitda / 1e6,
                        net_income=p.net_income / 1e6, fcf=p.fcf / 1e6)).to_string(index=False))

    prices = bidder_prices()
    print("\nWalk-away prices ($M) at 12x / 15x / 18x exit")
    print((prices.set_index("bidder") / 1e6).round(0).to_string())

    impacts, buyback = eps_impact(A["cmg_debt_rate"])
    print(f"\nChipotle EPS, debt-funded: buyback {buyback:+.2%}")
    for name, vals in impacts.items():
        print(f"  {name}: " + ", ".join(f"{v:+.2%}" for v in vals))

    q = PATHS["Qdoba-owned"]
    r = deal_irr(q, A["ask_price"], 15, A["qdoba_debt"], A["qdoba_debt_rate"])
    print(f"\nQdoba sponsor IRR at the $1.25B ask, 15x exit: {r:.1%}")

    chart_valuation(comps)
    chart_units()
    chart_bidders(prices)
    chart_eps(impacts, buyback)
    print(f"\nCharts saved to {CHARTS}")
