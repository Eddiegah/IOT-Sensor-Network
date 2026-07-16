"""
hub.py — Central IoT Hub

Subscribes to all sensor topics via MQTT wildcard:
  sensors/+/+        ← all node readings
  sensors/+/heartbeat ← all node heartbeats

Responsibilities:
  1. Log every reading to SQLite (data/sensor_data.db)
  2. Track last-seen time per node; flag as "offline" if heartbeat
     exceeds the configured timeout (OFFLINE_TIMEOUT_SECS)
  3. Write latest node state to SQLite so the dashboard can poll it
  4. Handle broker disconnections gracefully with auto-reconnect

MQTT pub/sub pattern:
  Sensor nodes publish → Broker (Mosquitto) → Hub subscribes
  The '+' wildcard in MQTT matches exactly one topic level.
  e.g. sensors/node_1/temperature   matches sensors/+/+
"""

import json
import signal
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt

# ─── Configuration ────────────────────────────────────────────────────────────
BROKER_HOST = "localhost"
BROKER_PORT = 1883

DB_PATH = Path(__file__).parent.parent / "data" / "sensor_data.db"

# How long (seconds) without a heartbeat before a node is marked offline.
# Must be longer than the node's HEARTBEAT_INTERVAL (5s) to avoid false alarms.
OFFLINE_TIMEOUT_SECS = 15

# How often (seconds) the fault-detection loop checks for stale nodes
FAULT_CHECK_INTERVAL = 5


# ─── Database setup ───────────────────────────────────────────────────────────

def init_db(db_path: Path) -> sqlite3.Connection:
    """
    Create (or connect to) the SQLite database and ensure all tables exist.

    Tables:
      readings    — time-series log of every sensor reading
      node_status — current state per node (latest reading + online/offline)
      alerts      — log of fault events (offline/online transitions, anomalies)
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS readings (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id       TEXT    NOT NULL,
            sensor_type   TEXT    NOT NULL,
            value         REAL,
            unit          TEXT,
            timestamp     TEXT    NOT NULL,
            received_at   TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS node_status (
            node_id       TEXT    PRIMARY KEY,
            sensor_type   TEXT,
            last_value    REAL,
            last_unit     TEXT,
            last_seen     TEXT,
            status        TEXT    DEFAULT 'unknown',
            sleep_mode    INTEGER DEFAULT 0,
            wake_at       TEXT
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id     TEXT    NOT NULL,
            alert_type  TEXT    NOT NULL,
            message     TEXT,
            timestamp   TEXT    NOT NULL
        );
    """)
    conn.commit()
    return conn


# ─── Hub class ────────────────────────────────────────────────────────────────

class Hub:
    """
    Central hub that aggregates all sensor data over MQTT.

    The heartbeat/timeout fault-detection works like this:
      - Each time a heartbeat arrives, we record the timestamp in
        self._last_heartbeat[node_id].
      - A background thread (the fault detector) runs every
        FAULT_CHECK_INTERVAL seconds and compares now() against each
        node's last heartbeat time.
      - If the gap exceeds OFFLINE_TIMEOUT_SECS, the node is marked
        offline and an alert is logged.
      - When a heartbeat arrives for a node that was previously offline,
        it's marked back online and another alert is logged.
    """

    def __init__(self):
        self.conn = init_db(DB_PATH)
        self._db_lock = threading.Lock()  # SQLite isn't thread-safe by default

        # node_id → last heartbeat epoch timestamp
        self._last_heartbeat: dict[str, float] = {}
        # node_id → sleep schedule info (for false-alarm suppression)
        self._sleep_schedules: dict[str, dict] = {}
        # node_id → current online/offline status
        self._node_status: dict[str, str] = {}

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="iot_hub"
        )
        self.client.reconnect_delay_set(min_delay=1, max_delay=5)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self._running = False

    # ── MQTT callbacks ────────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            print(f"[hub] Connected to broker at {BROKER_HOST}:{BROKER_PORT}")
            # Subscribe to all sensor data and heartbeat topics.
            # MQTT wildcard '+' matches a single topic level.
            client.subscribe("sensors/+/+", qos=1)
            print("[hub] Subscribed to sensors/+/+")
        else:
            print(f"[hub] Connection failed: reason_code={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        """
        Handle broker disconnection.
        We call reconnect() manually so loop_start()'s background thread
        can re-establish the connection without restarting.
        """
        if self._running and reason_code != 0:
            print(f"[hub] Disconnected (reason_code={reason_code}). Reconnecting...")
            try:
                client.reconnect()
            except Exception:
                pass

    def _on_message(self, client, userdata, msg):
        """Route incoming MQTT messages to the appropriate handler."""
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[hub] Malformed message on {topic}: {e}")
            return

        # Determine if this is a heartbeat or a sensor reading
        # Topic format: sensors/{node_id}/{sensor_type_or_heartbeat}
        parts = topic.split("/")
        if len(parts) != 3:
            return

        _, node_id, topic_suffix = parts

        if topic_suffix == "heartbeat":
            self._handle_heartbeat(node_id, payload)
        else:
            self._handle_reading(node_id, topic_suffix, payload)

    # ── Message handlers ──────────────────────────────────────────────────────

    def _handle_heartbeat(self, node_id: str, payload: dict):
        """
        Update the node's last-seen timestamp and handle sleep-mode scheduling.

        If the node was previously offline and is now sending heartbeats again,
        log an "online" alert.
        """
        now = time.time()
        self._last_heartbeat[node_id] = now

        # Update sleep schedule if the node publishes one
        status_str = payload.get("status", "alive")
        if payload.get("sleep_mode"):
            self._sleep_schedules[node_id] = {
                "sleep_dormant_secs": payload.get("sleep_dormant_secs", 20),
                "wake_at": payload.get("wake_at"),
                "status": status_str,
            }
        else:
            self._sleep_schedules.pop(node_id, None)

        # Was this node previously offline?
        prev_status = self._node_status.get(node_id, "unknown")
        if prev_status == "offline":
            print(f"[hub] ✅ Node {node_id} came back ONLINE")
            self._log_alert(node_id, "online", f"Node {node_id} reconnected")

        self._node_status[node_id] = "online"

        # Update node_status table
        received_at = datetime.utcnow().isoformat() + "Z"
        with self._db_lock:
            self.conn.execute("""
                INSERT INTO node_status (node_id, last_seen, status, sleep_mode, wake_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    status    = excluded.status,
                    sleep_mode = excluded.sleep_mode,
                    wake_at   = excluded.wake_at
            """, (
                node_id,
                received_at,
                "sleeping" if status_str == "sleeping" else "online",
                1 if payload.get("sleep_mode") else 0,
                payload.get("wake_at"),
            ))
            self.conn.commit()

    def _handle_reading(self, node_id: str, sensor_type: str, payload: dict):
        """
        Store a sensor reading and check for anomalous values.
        """
        value = payload.get("value")
        unit = payload.get("unit", "")
        timestamp = payload.get("timestamp", datetime.utcnow().isoformat() + "Z")
        received_at = datetime.utcnow().isoformat() + "Z"

        print(f"[hub] 📡 {node_id}/{sensor_type}: {value}{unit}")

        # Check for anomalous readings
        self._check_anomaly(node_id, sensor_type, value)

        with self._db_lock:
            # Log to readings table (time-series)
            self.conn.execute("""
                INSERT INTO readings (node_id, sensor_type, value, unit, timestamp, received_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (node_id, sensor_type, value, unit, timestamp, received_at))

            # Update latest state in node_status table
            self.conn.execute("""
                INSERT INTO node_status (node_id, sensor_type, last_value, last_unit, last_seen, status)
                VALUES (?, ?, ?, ?, ?, 'online')
                ON CONFLICT(node_id) DO UPDATE SET
                    sensor_type = excluded.sensor_type,
                    last_value  = excluded.last_value,
                    last_unit   = excluded.last_unit,
                    last_seen   = excluded.last_seen,
                    status      = 'online'
            """, (node_id, sensor_type, value, unit, received_at))

            self.conn.commit()

    def _check_anomaly(self, node_id: str, sensor_type: str, value):
        """Flag readings that exceed realistic thresholds."""
        alert = None
        if sensor_type == "temperature" and value is not None:
            if value > 30.0:
                alert = f"High temperature: {value}°C on {node_id}"
            elif value < 15.0:
                alert = f"Low temperature: {value}°C on {node_id}"
        elif sensor_type == "humidity" and value is not None:
            if value > 80.0:
                alert = f"High humidity: {value}% on {node_id}"
        elif sensor_type == "motion" and value == 1:
            alert = f"Motion detected on {node_id}"

        if alert:
            print(f"[hub] ⚠ ANOMALY: {alert}")
            self._log_alert(node_id, "anomaly", alert)

    def _log_alert(self, node_id: str, alert_type: str, message: str):
        """Write an alert record to SQLite."""
        timestamp = datetime.utcnow().isoformat() + "Z"
        with self._db_lock:
            self.conn.execute("""
                INSERT INTO alerts (node_id, alert_type, message, timestamp)
                VALUES (?, ?, ?, ?)
            """, (node_id, alert_type, message, timestamp))
            self.conn.commit()
        print(f"[hub] 🔔 ALERT [{alert_type}] {node_id}: {message}")

    # ── Fault detection loop ──────────────────────────────────────────────────

    def _fault_detection_loop(self):
        """
        Background thread: checks every FAULT_CHECK_INTERVAL seconds
        whether any known node has exceeded OFFLINE_TIMEOUT_SECS without
        a heartbeat.

        Sleep-mode awareness: if a node published a sleep schedule and
        we're within its expected dormant window, we don't alarm.
        This distinguishes "intentionally asleep" from "actually dead".
        """
        print(f"[hub] Fault detector running (timeout={OFFLINE_TIMEOUT_SECS}s)")
        while self._running:
            time.sleep(FAULT_CHECK_INTERVAL)
            now = time.time()
            for node_id, last_hb in list(self._last_heartbeat.items()):
                elapsed = now - last_hb

                # Check if node is in a known sleep cycle
                schedule = self._sleep_schedules.get(node_id, {})
                if schedule.get("status") == "sleeping":
                    dormant_secs = schedule.get("sleep_dormant_secs", 20)
                    # Give 5 extra seconds of grace
                    if elapsed < dormant_secs + 5:
                        continue  # Node is intentionally sleeping, don't alarm

                if elapsed > OFFLINE_TIMEOUT_SECS:
                    current_status = self._node_status.get(node_id, "unknown")
                    if current_status != "offline":
                        print(f"[hub] ❌ Node {node_id} OFFLINE "
                              f"(no heartbeat for {elapsed:.0f}s)")
                        self._node_status[node_id] = "offline"
                        self._log_alert(
                            node_id, "offline",
                            f"Node {node_id} went offline "
                            f"(no heartbeat for {elapsed:.0f}s)"
                        )
                        # Update node_status table
                        with self._db_lock:
                            self.conn.execute("""
                                UPDATE node_status SET status='offline'
                                WHERE node_id=?
                            """, (node_id,))
                            self.conn.commit()

    # ── Start/stop ────────────────────────────────────────────────────────────

    def start(self):
        """Connect to broker, subscribe, and start processing messages."""
        self._running = True

        try:
            # keepalive=60: Mosquitto won't drop the connection for 60s of inactivity
            self.client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        except ConnectionRefusedError:
            print(
                "\n[hub] ERROR: Cannot connect to Mosquitto at "
                f"{BROKER_HOST}:{BROKER_PORT}.\n"
                "  → Is Mosquitto installed and running?\n"
                "  → Run: net start mosquitto   (as admin)\n"
                "  → Check: netstat -an | findstr 1883\n"
            )
            sys.exit(1)

        # Start fault-detection in a daemon thread
        fault_thread = threading.Thread(
            target=self._fault_detection_loop, daemon=True
        )
        fault_thread.start()

        print("[hub] Hub started. Listening for sensor data...")
        # loop_start() runs MQTT in background thread; main thread keeps alive
        self.client.loop_start()
        while self._running:
            time.sleep(1)

    def stop(self):
        self._running = False
        self.client.loop_stop()
        self.client.disconnect()
        self.conn.close()
        print("[hub] Hub stopped.")


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    hub = Hub()

    def _sigint(sig, frame):
        print("\n[hub] Shutting down...")
        hub.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)
    hub.start()


if __name__ == "__main__":
    main()
