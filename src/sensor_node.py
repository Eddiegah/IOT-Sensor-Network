"""
sensor_node.py — Simulated IoT sensor node

Each node connects to the Mosquitto MQTT broker and publishes:
  - Sensor readings to:  sensors/{node_id}/{sensor_type}
  - Heartbeat messages to: sensors/{node_id}/heartbeat

MQTT pub/sub pattern:
  Publisher (this file) → Broker (Mosquitto) → Subscriber (hub.py)

The heartbeat is separate from readings so the hub can detect
a node that's still alive but not producing data (e.g. sensor fault)
versus a node that's fully offline.
"""

import argparse
import json
import random
import signal
import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt

# ─── MQTT broker settings ───────────────────────────────────────────────────
BROKER_HOST = "localhost"
BROKER_PORT = 1883

# ─── Sensor simulation parameters ────────────────────────────────────────────
TEMP_BASE = 22.0          # °C baseline
TEMP_DRIFT_MAX = 0.3      # max drift per reading (slow drift)
TEMP_SPIKE_PROB = 0.03    # 3% chance of a sudden spike

HUMIDITY_BASE = 55.0      # % baseline
HUMIDITY_DRIFT_MAX = 0.5

HEARTBEAT_INTERVAL = 5    # seconds between heartbeats


class SensorNode:
    """
    Simulates a single IoT sensor node.

    Publishes to:
      sensors/{node_id}/{sensor_type}   — sensor readings (JSON)
      sensors/{node_id}/heartbeat       — periodic alive signal (JSON)

    The node uses paho-mqtt's loop_start() so the MQTT network loop
    runs in a background thread, allowing the main thread to sleep
    between publish cycles without blocking reconnect logic.
    """

    def __init__(self, node_id: str, sensor_type: str,
                 publish_interval: float = 3.0,
                 sleep_mode: bool = False,
                 sleep_active_secs: float = 5.0,
                 sleep_dormant_secs: float = 20.0):
        self.node_id = node_id
        self.sensor_type = sensor_type
        self.publish_interval = publish_interval
        self.sleep_mode = sleep_mode
        self.sleep_active_secs = sleep_active_secs
        self.sleep_dormant_secs = sleep_dormant_secs

        # State for realistic sensor simulation
        self._temp_current = TEMP_BASE + random.uniform(-3, 3)
        self._humidity_current = HUMIDITY_BASE + random.uniform(-10, 10)

        # MQTT topic paths
        self.data_topic = f"sensors/{node_id}/{sensor_type}"
        self.heartbeat_topic = f"sensors/{node_id}/heartbeat"

        # Set up MQTT client (paho v2 requires callback_api_version)
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"node_{node_id}"
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        self._running = False
        self._last_heartbeat = 0.0

    # ── MQTT callbacks ────────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            print(f"[{self.node_id}] Connected to broker at {BROKER_HOST}:{BROKER_PORT}")
        else:
            print(f"[{self.node_id}] Connection failed: reason_code={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        if self._running:
            print(f"[{self.node_id}] Disconnected (reason_code={reason_code}), will reconnect...")

    # ── Sensor data generation ────────────────────────────────────────────────

    def _generate_reading(self) -> dict:
        """
        Generate a realistic sensor reading.

        Temperature: slow random walk + occasional spike
        Humidity:    slow random walk
        Motion:      binary, low probability trigger
        """
        if self.sensor_type == "temperature":
            # Random walk — drift a little each step
            drift = random.uniform(-TEMP_DRIFT_MAX, TEMP_DRIFT_MAX)
            self._temp_current += drift
            # Clamp to realistic indoor range
            self._temp_current = max(15.0, min(35.0, self._temp_current))
            # Occasional spike (e.g. someone opened a door)
            value = self._temp_current
            if random.random() < TEMP_SPIKE_PROB:
                value += random.uniform(3.0, 8.0)
                print(f"[{self.node_id}] ⚠ Temperature spike: {value:.1f}°C")
            return {"value": round(value, 2), "unit": "°C"}

        elif self.sensor_type == "humidity":
            drift = random.uniform(-HUMIDITY_DRIFT_MAX, HUMIDITY_DRIFT_MAX)
            self._humidity_current += drift
            self._humidity_current = max(20.0, min(90.0, self._humidity_current))
            return {"value": round(self._humidity_current, 2), "unit": "%"}

        elif self.sensor_type == "motion":
            # Binary: 1 = motion detected, 0 = no motion
            # ~5% chance of detection per reading
            triggered = 1 if random.random() < 0.05 else 0
            return {"value": triggered, "unit": "binary"}

        else:
            return {"value": 0.0, "unit": "unknown"}

    def _make_payload(self, reading: dict) -> str:
        """Wrap reading in a JSON envelope with timestamp and node metadata."""
        payload = {
            "node_id": self.node_id,
            "sensor_type": self.sensor_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **reading
        }
        return json.dumps(payload)

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    def _send_heartbeat(self):
        """
        Publish a heartbeat so the hub knows this node is alive.
        The hub watches these; if one goes missing for > timeout seconds,
        the node is flagged as offline.
        """
        payload = json.dumps({
            "node_id": self.node_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status": "alive",
            # If sleep_mode is enabled, publish the schedule so the hub
            # doesn't false-alarm during dormant periods.
            "sleep_mode": self.sleep_mode,
            "sleep_active_secs": self.sleep_active_secs if self.sleep_mode else None,
            "sleep_dormant_secs": self.sleep_dormant_secs if self.sleep_mode else None,
        })
        self.client.publish(self.heartbeat_topic, payload, qos=1)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def start(self):
        """Connect and begin publishing. Blocks until stopped."""
        self._running = True

        try:
            self.client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        except ConnectionRefusedError:
            print(
                f"\n[{self.node_id}] ERROR: Cannot connect to Mosquitto at "
                f"{BROKER_HOST}:{BROKER_PORT}.\n"
                "  → Is Mosquitto installed and running?\n"
                "  → Check: net start mosquitto   (run as admin)\n"
                "  → Check: netstat -an | findstr 1883\n"
            )
            sys.exit(1)
        except OSError as e:
            print(f"[{self.node_id}] ERROR connecting to broker: {e}")
            sys.exit(1)

        # loop_start() runs the MQTT network loop in a background thread
        self.client.loop_start()

        print(f"[{self.node_id}] Publishing {self.sensor_type} readings "
              f"every {self.publish_interval}s on topic: {self.data_topic}")
        if self.sleep_mode:
            print(f"[{self.node_id}] Sleep mode enabled: "
                  f"active={self.sleep_active_secs}s, dormant={self.sleep_dormant_secs}s")

        try:
            if self.sleep_mode:
                self._run_with_sleep()
            else:
                self._run_normal()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _run_normal(self):
        """Standard publish loop: reading + heartbeat on a fixed interval."""
        while self._running:
            now = time.time()

            # Publish sensor reading
            reading = self._generate_reading()
            payload = self._make_payload(reading)
            self.client.publish(self.data_topic, payload, qos=1)
            print(f"[{self.node_id}] Published {self.sensor_type}: "
                  f"{reading['value']}{reading['unit']}")

            # Publish heartbeat every HEARTBEAT_INTERVAL seconds
            if now - self._last_heartbeat >= HEARTBEAT_INTERVAL:
                self._send_heartbeat()
                self._last_heartbeat = now

            time.sleep(self.publish_interval)

    def _run_with_sleep(self):
        """
        Sleep-cycle loop (stretch feature):
        Active for sleep_active_secs, then dormant for sleep_dormant_secs.
        During dormant period, no data or heartbeat is published.
        The hub uses the published schedule to avoid false-alarming.
        """
        while self._running:
            # ── Active phase ──────────────────────────────────────────────
            active_end = time.time() + self.sleep_active_secs
            while self._running and time.time() < active_end:
                now = time.time()
                reading = self._generate_reading()
                payload = self._make_payload(reading)
                self.client.publish(self.data_topic, payload, qos=1)
                print(f"[{self.node_id}] [ACTIVE] {self.sensor_type}: "
                      f"{reading['value']}{reading['unit']}")

                if now - self._last_heartbeat >= HEARTBEAT_INTERVAL:
                    self._send_heartbeat()
                    self._last_heartbeat = now

                time.sleep(self.publish_interval)

            if not self._running:
                break

            # ── Publish a "going to sleep" heartbeat before dormancy ──────
            sleep_payload = json.dumps({
                "node_id": self.node_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "status": "sleeping",
                "sleep_mode": True,
                "sleep_dormant_secs": self.sleep_dormant_secs,
                "wake_at": datetime.utcfromtimestamp(
                    time.time() + self.sleep_dormant_secs
                ).isoformat() + "Z",
            })
            self.client.publish(self.heartbeat_topic, sleep_payload, qos=1)
            print(f"[{self.node_id}] 💤 Entering sleep for {self.sleep_dormant_secs}s")
            self._last_heartbeat = time.time()

            # ── Dormant phase (no publishing) ─────────────────────────────
            time.sleep(self.sleep_dormant_secs)
            print(f"[{self.node_id}] 🔔 Waking up from sleep")

    def stop(self):
        """Gracefully disconnect."""
        self._running = False
        self.client.loop_stop()
        self.client.disconnect()
        print(f"[{self.node_id}] Stopped.")


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="IoT Sensor Node Simulator")
    parser.add_argument("--node-id", required=True,
                        help="Unique node identifier, e.g. node_1")
    parser.add_argument("--sensor-type", required=True,
                        choices=["temperature", "humidity", "motion"],
                        help="Type of sensor to simulate")
    parser.add_argument("--interval", type=float, default=3.0,
                        help="Seconds between readings (default: 3)")
    parser.add_argument("--sleep-mode", action="store_true",
                        help="Enable simulated sleep/wake cycle")
    parser.add_argument("--sleep-active", type=float, default=5.0,
                        help="Seconds active before sleeping (default: 5)")
    parser.add_argument("--sleep-dormant", type=float, default=20.0,
                        help="Seconds dormant per sleep cycle (default: 20)")
    args = parser.parse_args()

    node = SensorNode(
        node_id=args.node_id,
        sensor_type=args.sensor_type,
        publish_interval=args.interval,
        sleep_mode=args.sleep_mode,
        sleep_active_secs=args.sleep_active,
        sleep_dormant_secs=args.sleep_dormant,
    )

    # Handle Ctrl+C gracefully
    def _sigint(sig, frame):
        print(f"\n[{args.node_id}] Shutting down...")
        node.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    node.start()


if __name__ == "__main__":
    main()
