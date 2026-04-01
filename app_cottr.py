import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from glob import glob
import os
import numpy as np

st.set_page_config(
    page_title="COTTR Metrics Report",
    page_icon="⏱️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS - Professional dark theme
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    }
    .main-header {
        background: linear-gradient(90deg, #e94560, #ff6b6b);
        color: white;
        padding: 20px 30px;
        font-size: 28px;
        font-weight: bold;
        margin: -1rem -1rem 1.5rem -1rem;
        text-align: center;
        border-radius: 0 0 10px 10px;
    }
    .sub-header {
        color: #aaa;
        text-align: center;
        margin-top: -15px;
        margin-bottom: 20px;
        font-size: 14px;
    }
    .metric-card {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 15px;
        padding: 20px;
        text-align: center;
        backdrop-filter: blur(10px);
    }
    .metric-value {
        font-size: 36px;
        font-weight: bold;
        background: linear-gradient(90deg, #e94560, #ff6b6b);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .metric-value-green {
        font-size: 36px;
        font-weight: bold;
        color: #00d9a5;
    }
    .metric-value-yellow {
        font-size: 36px;
        font-weight: bold;
        color: #ffc107;
    }
    .metric-value-blue {
        font-size: 36px;
        font-weight: bold;
        color: #00b4d8;
    }
    .metric-label {
        font-size: 12px;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 8px;
    }
    .section-title {
        color: #fff;
        font-size: 18px;
        font-weight: 600;
        margin: 25px 0 15px 0;
        padding-left: 10px;
        border-left: 4px solid #e94560;
    }
    .glass-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 15px;
        margin-bottom: 15px;
    }
    div[data-testid="stSidebar"] {
        background: rgba(15,52,96,0.95);
    }
    div[data-testid="stSidebar"] * {
        color: #fff !important;
    }
</style>
""", unsafe_allow_html=True)

@st.cache_data
def load_data():
    sso_path = r"C:\Users\JChalap1\OneDrive - T-Mobile USA\Documents\AI_CURSOR\query_execution_agent_sso_auth 5\query_execution_agent_sso_auth"
    csv_files = glob(os.path.join(sso_path, "results_sso_*.csv"))
    if csv_files:
        latest = max(csv_files, key=os.path.getmtime)
        df = pd.read_csv(latest, low_memory=False)
        return df
    return None

def format_duration(mins):
    if mins >= 1440:
        return f"{mins/1440:.1f}d"
    elif mins >= 60:
        return f"{mins/60:.1f}h"
    else:
        return f"{mins:.0f}m"

def get_cottr_category(mins):
    if mins <= 30:
        return "≤30 min (Excellent)"
    elif mins <= 60:
        return "30-60 min (Good)"
    elif mins <= 120:
        return "1-2 hrs (Moderate)"
    elif mins <= 240:
        return "2-4 hrs (Slow)"
    else:
        return ">4 hrs (Critical)"

def get_region(mkt):
    mkt_str = str(mkt).upper()
    south = ['MEMPHIS', 'BIRMINGHAM', 'MOBILE', 'AUSTIN', 'HOUSTON', 'DALLAS', 'PUERTO', 'JACKSONVILLE', 'ATLANTA', 'ORLANDO', 'TAMPA']
    central = ['WEST VIRGINIA', 'PITTSBURGH', 'NASHVILLE', 'OKLAHOMA', 'ARKANSAS', 'LOUISVILLE', 'INDIANAPOLIS', 'MILWAUKEE', 'ST. LOUIS', 'DENVER', 'OMAHA', 'KANSAS', 'COLUMBUS', 'CINCINNATI', 'DETROIT', 'KNOXVILLE', 'MINNEAPOLIS', 'CHICAGO', 'CLEVELAND', 'DES MOINES', 'WICHITA', 'TULSA']
    west = ['ALBUQUERQUE', 'MONTANA', 'SEATTLE', 'LOS ANGELES', 'HAWAII', 'LA NORTH', 'SOUTHERN CAL', 'SACRAMENTO', 'SAN FRANCISCO', 'PHOENIX', 'PORTLAND', 'DAKOTAS']
    northeast = ['NEW YORK', 'PHILADELPHIA', 'BOSTON', 'WASHINGTON', 'NEW JERSEY']
    
    for s in south:
        if s in mkt_str: return 'SOUTH'
    for c in central:
        if c in mkt_str: return 'CENTRAL'
    for w in west:
        if w in mkt_str: return 'WEST'
    for n in northeast:
        if n in mkt_str: return 'NORTHEAST'
    return 'OTHER'

def main():
    st.markdown('<div class="main-header">⏱️ COTTR Metrics Report</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Customer Outage Time To Restore - Performance Analytics</div>', unsafe_allow_html=True)
    
    df = load_data()
    
    if df is None or df.empty:
        st.error("No data available")
        return
    
    # Parse dates and calculate COTTR
    if 'LOCAL_START_TIMESTAMP' in df.columns and 'LOCAL_END_TIMESTAMP' in df.columns:
        df['START_TIME'] = pd.to_datetime(df['LOCAL_START_TIMESTAMP'], format='ISO8601')
        df['END_TIME'] = pd.to_datetime(df['LOCAL_END_TIMESTAMP'], format='ISO8601')
        df['DATE'] = df['START_TIME'].dt.date
        df['HOUR'] = df['START_TIME'].dt.hour
        df['DAY_OF_WEEK'] = df['START_TIME'].dt.day_name()
        df['MONTH'] = df['START_TIME'].dt.strftime('%Y-%m')
        
        # COTTR = Time to restore (end - start) in minutes
        df['COTTR_MINS'] = (df['END_TIME'] - df['START_TIME']).dt.total_seconds() / 60
        df['COTTR_MINS'] = df['COTTR_MINS'].clip(lower=0)  # Remove negative values
    
    # Add region
    if 'MKT_NAME' in df.columns:
        df['REGION'] = df['MKT_NAME'].apply(get_region)
    
    # Add COTTR category
    df['COTTR_CATEGORY'] = df['COTTR_MINS'].apply(get_cottr_category)
    
    # Sidebar filters
    with st.sidebar:
        st.markdown("### 📊 Filters")
        
        regions = ['All'] + sorted(df['REGION'].dropna().unique().tolist())
        selected_region = st.selectbox("Region", regions)
        
        markets = ['All'] + sorted(df['MKT_NAME'].dropna().unique().tolist()) if 'MKT_NAME' in df.columns else ['All']
        selected_market = st.selectbox("Market", markets)
        
        categories = ['All'] + sorted(df['FINAL_OUTAGE_CATEGORY'].dropna().unique().tolist()) if 'FINAL_OUTAGE_CATEGORY' in df.columns else ['All']
        selected_category = st.selectbox("Outage Category", categories)
        
        if 'DATE' in df.columns:
            min_date = df['DATE'].min()
            max_date = df['DATE'].max()
            date_range = st.date_input("Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
        
        st.markdown("---")
        st.markdown("### 🎯 COTTR Target (mins)")
        target_cottr = st.number_input("Target", value=60, min_value=1, max_value=480)
    
    # Apply filters
    filtered_df = df.copy()
    if selected_region != 'All':
        filtered_df = filtered_df[filtered_df['REGION'] == selected_region]
    if selected_market != 'All':
        filtered_df = filtered_df[filtered_df['MKT_NAME'] == selected_market]
    if selected_category != 'All':
        filtered_df = filtered_df[filtered_df['FINAL_OUTAGE_CATEGORY'] == selected_category]
    if 'DATE' in filtered_df.columns and len(date_range) == 2:
        filtered_df = filtered_df[(filtered_df['DATE'] >= date_range[0]) & (filtered_df['DATE'] <= date_range[1])]
    
    # ==================== KPI CARDS ====================
    st.markdown('<div class="section-title">Key COTTR Metrics</div>', unsafe_allow_html=True)
    
    avg_cottr = filtered_df['COTTR_MINS'].mean()
    median_cottr = filtered_df['COTTR_MINS'].median()
    p95_cottr = filtered_df['COTTR_MINS'].quantile(0.95)
    total_events = len(filtered_df)
    within_target = (filtered_df['COTTR_MINS'] <= target_cottr).sum()
    target_pct = (within_target / total_events * 100) if total_events > 0 else 0
    total_customer_mins = filtered_df['LOC_IMPACT_DURATION_IN_MINS_TOTAL'].sum() if 'LOC_IMPACT_DURATION_IN_MINS_TOTAL' in filtered_df.columns else 0
    
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    
    with c1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{format_duration(avg_cottr)}</div>
            <div class="metric-label">Avg COTTR</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value-blue">{format_duration(median_cottr)}</div>
            <div class="metric-label">Median COTTR</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value-yellow">{format_duration(p95_cottr)}</div>
            <div class="metric-label">P95 COTTR</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c4:
        color_class = "metric-value-green" if target_pct >= 90 else "metric-value-yellow" if target_pct >= 70 else "metric-value"
        st.markdown(f"""
        <div class="metric-card">
            <div class="{color_class}">{target_pct:.1f}%</div>
            <div class="metric-label">Within Target</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c5:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value-blue">{total_events:,}</div>
            <div class="metric-label">Total Events</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c6:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{total_customer_mins/1e6:.1f}M</div>
            <div class="metric-label">Customer Mins</div>
        </div>
        """, unsafe_allow_html=True)
    
    # ==================== CHARTS ROW 1 ====================
    st.markdown('<div class="section-title">COTTR Distribution & Categories</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        # COTTR Distribution Histogram
        fig = px.histogram(
            filtered_df[filtered_df['COTTR_MINS'] <= 480],  # Cap at 8 hours for viz
            x='COTTR_MINS',
            nbins=50,
            color_discrete_sequence=['#e94560']
        )
        fig.add_vline(x=target_cottr, line_dash="dash", line_color="#00d9a5", 
                      annotation_text=f"Target: {target_cottr}m")
        fig.add_vline(x=avg_cottr, line_dash="dot", line_color="#ffc107",
                      annotation_text=f"Avg: {avg_cottr:.0f}m")
        fig.update_layout(
            title="COTTR Distribution (capped at 8hrs)",
            height=300,
            margin=dict(l=20, r=20, t=50, b=20),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#fff'),
            xaxis=dict(title='Minutes', gridcolor='rgba(255,255,255,0.1)'),
            yaxis=dict(title='Count', gridcolor='rgba(255,255,255,0.1)')
        )
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col2:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        # COTTR Category Pie
        category_counts = filtered_df['COTTR_CATEGORY'].value_counts().reset_index()
        category_counts.columns = ['Category', 'Count']
        
        colors = ['#00d9a5', '#4cc9f0', '#ffc107', '#ff6b6b', '#e94560']
        
        fig = px.pie(
            category_counts,
            values='Count',
            names='Category',
            color_discrete_sequence=colors,
            hole=0.4
        )
        fig.update_layout(
            title="COTTR Categories",
            height=300,
            margin=dict(l=20, r=20, t=50, b=20),
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#fff'),
            legend=dict(orientation='h', y=-0.1)
        )
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    # ==================== CHARTS ROW 2 ====================
    st.markdown('<div class="section-title">COTTR by Region & Market</div>', unsafe_allow_html=True)
    
    col3, col4 = st.columns(2)
    
    with col3:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        # COTTR by Region
        region_cottr = filtered_df.groupby('REGION').agg({
            'COTTR_MINS': ['mean', 'median', 'count']
        }).reset_index()
        region_cottr.columns = ['Region', 'Avg_COTTR', 'Median_COTTR', 'Count']
        region_cottr = region_cottr.sort_values('Avg_COTTR', ascending=True)
        
        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=region_cottr['Region'],
            x=region_cottr['Avg_COTTR'],
            name='Avg COTTR',
            orientation='h',
            marker_color='#e94560',
            text=region_cottr['Avg_COTTR'].apply(lambda x: f"{x:.0f}m"),
            textposition='auto'
        ))
        fig.add_trace(go.Bar(
            y=region_cottr['Region'],
            x=region_cottr['Median_COTTR'],
            name='Median COTTR',
            orientation='h',
            marker_color='#4cc9f0',
            text=region_cottr['Median_COTTR'].apply(lambda x: f"{x:.0f}m"),
            textposition='auto'
        ))
        fig.add_vline(x=target_cottr, line_dash="dash", line_color="#00d9a5")
        fig.update_layout(
            title="COTTR by Region",
            height=280,
            barmode='group',
            margin=dict(l=20, r=20, t=50, b=20),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#fff'),
            xaxis=dict(title='Minutes', gridcolor='rgba(255,255,255,0.1)'),
            yaxis=dict(title=''),
            legend=dict(orientation='h', y=1.1)
        )
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col4:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        # Top 10 Markets by Avg COTTR (worst performers)
        market_cottr = filtered_df.groupby('MKT_NAME').agg({
            'COTTR_MINS': 'mean'
        }).reset_index()
        market_cottr.columns = ['Market', 'Avg_COTTR']
        market_cottr = market_cottr.nlargest(10, 'Avg_COTTR')
        
        colors = ['#e94560' if c > target_cottr else '#00d9a5' for c in market_cottr['Avg_COTTR']]
        
        fig = go.Figure(go.Bar(
            x=market_cottr['Market'],
            y=market_cottr['Avg_COTTR'],
            marker_color=colors,
            text=market_cottr['Avg_COTTR'].apply(lambda x: f"{x:.0f}m"),
            textposition='outside'
        ))
        fig.add_hline(y=target_cottr, line_dash="dash", line_color="#ffc107",
                      annotation_text=f"Target: {target_cottr}m")
        fig.update_layout(
            title="Top 10 Markets - Highest Avg COTTR",
            height=280,
            margin=dict(l=20, r=20, t=50, b=50),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#fff'),
            xaxis=dict(title='', tickangle=45, gridcolor='rgba(255,255,255,0.1)'),
            yaxis=dict(title='Minutes', gridcolor='rgba(255,255,255,0.1)')
        )
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    # ==================== CHARTS ROW 3 ====================
    st.markdown('<div class="section-title">COTTR Trends</div>', unsafe_allow_html=True)
    
    col5, col6 = st.columns(2)
    
    with col5:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        # Daily COTTR Trend
        daily_cottr = filtered_df.groupby('DATE').agg({
            'COTTR_MINS': ['mean', 'median'],
            'SITE_CD': 'count'
        }).reset_index()
        daily_cottr.columns = ['Date', 'Avg_COTTR', 'Median_COTTR', 'Events']
        daily_cottr['Date'] = pd.to_datetime(daily_cottr['Date'])
        
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        fig.add_trace(go.Scatter(
            x=daily_cottr['Date'],
            y=daily_cottr['Avg_COTTR'],
            name='Avg COTTR',
            line=dict(color='#e94560', width=2),
            fill='tozeroy',
            fillcolor='rgba(233,69,96,0.2)'
        ), secondary_y=False)
        
        fig.add_trace(go.Scatter(
            x=daily_cottr['Date'],
            y=daily_cottr['Events'],
            name='Event Count',
            line=dict(color='#4cc9f0', width=2, dash='dot')
        ), secondary_y=True)
        
        fig.add_hline(y=target_cottr, line_dash="dash", line_color="#00d9a5", secondary_y=False)
        
        fig.update_layout(
            title="Daily COTTR Trend",
            height=280,
            margin=dict(l=20, r=20, t=50, b=20),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#fff'),
            legend=dict(orientation='h', y=1.1)
        )
        fig.update_xaxes(gridcolor='rgba(255,255,255,0.1)')
        fig.update_yaxes(title_text="Minutes", gridcolor='rgba(255,255,255,0.1)', secondary_y=False)
        fig.update_yaxes(title_text="Events", secondary_y=True)
        
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col6:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        # COTTR by Hour of Day
        hourly_cottr = filtered_df.groupby('HOUR').agg({
            'COTTR_MINS': 'mean'
        }).reset_index()
        hourly_cottr.columns = ['Hour', 'Avg_COTTR']
        
        fig = go.Figure(go.Bar(
            x=hourly_cottr['Hour'],
            y=hourly_cottr['Avg_COTTR'],
            marker=dict(
                color=hourly_cottr['Avg_COTTR'],
                colorscale=[[0, '#00d9a5'], [0.5, '#ffc107'], [1, '#e94560']],
                showscale=True,
                colorbar=dict(title='Mins')
            )
        ))
        fig.add_hline(y=target_cottr, line_dash="dash", line_color="#fff")
        fig.update_layout(
            title="COTTR by Hour of Day",
            height=280,
            margin=dict(l=20, r=20, t=50, b=20),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#fff'),
            xaxis=dict(title='Hour', dtick=2, gridcolor='rgba(255,255,255,0.1)'),
            yaxis=dict(title='Avg Minutes', gridcolor='rgba(255,255,255,0.1)')
        )
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    # ==================== CHARTS ROW 4 ====================
    st.markdown('<div class="section-title">COTTR by Outage Category & Impact</div>', unsafe_allow_html=True)
    
    col7, col8 = st.columns(2)
    
    with col7:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        # COTTR by Outage Category
        if 'FINAL_OUTAGE_CATEGORY' in filtered_df.columns:
            cat_cottr = filtered_df.groupby('FINAL_OUTAGE_CATEGORY').agg({
                'COTTR_MINS': 'mean',
                'SITE_CD': 'count'
            }).reset_index()
            cat_cottr.columns = ['Category', 'Avg_COTTR', 'Events']
            cat_cottr = cat_cottr.nlargest(8, 'Events')
            
            fig = go.Figure(go.Bar(
                y=cat_cottr['Category'],
                x=cat_cottr['Avg_COTTR'],
                orientation='h',
                marker_color='#ff6b6b',
                text=cat_cottr['Avg_COTTR'].apply(lambda x: f"{x:.0f}m"),
                textposition='auto'
            ))
            fig.add_vline(x=target_cottr, line_dash="dash", line_color="#00d9a5")
            fig.update_layout(
                title="COTTR by Outage Category",
                height=280,
                margin=dict(l=20, r=20, t=50, b=20),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#fff'),
                xaxis=dict(title='Minutes', gridcolor='rgba(255,255,255,0.1)'),
                yaxis=dict(title='')
            )
            st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col8:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        # COTTR vs Customer Impact scatter
        sample = filtered_df.sample(n=min(1000, len(filtered_df)))
        
        fig = px.scatter(
            sample,
            x='COTTR_MINS',
            y='LOC_SEVERELY_IMPACTED_SUB_CNT_TOTAL' if 'LOC_SEVERELY_IMPACTED_SUB_CNT_TOTAL' in sample.columns else 'SERVICE_OUTAGE_DURATION',
            color='REGION',
            size='SERVICE_OUTAGE_DURATION',
            size_max=20,
            opacity=0.6,
            color_discrete_sequence=['#e94560', '#4cc9f0', '#ffc107', '#00d9a5', '#9b59b6']
        )
        fig.update_layout(
            title="COTTR vs Customer Impact",
            height=280,
            margin=dict(l=20, r=20, t=50, b=20),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#fff'),
            xaxis=dict(title='COTTR (mins)', gridcolor='rgba(255,255,255,0.1)'),
            yaxis=dict(title='Impacted Subscribers', gridcolor='rgba(255,255,255,0.1)'),
            legend=dict(orientation='h', y=-0.15)
        )
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    # ==================== DATA TABLE ====================
    st.markdown('<div class="section-title">Detailed COTTR Data</div>', unsafe_allow_html=True)
    
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    
    display_cols = ['SITE_CD', 'MKT_NAME', 'REGION', 'COTTR_MINS', 'COTTR_CATEGORY', 
                   'SERVICE_OUTAGE_DURATION', 'FINAL_OUTAGE_CATEGORY', 'DATE']
    display_cols = [c for c in display_cols if c in filtered_df.columns]
    
    display_df = filtered_df[display_cols].sort_values('COTTR_MINS', ascending=False).head(100)
    display_df['COTTR_MINS'] = display_df['COTTR_MINS'].apply(lambda x: f"{x:.1f}")
    
    st.dataframe(display_df, use_container_width=True, hide_index=True, height=300)
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Footer
    st.markdown("---")
    st.markdown(f"""
    <div style='text-align:center; color:#666; font-size:12px;'>
    COTTR Metrics Report | Data: {filtered_df['DATE'].min()} to {filtered_df['DATE'].max()} | 
    Total Events: {len(filtered_df):,} | Target: {target_cottr} mins
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
