"""
Smart grid model for the Smart Campus Twin: solar roof + battery + EV chargers.

Question: how much of the roof's solar power can the building use itself,
and how much do a battery and smart EV charging help?

One day in 15-minute steps. Energy balance every step:
    grid = building load + EV charging + battery charging - PV
    (positive = import from the grid, negative = export)

Four strategies x two days (a cloudy October weekday and a sunny June weekday):
  A. No flexibility    : EVs charge at full power when they arrive, no battery
  B. Battery           : a 50 kWh battery stores surplus solar and uses it later
  C. Smart EV charging : EVs charge from solar surplus, but still finish by 17:30
  D. Battery + smart EV

Run:  python models/smart_grid.py
Out:  models/results/smart_grid_summary.csv, smart_grid.png
"""
import math
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

STEP_H = 0.25                 # 15 minutes
PV_KWP = 36                   # solar roof size
BATT_KWH, BATT_KW = 50, 25    # battery capacity and max power
SOC_MIN, SOC_MAX = 0.10, 0.95
EV_CHARGERS, EV_KW = 4, 7.4   # 4 chargers x 7.4 kW
EV_NEED_KWH = 80              # energy the cars need per day
EV_ARRIVE, EV_LEAVE = 8.5, 17.5
EXPORT_PRICE = 0.05           # EUR/kWh paid for exported solar

# two days: sunrise, sunset, peak output per kWp, cloud factor
DAYS = {
    "October (cloudy)": dict(rise=7.5, set=17.4, peak=0.60, cloud=0.45),
    "June (sunny)":     dict(rise=5.9, set=21.9, peak=0.80, cloud=0.10),
}


def tariff(h):
    """Illustrative French peak / off-peak tariff, EUR/kWh."""
    return 0.2146 if 6 <= h < 22 else 0.1696


def grid_co2(h):
    """Illustrative French grid carbon intensity, gCO2/kWh (low, nuclear-heavy, peaks morning and evening)."""
    return 48 + 22 * math.exp(-((h - 9) ** 2) / 3) + 27 * math.exp(-((h - 19) ** 2) / 3)


def building_load(h):
    """Electric load of the building in kW (lights, plugs, server, fans): a weekday shape."""
    base = 9.0                                   # server room + standby, all day and night
    if 7.5 <= h < 19:
        base += 26 + 8 * math.sin(math.pi * (h - 7.5) / 11.5)   # occupied hours
    if 11.5 <= h < 13.5:
        base += 6                                # cafe kitchen at lunch
    return base


def pv_power(h, day):
    if h <= day["rise"] or h >= day["set"]:
        return 0.0
    return PV_KWP * day["peak"] * math.sin(math.pi * (h - day["rise"]) / (day["set"] - day["rise"])) * (1 - 0.72 * day["cloud"])


def simulate(day, battery, smart_ev):
    soc, delivered, rows = 0.45, 0.0, []
    for k in range(int(24 / STEP_H)):
        h = k * STEP_H
        load, pv = building_load(h), pv_power(h, day)

        # EV charging
        ev = 0.0
        remaining = EV_NEED_KWH - delivered
        if EV_ARRIVE <= h < EV_LEAVE and remaining > 0:
            max_kw = EV_CHARGERS * EV_KW
            if smart_ev:
                must = remaining / max(STEP_H, EV_LEAVE - h)    # minimum rate to finish in time
                ev = min(max_kw, max(must, pv - load))          # ...or more if there is solar surplus
            else:
                ev = max_kw                                     # dumb: full power on arrival
            ev = min(ev, remaining / STEP_H)
            delivered += ev * STEP_H

        # battery: charge from surplus, discharge to cover deficit
        batt = 0.0                                              # + charging, - discharging
        if battery:
            net = pv - load - ev
            if net > 0:
                batt = min(net, BATT_KW, (SOC_MAX - soc) * BATT_KWH / STEP_H)
            else:
                batt = -min(-net, BATT_KW, (soc - SOC_MIN) * BATT_KWH / STEP_H)
            soc += batt * STEP_H / BATT_KWH

        grid = load + ev + batt - pv
        rows.append(dict(hour=h, load=load, pv=pv, ev=ev, batt=batt, soc=soc * 100, grid=grid,
                         imp=max(0, grid), exp=max(0, -grid), price=tariff(h), co2=grid_co2(h)))
    return pd.DataFrame(rows)


def kpis(df):
    e = lambda col: (df[col] * STEP_H).sum()
    pv, exp, imp = e("pv"), e("exp"), e("imp")
    use = ((df.load + df.ev) * STEP_H).sum()
    return {
        "solar_kWh": round(pv, 1),
        "self_consumption_pct": round((pv - exp) / pv * 100, 1) if pv else 0,
        "self_sufficiency_pct": round((use - imp) / use * 100, 1),
        "grid_import_kWh": round(imp, 1),
        "export_kWh": round(exp, 1),
        "peak_import_kW": round(df.imp.max(), 1),
        "cost_EUR": round((df.imp * df.price).sum() * STEP_H - exp * EXPORT_PRICE, 2),
        "grid_CO2_kg": round((df.imp * df.co2).sum() * STEP_H / 1000, 1),
    }


STRATEGIES = {
    "A. No flexibility":     dict(battery=False, smart_ev=False),
    "B. Battery":            dict(battery=True,  smart_ev=False),
    "C. Smart EV charging":  dict(battery=False, smart_ev=True),
    "D. Battery + smart EV": dict(battery=True,  smart_ev=True),
}


def main():
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)

    rows, series = [], {}
    for day_name, day in DAYS.items():
        for s_name, opts in STRATEGIES.items():
            df = simulate(day, **opts)
            series[(day_name, s_name)] = df
            rows.append({"day": day_name, "strategy": s_name, **kpis(df)})
    summary = pd.DataFrame(rows)
    summary.to_csv(out_dir / "smart_grid_summary.csv", index=False)

    pd.set_option("display.width", 160)
    for day_name in DAYS:
        print(f"\n{day_name}\n")
        print(summary[summary.day == day_name].drop(columns="day").set_index("strategy").to_string())

    # ---------- Chart: June day, no flexibility vs battery + smart EV ----------
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), sharey=True)
    for ax, s in zip(axes, ["A. No flexibility", "D. Battery + smart EV"]):
        d = series[("June (sunny)", s)]
        ax.fill_between(d.hour, d.pv, color="#e2a637", alpha=0.35, label="Solar")
        ax.plot(d.hour, d.load + d.ev, color="#12231e", lw=1.6, label="Building + EV load")
        ax.plot(d.hour, d.ev, color="#2d6cb8", lw=1.4, label="EV charging")
        ax.plot(d.hour, d.grid, color="#bf3826", lw=2, label="Grid (+ import / - export)")
        ax.axhline(0, color="#566a64", lw=0.8)
        k = kpis(d)
        ax.set(title=f"{s}\nself-consumption {k['self_consumption_pct']:.0f}% · peak import {k['peak_import_kW']:.0f} kW",
               xlabel="Hour of day", xlim=(0, 24))
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("kW")
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.suptitle("Sunny June weekday: what flexibility changes", y=1.02)
    fig.tight_layout()
    fig.savefig(out_dir / "smart_grid.png", dpi=150, bbox_inches="tight")
    print(f"\nSaved results and chart to {out_dir}")


if __name__ == "__main__":
    main()
