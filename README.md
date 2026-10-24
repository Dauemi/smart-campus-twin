# Smart Campus Twin

An IoT digital twin of a campus building, built for my IoT & Sensors,
Smart Grid and Sustainable Energy Transition modules.

## Architecture
Sensor nodes (Arduino) → MQTT broker (Mosquitto) → Web dashboard (3D twin)

## Project structure
- `firmware/` — Arduino code for the sensor nodes
- `broker/` — Mosquitto configuration
- `dashboard/` — live web dashboard
- `models/` — building physics and energy models
- `docs/` — diagrams and screenshots

## Progress
-- [x] Week 0: tools set up, MQTT pipeline tested
- [x] Sensor node (Wokwi: DHT22, CO₂, alert LED, Wi-Fi, MQTT)
- [x] Live dashboard (v1: room tiles)
- [ ] 3D building model
- [ ] Physics models
- [ ] Smart grid