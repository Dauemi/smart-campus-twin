"""
Virtual sensor nodes for the Smart Campus Twin.

Simulates 15 rooms and publishes one JSON message per room every 2 seconds,
in the same format as the GridSense ESP32 node.
Time runs fast: 1 tick (2 real seconds) = 1 simulated minute.
"""
import json
import random
import time

import paho.mqtt.client as mqtt

# ---------- Settings ----------
BROKER = "broker.hivemq.com"
PORT = 1883
PREFIX = "gridsense-dauemi"
TICK_SECONDS = 2        # real time between updates
START_HOUR = 8          # simulated clock starts at 08:00
AUTO_VENT = False       # GTB rule: boost ventilation above 1000 ppm (try True later!)

# ---------- The building (the Energy lab is your Wokwi node, so it's not here) ----------
#        id             name                  volume m³  max people  use
ROOMS = [
    ("lobby",       "Lobby & reception",      240,  15, "circulation"),
    ("cafe",        "Café & kitchen",         240,  30, "social"),
    ("plant",       "Technical room",         180,   1, "services"),
    ("hall-a",      "Lecture hall A",         600,  80, "teaching"),
    ("c101",        "Classroom 101",          270,  30, "teaching"),
    ("c102",        "Classroom 102",          270,  30, "teaching"),
    ("library",     "Library & study",        360,  40, "study"),
    ("meeting",     "Meeting room",           240,  12, "office"),
    ("open-office", "Open office",            480,  24, "office"),
    ("grid-lab",    "Smart grid lab",         360,  20, "lab"),
    ("computer",    "Computer lab",           300,  28, "teaching"),
    ("server",      "Server room",            120,   0, "services"),
    ("research",    "Research office",        120,   8, "office"),
    ("seminar",     "Seminar room",           432,  40, "teaching"),
    ("staff",       "Staff room",             288,  12, "social"),
]


def occupancy_fraction(use, hour):
    """How full a room is (0 to 1) at a given hour, by room use."""
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
    return 0  # services


class Room:
    def __init__(self, room_id, name, volume, max_people, use):
        self.id, self.name, self.volume, self.max_people, self.use = room_id, name, volume, max_people, use
        self.co2 = 430.0
        self.temp = 19.5
        self.hum = 40.0
        self.people = 0.0
        self.alert = False

    def step(self, hour):
        """Advance this room by one simulated minute."""
        # Occupancy moves smoothly towards the schedule, with a bit of randomness
        target = self.max_people * occupancy_fraction(self.use, hour) * random.uniform(0.8, 1.05)
        self.people += (target - self.people) * 0.3
        people = round(self.people)

        # Ventilation: air changes per hour (ach)
        ach = 2.0 if 7.5 <= hour < 18.5 else 0.3
        if AUTO_VENT and self.alert:
            ach = 5.0

        # CO2 mass balance (per minute, so divide the hourly rate by 60)
        generation = people * 0.018 / self.volume * 1e6     # ppm per hour from people
        removal = ach * (self.co2 - 420)                     # ppm per hour by ventilation
        self.co2 += (generation - removal) / 60 + random.gauss(0, 5)

        # Temperature and humidity: simple drift towards a target
        load = people / max(1, self.max_people)
        target_temp = 20.0 + 3.5 * load + (4.0 if self.id == "server" else 0)
        self.temp += (target_temp - self.temp) * 0.05 + random.gauss(0, 0.03)
        self.hum += ((38 + 15 * load) - self.hum) * 0.05

        # Alert with hysteresis: on above 1000, off below 800
        if self.co2 > 1000:
            self.alert = True
        elif self.co2 < 800:
            self.alert = False

    def payload(self):
        return {
            "temp_C": round(self.temp, 1),
            "hum_pct": round(self.hum, 1),
            "co2_ppm": round(self.co2),
            "vent_alert": 1 if self.alert else 0,
            "occupied": round(self.people),
        }


def main():
    rooms = [Room(*r) for r in ROOMS]
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=f"{PREFIX}-simulator-{random.randint(0, 9999)}")
    client.connect(BROKER, PORT, keepalive=30)
    client.loop_start()     # handles the network in the background
    print(f"Connected to {BROKER}. Publishing {len(rooms)} rooms. Press Ctrl+C to stop.")

    sim_minutes = START_HOUR * 60
    try:
        while True:
            hour = (sim_minutes % 1440) / 60
            clock = f"{int(hour):02d}:{sim_minutes % 60:02d}"
            for room in rooms:
                room.step(hour)
                client.publish(f"{PREFIX}/{room.id}/state", json.dumps(room.payload()), retain=True)
            client.publish(f"{PREFIX}/sim/clock", json.dumps({"time": clock}), retain=True)

            alerts = [r.name for r in rooms if r.alert]
            print(f"{clock}  rooms in CO2 alert: {len(alerts)}  {', '.join(alerts)}")

            sim_minutes += 1
            time.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        print("Stopped.")
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()