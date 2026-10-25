"""
Campus low-voltage load flow: can the buildings share their solar without breaking the grid?

The campus is a small decentralised grid: 5 buildings, each with its own load and rooftop solar,
fed by one 20/0.4 kV transformer over two underground cable feeders.

                         Feeder 1:  [Teaching] ---150 m--- [Library]
   20 kV grid ==[630 kVA]== LV busbar
                         Feeder 2:  [Residence] ---250 m--- [Sports hall] ---150 m--- [Car park]
                                    (200 m from the busbar)

Three scenarios:
  A. Winter evening peak : high load, no sun       -> voltage DROP, heavy cables?
  B. Summer noon         : low load, full sun      -> power flows BACKWARDS, voltage RISE?
  C. Summer noon, smart  : the same, but the sports-hall battery soaks up surplus
                           and the solar inverters absorb reactive power  -> fixed?

Method: backward/forward sweep, the standard way to solve a radial (tree-shaped) network.
  backward: add up currents from the far end towards the transformer
  forward : start at the transformer and subtract each cable's voltage drop (V = V_parent - Z * I)
  repeat until the voltages stop changing.
Balanced three-phase, per-phase values. Use these results to check your NEPLAN model.

Run:  python models/campus_loadflow.py
Out:  models/results/loadflow_buses.csv, loadflow_lines.csv, neplan_input.csv, campus_loadflow.png
"""
import math
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

V_LL = 400.0                         # line-to-line voltage, V
V_PH = V_LL / math.sqrt(3)           # phase voltage, 230.9 V
V_MAX, V_MIN = 1.10, 0.90            # EN 50160 limits (+/-10 %)
V_WARN = 1.05                        # planning margin we flag as a warning (our assumption)

# ---------- Equipment ----------
TRAFO_KVA, TRAFO_UK, TRAFO_XR = 630, 0.04, 5          # 630 kVA, 4 % short-circuit voltage
z_base = 0.4 ** 2 / (TRAFO_KVA / 1000)                 # ohm, referred to the LV side
z_mag = TRAFO_UK * z_base
TRAFO_Z = complex(z_mag / math.sqrt(1 + TRAFO_XR ** 2), z_mag * TRAFO_XR / math.sqrt(1 + TRAFO_XR ** 2))

CABLE = dict(name="NAYY 4x150 SE", r=0.206, x=0.080, imax=270)   # ohm/km, ohm/km, A

# ---------- Network: (bus, parent, cable length km) ----------
BUSES = [
    ("LV busbar",   None,        None),
    ("Teaching",    "LV busbar", 0.150),
    ("Library",     "Teaching",  0.150),
    ("Residence",   "LV busbar", 0.200),
    ("Sports hall", "Residence", 0.250),
    ("Car park",    "Sports hall", 0.150),
]
FEEDERS = {"Feeder 1": ["LV busbar", "Teaching", "Library"],
           "Feeder 2": ["LV busbar", "Residence", "Sports hall", "Car park"]}

# ---------- Buildings: load kW (winter evening, summer noon), PV size kWp ----------
BUILDINGS = {
    "Teaching":    dict(load_winter=70,  load_summer=35, pv_kwp=36),    # the building in your twin
    "Library":     dict(load_winter=45,  load_summer=20, pv_kwp=30),
    "Residence":   dict(load_winter=120, load_summer=25, pv_kwp=60),
    "Sports hall": dict(load_winter=50,  load_summer=10, pv_kwp=150),   # big flat roof
    "Car park":    dict(load_winter=60,  load_summer=15, pv_kwp=100),   # EV chargers + solar canopy
}
PF_LOAD = 0.95          # loads draw some reactive power
PV_NOON = 0.80          # summer-noon output per kWp
BATTERY_KW = 80         # scenario C: battery at the sports hall
PF_PV_SMART = 0.90      # scenario C: inverters absorb reactive power (lowers the voltage)


def bus_power(scenario):
    """Net power per bus in kW / kvar (positive = taking from the grid, negative = exporting)."""
    out = {}
    for name, b in BUILDINGS.items():
        load = b["load_winter"] if scenario == "A" else b["load_summer"]
        q_load = load * math.tan(math.acos(PF_LOAD))
        pv = 0 if scenario == "A" else b["pv_kwp"] * PV_NOON
        p, q = load - pv, q_load
        if scenario == "C":
            q += pv * math.tan(math.acos(PF_PV_SMART))       # inverters absorb reactive power
            if name == "Sports hall":
                p += BATTERY_KW                               # battery charges from the surplus
        out[name] = (p, q)
    return out


def solve(scenario, tol=1e-6):
    """Backward/forward sweep. Returns bus voltages (pu) and branch currents (A)."""
    power = bus_power(scenario)
    children = {b: [c for c, p, _ in BUSES if p == b] for b, _, _ in BUSES}
    z = {c: complex(CABLE["r"], CABLE["x"]) * length for c, p, length in BUSES if p}
    V = {b: complex(V_PH, 0) for b, _, _ in BUSES}
    V_src = complex(V_PH, 0)                    # the 20 kV grid holds the transformer input at 1.0 pu

    for it in range(100):
        # backward sweep: current drawn at each bus (per phase), then add up branch currents
        I_bus = {b: ((power[b][0] + 1j * power[b][1]) * 1000 / 3 / V[b]).conjugate() if b in power else 0
                 for b, _, _ in BUSES}
        I_branch = {}
        def total(b):
            I_branch[b] = I_bus[b] + sum(total(c) for c in children[b])
            return I_branch[b]
        I_trafo = total("LV busbar")
        # forward sweep: voltages from the transformer outwards
        new = {"LV busbar": V_src - TRAFO_Z * I_trafo}
        for c, p, _ in BUSES:
            if p:
                new[c] = new[p] - z[c] * I_branch[c]
        change = max(abs(new[b] - V[b]) for b in V)
        V = new
        if change < tol:
            break

    buses = pd.DataFrame([{"scenario": scenario, "bus": b, "V_pu": abs(V[b]) / V_PH,
                           "V_LL_volts": abs(V[b]) * math.sqrt(3),
                           "P_kW": power.get(b, (0, 0))[0]} for b, _, _ in BUSES])
    lines = pd.DataFrame([{"scenario": scenario, "cable": f"{p} -> {c}", "to_bus": c, "length_m": round(L * 1000),
                           "I_A": abs(I_branch[c]), "loading_pct": abs(I_branch[c]) / CABLE["imax"] * 100,
                           "direction": "towards building" if (V[p] * I_branch[c].conjugate()).real > 0 else "BACK to transformer"}
                          for c, p, L in BUSES if p])
    trafo_kva = abs(3 * V["LV busbar"] * I_trafo.conjugate()) / 1000
    return buses, lines, trafo_kva, it + 1


def status(v):
    if v > V_MAX or v < V_MIN:
        return "VIOLATION"
    if v > V_WARN or v < 2 - V_WARN:
        return "warning"
    return "ok"


def main():
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    names = {"A": "A. Winter evening peak", "B": "B. Summer noon", "C": "C. Summer noon + smart control"}

    all_b, all_l = [], []
    pd.set_option("display.width", 150)
    for s in "ABC":
        b, l, kva, its = solve(s)
        b["status"] = b.V_pu.apply(status)
        l["status"] = l.loading_pct.apply(lambda x: "OVERLOAD" if x > 100 else "warning" if x > 80 else "ok")
        all_b.append(b); all_l.append(l)
        print(f"\n{names[s]}   (converged in {its} iterations, transformer {kva:.0f} of {TRAFO_KVA} kVA)\n")
        print(b[["bus", "P_kW", "V_LL_volts", "V_pu", "status"]].round(3).to_string(index=False))
        print()
        print(l[["cable", "I_A", "loading_pct", "direction", "status"]].round(1).to_string(index=False))

    buses, lines = pd.concat(all_b), pd.concat(all_l)
    buses.round(4).to_csv(out_dir / "loadflow_buses.csv", index=False)
    lines.round(2).to_csv(out_dir / "loadflow_lines.csv", index=False)

    # ---------- the data to type into NEPLAN ----------
    rows = [{"element": "External grid", "type": "Slack, 20 kV, 1.0 pu", "from": "", "to": "MV bus", "data": ""},
            {"element": "Transformer", "type": f"{TRAFO_KVA} kVA 20/0.4 kV", "from": "MV bus", "to": "LV busbar",
             "data": f"uk = {TRAFO_UK * 100:.0f} %, X/R = {TRAFO_XR}"}]
    for c, p, L in BUSES:
        if p:
            rows.append({"element": "Cable", "type": CABLE["name"], "from": p, "to": c,
                         "data": f"{L * 1000:.0f} m, R = {CABLE['r']} ohm/km, X = {CABLE['x']} ohm/km, Imax = {CABLE['imax']} A"})
    for n, bd in BUILDINGS.items():
        rows.append({"element": "Load", "type": f"cos phi {PF_LOAD}", "from": "", "to": n,
                     "data": f"A: {bd['load_winter']} kW, B/C: {bd['load_summer']} kW"})
        rows.append({"element": "PV (static generator)", "type": "cos phi 1 (C: 0.90 absorbing)", "from": "", "to": n,
                     "data": f"{bd['pv_kwp']} kWp, A: 0 kW, B/C: {bd['pv_kwp'] * PV_NOON:.0f} kW"})
    rows.append({"element": "Battery (scenario C only)", "type": "load", "from": "", "to": "Sports hall",
                 "data": f"+{BATTERY_KW} kW charging"})
    pd.DataFrame(rows).to_csv(out_dir / "neplan_input.csv", index=False)

    # ---------- chart: voltage along feeder 2, cable loading ----------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.8))
    dist = {"LV busbar": 0, "Residence": 200, "Sports hall": 450, "Car park": 600}
    colors = {"A": "#2d6cb8", "B": "#bf3826", "C": "#0c8770"}
    for s in "ABC":
        b = buses[buses.scenario == s].set_index("bus")
        f2 = FEEDERS["Feeder 2"]
        ax1.plot([dist[x] for x in f2], [b.loc[x, "V_pu"] * 100 for x in f2], "o-", color=colors[s], lw=2, label=names[s])
    for y, txt in [(110, "+10 % limit (EN 50160)"), (90, "-10 % limit")]:
        ax1.axhline(y, color="#566a64", ls="--", lw=1)
        ax1.text(5, y + 0.3, txt, fontsize=8, color="#566a64")
    ax1.set_xticks(list(dist.values()), [f"{k}\n{v} m" for k, v in dist.items()], fontsize=8)
    ax1.set(ylabel="Voltage (% of 400 V)", title="Feeder 2: voltage from transformer to car park", ylim=(82, 116))
    ax1.legend(frameon=False, fontsize=8, loc="upper left")
    ax1.grid(alpha=0.25)

    piv = lines.pivot(index="cable", columns="scenario", values="loading_pct").reindex([f"{p} -> {c}" for c, p, _ in BUSES if p])
    x = range(len(piv))
    for i, s in enumerate("ABC"):
        ax2.bar([k + (i - 1) * 0.27 for k in x], piv[s], width=0.27, color=colors[s], label=names[s][:2].strip())
    ax2.axhline(100, color="#bf3826", ls="--", lw=1)
    ax2.set_xticks(list(x), [c.replace(" -> ", "\n-> ") for c in piv.index], fontsize=7.5)
    ax2.set(ylabel="Cable loading (% of 270 A)", title="Cable loading")
    ax2.legend(frameon=False, fontsize=8)
    ax2.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_dir / "campus_loadflow.png", dpi=150)
    print(f"\nSaved results, NEPLAN input sheet and chart to {out_dir}")


if __name__ == "__main__":
    main()
