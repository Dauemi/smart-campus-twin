#include "DHTesp.h"

const int DHT_PIN = 15;   // DHT22 data pin
const int POT_PIN = 34;   // potentiometer = pretend CO2 sensor
const int LED_PIN = 2;    // ventilation alert LED

DHTesp dht;

void setup() {
  Serial.begin(115200);
  dht.setup(DHT_PIN, DHTesp::DHT22);
  pinMode(LED_PIN, OUTPUT);
  Serial.println("GridSense node starting...");
}

void loop() {
  // 1. Read the sensors
  TempAndHumidity data = dht.getTempAndHumidity();
  int raw = analogRead(POT_PIN);            // 0 to 4095
  int co2 = map(raw, 0, 4095, 400, 2000);   // convert to 400-2000 ppm

  // 2. Decide: is the air bad?
  bool alert = co2 > 1000;
  digitalWrite(LED_PIN, alert ? HIGH : LOW);

  // 3. Build the JSON message
  String json = "{\"temp_C\":" + String(data.temperature, 1) +
                ",\"hum_pct\":" + String(data.humidity, 1) +
                ",\"co2_ppm\":" + String(co2) +
                ",\"vent_alert\":" + String(alert ? 1 : 0) + "}";

  // 4. Report it
  Serial.println(json);
  delay(2000);   // wait 2 seconds
}