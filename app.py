"""
app.py — IoT Sensor Network — Live Dashboard
Professional dark UI with custom CSS, animated status indicators,
metric cards, and real-time Plotly charts.
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
REFRESH_INTERVAL = 3
CHART_MAX_POINTS = 150

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="IoT Network Monitor",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* ── Global ── */
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

  html, body, [class*="css"] {
      font-family: 'Inter', sans-serif;
  }

  /* Hide Streamlit chrome */
  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding: 1.5rem 2rem 2rem 2rem; }

  /* ── Header banner ── */
  .header-banner {
      background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
      border: 1px solid #2a2a4a;
      border-radius: 16px;
      padding: 28px 36px;
      margin-bottom: 24px;
      position: relative;
      overflow: hidden;
  }
  .header-banner::before {
      content: '';
      position: absolute;
      top: -50%;
      left: -50%;
      width: 200%;
      height: 200%;
      background: radial-gradient(ellipse at 70% 50%, rgba(99,102,241,0.08) 0%, transparent 60%);
      pointer-events: none;
  }
  .header-title {
      font-size: 1.9rem;
      font-weight: 700;
      color: #f1f5f9;
      letter-spacing: -0.5px;
      margin: 0 0 4px 0;
  }
  .header-subtitle {
      font-size: 0.85rem;
      color: #64748b;
      margin: 0;
      font-weight: 400;
  }
  .header-live-dot {
      display: inline-block;
      width: 8px;
      height: 8px;
      background: #22c55e;
      border-radius: 50%;
      margin-right: 6px;
      animation: pulse-green 2s infinite;
  }
  @keyframes pulse-green {
      0%   { box-shadow: 0 0 0 0 rgba(34,197,94,0.6); }
      70%  { box-shadow: 0 0 0 8px rgba(34,197,94,0); }
      100% { box-shadow: 0 0 0 0 rgba(34,197,94,0); }
  }

  /* ── Stat pills (top row) ── */
  .stat-pill {
      background: #0f172a;
      border: 1px solid #1e293b;
      border-radius: 12px;
      padding: 18px 20px;
      text-align: center;
  }
  .stat-pill .stat-value {
      font-size: 2rem;
      font-weight: 700;
      line-height: 1;
      margin-bottom: 4px;
  }
  .stat-pill .stat-label {
      font-size: 0.72rem;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 1px;
      font-weight: 500;
  }
  .stat-green  { color: #22c55e; }
  .stat-red    { color: #ef4444; }
  .stat-yellow { color: #f59e0b; }
  .stat-blue   { color: #6366f1; }
  .stat-white  { color: #f1f5f9; }

  /* ── Section headers ── */
  .section-header {
      font-size: 0.72rem;
      font-weight: 600;
      color: #475569;
      text-transform: uppercase;
      letter-spacing: 1.5px;
      margin: 28px 0 12px 0;
      padding-bottom: 8px;
      border-bottom: 1px solid #1e293b;
  }

  /* ── Node cards ── */
  .node-card {
      background: #0f172a;
      border: 1px solid #1e293b;
      border-radius: 14px;
      padding: 18px 20px;
      margin-bottom: 10px;
      transition: border-color 0.3s ease;
      position: relative;
      overflow: hidden;
  }
  .node-card:hover {
      border-color: #334155;
  }
  .node-card-online  { border-left: 3px solid #22c55e; }
  .node-card-offline { border-left: 3px solid #ef4444; }
  .node-card-sleeping{ border-left: 3px solid #f59e0b; }
  .node-card-unknown { border-left: 3px solid #475569; }

  .node-name {
      font-size: 0.95rem;
      font-weight: 600;
      color: #f1f5f9;
      margin-bottom: 2px;
      font-family: 'JetBrains Mono', monospace;
  }
  .node-sensor-type {
      font-size: 0.72rem;
      color: #475569;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      margin-bottom: 12px;
  }
  .node-value {
      font-size: 1.6rem;
      font-weight: 700;
      color: #f1f5f9;
      line-height: 1;
      margin-bottom: 2px;
      font-family: 'JetBrains Mono', monospace;
  }
  .node-unit {
      font-size: 0.8rem;
      color: #64748b;
  }
  .node-last-seen {
      font-size: 0.72rem;
      color: #334155;
      margin-top: 10px;
  }

  /* Status indicator */
  .status-indicator {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      margin-bottom: 10px;
  }
  .dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      display: inline-block;
  }
  .dot-online   { background: #22c55e; animation: pulse-green 2s infinite; }
  .dot-offline  { background: #ef4444; }
  .dot-sleeping { background: #f59e0b; animation: pulse-amber 2s infinite; }
  .dot-unknown  { background: #475569; }
  @keyframes pulse-amber {
      0%   { box-shadow: 0 0 0 0 rgba(245,158,11,0.6); }
      70%  { box-shadow: 0 0 0 6px rgba(245,158,11,0); }
      100% { box-shadow: 0 0 0 0 rgba(245,158,11,0); }
  }
  .text-online   { color: #22c55e; }
  .text-offline  { color: #ef4444; }
  .text-sleeping { color: #f59e0b; }
  .text-unknown  { color: #475569; }

  /* ── Alert rows ── */
  .alert-row {
      display: flex;
      align-items: flex-start;
      gap: 12px;
      padding: 10px 14px;
      border-radius: 8px;
      margin-bottom: 6px;
      font-size: 0.82rem;
  }
  .alert-offline { background: rgba(239,68,68,0.08);  border-left: 3px solid #ef4444; }
  .alert-online  { background: rgba(34,197,94,0.08);  border-left: 3px solid #22c55e; }
  .alert-anomaly { background: rgba(245,158,11,0.08); border-left: 3px solid #f59e0b; }
  .alert-info    { background: rgba(99,102,241,0.08); border-left: 3px solid #6366f1; }

  .alert-time {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.72rem;
      color: #475569;
      white-space: nowrap;
      margin-top: 1px;
  }
  .alert-node {
      font-weight: 600;
      color: #94a3b8;
      font-family: 'JetBrains Mono', monospace;
  }
  .alert-msg { color: #cbd5e1; }

  /* ── Sensor icon ── */
  .sensor-icon {
      font-size: 1.4rem;
      margin-bottom: 6px;
  }

  /* ── No-data state ── */
  .no-data-box {
      background: #0f172a;
      border: 1px dashed #1e293b;
      border-radius: 14px;
      padding: 48px;
      text-align: center;
      color: #334155;
  }
  .no-data-box .no-data-icon { font-size: 2.5rem; margin-bottom: 12px; }
  .no-data-box .no-data-title { font-size: 1rem; font-weight: 600; color: #475569; margin-bottom: 6px; }
  .no-data-box .no-data-cmd {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.78rem;
      background: #1e293b;
      padding: 8px 14px;
      border-radius: 6px;
      display: inline-block;
      color: #94a3b8;
      margin-top: 8px;
  }

  /* ── Divider ── */
  hr { border-color: #1e293b; margin: 20px 0; }

  /* ── Timestamp footer ── */
  .refresh-footer {
      font-size: 0.72rem;
      color: #1e293b;
      text-align: right;
      margin-top: 8px;
      font-family: 'JetBrains Mono', monospace;
  }
</style>
""", unsafe_allow_html=True)


# ─── Database helpers ─────────────────────────────────────────────────────────

def get_conn():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_node_status(conn) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM node_status ORDER BY node_id", conn)

def fetch_recent_readings(conn) -> pd.DataFrame:
    df = pd.read_sql_query(f"""
        SELECT node_id, sensor_type, value, unit, timestamp
        FROM readings ORDER BY id DESC LIMIT {CHART_MAX_POINTS * 10}
    """, conn)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp")
    return df

def fetch_alerts(conn, limit=25) -> pd.DataFrame:
    return pd.read_sql_query(f"""
        SELECT node_id, alert_type, message, timestamp
        FROM alerts ORDER BY id DESC LIMIT {limit}
    """, conn)

def fetch_total_readings(conn) -> int:
    row = conn.execute("SELECT COUNT(*) FROM readings").fetchone()
    return row[0] if row else 0

def format_last_seen(ts_str):
    if not ts_str:
        return "never"
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        secs = int((datetime.now(timezone.utc) - dt).total_seconds())
        if secs < 5:   return "just now"
        if secs < 60:  return f"{secs}s ago"
        if secs < 3600: return f"{secs // 60}m ago"
        return f"{secs // 3600}h ago"
    except Exception:
        return ts_str


# ─── Sensor metadata ──────────────────────────────────────────────────────────

SENSOR_ICONS = {
    "temperature": "🌡️",
    "humidity":    "💧",
    "motion":      "👁️",
}

SENSOR_COLORS = {
    "temperature": "#f97316",
    "humidity":    "#38bdf8",
    "motion":      "#a78bfa",
}

NODE_TRACE_COLORS = [
    "#6366f1", "#22c55e", "#f97316",
    "#38bdf8", "#f43f5e", "#a78bfa",
]


# ─── Dashboard ────────────────────────────────────────────────────────────────

def render():

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="header-banner">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <div>
          <div class="header-title">
            📡 IoT Sensor Network
          </div>
          <div class="header-subtitle">
            Real-time monitoring · MQTT over Mosquitto · Heartbeat fault detection
          </div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:0.72rem; color:#334155; font-family:'JetBrains Mono',monospace;">
            LIVE
          </div>
          <div style="display:flex; align-items:center; justify-content:flex-end; gap:6px; margin-top:4px;">
            <span class="header-live-dot"></span>
            <span style="font-size:0.8rem; color:#475569;">localhost:1883</span>
          </div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Load data ─────────────────────────────────────────────────────────────
    conn = get_conn()

    if conn is None:
        st.markdown("""
        <div class="no-data-box">
          <div class="no-data-icon">🔌</div>
          <div class="no-data-title">Database not found</div>
          <div style="color:#334155; font-size:0.82rem; margin-bottom:8px;">
            Start the hub to begin collecting data
          </div>
          <div class="no-data-cmd">venv\Scripts\python.exe src/hub.py</div>
        </div>
        """, unsafe_allow_html=True)
        time.sleep(REFRESH_INTERVAL)
        st.rerun()
        return

    node_df      = fetch_node_status(conn)
    readings_df  = fetch_recent_readings(conn)
    alerts_df    = fetch_alerts(conn)
    total_msgs   = fetch_total_readings(conn)
    conn.close()

    # ── Waiting state ─────────────────────────────────────────────────────────
    if node_df.empty:
        st.markdown("""
        <div class="no-data-box">
          <div class="no-data-icon">⏳</div>
          <div class="no-data-title">Waiting for sensor data</div>
          <div style="color:#334155; font-size:0.82rem; margin-bottom:8px;">
            Hub is running — launch the sensor nodes to start
          </div>
          <div class="no-data-cmd">venv\Scripts\python.exe src/launch_nodes.py</div>
        </div>
        """, unsafe_allow_html=True)
        time.sleep(REFRESH_INTERVAL)
        st.rerun()
        return

    # ── Stat pills ────────────────────────────────────────────────────────────
    n_online   = len(node_df[node_df["status"] == "online"])
    n_offline  = len(node_df[node_df["status"] == "offline"])
    n_sleeping = len(node_df[node_df["status"] == "sleeping"])
    n_total    = len(node_df)
    n_alerts   = len(alerts_df)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(f"""
        <div class="stat-pill">
          <div class="stat-value stat-white">{n_total}</div>
          <div class="stat-label">Total Nodes</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="stat-pill">
          <div class="stat-value stat-green">{n_online}</div>
          <div class="stat-label">Online</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="stat-pill">
          <div class="stat-value stat-red">{n_offline}</div>
          <div class="stat-label">Offline</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""
        <div class="stat-pill">
          <div class="stat-value stat-yellow">{n_sleeping}</div>
          <div class="stat-label">Sleeping</div>
        </div>""", unsafe_allow_html=True)
    with c5:
        st.markdown(f"""
        <div class="stat-pill">
          <div class="stat-value stat-blue">{total_msgs:,}</div>
          <div class="stat-label">Messages</div>
        </div>""", unsafe_allow_html=True)

    # ── Two-column layout: nodes | alerts ─────────────────────────────────────
    left_col, right_col = st.columns([3, 2], gap="large")

    # ── LEFT: Node cards ──────────────────────────────────────────────────────
    with left_col:
        st.markdown('<div class="section-header">Node Status</div>', unsafe_allow_html=True)

        for _, row in node_df.iterrows():
            status      = row["status"] or "unknown"
            sensor_type = row["sensor_type"] or "unknown"
            icon        = SENSOR_ICONS.get(sensor_type, "📊")
            value       = row["last_value"]
            unit        = row["last_unit"] or ""
            last_seen   = format_last_seen(row["last_seen"])

            # Format value display
            if value is not None:
                if sensor_type == "motion":
                    val_display = "DETECTED" if int(value) == 1 else "CLEAR"
                    unit_display = ""
                else:
                    val_display  = f"{value:.1f}"
                    unit_display = unit
            else:
                val_display  = "—"
                unit_display = ""

            st.markdown(f"""
            <div class="node-card node-card-{status}">
              <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <div>
                  <div class="sensor-icon">{icon}</div>
                  <div class="node-name">{row['node_id']}</div>
                  <div class="node-sensor-type">{sensor_type}</div>
                  <div class="status-indicator">
                    <span class="dot dot-{status}"></span>
                    <span class="text-{status}">{status.upper()}</span>
                  </div>
                </div>
                <div style="text-align:right;">
                  <div class="node-value">{val_display}</div>
                  <div class="node-unit">{unit_display}</div>
                  <div class="node-last-seen">Last seen: {last_seen}</div>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

    # ── RIGHT: Alerts panel ───────────────────────────────────────────────────
    with right_col:
        st.markdown('<div class="section-header">Alert Log</div>', unsafe_allow_html=True)

        if alerts_df.empty:
            st.markdown("""
            <div style="
                background:#0f172a; border:1px solid #1e293b;
                border-radius:12px; padding:32px; text-align:center;
            ">
                <div style="font-size:1.8rem; margin-bottom:8px;">✅</div>
                <div style="color:#22c55e; font-size:0.85rem; font-weight:600;">
                    All nodes nominal
                </div>
                <div style="color:#334155; font-size:0.75rem; margin-top:4px;">
                    No alerts triggered
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            for _, alert in alerts_df.iterrows():
                atype = alert["alert_type"]
                icon_map  = {"offline": "🔴", "online": "🟢", "anomaly": "⚠️"}
                icon      = icon_map.get(atype, "ℹ️")
                css_class = f"alert-{atype}" if atype in ["offline", "online", "anomaly"] else "alert-info"

                ts = alert["timestamp"] or ""
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M:%S")
                except Exception:
                    pass

                st.markdown(f"""
                <div class="alert-row {css_class}">
                  <div style="font-size:1rem; margin-top:1px;">{icon}</div>
                  <div style="flex:1; min-width:0;">
                    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                      <span class="alert-node">{alert['node_id']}</span>
                      <span class="alert-time">{ts}</span>
                    </div>
                    <div class="alert-msg">{alert['message']}</div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

    # ── Charts ────────────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Sensor Readings — Live Time Series</div>',
                unsafe_allow_html=True)

    if readings_df.empty:
        st.markdown("""
        <div style="color:#334155; font-size:0.85rem; padding:20px 0;">
            No readings recorded yet.
        </div>""", unsafe_allow_html=True)
    else:
        sensor_types = sorted(readings_df["sensor_type"].unique())
        chart_cols = st.columns(len(sensor_types))

        for col, sensor_type in zip(chart_cols, sensor_types):
            type_df = readings_df[readings_df["sensor_type"] == sensor_type]
            color   = SENSOR_COLORS.get(sensor_type, "#6366f1")
            icon    = SENSOR_ICONS.get(sensor_type, "📊")
            unit    = type_df["unit"].iloc[0] if not type_df.empty else ""

            fig = go.Figure()

            for idx, node_id in enumerate(sorted(type_df["node_id"].unique())):
                sub = type_df[type_df["node_id"] == node_id].tail(CHART_MAX_POINTS)
                if sub.empty:
                    continue
                trace_color = NODE_TRACE_COLORS[idx % len(NODE_TRACE_COLORS)]
                fig.add_trace(go.Scatter(
                    x=sub["timestamp"],
                    y=sub["value"],
                    mode="lines",
                    name=node_id,
                    line=dict(width=2, color=trace_color),
                    fill="tozeroy",
                    fillcolor=f"rgba({int(trace_color[1:3],16)},"
                              f"{int(trace_color[3:5],16)},"
                              f"{int(trace_color[5:7],16)},0.04)",
                    hovertemplate=f"<b>{node_id}</b><br>%{{y:.2f}}{unit}<br>%{{x}}<extra></extra>",
                ))

            fig.update_layout(
                title=dict(
                    text=f"{icon}  {sensor_type.capitalize()}",
                    font=dict(size=13, color="#94a3b8", family="Inter"),
                    x=0,
                ),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="#080d18",
                font=dict(family="Inter", color="#64748b", size=11),
                height=260,
                margin=dict(l=10, r=10, t=40, b=10),
                xaxis=dict(
                    showgrid=True, gridcolor="#0f172a",
                    showline=False, zeroline=False,
                    tickfont=dict(size=9, color="#334155"),
                    title="",
                ),
                yaxis=dict(
                    showgrid=True, gridcolor="#0f172a",
                    showline=False, zeroline=False,
                    tickfont=dict(size=9, color="#334155"),
                    title=unit,
                    titlefont=dict(size=9, color="#334155"),
                ),
                legend=dict(
                    orientation="h",
                    yanchor="bottom", y=1.0,
                    xanchor="left", x=0,
                    font=dict(size=9, color="#475569"),
                    bgcolor="rgba(0,0,0,0)",
                ),
                hovermode="x unified",
                hoverlabel=dict(
                    bgcolor="#1e293b",
                    font_size=11,
                    font_family="JetBrains Mono",
                ),
            )

            with col:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Footer ────────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="refresh-footer">
        refreshed at {datetime.now().strftime('%H:%M:%S')} · every {REFRESH_INTERVAL}s
    </div>
    """, unsafe_allow_html=True)


# ─── Run ──────────────────────────────────────────────────────────────────────
render()
time.sleep(REFRESH_INTERVAL)
st.rerun()
