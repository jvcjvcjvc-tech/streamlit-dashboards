"""
CPPS Paging Metrics Dashboard - Streamlit App

Core Performance Platform Statistics - Paging Success Metrics by Market
Source: PCMD_AMF_AGG_HOURLY

Run with: streamlit run app_cpps_paging_dashboard.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

# Page config
st.set_page_config(
    page_title="CPPS Paging Metrics Dashboard",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for T-Mobile theme
st.markdown("""
<style>
    .stApp {
        background-color: #0c111d;
    }
    .main-header {
        color: #e20074;
        font-size: 2rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        color: #8b9bb4;
        font-size: 0.9rem;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #151b2e;
        border: 1px solid #2a3548;
        border-radius: 10px;
        padding: 1rem;
    }
    .stMetric {
        background-color: #151b2e;
        border: 1px solid #2a3548;
        border-radius: 10px;
        padding: 1rem;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem;
    }
    .green-text { color: #22c55e !important; }
    .yellow-text { color: #eab308 !important; }
    .red-text { color: #ef4444 !important; }
</style>
""", unsafe_allow_html=True)

# Color thresholds: Green >= 99.895, Yellow >= 99.85, Red < 99.85
def get_status_color(val):
    if val >= 99.895:
        return "#22c55e"  # Green
    elif val >= 99.85:
        return "#eab308"  # Yellow
    else:
        return "#ef4444"  # Red

def get_status_text(val):
    if val >= 99.895:
        return "green"
    elif val >= 99.85:
        return "yellow"
    else:
        return "red"

# Sample data - all markets
@st.cache_data
def load_data():
    data = [
        # WEST Region
        {"market": "ALBUQUERQUE NM", "region": "WEST", "availPct": 99.92, "successRate": 99.94, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 3234567, "pagingAtt": 3236789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "DENVER CO", "region": "WEST", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 7234567, "pagingAtt": 7239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "EL PASO TX", "region": "WEST", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 2234567, "pagingAtt": 2236789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "HAWAII HI", "region": "WEST", "availPct": 99.89, "successRate": 99.91, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 1834567, "pagingAtt": 1836789, "latestDate": "2026-04-09", "latestAvail": 99.90},
        {"market": "LA NORTH", "region": "WEST", "availPct": 99.92, "successRate": 99.94, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 15234567, "pagingAtt": 15246789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "LAS VEGAS", "region": "WEST", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 6234567, "pagingAtt": 6239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "LOS ANGELES", "region": "WEST", "availPct": 99.93, "successRate": 99.95, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 25234567, "pagingAtt": 25246789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "MONTANA", "region": "WEST", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 1234567, "pagingAtt": 1236789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "PHOENIX", "region": "WEST", "availPct": 99.92, "successRate": 99.94, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 9234567, "pagingAtt": 9241789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "PORTLAND OR", "region": "WEST", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 5234567, "pagingAtt": 5239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "SACRAMENTO", "region": "WEST", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 4234567, "pagingAtt": 4238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "SALT LAKE CITY UT", "region": "WEST", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 3234567, "pagingAtt": 3237789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "SAN DIEGO", "region": "WEST", "availPct": 99.92, "successRate": 99.94, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 7234567, "pagingAtt": 7239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "SAN FRANCISCO", "region": "WEST", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 10234567, "pagingAtt": 10241789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "SEATTLE WA", "region": "WEST", "availPct": 99.92, "successRate": 99.94, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 7234567, "pagingAtt": 7239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "SOUTHERN CALIFORNIA", "region": "WEST", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 12234567, "pagingAtt": 12241789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "SPOKANE WA", "region": "WEST", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 2234567, "pagingAtt": 2237789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        
        # CENTRAL Region
        {"market": "ARKANSAS", "region": "CENTRAL", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 2234567, "pagingAtt": 2237789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "CHICAGO", "region": "CENTRAL", "availPct": 99.93, "successRate": 99.95, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 22345678, "pagingAtt": 22356789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "CINCINNATI", "region": "CENTRAL", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 5234567, "pagingAtt": 5239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "CLEVELAND", "region": "CENTRAL", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 6234567, "pagingAtt": 6239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "COLUMBUS", "region": "CENTRAL", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 5234567, "pagingAtt": 5238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "DAKOTAS", "region": "CENTRAL", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 1234567, "pagingAtt": 1236789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "DES MOINES IA", "region": "CENTRAL", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 2234567, "pagingAtt": 2237789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "DETROIT MI", "region": "CENTRAL", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 9234567, "pagingAtt": 9241789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "INDIANAPOLIS IN", "region": "CENTRAL", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 5234567, "pagingAtt": 5238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "KANSAS CITY KS", "region": "CENTRAL", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 4234567, "pagingAtt": 4238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "KNOXVILLE TN", "region": "CENTRAL", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 2234567, "pagingAtt": 2237789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "LOUISVILLE", "region": "CENTRAL", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 3234567, "pagingAtt": 3238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "MILWAUKEE", "region": "CENTRAL", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 4234567, "pagingAtt": 4238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "MINNEAPOLIS MN", "region": "CENTRAL", "availPct": 99.92, "successRate": 99.94, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 7234567, "pagingAtt": 7239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "NASHVILLE", "region": "CENTRAL", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 5234567, "pagingAtt": 5239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "OKLAHOMA CITY OK", "region": "CENTRAL", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 3234567, "pagingAtt": 3238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "OMAHA", "region": "CENTRAL", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 2234567, "pagingAtt": 2237789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "PITTSBURGH PA", "region": "CENTRAL", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 4234567, "pagingAtt": 4238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "ST. LOUIS", "region": "CENTRAL", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 5234567, "pagingAtt": 5239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "TULSA OK", "region": "CENTRAL", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 2234567, "pagingAtt": 2237789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "WEST VIRGINIA", "region": "CENTRAL", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 1234567, "pagingAtt": 1237789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "WICHITA KS", "region": "CENTRAL", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 1234567, "pagingAtt": 1236789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        
        # NORTHEAST Region
        {"market": "CENTRAL PA", "region": "NORTHEAST", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 3234567, "pagingAtt": 3238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "CONNECTICUT", "region": "NORTHEAST", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 4234567, "pagingAtt": 4238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "LONG ISLAND - NY", "region": "NORTHEAST", "availPct": 99.92, "successRate": 99.94, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 6234567, "pagingAtt": 6239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "NEW ENGLAND MARKET", "region": "NORTHEAST", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 8234567, "pagingAtt": 8241789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "NEW JERSEY NJ", "region": "NORTHEAST", "availPct": 99.92, "successRate": 99.94, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 9234567, "pagingAtt": 9241789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "NEW YORK NY", "region": "NORTHEAST", "availPct": 99.93, "successRate": 99.95, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 28234567, "pagingAtt": 28246789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "NORTH CAROLINA", "region": "NORTHEAST", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 7234567, "pagingAtt": 7239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "NY (UPSTATE)", "region": "NORTHEAST", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 4234567, "pagingAtt": 4238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "PHILADELPHIA PA", "region": "NORTHEAST", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 11234567, "pagingAtt": 11241789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "SOUTH CAROLINA", "region": "NORTHEAST", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 4234567, "pagingAtt": 4238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "VIRGINIA", "region": "NORTHEAST", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 6234567, "pagingAtt": 6239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "WASHINGTON DC", "region": "NORTHEAST", "availPct": 99.92, "successRate": 99.94, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 13234567, "pagingAtt": 13241789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        
        # SOUTH Region
        {"market": "ATLANTA", "region": "SOUTH", "availPct": 99.92, "successRate": 99.94, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 15234567, "pagingAtt": 15241789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "AUSTIN TX", "region": "SOUTH", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 8234567, "pagingAtt": 8239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "BIRMINGHAM", "region": "SOUTH", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 4234567, "pagingAtt": 4238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "DALLAS TX", "region": "SOUTH", "availPct": 99.92, "successRate": 99.94, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 18234567, "pagingAtt": 18241789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "HOUSTON TX", "region": "SOUTH", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 14234567, "pagingAtt": 14241789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "JACKSONVILLE", "region": "SOUTH", "availPct": 99.92, "successRate": 99.94, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 5234567, "pagingAtt": 5238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "MEMPHIS", "region": "SOUTH", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 3234567, "pagingAtt": 3237789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "MIAMI FL", "region": "SOUTH", "availPct": 99.92, "successRate": 99.94, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 12234567, "pagingAtt": 12241789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "MOBILE", "region": "SOUTH", "availPct": 99.90, "successRate": 99.92, "totalHours": 720, "downtimeHrs": 1, "pagingSucc": 2234567, "pagingAtt": 2237789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "ORLANDO", "region": "SOUTH", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 8234567, "pagingAtt": 8239789, "latestDate": "2026-04-09", "latestAvail": 100.00},
        {"market": "PUERTO RICO", "region": "SOUTH", "availPct": 99.87, "successRate": 99.89, "totalHours": 720, "downtimeHrs": 2, "pagingSucc": 2234567, "pagingAtt": 2239789, "latestDate": "2026-04-09", "latestAvail": 99.85},
        {"market": "TAMPA FL", "region": "SOUTH", "availPct": 99.91, "successRate": 99.93, "totalHours": 720, "downtimeHrs": 0, "pagingSucc": 6234567, "pagingAtt": 6238789, "latestDate": "2026-04-09", "latestAvail": 100.00},
    ]
    return pd.DataFrame(data)

# Load data
df = load_data()

# Header
st.markdown('<h1 class="main-header">📡 CPPS Paging Metrics Dashboard</h1>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Core Performance Platform Statistics - Paging Success Metrics by Market | Source: PCMD_AMF_AGG_HOURLY | Data Date: 4/9/2026</p>', unsafe_allow_html=True)

# Sidebar filters
st.sidebar.header("🔍 Filters")

# Region filter
regions = ["All Regions"] + sorted(df["region"].unique().tolist())
selected_region = st.sidebar.selectbox("Region", regions)

# Market filter (filtered by region)
if selected_region == "All Regions":
    markets_list = sorted(df["market"].unique().tolist())
else:
    markets_list = sorted(df[df["region"] == selected_region]["market"].unique().tolist())
markets = ["All Markets"] + markets_list
selected_market = st.sidebar.selectbox("Market", markets)

# Date filter
st.sidebar.subheader("Date Range")
date_from = st.sidebar.date_input("From", datetime(2026, 3, 10))
date_to = st.sidebar.date_input("To", datetime(2026, 4, 9))

# Apply filters
filtered_df = df.copy()
if selected_region != "All Regions":
    filtered_df = filtered_df[filtered_df["region"] == selected_region]
if selected_market != "All Markets":
    filtered_df = filtered_df[filtered_df["market"] == selected_market]

# Filter count
st.sidebar.markdown(f"**Showing {len(filtered_df)} of {len(df)} markets**")

# Reset button
if st.sidebar.button("Reset Filters"):
    st.rerun()

# KPI Metrics
st.markdown("### 📊 Key Metrics")
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Markets Shown", len(filtered_df))

with col2:
    avg_avail = filtered_df["availPct"].mean() if len(filtered_df) > 0 else 0
    color = get_status_text(avg_avail)
    st.metric("Avg Availability", f"{avg_avail:.3f}%")

with col3:
    avg_rate = filtered_df["successRate"].mean() if len(filtered_df) > 0 else 0
    st.metric("Avg Success Rate", f"{avg_rate:.3f}%")

with col4:
    total_success = filtered_df["pagingSucc"].sum() if len(filtered_df) > 0 else 0
    st.metric("Total Paging Success", f"{total_success:,}")

with col5:
    total_downtime = filtered_df["downtimeHrs"].sum() if len(filtered_df) > 0 else 0
    st.metric("Total Downtime Hours", total_downtime)

# Charts
st.markdown("### 📈 Charts")
col_chart1, col_chart2 = st.columns(2)

with col_chart1:
    st.markdown("#### Availability by Market (%)")
    if len(filtered_df) > 0:
        sorted_df = filtered_df.sort_values("availPct")
        colors = [get_status_color(v) for v in sorted_df["availPct"]]
        
        fig = go.Figure(go.Bar(
            x=sorted_df["availPct"],
            y=sorted_df["market"],
            orientation='h',
            marker_color=colors,
            text=sorted_df["availPct"].apply(lambda x: f"{x:.3f}%"),
            textposition='auto'
        ))
        fig.update_layout(
            height=max(400, len(filtered_df) * 25),
            xaxis_title="Availability % (Green >= 99.895, Yellow >= 99.85, Red < 99.85)",
            xaxis=dict(range=[99.5, 100]),
            yaxis_title="",
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#e8ecf4'),
            margin=dict(l=150)
        )
        st.plotly_chart(fig, use_container_width=True)

with col_chart2:
    st.markdown("#### Paging Success Rate by Market (%)")
    if len(filtered_df) > 0:
        sorted_df = filtered_df.sort_values("successRate")
        colors = [get_status_color(v) for v in sorted_df["successRate"]]
        
        fig = go.Figure(go.Bar(
            x=sorted_df["successRate"],
            y=sorted_df["market"],
            orientation='h',
            marker_color=colors,
            text=sorted_df["successRate"].apply(lambda x: f"{x:.3f}%"),
            textposition='auto'
        ))
        fig.update_layout(
            height=max(400, len(filtered_df) * 25),
            xaxis_title="Success Rate % (Green >= 99.895, Yellow >= 99.85, Red < 99.85)",
            xaxis=dict(range=[99.5, 100]),
            yaxis_title="",
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#e8ecf4'),
            margin=dict(l=150)
        )
        st.plotly_chart(fig, use_container_width=True)

# Data Table
st.markdown("### 📋 Market Details")

if len(filtered_df) > 0:
    # Sort by availability (worst first)
    display_df = filtered_df.sort_values("availPct").copy()
    
    # Format columns
    display_df["Availability %"] = display_df["availPct"].apply(lambda x: f"{x:.3f}%")
    display_df["Success Rate %"] = display_df["successRate"].apply(lambda x: f"{x:.3f}%")
    display_df["Latest Avail %"] = display_df["latestAvail"].apply(lambda x: f"{x:.2f}%")
    display_df["Paging Success"] = display_df["pagingSucc"].apply(lambda x: f"{x:,}")
    display_df["Paging Attempts"] = display_df["pagingAtt"].apply(lambda x: f"{x:,}")
    
    # Select columns to display
    display_cols = ["market", "region", "Availability %", "Success Rate %", "totalHours", 
                    "downtimeHrs", "Paging Success", "Paging Attempts", "latestDate", "Latest Avail %"]
    
    st.dataframe(
        display_df[display_cols].rename(columns={
            "market": "Market",
            "region": "Region",
            "totalHours": "Total Hours",
            "downtimeHrs": "Downtime Hrs",
            "latestDate": "Latest Date"
        }),
        use_container_width=True,
        height=600
    )
else:
    st.info("No data matches the selected filters")

# Footer
st.markdown("---")
st.markdown(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Data Period: Last 30 Days | Color Thresholds: Green >= 99.895%, Yellow >= 99.85%, Red < 99.85%*")
