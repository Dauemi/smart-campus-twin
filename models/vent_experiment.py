"""
Ventilation experiment for the Smart Campus Twin.

Question: does automatic CO2-controlled ventilation fix the air quality problem,
and what does it cost in energy?

Three strategies are simulated for one full school day (1-minute steps):
  1. Normal      : fixed 2 air changes per hour (ach) during the day
  2. Auto (CO2)  : 2 ach, boosted to 5 ach while CO2 > 1000 ppm (off again below 800)
  3. Always high : 5 ach all day

For each strategy we measure air quality (room-minutes above 1000 ppm) and
energy (fan electricity + the extra heating needed to warm the outdoor air).

Run:  python models/vent_experiment.py
Out:  models/results/vent_summary.csv, vent_timeseries.csv, vent_experiment.png
"""
import random
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

# ---------- Assumptions (change these and re-run) ----------
SFP = 1.5          # specific fan power, kW per (m3/s) of air moved
T_INSIDE = 20.0    # heating setpoint, degC
T_OUTSIDE = 9.0    # a typical late-October day in Paris, degC
OCCUPIED = (8, 18) # hours used for the air-quality score
SEED = 42          # same random occupancy in every strategy = a fair comparison

#        id             name                volume m3  max people  use
ROOMS = [
    ("lobby",       "Lobby & reception",    240, 15, "circulation"),
    ("cafe",        "Cafe & kitchen",       240, 30, "social"),
    ("energy-lab",  "Energy lab",           360, 16, "lab"),
    ("hall-a",      "Lecture hall A",       600, 80, "teaching"),
    ("c101",        "Classroom 101",        270, 30, "teaching"),
    ("c102",        "Classroom 102",        270, 30, "teaching"),
    ("library",     "Library & study",      360, 40, "study"),
    ("meeting",     "Meeting room",         240, 12, "office"),
    ("open-office", "Open office",          480, 24, "office"),
    ("grid-lab",    "Smart grid lab",       360, 20, "lab"),
    ("computer",    "Computer lab",         300, 28, "teaching"),
    ("research",    "Research office",      120,  8, "office"),
    ("seminar",     "Seminar room",         432, 40, "teaching"),
    ("staff",       "Staff room",           288, 12, "social"),
]


def occupancy_fraction(use, hour):
    """How full a room is (0 to 1) at a given hour. Same schedules as the simulator."""
    def between(a, b):
        return a <= hour < b
    if use == "teaching":
        return 0.85 if between(8.25, 10) or between(10.25, 12) or between(13.5, 17) else 0
    if use == "office":
        return 0.65 if between(8, 12) or between(13.5, 18) else 0.3 if between(12, 13.5) else 0
    if use == "study":
        return 0.5 if between(8, 20) else 0
    if use == "social":
        return 0.9 if between(11.5, 14) else 0.2 if between(7.5, 17) else 0
    if use == "lab":
        return 0.6 if between(9, 12) or between(13.5, 17.5) else 0
    if use == "circulation":
        return 0.3 if between(7.5, 19) else 0
    return 0


def simulate(strategy):
    """Simulate every room for 24 h. Returns one row per room per minute."""
    random.seed(SEED)
    rows = []
    for room_id, name, volume, max_people, use in ROOMS:
        co2, people, boost = 430.0, 0.0, False
        for minute in range(24 * 60):
            hour = minute / 60
            day = 7.5 <= hour < 18.5

            # people follow the timetable, with a little randomness
            target = max_people * occupancy_fraction(use, hour) * random.uniform(0.8, 1.05)
            people += (target - people) * 0.3

            # the ventilation strategy decides the air change rate
            if strategy == "Normal":
                ach = 2.0 if day else 0.3
            elif strategy == "Always high":
                ach = 5.0 if day else 0.3
            else:  # "Auto (CO2)": hysteresis between 800 and 1000 ppm
                if co2 > 1000:
                    boost = True
                elif co2 < 800:
                    boost = False
                ach = (5.0 if boost else 2.0) if day else 0.3

            # CO2 mass balance, one minute: people add CO2, ventilation removes it
            generation = round(people) * 0.018 / volume * 1e6   # ppm per hour
            removal = ach * (co2 - 420)                          # ppm per hour
            co2 += (generation - removal) / 60

            # energy for this minute
            airflow_m3s = ach * volume / 3600                     # m3/s
            fan_kw = SFP * airflow_m3s
            heat_kw = 0.34 * ach * volume * (T_INSIDE - T_OUTSIDE) / 1000   # warming outdoor air

            rows.append({"strategy": strategy, "room": name, "minute": minute, "hour": hour,
                         "co2_ppm": co2, "ach": ach, "people": round(people),
                         "fan_kWh": fan_kw / 60, "heat_kWh": heat_kw / 60})
    return pd.DataFrame(rows)


def main():
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)

    strategies = ["Normal", "Auto (CO2)", "Always high"]
    df = pd.concat([simulate(s) for s in strategies], ignore_index=True)

    # ---------- Summary: one row per strategy ----------
    occ = df[(df.hour >= OCCUPIED[0]) & (df.hour < OCCUPIED[1])]
    summary = pd.DataFrame({
        "room_minutes_above_1000ppm": occ[occ.co2_ppm > 1000].groupby("strategy").size(),
        "worst_room_peak_ppm": df.groupby("strategy").co2_ppm.max().round(0),
        "mean_co2_occupied_ppm": occ.groupby("strategy").co2_ppm.mean().round(0),
        "fan_kWh_per_day": df.groupby("strategy").fan_kWh.sum().round(1),
        "heating_kWh_per_day": df.groupby("strategy").heat_kWh.sum().round(1),
    }).reindex(strategies).fillna(0)
    summary["total_kWh_per_day"] = summary.fan_kWh_per_day + summary.heating_kWh_per_day
    base = summary.loc["Normal"]
    summary["energy_vs_normal_pct"] = ((summary.total_kWh_per_day / base.total_kWh_per_day - 1) * 100).round(1)

    summary.to_csv(out_dir / "vent_summary.csv")
    df.to_csv(out_dir / "vent_timeseries.csv", index=False)

    pd.set_option("display.width", 140)
    print("\nVentilation experiment: one school day, 14 rooms\n")
    print(summary.to_string())

    # ---------- Chart ----------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.8), gridspec_kw={"width_ratios": [2, 1]})
    colors = {"Normal": "#566a64", "Auto (CO2)": "#0c8770", "Always high": "#2d6cb8"}
    for s in strategies:
        d = df[(df.strategy == s) & (df.room == "Lecture hall A")]
        ax1.plot(d.hour, d.co2_ppm, label=s, color=colors[s], lw=2)
    ax1.axhline(1000, color="#bf3826", ls="--", lw=1.2, label="1000 ppm limit")
    ax1.set(xlim=(7, 19), xlabel="Hour of day", ylabel="CO2 (ppm)", title="Lecture hall A: CO2 over the day")
    ax1.legend(frameon=False)
    ax1.grid(alpha=0.25)

    x = range(len(strategies))
    ax2.bar(x, summary.fan_kWh_per_day, color="#e2a637", label="Fans")
    ax2.bar(x, summary.heating_kWh_per_day, bottom=summary.fan_kWh_per_day, color="#bf3826", label="Heating fresh air")
    ax2.set_xticks(list(x), strategies)
    ax2.set(ylabel="kWh per day", title="Ventilation energy")
    for i, s in enumerate(strategies):
        ax2.text(i, summary.loc[s, "total_kWh_per_day"] + 5,
                 f"{summary.loc[s, 'room_minutes_above_1000ppm']:.0f} min\n>1000 ppm", ha="center", fontsize=8)
    ax2.legend(frameon=False, loc="upper left")
    ax2.set_ylim(0, summary.total_kWh_per_day.max() * 1.3)
    fig.tight_layout()
    fig.savefig(out_dir / "vent_experiment.png", dpi=150)
    print(f"\nSaved results and chart to {out_dir}")


if __name__ == "__main__":
    main()
