"""
app.py — Live IoT Sensor Network Dashboard (Streamlit)

Reads from the SQLite database written by hub.py and displays:
  1. Node status grid — online/offline (green/red), current reading, last-seen
  2. Time-series chart — rolling history of sensor readings per node
  3. Alerts panel — recent fault events and anomalies

Auto-refreshes every 3 seconds using Streamlit's st.rerun() via a fragment
so only the data sections update, not the full page.

To run:
  venv\\Scripts\\streamlit.exe run app.py
"""

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ─── Config ───────────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "data" / "sensor_data.db"
REFRESH_INTERVAL = 3       # seconds between auto-refreshes
CHART_MAX_POINTS = 200     # max readings shown per node in charts
OFFLINE_TIMEOUT_SECS = 15  # must match hub.py

# ─── Page setup ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="IoT Sensor Network Dashboard",
    page_icon="📡",
    layout="wide",
)

st.title("📡 IoT Sensor Network — Live Dashboard")
st.caption(
    "Simulated multi-node sensor network using real MQTT (Mosquitto broker). "
    "Hub detects offline nodes via heartbeat timeouts."
)


# ─── Database helpers ─────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    """Return a read-only connection to the SQLite database."""
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def db_available() -> bool:
    return DB_PATH.exists()


def fetch_node_status(conn) -> pd.DataFrame:
    """Fetch the latest state for every known node."""
    df = pd.read_sql_query(
        "SELECT * FROM node_status ORDER BY node_id",
        conn
    )
    return df


def fetch_recent_readings(conn, limit: int = CHART_MAX_POINTS) -> pd.DataFrame:
    """Fetch the most recent readings for charting."""
    df = pd.read_sql_query(
        f"""
        SELECT node_id, sensor_type, value, unit, timestamp
        FROM readings
        ORDER BY id DESC
        LIMIT {limit * 10}
        """,
        conn
    )
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp")
    return df


def fetch_alerts(conn, limit: int = 30) -> pd.DataFrame:
    """Fetch the most recent alerts."""
    df = pd.read_sql_query(
        f"""
        SELECT node_id, alert_type, message, timestamp
        FROM alerts
        ORDER BY id DESC
        LIMIT {limit}
        """,
        conn
    )
    return df


# ─── UI helpers ───────────────────────────────────────────────────────────────

def status_badge(status: str) -> str:
    """Return a colored emoji badge for a node status."""
    badges = {
        "online":   "🟢 ONLINE",
        "offline":  "🔴 OFFLINE",
        "sleeping": "🟡 SLEEPING",
        "unknown":  "⚪ UNKNOWN",
    }
    return badges.get(status, f"⚪ {status.upper()}")


def format_last_seen(last_seen_str: str | None) -> str:
    """Show how long ago the node was last seen."""
    if not last_seen_str:
        return "never"
    try:
        last_seen = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - last_seen
        secs = int(delta.total_seconds())
        if secs < 5:
            return "just now"
        elif secs < 60:
            return f"{secs}s ago"
        elif secs < 3600:
            return f"{secs // 60}m ago"
        else:
            return f"{secs // 3600}h ago"
    except Exception:
        return last_seen_str


# ─── Main dashboard (wrapped in fragment for partial rerun) ───────────────────

def dashboard():
    """
    Dashboard content. Called on every page rerun.
    Auto-refresh is handled at the bottom of the file via time.sleep + st.rerun().
    """
    if not db_available():
        st.warning(
            "⚠️ Database not found. Make sure the hub is running:\n\n"
            "```\nvenv\\Scripts\\python.exe src/hub.py\n```"
        )
        return

    conn = get_conn()
    if conn is None:
        st.error("Could not open database.")
        return

    # Check if Mosquitto is reachable by seeing if there's any data
    node_df = fetch_node_status(conn)
    readings_df = fetch_recent_readings(conn)
    alerts_df = fetch_alerts(conn)

    conn.close()

    # ── Broker / hub status bar ───────────────────────────────────────────────
    col_status, col_refresh = st.columns([4, 1])
    with col_status:
        if node_df.empty:
            st.info(
                "Waiting for data... Is the hub running? "
                "(`venv\\Scripts\\python.exe src/hub.py`)\n\n"
                "Also verify Mosquitto is running on port 1883."
            )
        else:
            online = len(node_df[node_df["status"] == "online"])
            offline = len(node_df[node_df["status"] == "offline"])
            sleeping = len(node_df[node_df["status"] == "sleeping"])
            total = len(node_df)
            st.markdown(
                f"**Network:** {total} nodes — "
                f"🟢 {online} online  "
                f"🔴 {offline} offline  "
                f"🟡 {sleeping} sleeping"
            )
    with col_refresh:
        st.caption(f"🔄 Auto-refresh: {REFRESH_INTERVAL}s")

    if node_df.empty:
        return

    st.divider()

    # ── Node status grid ──────────────────────────────────────────────────────
    st.subheader("Node Status")

    cols = st.columns(min(len(node_df), 5))
    for i, row in node_df.iterrows():
        col = cols[i % len(cols)]
        status = row["status"] or "unknown"

        # Card background color via markdown hack
        border_color = {
            "online": "#28a745",
            "offline": "#dc3545",
            "sleeping": "#ffc107",
        }.get(status, "#6c757d")

        with col:
            st.markdown(
                f"""
                <div style="
                    border-left: 4px solid {border_color};
                    padding: 10px 12px;
                    border-radius: 4px;
                    background: #1e1e1e;
                    margin-bottom: 8px;
                ">
                    <b>{row['node_id']}</b><br>
                    <span style="color:{border_color}">{status_badge(status)}</span><br>
                    <small>
                        {row['sensor_type'] or '—'}: 
                        <b>{row['last_value'] if row['last_value'] is not None else '—'}
                        {row['last_unit'] or ''}</b>
                    </small><br>
                    <small style="color:#888">Last seen: {format_last_seen(row['last_seen'])}</small>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.divider()

    # ── Time-series charts ────────────────────────────────────────────────────
    st.subheader("Sensor Readings Over Time")

    if readings_df.empty:
        st.info("No readings recorded yet.")
    else:
        # Group by sensor_type for separate charts
        for sensor_type in sorted(readings_df["sensor_type"].unique()):
            type_df = readings_df[readings_df["sensor_type"] == sensor_type]

            fig = go.Figure()

            # One trace per node, limited to recent points
            for node_id in sorted(type_df["node_id"].unique()):
                node_df_sub = (
                    type_df[type_df["node_id"] == node_id]
                    .tail(CHART_MAX_POINTS)
                )
                if node_df_sub.empty:
                    continue

                fig.add_trace(go.Scatter(
                    x=node_df_sub["timestamp"],
                    y=node_df_sub["value"],
                    mode="lines+markers",
                    name=node_id,
                    marker=dict(size=4),
                    line=dict(width=1.5),
                ))

            unit = type_df["unit"].iloc[0] if not type_df.empty else ""
            fig.update_layout(
                title=f"{sensor_type.capitalize()} readings",
                xaxis_title="Time (UTC)",
                yaxis_title=f"Value ({unit})",
                template="plotly_dark",
                height=300,
                margin=dict(l=40, r=20, t=40, b=40),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Alerts panel ─────────────────────────────────────────────────────────
    st.subheader("Recent Alerts & Events")

    if alerts_df.empty:
        st.success("No alerts — all nodes nominal.")
    else:
        for _, alert in alerts_df.iterrows():
            alert_type = alert["alert_type"]
            icon = {
                "offline": "🔴",
                "online":  "🟢",
                "anomaly": "⚠️",
            }.get(alert_type, "ℹ️")

            # Color-coded alert rows
            bg = {
                "offline": "#3d0000",
                "online":  "#003d00",
                "anomaly": "#3d2600",
            }.get(alert_type, "#1e1e1e")

            ts = alert["timestamp"] or ""
            try:
                ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                ts = ts_dt.strftime("%H:%M:%S")
            except Exception:
                pass

            st.markdown(
                f"""
                <div style="
                    background:{bg};
                    padding:6px 10px;
                    border-radius:3px;
                    margin-bottom:4px;
                    font-size:0.85rem;
                ">
                    {icon} <b>[{alert_type.upper()}]</b>
                    <span style="color:#888">{ts}</span>
                    — <b>{alert['node_id']}</b>: {alert['message']}
                </div>
                """,
                unsafe_allow_html=True,
            )

    # Show last-updated timestamp
    st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")


# ─── Run ─────────────────────────────────────────────────────────────────────
dashboard()

# Auto-refresh: sleep then trigger a full page rerun
time.sleep(REFRESH_INTERVAL)
st.rerun()
