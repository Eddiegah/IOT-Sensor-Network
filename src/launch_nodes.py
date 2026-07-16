"""
launch_nodes.py — Spawn multiple sensor nodes as separate processes

Each node runs as its own Python process, mimicking independent embedded
devices that happen to share the same MQTT broker.

Usage:
  python src/launch_nodes.py

Press Ctrl+C to stop all nodes.

The script writes a PID file for each node to data/pids/ so that
fault_injector.py can kill/revive individual nodes by name.
"""

import json
import signal
import subprocess
import sys
import time
from pathlib import Path

# ─── Node definitions ─────────────────────────────────────────────────────────
# Each entry describes one simulated device.
# Add or remove entries to change the network topology.

NODES = [
    {"node_id": "node_1", "sensor_type": "temperature", "interval": 3.0},
    {"node_id": "node_2", "sensor_type": "temperature", "interval": 4.0},
    {"node_id": "node_3", "sensor_type": "humidity",    "interval": 3.0},
    {"node_id": "node_4", "sensor_type": "humidity",    "interval": 5.0},
    {"node_id": "node_5", "sensor_type": "motion",      "interval": 2.0},
    # Uncomment below to add a sleep-mode node (stretch feature):
    # {"node_id": "node_6", "sensor_type": "temperature", "interval": 3.0,
    #  "sleep_mode": True, "sleep_active": 10.0, "sleep_dormant": 25.0},
]

# ─── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
SENSOR_SCRIPT = Path(__file__).parent / "sensor_node.py"
PID_DIR = PROJECT_ROOT / "data" / "pids"

# Use the same Python interpreter that's running this script
PYTHON = sys.executable


def launch_node(config: dict) -> subprocess.Popen:
    """Spawn a sensor_node.py process with the given configuration."""
    node_id = config["node_id"]
    cmd = [
        PYTHON, str(SENSOR_SCRIPT),
        "--node-id",      node_id,
        "--sensor-type",  config["sensor_type"],
        "--interval",     str(config.get("interval", 3.0)),
    ]
    if config.get("sleep_mode"):
        cmd.append("--sleep-mode")
        cmd += ["--sleep-active",  str(config.get("sleep_active", 5.0))]
        cmd += ["--sleep-dormant", str(config.get("sleep_dormant", 20.0))]

    # On Windows, each node gets its own console window
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

    proc = subprocess.Popen(cmd, **kwargs)
    return proc


def save_pid(config: dict, pid: int):
    """Write a PID record so fault_injector.py can track this node."""
    PID_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "node_id":     config["node_id"],
        "sensor_type": config["sensor_type"],
        "pid":         pid,
        "status":      "running",
        "python_exe":  PYTHON,
    }
    pid_file = PID_DIR / f"{config['node_id']}.json"
    with open(pid_file, "w") as f:
        json.dump(record, f, indent=2)


def cleanup_pids():
    """Remove all PID records on shutdown."""
    if PID_DIR.exists():
        for f in PID_DIR.glob("*.json"):
            f.unlink()


def main():
    processes: list[tuple[dict, subprocess.Popen]] = []

    print(f"Launching {len(NODES)} sensor nodes...")
    print("Each node opens in its own terminal window.")
    print("Press Ctrl+C here to stop all nodes.\n")

    for config in NODES:
        proc = launch_node(config)
        save_pid(config, proc.pid)
        processes.append((config, proc))
        print(f"  ✅ {config['node_id']:12s} ({config['sensor_type']:12s}) — PID {proc.pid}")
        time.sleep(0.3)  # slight stagger to avoid thundering herd on broker

    print(f"\nAll {len(processes)} nodes running.")
    print("Use  python src/fault_injector.py --kill   <node_id>  to kill a node")
    print("     python src/fault_injector.py --revive <node_id>  to revive it\n")

    def _sigint(sig, frame):
        print("\nShutting down all nodes...")
        for cfg, proc in processes:
            proc.terminate()
            print(f"  Stopped {cfg['node_id']}")
        cleanup_pids()
        print("All nodes stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    # Wait: monitor for any processes that crash and report
    while True:
        time.sleep(5)
        for cfg, proc in processes:
            if proc.poll() is not None:
                print(f"  ⚠ {cfg['node_id']} exited (returncode={proc.returncode})")


if __name__ == "__main__":
    main()
