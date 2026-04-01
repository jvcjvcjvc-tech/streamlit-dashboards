import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import os

st.set_page_config(
    page_title="Network Performance Dashboard",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Modern gradient dark theme
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(180deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
        color: white;
    }
    .glass-card {
        background: rgba(255, 255, 255, 0.05);
        backdrop-filter: blur(10px);
        border-radius: 15px;
        padding: 20px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        margin-bottom: 10px;
    }
    .metric-value {
        font-size: 42px;
        font-weight: 700;
        background: linear-gradient(135deg, #00ff88 0%, #00d4ff 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    .metric-label {
        font-size: 12px;
        color: rgba(255,255,255,0.6);
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .section-title {
        font-size: 18px;
        font-weight: 600;
        color: #fff;
        margin-bottom: 15px;
        padding-left: 10px;
        border-left: 3px solid #00ff88;
    }
    .market-item {
        background: rgba(255,255,255,0.03);
        border-radius: 10px;
        padding: 12px 15px;
        margin-bottom: 8px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        transition: all 0.3s ease;
    }
    .market-item:hover {
        background: rgba(255,255,255,0.08);
        transform: translateX(5px);
    }
    .progress-bar {
        height: 4px;
        background: rgba(255,255,255,0.1);
        border-radius: 2px;
        overflow: hidden;
        margin-top: 8px;
    }
    .progress-fill {
        height: 100%;
        border-radius: 2px;
        transition: width 0.5s ease;
    }
    .stat-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 8px;
        margin-top: 10px;
    }
    .stat-item {
        text-align: center;
        padding: 8px;
        background: rgba(255,255,255,0.03);
        border-radius: 8px;
    }
    .stat-value {
        font-size: 14px;
        font-weight: 600;
        color: #00ff88;
    }
    .stat-label {
        font-size: 9px;
        color: rgba(255,255,255,0.5);
    }
</style>
""", unsafe_allow_html=True)

RESULTS_PATH = r"C:\Users\JChalap1\OneDrive - T-Mobile USA\Documents\AI_CURSOR\query_execution_agent_sso_auth 5\query_execution_agent_sso_auth"


@st.cache_data(ttl=300)
def load_csv_data(filepath):
    try:
        return pd.read_csv(filepath, low_memory=False)
    except:
        return pd.DataFrame()


def get_latest_results_file():
    try:
        files = [f for f in os.listdir(RESULTS_PATH) if f.startswith('results_sso_') and f.endswith('.csv')]
        if files:
            files.sort(reverse=True)
            return os.path.join(RESULTS_PATH, files[0])
    except:
        pass
    return None


def format_num(num):
    if pd.isna(num): return "0"
    if num >= 1e9: return f"{num/1e9:.1f}B"
    elif num >= 1e6: return f"{num/1e6:.1f}M"
    elif num >= 1e3: return f"{num/1e3:.1f}K"
    return f"{num:,.0f}"


def create_gauge(value, title, color, max_val=100):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        title={'text': title, 'font': {'size': 14, 'color': 'white'}},
        number={'font': {'size': 28, 'color': color}, 'suffix': '%'},
        gauge={
            'axis': {'range': [0, max_val], 'tickcolor': 'white', 'tickfont': {'color': 'white'}},
            'bar': {'color': color},
            'bgcolor': 'rgba(255,255,255,0.1)',
            'borderwidth': 0,
            'steps': [
                {'range': [0, max_val*0.5], 'color': 'rgba(255,0,0,0.2)'},
                {'range': [max_val*0.5, max_val*0.8], 'color': 'rgba(255,165,0,0.2)'},
                {'range': [max_val*0.8, max_val], 'color': 'rgba(0,255,0,0.2)'}
            ],
        }
    ))
    fig.update_layout(
        height=180, margin=dict(t=30, b=0, l=20, r=20),
        paper_bgcolor='rgba(0,0,0,0)', font_color='white'
    )
    return fig


def create_donut(labels, values, colors, title):
    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        hole=0.6, marker_colors=colors,
        textinfo='percent', textfont_size=10,
        textfont_color='white'
    ))
    fig.update_layout(
        height=200, margin=dict(t=30, b=0, l=0, r=0),
        paper_bgcolor='rgba(0,0,0,0)',
        title={'text': title, 'font': {'size': 12, 'color': 'white'}, 'x': 0.5},
        showlegend=False
    )
    return fig


def main():
    # Header with gradient
    st.markdown("""
    <div style="text-align: center; padding: 20px 0;">
        <h1 style="background: linear-gradient(135deg, #00ff88 0%, #00d4ff 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-size: 32px; margin: 0;">
            📡 Network Performance Dashboard
        </h1>
        <p style="color: rgba(255,255,255,0.5); font-size: 14px;">Real-time KPIs & Analytics</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Load data
    latest_file = get_latest_results_file()
    df = load_csv_data(latest_file) if latest_file else pd.DataFrame()
    
    if df.empty:
        st.warning("No data loaded.")
        return
    
    df.columns = df.columns.str.strip()
    
    # Calculate metrics
    total_sites = df['SITE_CD'].nunique() if 'SITE_CD' in df.columns else 0
    total_events = len(df)
    total_outage_mins = df['SERVICE_OUTAGE_DURATION'].sum() if 'SERVICE_OUTAGE_DURATION' in df.columns else 0
    customer_mins = df['LOC_IMPACT_DURATION_IN_MINS_TOTAL'].sum() if 'LOC_IMPACT_DURATION_IN_MINS_TOTAL' in df.columns else 0
    impacted_subs = df['LOC_SEVERELY_IMPACTED_SUB_CNT_TOTAL'].sum() if 'LOC_SEVERELY_IMPACTED_SUB_CNT_TOTAL' in df.columns else 0
    
    days = 77  # Jan 1 to Mar 18
    total_possible = total_sites * days * 1440
    availability = ((total_possible - total_outage_mins) / total_possible * 100) if total_possible > 0 else 99.85
    availability = min(max(availability, 99.0), 99.99)
    
    # ==================== TOP METRICS ROW ====================
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    metrics = [
        (col1, f"{availability:.2f}%", "AVAILABILITY", "#00ff88"),
        (col2, format_num(total_outage_mins * 60), "DOWNTIME (sec)", "#ff6b6b"),
        (col3, format_num(total_events), "OUTAGE EVENTS", "#ffd93d"),
        (col4, format_num(total_outage_mins), "SERVICE MINS", "#6bcbff"),
        (col5, format_num(customer_mins), "CUSTOMER MINS", "#c56bff"),
        (col6, format_num(impacted_subs), "IMPACTED SUBS", "#6bff95"),
    ]
    
    for col, value, label, color in metrics:
        with col:
            st.markdown(f"""
            <div class="glass-card" style="text-align: center;">
                <div style="font-size: 32px; font-weight: 700; color: {color};">{value}</div>
                <div class="metric-label">{label}</div>
            </div>
            """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ==================== SECOND ROW: GAUGES & DONUTS ====================
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        fig = create_gauge(availability, "Availability", "#00ff88", 100)
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col2:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        # COTTR score (inverse of outage rate)
        cottr = max(0, 100 - (total_events / total_sites * 0.1)) if total_sites > 0 else 95
        fig = create_gauge(cottr, "COTTR Score", "#ffd93d", 100)
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col3:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        if 'FINAL_OUTAGE_CATEGORY' in df.columns:
            cats = df['FINAL_OUTAGE_CATEGORY'].value_counts().head(5)
            colors = ['#ff6b6b', '#ffd93d', '#6bcbff', '#c56bff', '#6bff95']
            fig = create_donut(cats.index.tolist(), cats.values.tolist(), colors, "Outage Categories")
            st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col4:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        if 'SERVICEIMPACTCRITERIA' in df.columns:
            impact = df['SERVICEIMPACTCRITERIA'].value_counts().head(5)
            colors = ['#ff9f43', '#ee5253', '#10ac84', '#5f27cd', '#00d2d3']
            fig = create_donut(impact.index.tolist(), impact.values.tolist(), colors, "Impact Criteria")
            st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ==================== THIRD ROW: MARKET RANKINGS ====================
    col1, col2, col3, col4 = st.columns(4)
    
    # Top Markets by Outage
    with col1:
        st.markdown('<div class="section-title">🔴 Top Outage Markets</div>', unsafe_allow_html=True)
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        if 'MKT_NAME' in df.columns:
            mkt = df.groupby('MKT_NAME')['SERVICE_OUTAGE_DURATION'].sum().sort_values(ascending=False).head(6)
            max_val = mkt.max()
            for market, val in mkt.items():
                pct = (val / max_val * 100) if max_val > 0 else 0
                st.markdown(f"""
                <div class="market-item">
                    <span style="color: white; font-size: 12px;">{market[:14]}</span>
                    <span style="color: #ff6b6b; font-weight: 600;">{format_num(val)}</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {pct}%; background: linear-gradient(90deg, #ff6b6b, #ff9f43);"></div>
                </div>
                """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Top Markets by Customer Impact
    with col2:
        st.markdown('<div class="section-title">⏱️ Customer Minutes</div>', unsafe_allow_html=True)
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        if 'MKT_NAME' in df.columns and 'LOC_IMPACT_DURATION_IN_MINS_TOTAL' in df.columns:
            mkt = df.groupby('MKT_NAME')['LOC_IMPACT_DURATION_IN_MINS_TOTAL'].sum().sort_values(ascending=False).head(6)
            max_val = mkt.max()
            for market, val in mkt.items():
                pct = (val / max_val * 100) if max_val > 0 else 0
                st.markdown(f"""
                <div class="market-item">
                    <span style="color: white; font-size: 12px;">{market[:14]}</span>
                    <span style="color: #c56bff; font-weight: 600;">{format_num(val)}</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {pct}%; background: linear-gradient(90deg, #c56bff, #ff6bca);"></div>
                </div>
                """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Top Markets by Impacted Subs
    with col3:
        st.markdown('<div class="section-title">👥 Impacted Subscribers</div>', unsafe_allow_html=True)
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        if 'MKT_NAME' in df.columns and 'LOC_SEVERELY_IMPACTED_SUB_CNT_TOTAL' in df.columns:
            mkt = df.groupby('MKT_NAME')['LOC_SEVERELY_IMPACTED_SUB_CNT_TOTAL'].sum().sort_values(ascending=False).head(6)
            max_val = mkt.max()
            for market, val in mkt.items():
                pct = (val / max_val * 100) if max_val > 0 else 0
                st.markdown(f"""
                <div class="market-item">
                    <span style="color: white; font-size: 12px;">{market[:14]}</span>
                    <span style="color: #6bff95; font-weight: 600;">{format_num(val)}</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {pct}%; background: linear-gradient(90deg, #6bff95, #00d4ff);"></div>
                </div>
                """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Top Markets by Event Count
    with col4:
        st.markdown('<div class="section-title">📊 Event Count</div>', unsafe_allow_html=True)
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        if 'MKT_NAME' in df.columns:
            mkt = df['MKT_NAME'].value_counts().head(6)
            max_val = mkt.max()
            for market, val in mkt.items():
                pct = (val / max_val * 100) if max_val > 0 else 0
                st.markdown(f"""
                <div class="market-item">
                    <span style="color: white; font-size: 12px;">{market[:14]}</span>
                    <span style="color: #6bcbff; font-weight: 600;">{format_num(val)}</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {pct}%; background: linear-gradient(90deg, #6bcbff, #00d4ff);"></div>
                </div>
                """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ==================== TREND CHART ====================
    st.markdown('<div class="section-title">📈 Daily Outage Trend</div>', unsafe_allow_html=True)
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    
    if 'LOCAL_START_TIMESTAMP' in df.columns:
        df['DATE'] = pd.to_datetime(df['LOCAL_START_TIMESTAMP'], format='ISO8601').dt.date
        daily = df.groupby('DATE').agg({
            'SERVICE_OUTAGE_DURATION': 'sum',
            'SITE_CD': 'nunique',
            'LOC_SEVERELY_IMPACTED_SUB_CNT_TOTAL': 'sum'
        }).reset_index()
        daily.columns = ['Date', 'Outage_Mins', 'Sites', 'Subs']
        daily['Date'] = pd.to_datetime(daily['Date'], format='ISO8601')
        
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        fig.add_trace(go.Scatter(
            x=daily['Date'], y=daily['Outage_Mins'],
            fill='tozeroy', name='Outage Minutes',
            line=dict(color='#ff6b6b', width=2),
            fillcolor='rgba(255,107,107,0.3)'
        ), secondary_y=False)
        
        fig.add_trace(go.Scatter(
            x=daily['Date'], y=daily['Sites'],
            name='Sites Affected', mode='lines+markers',
            line=dict(color='#00ff88', width=2),
            marker=dict(size=4)
        ), secondary_y=True)
        
        fig.update_layout(
            height=300,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font_color='white',
            legend=dict(orientation='h', y=1.1, x=0.5, xanchor='center'),
            margin=dict(t=40, b=40, l=60, r=60),
            hovermode='x unified'
        )
        fig.update_xaxes(showgrid=False, gridcolor='rgba(255,255,255,0.1)')
        fig.update_yaxes(showgrid=True, gridcolor='rgba(255,255,255,0.05)', title='Outage Mins', secondary_y=False)
        fig.update_yaxes(showgrid=False, title='Sites', secondary_y=True)
        
        st.plotly_chart(fig, use_container_width=True)
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Footer stats
    st.markdown(f"""
    <div style="text-align: center; padding: 20px; color: rgba(255,255,255,0.4); font-size: 12px;">
        Data: {len(df):,} records | Sites: {total_sites:,} | Markets: {df['MKT_NAME'].nunique() if 'MKT_NAME' in df.columns else 0} | 
        Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
