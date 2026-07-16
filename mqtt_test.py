"""
mqtt_test.py — MQTT connectivity verification

Connects to the local Mosquitto broker, publishes a test message,
and verifies it can be received back. Must pass before running
the full simulation.

Usage:
  venv\\Scripts\\python.exe mqtt_test.py
"""

import json
import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt

BROKER_HOST = "localhost"
BROKER_PORT = 1883
TEST_TOPIC = "iot_test/connectivity"
TIMEOUT_SECS = 5

received_messages = []


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"✅ Connected to Mosquitto at {BROKER_HOST}:{BROKER_PORT}")
        client.subscribe(TEST_TOPIC)
    else:
        print(f"❌ Connection failed: reason_code={reason_code}")
        sys.exit(1)


def on_message(client, userdata, msg):
    payload = json.loads(msg.payload.decode())
    received_messages.append(payload)
    print(f"✅ Received message: {payload}")


def main():
    print("=" * 50)
    print("MQTT Connectivity Test")
    print("=" * 50)

    # Check imports first
    try:
        import paho.mqtt.client
        import streamlit
        import pandas
        import plotly
        print("✅ All Python imports OK")
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Run: venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        sys.exit(1)

    # Test MQTT connectivity
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="mqtt_test"
    )
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"\nConnecting to {BROKER_HOST}:{BROKER_PORT}...")
    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=10)
    except ConnectionRefusedError:
        print(f"\n❌ Connection REFUSED at {BROKER_HOST}:{BROKER_PORT}")
        print("\nTroubleshooting:")
        print("  1. Download Mosquitto: https://mosquitto.org/download/")
        print("  2. Install the Windows .exe")
        print("  3. Start the service: net start mosquitto  (run as admin)")
        print("  4. Verify: netstat -an | findstr 1883")
        print("  5. If firewall blocks it: allow port 1883 inbound on localhost")
        sys.exit(1)
    except OSError as e:
        print(f"\n❌ OS error: {e}")
        sys.exit(1)

    client.loop_start()
    time.sleep(1)  # wait for connection

    # Publish a test message
    test_payload = json.dumps({
        "test": True,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "message": "MQTT connectivity test"
    })

    print(f"\nPublishing to {TEST_TOPIC}...")
    client.publish(TEST_TOPIC, test_payload, qos=1)

    # Wait for it to come back
    deadline = time.time() + TIMEOUT_SECS
    while time.time() < deadline and not received_messages:
        time.sleep(0.1)

    client.loop_stop()
    client.disconnect()

    if received_messages:
        print("\n" + "=" * 50)
        print("✅ MQTT CONNECTIVITY TEST PASSED")
        print("   Mosquitto is running and accepting connections.")
        print("   You can now start the full simulation.")
        print("=" * 50)
    else:
        print("\n❌ No message received within timeout.")
        print("   Mosquitto may be running but messages aren't routing correctly.")
        print("   Check that Mosquitto is configured to allow local connections.")
        sys.exit(1)


if __name__ == "__main__":
    main()
