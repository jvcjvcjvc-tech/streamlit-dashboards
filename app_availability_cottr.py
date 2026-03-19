import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from glob import glob
import os
from datetime import datetime, date

st.set_page_config(
    page_title="All-In Availability vs COTTR",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #0a0a1a 0%, #1a1a3e 50%, #0d2137 100%);
    }
    .main-header {
        background: linear-gradient(90deg, #00b4d8, #0077b6, #023e8a);
        color: white;
        padding: 25px 30px;
        font-size: 30px;
        font-weight: bold;
        margin: -1rem -1rem 1.5rem -1rem;
        text-align: center;
        border-radius: 0 0 15px 15px;
        box-shadow: 0 4px 20px rgba(0,180,216,0.3);
    }
    .sub-header {
        color: #90e0ef;
        text-align: center;
        margin-top: -10px;
        margin-bottom: 25px;
        font-size: 14px;
    }
    .metric-card {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 16px;
        padding: 20px;
        text-align: center;
        backdrop-filter: blur(10px);
        transition: transform 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-3px);
    }
    .metric-value-green {
        font-size: 38px;
        font-weight: bold;
        color: #00d9a5;
    }
    .metric-value-blue {
        font-size: 38px;
        font-weight: bold;
        color: #00b4d8;
    }
    .metric-value-orange {
        font-size: 38px;
        font-weight: bold;
        color: #f77f00;
    }
    .metric-value-red {
        font-size: 38px;
        font-weight: bold;
        color: #e63946;
    }
    .metric-value-purple {
        font-size: 38px;
        font-weight: bold;
        color: #9d4edd;
    }
    .metric-label {
        font-size: 11px;
        color: #90e0ef;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        margin-top: 8px;
    }
    .section-title {
        color: #caf0f8;
        font-size: 18px;
        font-weight: 600;
        margin: 25px 0 15px 0;
        padding-left: 12px;
        border-left: 4px solid #00b4d8;
    }
    .glass-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 15px;
        margin-bottom: 15px;
    }
    .comparison-card {
        background: linear-gradient(135deg, rgba(0,180,216,0.1), rgba(0,119,182,0.1));
        border: 1px solid rgba(0,180,216,0.2);
        border-radius: 12px;
        padding: 20px;
        margin: 10px 0;
    }
    div[data-testid="stSidebar"] {
        background: rgba(10,10,26,0.95);
    }
    div[data-testid="stSidebar"] * {
        color: #caf0f8 !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: rgba(255,255,255,0.03);
        padding: 8px;
        border-radius: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: rgba(255,255,255,0.05);
        border-radius: 8px;
        color: white;
        padding: 10px 20px;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(90deg, #00b4d8, #0077b6) !important;
    }
    .target-met {
        color: #00d9a5;
        font-weight: bold;
    }
    .target-missed {
        color: #e63946;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

AVAILABILITY_TARGET = 99.95
COTTR_TARGET = 60

REGIONS = {
    'SOUTH': ['MEMPHIS', 'BIRMINGHAM', 'MOBILE', 'AUSTIN', 'HOUSTON', 'DALLAS', 'PUERTO', 'JACKSONVILLE', 'ATLANTA', 'ORLANDO', 'TAMPA', 'MIAMI', 'NEW ORLEANS', 'CHARLOTTE'],
    'CENTRAL': ['WEST VIRGINIA', 'PITTSBURGH', 'NASHVILLE', 'OKLAHOMA', 'ARKANSAS', 'LOUISVILLE', 'INDIANAPOLIS', 'MILWAUKEE', 'ST. LOUIS', 'DENVER', 'OMAHA', 'KANSAS', 'COLUMBUS', 'CINCINNATI', 'DETROIT', 'KNOXVILLE', 'MINNEAPOLIS', 'CHICAGO', 'CLEVELAND', 'DES MOINES', 'WICHITA', 'TULSA'],
    'WEST': ['ALBUQUERQUE', 'MONTANA', 'SEATTLE', 'LOS ANGELES', 'HAWAII', 'LA NORTH', 'SOUTHERN CAL', 'SACRAMENTO', 'SAN FRANCISCO', 'PHOENIX', 'PORTLAND', 'DAKOTAS', 'SAN DIEGO', 'LAS VEGAS', 'SALT LAKE'],
    'NORTHEAST': ['NEW YORK', 'PHILADELPHIA', 'BOSTON', 'WASHINGTON', 'NEW JERSEY', 'BALTIMORE', 'HARTFORD', 'BUFFALO']
}

@st.cache_data(ttl=300)
def load_data():
    sso_path = r"C:\Users\JChalap1\OneDrive - T-Mobile USA\Documents\AI_CURSOR\query_execution_agent_sso_auth 5\query_execution_agent_sso_auth"
    csv_files = glob(os.path.join(sso_path, "results_sso_*.csv"))
    
    if csv_files:
        latest = max(csv_files, key=os.path.getmtime)
        df = pd.read_csv(latest, low_memory=False)
        return df
    return None


def get_region(mkt):
    if pd.isna(mkt):
        return 'OTHER'
    mkt_str = str(mkt).upper()
    for region, markets in REGIONS.items():
        for m in markets:
            if m in mkt_str:
                return region
    return 'OTHER'


def calculate_availability(df, total_sites, days):
    """Calculate All-In Availability percentage"""
    total_outage_mins = df['SERVICE_OUTAGE_DURATION'].sum() if 'SERVICE_OUTAGE_DURATION' in df.columns else 0
    total_possible_mins = total_sites * days * 1440
    if total_possible_mins > 0:
        availability = ((total_possible_mins - total_outage_mins) / total_possible_mins) * 100
        return min(max(availability, 0), 100)
    return 99.95


def calculate_cottr(df):
    """Calculate average COTTR in minutes"""
    if 'LOCAL_START_TIMESTAMP' in df.columns and 'LOCAL_END_TIMESTAMP' in df.columns:
        df_copy = df.copy()
        df_copy['START_TIME'] = pd.to_datetime(df_copy['LOCAL_START_TIMESTAMP'], format='ISO8601', errors='coerce')
        df_copy['END_TIME'] = pd.to_datetime(df_copy['LOCAL_END_TIMESTAMP'], format='ISO8601', errors='coerce')
        df_copy['COTTR_MINS'] = (df_copy['END_TIME'] - df_copy['START_TIME']).dt.total_seconds() / 60
        df_copy['COTTR_MINS'] = df_copy['COTTR_MINS'].clip(lower=0)
        return df_copy['COTTR_MINS'].mean(), df_copy['COTTR_MINS'].median(), df_copy
    return 0, 0, df


def format_duration(mins):
    if pd.isna(mins):
        return "N/A"
    if mins >= 1440:
        return f"{mins/1440:.1f}d"
    elif mins >= 60:
        return f"{mins/60:.1f}h"
    else:
        return f"{mins:.0f}m"


def main():
    st.markdown('<div class="main-header">📊 All-In Availability vs COTTR Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Performance Metrics Comparison | Data from January 1, 2026</div>', unsafe_allow_html=True)
    
    df = load_data()
    
    if df is None or df.empty:
        st.error("No data available. Please ensure outage data is loaded.")
        return
    
    if 'LOCAL_START_TIMESTAMP' in df.columns:
        df['START_TIME'] = pd.to_datetime(df['LOCAL_START_TIMESTAMP'], format='ISO8601', errors='coerce')
        df['DATE'] = df['START_TIME'].dt.date
        df['WEEK'] = df['START_TIME'].dt.isocalendar().week
        df['MONTH'] = df['START_TIME'].dt.to_period('M').astype(str)
        df['DAY_OF_WEEK'] = df['START_TIME'].dt.day_name()
    
    if 'LOCAL_END_TIMESTAMP' in df.columns:
        df['END_TIME'] = pd.to_datetime(df['LOCAL_END_TIMESTAMP'], format='ISO8601', errors='coerce')
        df['COTTR_MINS'] = (df['END_TIME'] - df['START_TIME']).dt.total_seconds() / 60
        df['COTTR_MINS'] = df['COTTR_MINS'].clip(lower=0)
    
    if 'MKT_NAME' in df.columns:
        df['REGION'] = df['MKT_NAME'].apply(get_region)
    
    start_2026 = date(2026, 1, 1)
    if 'DATE' in df.columns:
        df = df[df['DATE'] >= start_2026]
    
    if df.empty:
        st.warning("No data available from January 1, 2026 onwards.")
        return
    
    with st.sidebar:
        st.markdown("### 📊 Filters")
        
        if 'REGION' in df.columns:
            regions = ['All'] + sorted(df['REGION'].dropna().unique().tolist())
            selected_region = st.selectbox("Region", regions)
        else:
            selected_region = 'All'
        
        if 'MKT_NAME' in df.columns:
            markets = ['All'] + sorted(df['MKT_NAME'].dropna().unique().tolist())
            selected_market = st.selectbox("Market", markets)
        else:
            selected_market = 'All'
        
        if 'FINAL_OUTAGE_CATEGORY' in df.columns:
            categories = ['All'] + sorted(df['FINAL_OUTAGE_CATEGORY'].dropna().unique().tolist())
            selected_category = st.selectbox("Outage Category", categories)
        else:
            selected_category = 'All'
        
        st.markdown("---")
        st.markdown("### 🎯 Targets")
        avail_target = st.number_input("Availability Target (%)", value=99.95, min_value=90.0, max_value=100.0, step=0.01)
        cottr_target = st.number_input("COTTR Target (mins)", value=60, min_value=1, max_value=480)
        
        st.markdown("---")
        st.markdown("### 📅 Date Range")
        if 'DATE' in df.columns:
            min_date = df['DATE'].min()
            max_date = df['DATE'].max()
            st.markdown(f"**From:** {min_date}")
            st.markdown(f"**To:** {max_date}")
            days_in_range = (max_date - min_date).days + 1
            st.markdown(f"**Days:** {days_in_range}")
    
    filtered_df = df.copy()
    if selected_region != 'All' and 'REGION' in df.columns:
        filtered_df = filtered_df[filtered_df['REGION'] == selected_region]
    if selected_market != 'All' and 'MKT_NAME' in df.columns:
        filtered_df = filtered_df[filtered_df['MKT_NAME'] == selected_market]
    if selected_category != 'All' and 'FINAL_OUTAGE_CATEGORY' in df.columns:
        filtered_df = filtered_df[filtered_df['FINAL_OUTAGE_CATEGORY'] == selected_category]
    
    total_sites = filtered_df['SITE_CD'].nunique() if 'SITE_CD' in filtered_df.columns else 1
    min_date = filtered_df['DATE'].min() if 'DATE' in filtered_df.columns else start_2026
    max_date = filtered_df['DATE'].max() if 'DATE' in filtered_df.columns else date.today()
    days_in_period = (max_date - min_date).days + 1
    
    availability = calculate_availability(filtered_df, total_sites, days_in_period)
    avg_cottr = filtered_df['COTTR_MINS'].mean() if 'COTTR_MINS' in filtered_df.columns else 0
    median_cottr = filtered_df['COTTR_MINS'].median() if 'COTTR_MINS' in filtered_df.columns else 0
    p95_cottr = filtered_df['COTTR_MINS'].quantile(0.95) if 'COTTR_MINS' in filtered_df.columns else 0
    
    total_events = len(filtered_df)
    total_outage_mins = filtered_df['SERVICE_OUTAGE_DURATION'].sum() if 'SERVICE_OUTAGE_DURATION' in filtered_df.columns else 0
    customer_mins = filtered_df['LOC_IMPACT_DURATION_IN_MINS_TOTAL'].sum() if 'LOC_IMPACT_DURATION_IN_MINS_TOTAL' in filtered_df.columns else 0
    within_cottr_target = (filtered_df['COTTR_MINS'] <= cottr_target).sum() if 'COTTR_MINS' in filtered_df.columns else 0
    cottr_target_pct = (within_cottr_target / total_events * 100) if total_events > 0 else 0
    
    st.markdown('<div class="section-title">📈 Key Performance Indicators</div>', unsafe_allow_html=True)
    
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    
    avail_color = "metric-value-green" if availability >= avail_target else "metric-value-red"
    cottr_color = "metric-value-green" if avg_cottr <= cottr_target else "metric-value-orange"
    
    with c1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="{avail_color}">{availability:.3f}%</div>
            <div class="metric-label">All-In Availability</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="{cottr_color}">{format_duration(avg_cottr)}</div>
            <div class="metric-label">Avg COTTR</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value-blue">{format_duration(median_cottr)}</div>
            <div class="metric-label">Median COTTR</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c4:
        target_color = "metric-value-green" if cottr_target_pct >= 90 else "metric-value-orange"
        st.markdown(f"""
        <div class="metric-card">
            <div class="{target_color}">{cottr_target_pct:.1f}%</div>
            <div class="metric-label">Within COTTR Target</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c5:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value-purple">{total_events:,}</div>
            <div class="metric-label">Total Outage Events</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c6:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value-orange">{total_outage_mins/1e3:.1f}K</div>
            <div class="metric-label">Total Outage Mins</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "📈 Trends Over Time",
        "🗺️ Regional Comparison",
        "📊 Correlation Analysis",
        "📋 Detailed Data"
    ])
    
    with tab1:
        st.markdown('<div class="section-title">Daily Availability & COTTR Trends</div>', unsafe_allow_html=True)
        
        if 'DATE' in filtered_df.columns:
            daily = filtered_df.groupby('DATE').agg({
                'SERVICE_OUTAGE_DURATION': 'sum',
                'COTTR_MINS': ['mean', 'median'],
                'SITE_CD': 'nunique'
            }).reset_index()
            daily.columns = ['Date', 'Outage_Mins', 'Avg_COTTR', 'Median_COTTR', 'Sites']
            daily['Date'] = pd.to_datetime(daily['Date'])
            
            daily['Daily_Avail'] = daily.apply(
                lambda row: ((row['Sites'] * 1440 - row['Outage_Mins']) / (row['Sites'] * 1440) * 100) 
                if row['Sites'] > 0 else 99.95, axis=1
            )
            daily['Daily_Avail'] = daily['Daily_Avail'].clip(lower=95, upper=100)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                fig = make_subplots(specs=[[{"secondary_y": True}]])
                
                fig.add_trace(go.Scatter(
                    x=daily['Date'],
                    y=daily['Daily_Avail'],
                    name='Daily Availability',
                    line=dict(color='#00d9a5', width=2),
                    fill='tozeroy',
                    fillcolor='rgba(0,217,165,0.1)'
                ), secondary_y=False)
                
                fig.add_hline(y=avail_target, line_dash="dash", line_color="#f77f00",
                             annotation_text=f"Target: {avail_target}%", secondary_y=False)
                
                fig.update_layout(
                    title="Daily All-In Availability",
                    height=350,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#caf0f8'),
                    legend=dict(orientation='h', y=1.1),
                    margin=dict(t=60, b=40)
                )
                fig.update_xaxes(gridcolor='rgba(255,255,255,0.05)')
                fig.update_yaxes(title_text="Availability %", gridcolor='rgba(255,255,255,0.05)', 
                               range=[99, 100], secondary_y=False)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col2:
                st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                fig = make_subplots(specs=[[{"secondary_y": True}]])
                
                fig.add_trace(go.Scatter(
                    x=daily['Date'],
                    y=daily['Avg_COTTR'],
                    name='Avg COTTR',
                    line=dict(color='#00b4d8', width=2),
                    fill='tozeroy',
                    fillcolor='rgba(0,180,216,0.1)'
                ), secondary_y=False)
                
                fig.add_trace(go.Scatter(
                    x=daily['Date'],
                    y=daily['Median_COTTR'],
                    name='Median COTTR',
                    line=dict(color='#9d4edd', width=2, dash='dot')
                ), secondary_y=False)
                
                fig.add_hline(y=cottr_target, line_dash="dash", line_color="#f77f00",
                             annotation_text=f"Target: {cottr_target}m")
                
                fig.update_layout(
                    title="Daily COTTR Trend",
                    height=350,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#caf0f8'),
                    legend=dict(orientation='h', y=1.1),
                    margin=dict(t=60, b=40)
                )
                fig.update_xaxes(gridcolor='rgba(255,255,255,0.05)')
                fig.update_yaxes(title_text="Minutes", gridcolor='rgba(255,255,255,0.05)')
                st.plotly_chart(fig, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="section-title">Weekly Performance Summary</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            weekly = filtered_df.groupby('WEEK').agg({
                'SERVICE_OUTAGE_DURATION': 'sum',
                'COTTR_MINS': 'mean',
                'SITE_CD': 'nunique',
                'DATE': 'min'
            }).reset_index()
            weekly.columns = ['Week', 'Outage_Mins', 'Avg_COTTR', 'Sites', 'Week_Start']
            weekly['Week_Start'] = pd.to_datetime(weekly['Week_Start'])
            
            weekly['Weekly_Avail'] = weekly.apply(
                lambda row: ((row['Sites'] * 7 * 1440 - row['Outage_Mins']) / (row['Sites'] * 7 * 1440) * 100) 
                if row['Sites'] > 0 else 99.95, axis=1
            )
            weekly['Weekly_Avail'] = weekly['Weekly_Avail'].clip(lower=95, upper=100)
            
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            
            fig.add_trace(go.Bar(
                x=weekly['Week_Start'],
                y=weekly['Weekly_Avail'] - 99,
                name='Availability (above 99%)',
                marker_color='#00d9a5',
                text=weekly['Weekly_Avail'].apply(lambda x: f"{x:.3f}%"),
                textposition='outside'
            ), secondary_y=False)
            
            fig.add_trace(go.Scatter(
                x=weekly['Week_Start'],
                y=weekly['Avg_COTTR'],
                name='Avg COTTR',
                mode='lines+markers',
                line=dict(color='#00b4d8', width=3),
                marker=dict(size=10)
            ), secondary_y=True)
            
            fig.add_hline(y=cottr_target, line_dash="dash", line_color="#f77f00", secondary_y=True)
            
            fig.update_layout(
                title="Weekly Availability & COTTR Comparison",
                height=400,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#caf0f8'),
                legend=dict(orientation='h', y=1.12),
                margin=dict(t=80, b=40),
                barmode='relative'
            )
            fig.update_xaxes(gridcolor='rgba(255,255,255,0.05)', title='Week Starting')
            fig.update_yaxes(title_text="Availability (above 99%)", gridcolor='rgba(255,255,255,0.05)', secondary_y=False)
            fig.update_yaxes(title_text="COTTR (mins)", secondary_y=True)
            
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
    
    with tab2:
        st.markdown('<div class="section-title">Regional Performance Comparison</div>', unsafe_allow_html=True)
        
        if 'REGION' in filtered_df.columns:
            regional = filtered_df.groupby('REGION').agg({
                'SERVICE_OUTAGE_DURATION': 'sum',
                'COTTR_MINS': ['mean', 'median'],
                'SITE_CD': 'nunique',
                'DATE': ['min', 'max']
            }).reset_index()
            regional.columns = ['Region', 'Outage_Mins', 'Avg_COTTR', 'Median_COTTR', 'Sites', 'Start_Date', 'End_Date']
            
            regional['Days'] = regional.apply(lambda row: (row['End_Date'] - row['Start_Date']).days + 1, axis=1)
            regional['Availability'] = regional.apply(
                lambda row: ((row['Sites'] * row['Days'] * 1440 - row['Outage_Mins']) / 
                           (row['Sites'] * row['Days'] * 1440) * 100) if row['Sites'] > 0 else 99.95, axis=1
            )
            regional['Availability'] = regional['Availability'].clip(lower=95, upper=100)
            regional['Avail_Status'] = regional['Availability'].apply(lambda x: '✅' if x >= avail_target else '⚠️')
            regional['COTTR_Status'] = regional['Avg_COTTR'].apply(lambda x: '✅' if x <= cottr_target else '⚠️')
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                
                fig = go.Figure()
                colors = ['#00d9a5' if a >= avail_target else '#e63946' for a in regional['Availability']]
                
                fig.add_trace(go.Bar(
                    y=regional['Region'],
                    x=regional['Availability'],
                    orientation='h',
                    marker_color=colors,
                    text=regional['Availability'].apply(lambda x: f"{x:.3f}%"),
                    textposition='auto'
                ))
                
                fig.add_vline(x=avail_target, line_dash="dash", line_color="#f77f00",
                             annotation_text=f"Target: {avail_target}%")
                
                fig.update_layout(
                    title="Availability by Region",
                    height=350,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#caf0f8'),
                    xaxis=dict(range=[99, 100], gridcolor='rgba(255,255,255,0.05)'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                    margin=dict(l=20, r=20, t=50, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col2:
                st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                
                fig = go.Figure()
                colors = ['#00d9a5' if c <= cottr_target else '#e63946' for c in regional['Avg_COTTR']]
                
                fig.add_trace(go.Bar(
                    y=regional['Region'],
                    x=regional['Avg_COTTR'],
                    orientation='h',
                    marker_color=colors,
                    text=regional['Avg_COTTR'].apply(lambda x: f"{x:.0f}m"),
                    textposition='auto',
                    name='Avg COTTR'
                ))
                
                fig.add_trace(go.Scatter(
                    y=regional['Region'],
                    x=regional['Median_COTTR'],
                    mode='markers',
                    marker=dict(size=12, color='#9d4edd', symbol='diamond'),
                    name='Median COTTR'
                ))
                
                fig.add_vline(x=cottr_target, line_dash="dash", line_color="#f77f00",
                             annotation_text=f"Target: {cottr_target}m")
                
                fig.update_layout(
                    title="COTTR by Region",
                    height=350,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#caf0f8'),
                    xaxis=dict(gridcolor='rgba(255,255,255,0.05)', title='Minutes'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                    legend=dict(orientation='h', y=1.1),
                    margin=dict(l=20, r=20, t=60, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            st.markdown("**Regional Performance Summary**")
            
            display_regional = regional[['Region', 'Availability', 'Avail_Status', 'Avg_COTTR', 'Median_COTTR', 'COTTR_Status', 'Sites', 'Outage_Mins']].copy()
            display_regional['Availability'] = display_regional['Availability'].apply(lambda x: f"{x:.3f}%")
            display_regional['Avg_COTTR'] = display_regional['Avg_COTTR'].apply(lambda x: f"{x:.1f} mins")
            display_regional['Median_COTTR'] = display_regional['Median_COTTR'].apply(lambda x: f"{x:.1f} mins")
            display_regional['Outage_Mins'] = display_regional['Outage_Mins'].apply(lambda x: f"{x:,.0f}")
            
            st.dataframe(display_regional, use_container_width=True, hide_index=True)
            st.markdown('</div>', unsafe_allow_html=True)
    
    with tab3:
        st.markdown('<div class="section-title">Availability vs COTTR Correlation</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            
            if 'DATE' in filtered_df.columns and 'COTTR_MINS' in filtered_df.columns:
                daily_corr = filtered_df.groupby('DATE').agg({
                    'SERVICE_OUTAGE_DURATION': 'sum',
                    'COTTR_MINS': 'mean',
                    'SITE_CD': 'nunique'
                }).reset_index()
                daily_corr.columns = ['Date', 'Outage_Mins', 'Avg_COTTR', 'Sites']
                daily_corr['Availability'] = daily_corr.apply(
                    lambda row: ((row['Sites'] * 1440 - row['Outage_Mins']) / (row['Sites'] * 1440) * 100) 
                    if row['Sites'] > 0 else 99.95, axis=1
                )
                daily_corr['Availability'] = daily_corr['Availability'].clip(lower=95, upper=100)
                
                fig = px.scatter(
                    daily_corr,
                    x='Availability',
                    y='Avg_COTTR',
                    size='Outage_Mins',
                    color='Outage_Mins',
                    color_continuous_scale=['#00d9a5', '#f77f00', '#e63946'],
                    hover_data=['Date', 'Sites']
                )
                
                fig.add_hline(y=cottr_target, line_dash="dash", line_color="#90e0ef")
                fig.add_vline(x=avail_target, line_dash="dash", line_color="#90e0ef")
                
                fig.update_layout(
                    title="Daily Availability vs COTTR",
                    height=400,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#caf0f8'),
                    xaxis=dict(title='Availability %', gridcolor='rgba(255,255,255,0.05)'),
                    yaxis=dict(title='Avg COTTR (mins)', gridcolor='rgba(255,255,255,0.05)')
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            
            if 'REGION' in filtered_df.columns:
                fig = px.scatter(
                    regional,
                    x='Availability',
                    y='Avg_COTTR',
                    size='Sites',
                    color='Region',
                    text='Region',
                    color_discrete_sequence=['#00d9a5', '#00b4d8', '#9d4edd', '#f77f00', '#e63946']
                )
                
                fig.add_hline(y=cottr_target, line_dash="dash", line_color="#90e0ef")
                fig.add_vline(x=avail_target, line_dash="dash", line_color="#90e0ef")
                
                fig.update_traces(textposition='top center')
                fig.update_layout(
                    title="Regional Availability vs COTTR",
                    height=400,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#caf0f8'),
                    xaxis=dict(title='Availability %', gridcolor='rgba(255,255,255,0.05)', range=[99, 100]),
                    yaxis=dict(title='Avg COTTR (mins)', gridcolor='rgba(255,255,255,0.05)'),
                    showlegend=False
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="section-title">Performance Quadrant Analysis</div>', unsafe_allow_html=True)
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        if 'DATE' in filtered_df.columns and 'COTTR_MINS' in filtered_df.columns:
            daily_corr_quad = filtered_df.groupby('DATE').agg({
                'SERVICE_OUTAGE_DURATION': 'sum',
                'COTTR_MINS': 'mean',
                'SITE_CD': 'nunique'
            }).reset_index()
            daily_corr_quad.columns = ['Date', 'Outage_Mins', 'Avg_COTTR', 'Sites']
            daily_corr_quad['Availability'] = daily_corr_quad.apply(
                lambda row: ((row['Sites'] * 1440 - row['Outage_Mins']) / (row['Sites'] * 1440) * 100) 
                if row['Sites'] > 0 else 99.95, axis=1
            )
            daily_corr_quad['Availability'] = daily_corr_quad['Availability'].clip(lower=95, upper=100)
            
            q1 = len(daily_corr_quad[(daily_corr_quad['Availability'] >= avail_target) & (daily_corr_quad['Avg_COTTR'] <= cottr_target)])
            q2 = len(daily_corr_quad[(daily_corr_quad['Availability'] < avail_target) & (daily_corr_quad['Avg_COTTR'] <= cottr_target)])
            q3 = len(daily_corr_quad[(daily_corr_quad['Availability'] < avail_target) & (daily_corr_quad['Avg_COTTR'] > cottr_target)])
            q4 = len(daily_corr_quad[(daily_corr_quad['Availability'] >= avail_target) & (daily_corr_quad['Avg_COTTR'] > cottr_target)])
            total_days = len(daily_corr_quad)
            
            if total_days > 0:
                qc1, qc2, qc3, qc4 = st.columns(4)
                
                with qc1:
                    st.markdown(f"""
                    <div class="comparison-card" style="border-color: #00d9a5;">
                        <div style="color: #00d9a5; font-size: 28px; font-weight: bold;">{q1} days</div>
                        <div style="color: #90e0ef; font-size: 11px;">({q1/total_days*100:.1f}%)</div>
                        <div style="color: #caf0f8; font-size: 12px; margin-top: 8px;">✅ BOTH TARGETS MET</div>
                        <div style="color: #90e0ef; font-size: 10px;">High Avail + Low COTTR</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with qc2:
                    st.markdown(f"""
                    <div class="comparison-card" style="border-color: #f77f00;">
                        <div style="color: #f77f00; font-size: 28px; font-weight: bold;">{q2} days</div>
                        <div style="color: #90e0ef; font-size: 11px;">({q2/total_days*100:.1f}%)</div>
                        <div style="color: #caf0f8; font-size: 12px; margin-top: 8px;">⚠️ COTTR MET ONLY</div>
                        <div style="color: #90e0ef; font-size: 10px;">Low Avail + Low COTTR</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with qc3:
                    st.markdown(f"""
                    <div class="comparison-card" style="border-color: #e63946;">
                        <div style="color: #e63946; font-size: 28px; font-weight: bold;">{q3} days</div>
                        <div style="color: #90e0ef; font-size: 11px;">({q3/total_days*100:.1f}%)</div>
                        <div style="color: #caf0f8; font-size: 12px; margin-top: 8px;">❌ BOTH MISSED</div>
                        <div style="color: #90e0ef; font-size: 10px;">Low Avail + High COTTR</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with qc4:
                    st.markdown(f"""
                    <div class="comparison-card" style="border-color: #9d4edd;">
                        <div style="color: #9d4edd; font-size: 28px; font-weight: bold;">{q4} days</div>
                        <div style="color: #90e0ef; font-size: 11px;">({q4/total_days*100:.1f}%)</div>
                        <div style="color: #caf0f8; font-size: 12px; margin-top: 8px;">⚠️ AVAIL MET ONLY</div>
                        <div style="color: #90e0ef; font-size: 10px;">High Avail + High COTTR</div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("No data available for quadrant analysis.")
        else:
            st.warning("DATE or COTTR_MINS columns not found for quadrant analysis.")
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    with tab4:
        st.markdown('<div class="section-title">Detailed Outage Data</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        display_cols = ['DATE', 'SITE_CD', 'MKT_NAME', 'REGION', 'SERVICE_OUTAGE_DURATION', 
                       'COTTR_MINS', 'FINAL_OUTAGE_CATEGORY', 'LOC_SEVERELY_IMPACTED_SUB_CNT_TOTAL']
        display_cols = [c for c in display_cols if c in filtered_df.columns]
        
        display_df = filtered_df[display_cols].copy()
        if 'SERVICE_OUTAGE_DURATION' in display_df.columns:
            display_df = display_df.sort_values('SERVICE_OUTAGE_DURATION', ascending=False)
        
        if 'COTTR_MINS' in display_df.columns:
            display_df['COTTR_MINS'] = display_df['COTTR_MINS'].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "N/A")
        
        st.dataframe(display_df.head(500), use_container_width=True, hide_index=True, height=400)
        
        csv = filtered_df[display_cols].to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Full Dataset (CSV)",
            data=csv,
            file_name=f"availability_cottr_data_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
        st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    st.markdown(f"""
    <div style='text-align:center; color:#90e0ef; font-size:11px;'>
    All-In Availability vs COTTR Dashboard | Data: Jan 1, 2026 to {max_date} | 
    Events: {total_events:,} | Sites: {total_sites:,} | 
    Targets: Avail {avail_target}% / COTTR {cottr_target}m
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
