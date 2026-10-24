#include <WiFi.h>
#include <PubSubClient.h>
#include "DHTesp.h"

// ---------- Network ----------
const char* WIFI_SSID   = "Wokwi-GUEST";        // Wokwi's virtual Wi-Fi
const char* WIFI_PASS   = "";                   // no password
const char* MQTT_BROKER = "broker.hivemq.com";  // free public broker
const int   MQTT_PORT   = 1883;
const char* TOPIC       = "gridsense-dauemi/energy-lab/state";

// ---------- Pins ----------
const int DHT_PIN = 15;
const int POT_PIN = 34;
const int LED_PIN = 2;

DHTesp dht;
WiFiClient espClient;            // the network connection
PubSubClient mqtt(espClient);    // MQTT runs on top of it

void connectWiFi() {
  Serial.print("Connecting to Wi-Fi");
  WiFi.begin(WIFI_SSID, WIFI_PASS, 6);
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print(".");
  }
  Serial.print(" connected! IP: ");
  Serial.println(WiFi.localIP());
}

void connectMQTT() {
  while (!mqtt.connected()) {
    Serial.print("Connecting to MQTT broker...");
    String clientId = "gridsense-" + String(random(0xffff), HEX);  // unique name
    if (mqtt.connect(clientId.c_str())) {
      Serial.println(" connected!");
    } else {
      Serial.print(" failed (state ");
      Serial.print(mqtt.state());
      Serial.println("), retrying in 2 s");
      delay(2000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  dht.setup(DHT_PIN, DHTesp::DHT22);
  pinMode(LED_PIN, OUTPUT);
  Serial.println("GridSense node starting...");
  connectWiFi();
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
}

void loop() {
  if (!mqtt.connected()) connectMQTT();   // reconnect if the link drops
  mqtt.loop();                            // keeps the MQTT connection alive

  // 1. Read the sensors
  TempAndHumidity data = dht.getTempAndHumidity();
  int raw = analogRead(POT_PIN);
  int co2 = map(raw, 0, 4095, 400, 2000);

  // 2. Decide
  bool alert = co2 > 1000;
  digitalWrite(LED_PIN, alert ? HIGH : LOW);

  // 3. Build the JSON
  String json = "{\"temp_C\":" + String(data.temperature, 1) +
                ",\"hum_pct\":" + String(data.humidity, 1) +
                ",\"co2_ppm\":" + String(co2) +
                ",\"vent_alert\":" + String(alert ? 1 : 0) + "}";

  // 4. Publish (true = retained, so new subscribers get the latest value)
  bool ok = mqtt.publish(TOPIC, json.c_str(), true);
  Serial.print(ok ? "Published: " : "Publish FAILED: ");
  Serial.println(json);

  delay(2000);
}