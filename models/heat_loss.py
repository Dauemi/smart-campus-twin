"""
Building heat-loss model for the Smart Campus Twin.

H = sum(U * A * b) + sum(psi * L) + 0.34 * n * V * (1 - heat recovery)
  U   = U-value of a wall, window, roof or floor (W/m2K)
  A   = its area (m2);  b = 0.5 for the ground floor slab (the ground is warmer than air)
  psi = linear thermal bridge (W/mK) along a length L (m), e.g. where a floor meets a wall
  n   = average air changes per hour, V = heated volume (m3)

From H we get:
  design heat load (kW)  = H * (T_inside - T_design_outside) / 1000
  annual heat demand     = H * degree-days * 24 / 1000 * (1 - share covered by free gains)

The building is uninsulated 1970s concrete (30 m x 18 m, 3 floors).
The script compares it with a renovated version.

Run:  python models/heat_loss.py
Out:  models/results/heat_loss.csv, heat_loss.png
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

# ---------- Climate (Paris) ----------
T_INSIDE = 19          # degC
T_DESIGN_OUT = -5      # coldest design day, degC
DEGREE_DAYS = 2400     # heating degree days, base 18
FREE_GAINS = 0.25      # share of the heat covered by people, lights, sun
FLOOR_AREA = 30 * 18 * 3   # m2

# ---------- Building today ----------
#  name,                  area m2, U today, U renovated, b
ELEMENTS = [
    ("External walls",      645, 1.40, 0.25, 1.0),
    ("Windows",             277, 2.80, 1.20, 1.0),
    ("Roof",                540, 0.90, 0.15, 1.0),
    ("Ground floor slab",   540, 0.80, 0.80, 0.5),
]
#  name,                  length m, psi today, psi renovated
BRIDGES = [
    ("Floor-wall junctions", 384, 0.60, 0.20),
    ("Window reveals",       766, 0.15, 0.05),
    ("Roof parapet",          96, 0.35, 0.10),
]
VOLUME = 4860              # heated volume, m3
ACH = 1.0                  # average air changes per hour over a year
HEAT_RECOVERY = {"Today": 0.0, "Renovated": 0.75}


def heat_loss(case):
    """Return a table of heat loss per element (W/K) for 'Today' or 'Renovated'."""
    rows = []
    for name, area, u_now, u_new, b in ELEMENTS:
        u = u_now if case == "Today" else u_new
        rows.append({"element": name, "type": "Fabric", "W_per_K": area * u * b})
    for name, length, psi_now, psi_new in BRIDGES:
        psi = psi_now if case == "Today" else psi_new
        rows.append({"element": name, "type": "Thermal bridge", "W_per_K": length * psi})
    vent = 0.34 * ACH * VOLUME * (1 - HEAT_RECOVERY[case])
    rows.append({"element": "Ventilation", "type": "Ventilation", "W_per_K": vent})
    df = pd.DataFrame(rows)
    df["case"] = case
    return df


def main():
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)

    table = pd.concat([heat_loss("Today"), heat_loss("Renovated")], ignore_index=True)
    table.to_csv(out_dir / "heat_loss.csv", index=False)

    print("\nHeat loss by element (W/K)\n")
    print(table.pivot(index="element", columns="case", values="W_per_K").round(0)
          .reindex([e[0] for e in ELEMENTS] + [b[0] for b in BRIDGES] + ["Ventilation"]).to_string())

    print("\nWhole building\n")
    results = {}
    for case in ["Today", "Renovated"]:
        H = table[table.case == case].W_per_K.sum()
        design_kw = H * (T_INSIDE - T_DESIGN_OUT) / 1000
        annual_mwh = H * DEGREE_DAYS * 24 / 1e6 * (1 - FREE_GAINS)
        results[case] = (H, design_kw, annual_mwh)
        bridges_share = table[(table.case == case) & (table.type == "Thermal bridge")].W_per_K.sum() / H * 100
        print(f"{case:10s}  H = {H:6.0f} W/K   design load = {design_kw:5.0f} kW   "
              f"heat demand = {annual_mwh:5.0f} MWh/yr = {annual_mwh * 1000 / FLOOR_AREA:4.0f} kWh/m2   "
              f"bridges = {bridges_share:3.0f}% of losses")
    cut = (1 - results["Renovated"][2] / results["Today"][2]) * 100
    print(f"\nRenovation cuts the heat demand by {cut:.0f}%.")

    # ---------- Chart: where the heat goes ----------
    piv = table.pivot(index="element", columns="case", values="W_per_K")
    piv = piv.loc[piv["Today"].sort_values().index]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    y = range(len(piv))
    ax.barh([i + 0.2 for i in y], piv["Today"], height=0.4, color="#bf3826", label="Today")
    ax.barh([i - 0.2 for i in y], piv["Renovated"], height=0.4, color="#0c8770", label="Renovated")
    ax.set_yticks(list(y), piv.index)
    ax.set(xlabel="Heat loss coefficient (W/K)",
           title=f"Where the heat goes: H {results['Today'][0]:.0f} -> {results['Renovated'][0]:.0f} W/K")
    ax.legend(frameon=False)
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_dir / "heat_loss.png", dpi=150)
    print(f"Saved table and chart to {out_dir}")


if __name__ == "__main__":
    main()
