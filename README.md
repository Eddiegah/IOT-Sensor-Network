# IoT Sensor Network Simulator

A working demonstration of **distributed systems and networking concepts** using the real MQTT protocol — the same protocol used by billions of IoT devices in the real world (smart home hubs, industrial sensors, Tesla vehicles, AWS IoT).

Five independent simulated sensor nodes publish data over MQTT to a central hub. The hub performs fault detection and feeds a live Streamlit dashboard. Everything communicates through a real message broker (Mosquitto), not a fake in-process simulation.

> Built to learn and demonstrate: MQTT pub/sub, distributed process architecture, heartbeat-based fault detection, and real-time monitoring.

---

## What it looks like

```
┌─────────────┐     MQTT publish      ┌─────────────────────┐
│  node_1     │ ──────────────────►   │                     │
│ temperature │                       │  Mosquitto Broker   │
├─────────────┤                       │    localhost:1883   │
│  node_2     │ ──────────────────►   │                     │
│ temperature │                       └──────────┬──────────┘
├─────────────┤                                  │ MQTT subscribe
│  node_3     │ ──────────────────►              ▼
│  humidity   │                       ┌─────────────────────┐
├─────────────┤                       │       hub.py        │
│  node_4     │ ──────────────────►   │  - logs to SQLite   │
│  humidity   │                       │  - fault detection  │
├─────────────┤                       │  - heartbeat watch  │
│  node_5     │ ──────────────────►   └──────────┬──────────┘
│   motion    │                                  │ polls DB
└─────────────┘                                  ▼
                                       ┌─────────────────────┐
                                       │   Streamlit app.py  │
                                       │   live dashboard    │
                                       └─────────────────────┘
```

---

## Concepts demonstrated

### MQTT publish/subscribe
MQTT is a lightweight messaging protocol designed for constrained devices and unreliable networks. A **broker** (Mosquitto) sits in the middle. Publishers and subscribers never talk directly — they're fully decoupled.

- Nodes publish to: `sensors/{node_id}/{sensor_type}`
- Nodes publish heartbeats to: `sensors/{node_id}/heartbeat`
- The hub subscribes to: `sensors/+/+` (the `+` wildcard matches one topic level)

This is exactly how a real smart home hub, industrial SCADA system, or fleet tracker works.

### Distributed process architecture
Each sensor node is a completely independent OS process with its own MQTT connection, its own data generation loop, and no shared memory with any other node. Killing one doesn't affect the others. This mirrors real embedded hardware — each physical device is independent.

### Heartbeat-based fault detection
A classic pattern in distributed systems (used in Kubernetes, ZooKeeper, distributed databases, etc.):

1. Every node publishes a `heartbeat` message every 5 seconds
2. The hub's fault-detection thread checks every 5 seconds: *"has it been more than 15 seconds since the last heartbeat for this node?"*
3. If yes → mark **offline**, log an alert
4. When the heartbeat resumes → mark **online**, log a recovery alert

This distinguishes a crashed/offline node from one that's just not producing readings, and avoids false alarms for nodes in a known sleep cycle.

### Real-time monitoring dashboard
The Streamlit dashboard polls the SQLite database and reruns every 3 seconds, showing:
- Per-node status (🟢 online / 🔴 offline) with last reading and timestamp
- Rolling time-series charts per sensor type (Plotly)
- Alert log of fault events and anomalous readings

---

## Tech stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Message broker | Mosquitto 2.x | Industry-standard open-source MQTT broker |
| MQTT client | paho-mqtt 2.1.0 | Official Eclipse MQTT Python client |
| Database | SQLite (stdlib) | Zero-dependency time-series store |
| Dashboard | Streamlit 1.36 | Fast Python-native web UI |
| Charts | Plotly 5.22 | Interactive time-series charts |
| Data | pandas 2.2.2 | DataFrame queries from SQLite |

---

## Project structure

```
iot-sensor-network/
├── src/
│   ├── sensor_node.py      # Simulated sensor device — MQTT publisher
│   ├── hub.py              # Central hub — MQTT subscriber, fault detector
│   ├── fault_injector.py   # Kill/revive nodes to demo fault detection
│   └── launch_nodes.py     # Spawns all 5 nodes as separate processes
├── app.py                  # Streamlit live dashboard
├── mqtt_test.py            # Connectivity verification (run before sim)
├── data/
│   └── sensor_data.db      # SQLite store — created at runtime (gitignored)
├── requirements.txt
└── README.md
```

---

## Setup & running

### Prerequisites
- Python 3.9–3.12
- **Mosquitto MQTT broker** — this is a system service, not a pip package

### 1. Install Mosquitto

Download from **https://mosquitto.org/download/** (Windows 64-bit installer).

After installing, start the service:
```
# Windows (run PowerShell as Administrator)
net start mosquitto

# Verify it's listening on port 1883
netstat -an | findstr 1883
```

### 2. Python environment

```bash
py -3.11 -m venv venv

# Windows
venv\Scripts\python.exe -m pip install -r requirements.txt

# macOS/Linux
source venv/bin/activate && pip install -r requirements.txt
```

### 3. Verify everything works

```bash
venv\Scripts\python.exe mqtt_test.py
# Expected: ✅ MQTT CONNECTIVITY TEST PASSED
```

### 4. Run the simulation

You need **three terminal windows**, all in the project root.

**Terminal 1 — Hub** (start first):
```bash
venv\Scripts\python.exe src/hub.py
```
Expected output:
```
[hub] Connected to broker at localhost:1883
[hub] Subscribed to sensors/+/+
[hub] 📡 node_1/temperature: 22.4°C
```

**Terminal 2 — Launch all sensor nodes:**
```bash
venv\Scripts\python.exe src/launch_nodes.py
```
Spawns 5 nodes as separate processes. The hub terminal will start printing readings.

**Terminal 3 — Dashboard:**
```bash
venv\Scripts\streamlit.exe run app.py
```
Opens at **http://localhost:8501**

### 5. Demo fault detection

```bash
# Kill node_3 — simulates a dead battery or lost connection
venv\Scripts\python.exe src/fault_injector.py --kill node_3

# After ~15 seconds, node_3 goes 🔴 RED on the dashboard
# The hub logs: ❌ Node node_3 OFFLINE (no heartbeat for 15s)

# Revive it
venv\Scripts\python.exe src/fault_injector.py --revive node_3

# node_3 goes 🟢 GREEN again
# The hub logs: ✅ Node node_3 came back ONLINE
```

---

## Sensor simulation details

| Sensor | Behaviour |
|--------|-----------|
| Temperature | Slow random walk (±0.3°C per step), 3% chance of a spike (+3–8°C) |
| Humidity | Slow random walk (±0.5% per step), clamped 20–90% |
| Motion | Binary (0/1), ~5% trigger probability per reading |

Anomaly detection in the hub flags readings outside normal ranges and logs them as alerts on the dashboard.

---

## Troubleshooting

**Connection refused on port 1883**
→ Mosquitto isn't running. Run `net start mosquitto` as Administrator.

**Dashboard shows "waiting for data"**
→ Start `hub.py` first, then `launch_nodes.py`, then open the dashboard.

**Nodes exit immediately**
→ Test connectivity first: `venv\Scripts\python.exe mqtt_test.py`

---

## Future work / real-world path

- **TLS + authentication** — production MQTT uses port 8883 with client certificates. This project intentionally omits auth for simplicity.
- **Cloud broker** — swap `localhost:1883` for AWS IoT Core, HiveMQ Cloud, or EMQX to connect nodes over the internet.
- **Real hardware** — the sensor node code runs unmodified on a Raspberry Pi. Just point `BROKER_HOST` at a real broker.
- **Time-series DB** — replace SQLite with InfluxDB or TimescaleDB for production-scale workloads.
- **Sleep mode** — nodes can simulate battery-saving sleep cycles; the hub uses published sleep schedules to avoid false-alarm timeouts during intentional dormant periods.

---

## Why MQTT?

MQTT was designed in 1999 for monitoring oil pipelines over satellite links — low bandwidth, high latency, unreliable connections. Those constraints make it perfect for IoT:

- **Tiny overhead** — 2-byte fixed header vs. HTTP's kilobytes of headers
- **Broker decoupling** — publishers and subscribers never connect to each other directly
- **QoS levels** — guaranteed delivery even over unreliable networks
- **Last Will** — broker can notify subscribers if a client disconnects unexpectedly

It's now the default protocol for AWS IoT, Azure IoT Hub, Google Cloud IoT, and most commercial smart home platforms.
