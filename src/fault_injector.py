"""
fault_injector.py — Fault injection utility

Allows deliberate killing and reviving of sensor node processes
to demonstrate fault detection in the hub and dashboard.

Usage:
  python src/fault_injector.py --kill   node_1
  python src/fault_injector.py --revive node_1 --sensor-type temperature

The injector uses a PID file in data/pids/ to track running node processes.
launch_nodes.py writes these PID files when it spawns nodes.

Windows note: We use taskkill to terminate processes, since Unix signals
(SIGKILL etc.) are not reliably available on Windows via Python's os.kill.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ─── PID store ───────────────────────────────────────────────────────────────
# launch_nodes.py writes a JSON file per node here.
PID_DIR = Path(__file__).parent.parent / "data" / "pids"


def get_pid_file(node_id: str) -> Path:
    return PID_DIR / f"{node_id}.json"


def load_node_info(node_id: str) -> dict | None:
    pid_file = get_pid_file(node_id)
    if not pid_file.exists():
        print(f"[injector] No PID record found for {node_id}.")
        print(f"           Expected: {pid_file}")
        print("           Is the node running via launch_nodes.py?")
        return None
    with open(pid_file) as f:
        return json.load(f)


def save_node_info(node_id: str, info: dict):
    PID_DIR.mkdir(parents=True, exist_ok=True)
    with open(get_pid_file(node_id), "w") as f:
        json.dump(info, f, indent=2)


def delete_node_info(node_id: str):
    pid_file = get_pid_file(node_id)
    if pid_file.exists():
        pid_file.unlink()


# ─── Kill a node ─────────────────────────────────────────────────────────────

def kill_node(node_id: str):
    """
    Terminate a running sensor node process.
    Simulates: dead battery, lost network connection, hardware failure.
    """
    info = load_node_info(node_id)
    if info is None:
        return

    pid = info.get("pid")
    if pid is None:
        print(f"[injector] PID record for {node_id} has no PID entry.")
        return

    print(f"[injector] 💀 Killing node {node_id} (PID {pid})...")

    # On Windows, use taskkill; on Unix, os.kill would suffice
    if sys.platform == "win32":
        result = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"[injector] ✅ Node {node_id} (PID {pid}) killed.")
            # Mark as killed in the PID record
            info["status"] = "killed"
            save_node_info(node_id, info)
        else:
            # Process may have already exited
            print(f"[injector] taskkill output: {result.stdout.strip()} {result.stderr.strip()}")
            print(f"[injector] Node {node_id} may have already stopped.")
    else:
        # Unix fallback
        try:
            os.kill(pid, 9)
            print(f"[injector] ✅ Node {node_id} (PID {pid}) killed.")
            info["status"] = "killed"
            save_node_info(node_id, info)
        except ProcessLookupError:
            print(f"[injector] Process {pid} not found — already stopped?")
        except PermissionError:
            print(f"[injector] Permission denied killing PID {pid}.")


# ─── Revive a node ────────────────────────────────────────────────────────────

def revive_node(node_id: str, sensor_type: str | None, interval: float):
    """
    Restart a previously killed sensor node.
    Simulates: battery replaced, network restored, hardware rebooted.

    If sensor_type is not provided, we attempt to read it from the PID record.
    """
    info = load_node_info(node_id)

    if info is None:
        # No record at all — create a fresh one if sensor_type is provided
        if sensor_type is None:
            print(f"[injector] No record for {node_id} and no --sensor-type given.")
            print("           Provide --sensor-type to revive a node with no history.")
            return
        info = {}

    resolved_type = sensor_type or info.get("sensor_type")
    if resolved_type is None:
        print(f"[injector] Cannot determine sensor type for {node_id}.")
        print("           Use --sensor-type <temperature|humidity|motion>")
        return

    python_exe = info.get("python_exe", sys.executable)
    node_script = Path(__file__).parent / "sensor_node.py"

    cmd = [
        python_exe, str(node_script),
        "--node-id", node_id,
        "--sensor-type", resolved_type,
        "--interval", str(interval),
    ]

    print(f"[injector] 🔄 Reviving node {node_id} ({resolved_type})...")
    print(f"           Command: {' '.join(cmd)}")

    # Spawn the node in a new console window on Windows so it's visible
    if sys.platform == "win32":
        proc = subprocess.Popen(
            cmd,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    else:
        proc = subprocess.Popen(cmd)

    time.sleep(0.5)  # brief wait to see if it immediately crashes

    if proc.poll() is not None:
        print(f"[injector] ❌ Node {node_id} exited immediately (returncode={proc.returncode}).")
        return

    new_info = {
        "node_id": node_id,
        "sensor_type": resolved_type,
        "pid": proc.pid,
        "status": "running",
        "python_exe": python_exe,
    }
    save_node_info(node_id, new_info)
    print(f"[injector] ✅ Node {node_id} revived (new PID {proc.pid}).")


# ─── List nodes ──────────────────────────────────────────────────────────────

def list_nodes():
    """Show all tracked nodes and their recorded status."""
    if not PID_DIR.exists() or not any(PID_DIR.glob("*.json")):
        print("[injector] No node PID records found.")
        print(f"           Expected records in: {PID_DIR}")
        return

    print(f"{'NODE ID':<20} {'SENSOR TYPE':<15} {'PID':<10} {'STATUS'}")
    print("-" * 60)
    for pid_file in sorted(PID_DIR.glob("*.json")):
        with open(pid_file) as f:
            info = json.load(f)
        print(f"{info.get('node_id','?'):<20} "
              f"{info.get('sensor_type','?'):<15} "
              f"{info.get('pid','?'):<10} "
              f"{info.get('status','?')}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fault Injector — kill or revive sensor node processes"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--kill", metavar="NODE_ID",
                       help="Kill a running sensor node")
    group.add_argument("--revive", metavar="NODE_ID",
                       help="Restart a killed sensor node")
    group.add_argument("--list", action="store_true",
                       help="List all tracked nodes")

    parser.add_argument("--sensor-type", choices=["temperature", "humidity", "motion"],
                        help="Sensor type for --revive (read from record if omitted)")
    parser.add_argument("--interval", type=float, default=3.0,
                        help="Publish interval for revived node (default: 3.0)")

    args = parser.parse_args()

    if args.list:
        list_nodes()
    elif args.kill:
        kill_node(args.kill)
    elif args.revive:
        revive_node(args.revive, args.sensor_type, args.interval)


if __name__ == "__main__":
    main()
