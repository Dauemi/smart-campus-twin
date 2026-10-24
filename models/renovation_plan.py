"""
Renovation plan for the Smart Campus Twin, checked against the French Decret tertiaire.

The Decret tertiaire requires non-residential buildings over 1,000 m2 to cut their
final energy use by 40% by 2030, 50% by 2040 and 60% by 2050 against a reference year.

This script:
  1. builds a simple annual energy model of the building (heat + electricity - solar)
  2. tests each renovation measure on its own and ranks them by cost per MWh saved
  3. builds three packages (light, medium, deep) and checks each against the targets

It reuses the envelope data from heat_loss.py, so changing a U-value there changes this too.
All prices, costs and emission factors are planning assumptions: replace them with real quotes.

Run:  python models/renovation_plan.py
Out:  models/results/renovation_measures.csv, renovation_packages.csv, renovation_plan.png
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from heat_loss import ELEMENTS, BRIDGES, VOLUME, ACH, DEGREE_DAYS, FREE_GAINS, FLOOR_AREA

# ---------- Assumptions ----------
PRICE_ELEC, PRICE_GAS, PRICE_EXPORT = 0.20, 0.11, 0.05     # EUR/kWh
CO2_ELEC, CO2_GAS = 0.060, 0.227                           # kgCO2/kWh (illustrative French values)
BOILER_EFF, HP_SCOP = 0.90, 3.0
PV_YIELD = 1100                                            # kWh per kWp per year (Paris)
LIFETIME = 20                                              # years, for cost per MWh saved

# measure: name, investment (EUR), description
MEASURES = {
    "walls":   ("External wall insulation",   97_000, "Walls U 1.40 -> 0.25"),
    "windows": ("Triple-glazed windows",     180_000, "Windows U 2.80 -> 1.20"),
    "roof":    ("Roof insulation",            38_000, "Roof U 0.90 -> 0.15"),
    "mvhr":    ("Heat recovery ventilation",  60_000, "75% heat recovery"),
    "hp":      ("Air-to-water heat pump",    106_000, "Replaces the gas boiler"),
    "led":     ("LED lighting + sensors",     41_000, "10 -> 4.5 W/m2, 25% less run time"),
    "pv2":     ("Car-park solar canopy",      26_000, "+20 kWp"),
    "flex":    ("Battery + smart EV",         30_000, "Self-consumption 85% -> 97%"),
}
PACKAGES = {
    "Light":  ["roof", "led", "flex"],
    "Medium": ["roof", "led", "flex", "walls", "hp"],
    "Deep":   ["roof", "led", "flex", "walls", "hp", "windows", "mvhr", "pv2"],
}


def annual(works):
    """Annual energy (kWh), cost (EUR) and CO2 (kg) for a set of measures."""
    w = set(works)
    # heat loss coefficient H with the selected envelope measures
    H = 0.0
    for (name, area, u_now, u_new, b), key in zip(ELEMENTS, ["walls", "windows", "roof", None]):
        H += area * (u_new if key in w else u_now) * b
    for (name, length, psi_now, psi_new), key in zip(BRIDGES, ["walls", "windows", "roof"]):
        H += length * (psi_new if key in w else psi_now)
    H += 0.34 * ACH * VOLUME * (1 - (0.75 if "mvhr" in w else 0))
    heat = H * DEGREE_DAYS * 24 / 1000 * (1 - FREE_GAINS)          # kWh of useful heat

    gas = 0 if "hp" in w else heat / BOILER_EFF
    hp_elec = heat / HP_SCOP if "hp" in w else 0
    lights = FLOOR_AREA * (4.5 * 2500 * 0.75 if "led" in w else 10 * 2500) / 1000
    plugs, server, ev = FLOOR_AREA * 25, 6 * 8760, 80 * 250
    fans = 8000 + (4000 if "mvhr" in w else 0)
    elec = lights + plugs + server + fans + ev + hp_elec

    pv = (36 + (20 if "pv2" in w else 0)) * PV_YIELD
    pv_used = min(pv * (0.97 if "flex" in w else 0.85), elec * 0.6)
    grid = elec - pv_used
    final = gas + grid
    return {
        "heat_loss_W_per_K": round(H),
        "gas_MWh": gas / 1000, "grid_elec_MWh": grid / 1000, "final_MWh": final / 1000,
        "final_kWh_m2": final / FLOOR_AREA,
        "cost_kEUR": (gas * PRICE_GAS + grid * PRICE_ELEC - (pv - pv_used) * PRICE_EXPORT) / 1000,
        "CO2_t": (gas * CO2_GAS + grid * CO2_ELEC) / 1000,
        "invest_kEUR": sum(MEASURES[k][1] for k in w) / 1000,
    }


def main():
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    base = annual([])

    # ---------- 1. each measure on its own ----------
    rows = []
    for key, (name, cost, desc) in MEASURES.items():
        r = annual([key])
        saved = base["final_MWh"] - r["final_MWh"]
        rows.append({"measure": name, "detail": desc, "invest_kEUR": cost / 1000,
                     "saved_MWh_yr": round(saved, 1),
                     "saved_CO2_t_yr": round(base["CO2_t"] - r["CO2_t"], 1),
                     "bill_saving_kEUR_yr": round(base["cost_kEUR"] - r["cost_kEUR"], 1),
                     "EUR_per_MWh_saved": round(cost / (saved * LIFETIME)) if saved > 0 else None})
    measures = pd.DataFrame(rows).sort_values("EUR_per_MWh_saved", na_position="last")
    measures.to_csv(out_dir / "renovation_measures.csv", index=False)

    pd.set_option("display.width", 170)
    print("\n1. Each measure on its own (ranked: cheapest MWh first)\n")
    print(measures.drop(columns="detail").to_string(index=False))

    # ---------- 2. packages against the Decret tertiaire ----------
    rows = [{"package": "Today", **base, "reduction_pct": 0.0}]
    for p, works in PACKAGES.items():
        r = annual(works)
        rows.append({"package": p, **r, "reduction_pct": (1 - r["final_MWh"] / base["final_MWh"]) * 100})
    pk = pd.DataFrame(rows).set_index("package")
    pk["payback_years"] = pk.invest_kEUR / (base["cost_kEUR"] - pk.cost_kEUR).where(pk.index != "Today")
    for t, y in [(40, 2030), (50, 2040), (60, 2050)]:
        pk[f"meets_{y}"] = pk.reduction_pct >= t
    pk.round(1).to_csv(out_dir / "renovation_packages.csv")

    print("\n2. Packages vs the Decret tertiaire (-40% 2030, -50% 2040, -60% 2050)\n")
    cols = ["final_MWh", "final_kWh_m2", "reduction_pct", "CO2_t", "cost_kEUR", "invest_kEUR",
            "payback_years", "meets_2030", "meets_2040", "meets_2050"]
    print(pk[cols].round(1).to_string())

    # ---------- Chart ----------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1, 1.2]})
    names = list(pk.index)
    ax1.bar(names, pk.gas_MWh, color="#bf3826", label="Gas")
    ax1.bar(names, pk.grid_elec_MWh, bottom=pk.gas_MWh, color="#2d6cb8", label="Grid electricity")
    for t, y in [(0.6, 2030), (0.5, 2040), (0.4, 2050)]:
        ax1.axhline(base["final_MWh"] * t, color="#566a64", ls="--", lw=1)
        ax1.text(len(names) - 0.45, base["final_MWh"] * t + 3, f"{y} target", va="bottom", fontsize=8, color="#566a64")
    ax1.set(ylabel="Final energy (MWh/yr)", title="Packages vs Decret tertiaire targets")
    ax1.legend(frameon=False)
    ax1.set_xlim(-0.6, len(names) + 0.3)

    m = measures.dropna(subset=["EUR_per_MWh_saved"]).iloc[::-1]
    ax2.barh(m.measure, m.EUR_per_MWh_saved, color="#0c8770")
    ax2.set(xlabel=f"Investment per MWh saved over {LIFETIME} years (EUR)", title="Best value measures (shortest bar first)")
    ax2.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_dir / "renovation_plan.png", dpi=150)
    print(f"\nSaved results and chart to {out_dir}")


if __name__ == "__main__":
    main()
