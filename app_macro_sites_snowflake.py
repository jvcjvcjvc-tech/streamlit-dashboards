"""
Macro Sites Dashboard - Snowflake Streamlit Version (Enhanced)
Coverage ID 'A' Analysis - Based on Atoll Naming Convention
Deploys to Snowflake Streamlit
Enhanced with additional visualizations and analytics
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

# Snowflake imports for Streamlit in Snowflake
from snowflake.snowpark.context import get_active_session

st.set_page_config(
    page_title="Macro Sites Dashboard - Coverage ID 'A'",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    }
    .main-header {
        background: linear-gradient(90deg, #e94560, #0f3460);
        color: white;
        padding: 25px 30px;
        font-size: 28px;
        font-weight: bold;
        margin: -1rem -1rem 1.5rem -1rem;
        text-align: center;
        border-radius: 0 0 15px 15px;
        box-shadow: 0 4px 20px rgba(233,69,96,0.3);
    }
    .sub-header {
        color: #e94560;
        text-align: center;
        margin-top: -10px;
        margin-bottom: 25px;
        font-size: 14px;
    }
    .naming-convention {
        background: rgba(233,69,96,0.1);
        border: 1px solid rgba(233,69,96,0.3);
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 20px;
    }
    .metric-card {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 16px;
        padding: 20px;
        text-align: center;
        backdrop-filter: blur(10px);
    }
    .metric-value {
        font-size: 40px;
        font-weight: bold;
        background: linear-gradient(90deg, #e94560, #ff6b6b);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .metric-value-blue {
        font-size: 40px;
        font-weight: bold;
        color: #00b4d8;
    }
    .metric-value-green {
        font-size: 40px;
        font-weight: bold;
        color: #00d9a5;
    }
    .metric-value-orange {
        font-size: 40px;
        font-weight: bold;
        color: #f77f00;
    }
    .metric-value-purple {
        font-size: 40px;
        font-weight: bold;
        color: #9d4edd;
    }
    .metric-label {
        font-size: 11px;
        color: #aaa;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        margin-top: 8px;
    }
    .section-title {
        color: #fff;
        font-size: 18px;
        font-weight: 600;
        margin: 25px 0 15px 0;
        padding-left: 12px;
        border-left: 4px solid #e94560;
    }
    .glass-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 15px;
        margin-bottom: 15px;
    }
    .coverage-badge {
        display: inline-block;
        background: linear-gradient(90deg, #e94560, #ff6b6b);
        color: white;
        padding: 5px 15px;
        border-radius: 20px;
        font-weight: bold;
        margin: 2px;
    }
    div[data-testid="stSidebar"] {
        background: rgba(15,52,96,0.95);
    }
    div[data-testid="stSidebar"] * {
        color: #fff !important;
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
        background: linear-gradient(90deg, #e94560, #0f3460) !important;
    }
    .insight-card {
        background: linear-gradient(145deg, rgba(233,69,96,0.1), rgba(15,52,96,0.2));
        border: 1px solid rgba(233,69,96,0.3);
        border-radius: 12px;
        padding: 15px;
        margin: 10px 0;
    }
    .insight-title {
        color: #e94560;
        font-size: 14px;
        font-weight: 600;
        margin-bottom: 8px;
    }
    .insight-value {
        color: #fff;
        font-size: 24px;
        font-weight: 700;
    }
    .comparison-positive {
        color: #00d9a5;
    }
    .comparison-negative {
        color: #ff6b6b;
    }
    .search-highlight {
        background: rgba(233,69,96,0.3);
        padding: 2px 6px;
        border-radius: 4px;
    }
    .stat-box {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 8px;
        padding: 12px;
        text-align: center;
    }
    .mini-metric {
        font-size: 18px;
        font-weight: 600;
        color: #00b4d8;
    }
    .mini-label {
        font-size: 10px;
        color: #888;
        text-transform: uppercase;
    }
</style>
""", unsafe_allow_html=True)

COVERAGE_TYPES = {
    'A': ('Macro', '#e94560', 'Standard outdoor sites - monopoles & rooftops'),
    'B': ('Micro', '#00b4d8', '250mW-5W small footprint outdoor sites'),
    'C': ('Repeater', '#00d9a5', 'Repeater equipment in outdoor settings'),
    'D': ('DAS', '#f77f00', 'Distributed Antenna System - 3rd party maintained'),
    'E': ('Temp/Toy Cell', '#9d4edd', 'Temporary outdoor sites'),
    'F': ('Pico', '#ff6b6b', '250mW-5W outdoor IPBTS deployment')
}


@st.cache_data(ttl=300)
def load_macro_data():
    """Load macro site data from Snowflake"""
    session = get_active_session()
    
    # Query to get macro sites data with coverage ID analysis
    # Modify this query to match your actual table/view structure
    query = """
    SELECT 
        COVERAGE_ID,
        REGION,
        MARKET,
        RING_ID_DESCRIPTION,
        COUNT(DISTINCT SITE_ID) AS SITE_COUNT,
        COUNT(DISTINCT SECTOR_ID) AS SECTOR_COUNT
    FROM YOUR_DATABASE.YOUR_SCHEMA.YOUR_SITES_TABLE
    WHERE COVERAGE_ID IS NOT NULL
    GROUP BY 
        COVERAGE_ID,
        REGION,
        MARKET,
        RING_ID_DESCRIPTION
    ORDER BY REGION, MARKET
    """
    
    try:
        df = session.sql(query).to_pandas()
        return df
    except Exception as e:
        st.error(f"Error loading data: {str(e)}")
        return None


def format_number(num):
    """Format large numbers for display"""
    if num >= 1e6:
        return f"{num/1e6:.1f}M"
    elif num >= 1e3:
        return f"{num/1e3:.1f}K"
    return f"{num:,.0f}"


def create_gauge_chart(value, title, max_value=100, color="#e94560"):
    """Create a gauge chart for metrics"""
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=value,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': title, 'font': {'size': 14, 'color': '#fff'}},
        number={'font': {'size': 28, 'color': '#fff'}},
        gauge={
            'axis': {'range': [0, max_value], 'tickcolor': '#fff'},
            'bar': {'color': color},
            'bgcolor': 'rgba(255,255,255,0.1)',
            'bordercolor': 'rgba(255,255,255,0.2)',
            'steps': [
                {'range': [0, max_value*0.33], 'color': 'rgba(255,107,107,0.2)'},
                {'range': [max_value*0.33, max_value*0.66], 'color': 'rgba(255,193,7,0.2)'},
                {'range': [max_value*0.66, max_value], 'color': 'rgba(0,217,165,0.2)'}
            ],
            'threshold': {
                'line': {'color': '#fff', 'width': 2},
                'thickness': 0.75,
                'value': value
            }
        }
    ))
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        font={'color': '#fff'},
        height=200,
        margin=dict(l=20, r=20, t=40, b=20)
    )
    return fig


def create_treemap(df, path_cols, value_col, color_col=None):
    """Create a treemap visualization"""
    fig = px.treemap(
        df,
        path=path_cols,
        values=value_col,
        color=color_col if color_col else value_col,
        color_continuous_scale='Magenta'
    )
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        font={'color': '#fff'},
        height=500,
        margin=dict(l=10, r=10, t=30, b=10)
    )
    return fig


def create_heatmap(df, x_col, y_col, value_col):
    """Create a heatmap visualization"""
    pivot_df = df.pivot_table(index=y_col, columns=x_col, values=value_col, aggfunc='sum').fillna(0)
    
    fig = go.Figure(data=go.Heatmap(
        z=pivot_df.values,
        x=pivot_df.columns.tolist(),
        y=pivot_df.index.tolist(),
        colorscale=[[0, '#0f3460'], [0.5, '#e94560'], [1, '#ff6b6b']],
        hovertemplate='%{x}<br>%{y}<br>Sites: %{z:,}<extra></extra>'
    ))
    
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font={'color': '#fff'},
        height=400,
        margin=dict(l=20, r=20, t=30, b=20),
        xaxis={'title': '', 'tickangle': -45},
        yaxis={'title': ''}
    )
    return fig


def create_sunburst(df, path_cols, value_col):
    """Create a sunburst chart"""
    fig = px.sunburst(
        df,
        path=path_cols,
        values=value_col,
        color=value_col,
        color_continuous_scale='Magenta'
    )
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        font={'color': '#fff'},
        height=500,
        margin=dict(l=10, r=10, t=30, b=10)
    )
    return fig


def calculate_statistics(df, col):
    """Calculate comprehensive statistics for a column"""
    return {
        'mean': df[col].mean(),
        'median': df[col].median(),
        'std': df[col].std(),
        'min': df[col].min(),
        'max': df[col].max(),
        'sum': df[col].sum(),
        'count': len(df)
    }


def main():
    st.markdown('<div class="main-header">📡 Macro Sites Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Coverage ID Analysis | Based on Atoll Naming Convention | Snowflake Streamlit</div>', unsafe_allow_html=True)
    
    with st.expander("📋 Coverage Type Naming Convention (Atoll)", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            | Coverage ID | Type | Description |
            |:-----------:|:-----|:------------|
            | **A** | **Macro** | Standard outdoor sites (monopoles, rooftops) |
            | **B** | Micro | 250mW-5W small footprint sites |
            | **C** | Repeater | Outdoor repeater equipment |
            """)
        with col2:
            st.markdown("""
            | Coverage ID | Type | Description |
            |:-----------:|:-----|:------------|
            | **D** | DAS | Distributed Antenna System |
            | **E** | Temp/Toy Cell | Temporary outdoor sites |
            | **F** | Pico | 250mW-5W IPBTS deployment |
            """)
    
    df = load_macro_data()
    
    if df is None or df.empty:
        st.error("No macro sites data available. Please check your Snowflake query and table access.")
        st.info("""
        **Setup Instructions:**
        1. Update the `load_macro_data()` function with your actual table/view path
        2. Ensure the table contains columns: COVERAGE_ID, REGION, MARKET, RING_ID_DESCRIPTION, SITE_ID, SECTOR_ID
        3. Grant SELECT permissions to the Streamlit app role
        """)
        
        # Show sample data structure
        st.markdown("### Expected Data Structure")
        sample_df = pd.DataFrame({
            'COVERAGE_ID': ['A', 'A', 'B', 'C'],
            'REGION': ['WEST', 'EAST', 'WEST', 'SOUTH'],
            'MARKET': ['Los Angeles', 'New York', 'Seattle', 'Dallas'],
            'RING_ID_DESCRIPTION': ['Urban', 'Urban', 'Suburban', 'Rural'],
            'SITE_COUNT': [150, 200, 45, 30],
            'SECTOR_COUNT': [450, 600, 135, 90]
        })
        st.dataframe(sample_df, use_container_width=True, hide_index=True)
        return
    
    coverage_id_col = 'COVERAGE_ID' if 'COVERAGE_ID' in df.columns else 'COVERAGE_TYPE'
    
    # Sidebar filters
    with st.sidebar:
        st.markdown("### 🎯 Filters")
        
        if 'REGION' in df.columns:
            regions = ['All'] + sorted(df['REGION'].dropna().unique().tolist())
            selected_region = st.selectbox("Region", regions)
        else:
            selected_region = 'All'
        
        if coverage_id_col in df.columns:
            coverage_ids = ['All'] + sorted(df[coverage_id_col].dropna().unique().tolist())
            selected_coverage = st.selectbox("Coverage ID", coverage_ids, 
                help="A=Macro, B=Micro, C=Repeater, D=DAS, E=Temp, F=Pico")
        else:
            selected_coverage = 'All'
        
        if 'RING_ID_DESCRIPTION' in df.columns:
            ring_types = ['All'] + sorted(df['RING_ID_DESCRIPTION'].dropna().unique().tolist())
            selected_ring = st.selectbox("Ring Description", ring_types)
        else:
            selected_ring = 'All'
        
        if 'MARKET' in df.columns:
            markets = ['All'] + sorted(df['MARKET'].dropna().unique().tolist())
            selected_market = st.selectbox("Market", markets)
        else:
            selected_market = 'All'
        
        st.markdown("---")
        st.markdown("### 📊 Naming Convention")
        st.markdown("**Coverage ID 'A' = Macro**")
        st.markdown("Extracted from site name")
        st.markdown("---")
        st.markdown(f"**Total Rows:** {len(df):,}")
        st.markdown(f"**Last Refresh:** {datetime.now().strftime('%H:%M')}")
        
        # Refresh button
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    
    # Apply filters
    filtered_df = df.copy()
    if selected_region != 'All' and 'REGION' in df.columns:
        filtered_df = filtered_df[filtered_df['REGION'] == selected_region]
    if selected_coverage != 'All' and coverage_id_col in df.columns:
        filtered_df = filtered_df[filtered_df[coverage_id_col] == selected_coverage]
    if selected_ring != 'All' and 'RING_ID_DESCRIPTION' in df.columns:
        filtered_df = filtered_df[filtered_df['RING_ID_DESCRIPTION'] == selected_ring]
    if selected_market != 'All' and 'MARKET' in df.columns:
        filtered_df = filtered_df[filtered_df['MARKET'] == selected_market]
    
    # Calculate metrics
    total_sites = filtered_df['SITE_COUNT'].sum() if 'SITE_COUNT' in filtered_df.columns else 0
    total_sectors = filtered_df['SECTOR_COUNT'].sum() if 'SECTOR_COUNT' in filtered_df.columns else 0
    total_markets = filtered_df['MARKET'].nunique() if 'MARKET' in filtered_df.columns else 0
    total_regions = filtered_df['REGION'].nunique() if 'REGION' in filtered_df.columns else 0
    avg_sectors_per_site = total_sectors / total_sites if total_sites > 0 else 0
    
    macro_a_only = filtered_df[filtered_df[coverage_id_col] == 'A'] if coverage_id_col in filtered_df.columns else filtered_df
    macro_a_sites = macro_a_only['SITE_COUNT'].sum() if 'SITE_COUNT' in macro_a_only.columns else 0
    
    # Key Metrics
    st.markdown('<div class="section-title">📈 Key Metrics</div>', unsafe_allow_html=True)
    
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    
    with c1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{format_number(total_sites)}</div>
            <div class="metric-label">Total Sites</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value-blue">{format_number(macro_a_sites)}</div>
            <div class="metric-label">Coverage ID 'A' Sites</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value-green">{format_number(total_sectors)}</div>
            <div class="metric-label">Total Sectors</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value-orange">{avg_sectors_per_site:.1f}</div>
            <div class="metric-label">Avg Sectors/Site</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c5:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value-purple">{total_markets}</div>
            <div class="metric-label">Markets</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c6:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value-blue">{total_regions}</div>
            <div class="metric-label">Regions</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Tabs - Enhanced with more visualizations
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "🔤 Coverage Analysis",
        "🗺️ Regional View",
        "📊 Market Analysis",
        "🎯 Ring Description",
        "🔥 Heatmap",
        "🌳 Hierarchy View",
        "📈 Advanced Analytics",
        "📋 Data Explorer"
    ])
    
    with tab1:
        st.markdown('<div class="section-title">Coverage ID Distribution (Naming Convention)</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            if coverage_id_col in filtered_df.columns:
                coverage_data = filtered_df.groupby(coverage_id_col).agg({
                    'SITE_COUNT': 'sum',
                    'SECTOR_COUNT': 'sum'
                }).reset_index()
                coverage_data = coverage_data.sort_values('SITE_COUNT', ascending=False)
                
                coverage_data['Type_Name'] = coverage_data[coverage_id_col].apply(
                    lambda x: f"{x} - {COVERAGE_TYPES.get(x, ('Unknown', '#888', ''))[0]}"
                )
                
                colors = [COVERAGE_TYPES.get(x, ('Unknown', '#888', ''))[1] for x in coverage_data[coverage_id_col]]
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=coverage_data['Type_Name'],
                    y=coverage_data['SITE_COUNT'],
                    marker_color=colors,
                    text=coverage_data['SITE_COUNT'].apply(lambda x: f"{x:,}"),
                    textposition='outside'
                ))
                
                fig.update_layout(
                    title="Sites by Coverage ID",
                    height=400,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    xaxis=dict(gridcolor='rgba(255,255,255,0.05)', title=''),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Site Count'),
                    margin=dict(l=20, r=20, t=50, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            if coverage_id_col in filtered_df.columns:
                fig = px.pie(
                    coverage_data,
                    values='SITE_COUNT',
                    names='Type_Name',
                    color=coverage_data[coverage_id_col],
                    color_discrete_map={k: v[1] for k, v in COVERAGE_TYPES.items()},
                    hole=0.4
                )
                fig.update_layout(
                    title="Coverage ID Distribution",
                    height=400,
                    paper_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    margin=dict(l=20, r=20, t=50, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        if coverage_id_col in filtered_df.columns:
            coverage_summary = coverage_data.copy()
            coverage_summary['Pct_of_Total'] = (coverage_summary['SITE_COUNT'] / coverage_summary['SITE_COUNT'].sum() * 100).round(2)
            coverage_summary['Avg_Sectors_Per_Site'] = (coverage_summary['SECTOR_COUNT'] / coverage_summary['SITE_COUNT']).round(1)
            coverage_summary.columns = ['Coverage ID', 'Site Count', 'Sector Count', 'Type Name', '% of Total', 'Avg Sectors/Site']
            
            st.markdown("**Coverage ID Summary**")
            st.dataframe(coverage_summary[['Coverage ID', 'Type Name', 'Site Count', 'Sector Count', '% of Total', 'Avg Sectors/Site']], 
                        use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with tab2:
        st.markdown('<div class="section-title">Sites by Region</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            if 'REGION' in filtered_df.columns:
                region_data = filtered_df.groupby('REGION').agg({
                    'SITE_COUNT': 'sum',
                    'SECTOR_COUNT': 'sum'
                }).reset_index()
                region_data = region_data.sort_values('SITE_COUNT', ascending=True)
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    y=region_data['REGION'],
                    x=region_data['SITE_COUNT'],
                    orientation='h',
                    marker_color='#e94560',
                    text=region_data['SITE_COUNT'].apply(lambda x: f"{x:,}"),
                    textposition='auto'
                ))
                
                fig.update_layout(
                    title="Total Sites by Region",
                    height=400,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    xaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Site Count'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.05)', title=''),
                    margin=dict(l=20, r=20, t=50, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            if 'REGION' in filtered_df.columns and coverage_id_col in filtered_df.columns:
                region_coverage = filtered_df.groupby(['REGION', coverage_id_col]).agg({
                    'SITE_COUNT': 'sum'
                }).reset_index()
                
                fig = px.bar(
                    region_coverage,
                    x='REGION',
                    y='SITE_COUNT',
                    color=coverage_id_col,
                    color_discrete_map={k: v[1] for k, v in COVERAGE_TYPES.items()},
                    barmode='stack'
                )
                fig.update_layout(
                    title="Sites by Region & Coverage ID",
                    height=400,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    xaxis=dict(gridcolor='rgba(255,255,255,0.05)', title=''),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Site Count'),
                    legend=dict(title='Coverage ID'),
                    margin=dict(l=20, r=20, t=50, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
    
    with tab3:
        st.markdown('<div class="section-title">Top Markets by Site Count</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            if 'MARKET' in filtered_df.columns:
                market_data = filtered_df.groupby('MARKET').agg({
                    'SITE_COUNT': 'sum',
                    'SECTOR_COUNT': 'sum'
                }).reset_index()
                top_markets = market_data.nlargest(15, 'SITE_COUNT')
                top_markets = top_markets.sort_values('SITE_COUNT', ascending=True)
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    y=top_markets['MARKET'],
                    x=top_markets['SITE_COUNT'],
                    orientation='h',
                    marker=dict(
                        color=top_markets['SITE_COUNT'],
                        colorscale=[[0, '#0f3460'], [0.5, '#e94560'], [1, '#ff6b6b']]
                    ),
                    text=top_markets['SITE_COUNT'].apply(lambda x: f"{x:,}"),
                    textposition='auto'
                ))
                
                fig.update_layout(
                    title="Top 15 Markets by Site Count",
                    height=500,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    xaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Site Count'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.05)', title=''),
                    margin=dict(l=20, r=20, t=50, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            if 'MARKET' in filtered_df.columns:
                top_sectors = market_data.nlargest(15, 'SECTOR_COUNT')
                top_sectors = top_sectors.sort_values('SECTOR_COUNT', ascending=True)
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    y=top_sectors['MARKET'],
                    x=top_sectors['SECTOR_COUNT'],
                    orientation='h',
                    marker=dict(
                        color=top_sectors['SECTOR_COUNT'],
                        colorscale=[[0, '#0f3460'], [0.5, '#00b4d8'], [1, '#00d9a5']]
                    ),
                    text=top_sectors['SECTOR_COUNT'].apply(lambda x: f"{x:,}"),
                    textposition='auto'
                ))
                
                fig.update_layout(
                    title="Top 15 Markets by Sector Count",
                    height=500,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    xaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Sector Count'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.05)', title=''),
                    margin=dict(l=20, r=20, t=50, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
    
    with tab4:
        st.markdown('<div class="section-title">Analysis by Ring ID Description</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            if 'RING_ID_DESCRIPTION' in filtered_df.columns:
                ring_data = filtered_df.groupby('RING_ID_DESCRIPTION').agg({
                    'SITE_COUNT': 'sum',
                    'SECTOR_COUNT': 'sum'
                }).reset_index()
                ring_data = ring_data.sort_values('SITE_COUNT', ascending=False)
                
                colors = ['#e94560', '#00b4d8', '#00d9a5', '#f77f00', '#9d4edd', '#ff6b6b']
                
                fig = px.bar(
                    ring_data,
                    x='RING_ID_DESCRIPTION',
                    y='SITE_COUNT',
                    color='RING_ID_DESCRIPTION',
                    color_discrete_sequence=colors,
                    text='SITE_COUNT'
                )
                fig.update_layout(
                    title="Sites by Ring Description",
                    height=400,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    xaxis=dict(gridcolor='rgba(255,255,255,0.05)', title=''),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Site Count'),
                    showlegend=False,
                    margin=dict(l=20, r=20, t=50, b=20)
                )
                fig.update_traces(texttemplate='%{text:,}', textposition='outside')
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            if 'RING_ID_DESCRIPTION' in filtered_df.columns:
                fig = px.pie(
                    ring_data,
                    values='SITE_COUNT',
                    names='RING_ID_DESCRIPTION',
                    color_discrete_sequence=colors,
                    hole=0.4
                )
                fig.update_layout(
                    title="Ring Description Distribution",
                    height=400,
                    paper_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    margin=dict(l=20, r=20, t=50, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
    
    with tab5:
        st.markdown('<div class="section-title">Region vs Coverage ID Heatmap</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            if 'REGION' in filtered_df.columns and coverage_id_col in filtered_df.columns:
                heatmap_data = filtered_df.groupby(['REGION', coverage_id_col]).agg({
                    'SITE_COUNT': 'sum'
                }).reset_index()
                
                fig = create_heatmap(heatmap_data, coverage_id_col, 'REGION', 'SITE_COUNT')
                fig.update_layout(title="Sites Distribution: Region × Coverage ID")
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            st.markdown("**Heatmap Insights**")
            
            if 'REGION' in filtered_df.columns and coverage_id_col in filtered_df.columns:
                region_max = filtered_df.groupby('REGION')['SITE_COUNT'].sum().idxmax()
                coverage_max = filtered_df.groupby(coverage_id_col)['SITE_COUNT'].sum().idxmax()
                
                st.markdown(f"""
                <div class="insight-card">
                    <div class="insight-title">🏆 Top Region</div>
                    <div class="insight-value">{region_max}</div>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown(f"""
                <div class="insight-card">
                    <div class="insight-title">📊 Dominant Coverage ID</div>
                    <div class="insight-value">{coverage_max} - {COVERAGE_TYPES.get(coverage_max, ('Unknown',))[0]}</div>
                </div>
                """, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Market vs Ring Description Heatmap
        st.markdown('<div class="section-title">Market vs Ring Description Heatmap</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        if 'MARKET' in filtered_df.columns and 'RING_ID_DESCRIPTION' in filtered_df.columns:
            market_ring_data = filtered_df.groupby(['MARKET', 'RING_ID_DESCRIPTION']).agg({
                'SITE_COUNT': 'sum'
            }).reset_index()
            
            top_markets_list = market_ring_data.groupby('MARKET')['SITE_COUNT'].sum().nlargest(10).index.tolist()
            market_ring_filtered = market_ring_data[market_ring_data['MARKET'].isin(top_markets_list)]
            
            fig = create_heatmap(market_ring_filtered, 'RING_ID_DESCRIPTION', 'MARKET', 'SITE_COUNT')
            fig.update_layout(title="Top 10 Markets × Ring Description")
            st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with tab6:
        st.markdown('<div class="section-title">Hierarchical Data Visualization</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            st.markdown("**Treemap: Region → Market → Coverage ID**")
            
            if all(col in filtered_df.columns for col in ['REGION', 'MARKET', coverage_id_col]):
                treemap_data = filtered_df.groupby(['REGION', 'MARKET', coverage_id_col]).agg({
                    'SITE_COUNT': 'sum'
                }).reset_index()
                
                fig = create_treemap(
                    treemap_data,
                    ['REGION', 'MARKET', coverage_id_col],
                    'SITE_COUNT'
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            st.markdown("**Sunburst: Coverage ID → Region → Ring**")
            
            if all(col in filtered_df.columns for col in [coverage_id_col, 'REGION', 'RING_ID_DESCRIPTION']):
                sunburst_data = filtered_df.groupby([coverage_id_col, 'REGION', 'RING_ID_DESCRIPTION']).agg({
                    'SITE_COUNT': 'sum'
                }).reset_index()
                
                fig = create_sunburst(
                    sunburst_data,
                    [coverage_id_col, 'REGION', 'RING_ID_DESCRIPTION'],
                    'SITE_COUNT'
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Sector density analysis
        st.markdown('<div class="section-title">Sector Density Analysis</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        if 'SITE_COUNT' in filtered_df.columns and 'SECTOR_COUNT' in filtered_df.columns:
            scatter_data = filtered_df.groupby(['REGION', 'MARKET']).agg({
                'SITE_COUNT': 'sum',
                'SECTOR_COUNT': 'sum'
            }).reset_index()
            scatter_data['SECTORS_PER_SITE'] = scatter_data['SECTOR_COUNT'] / scatter_data['SITE_COUNT']
            
            fig = px.scatter(
                scatter_data,
                x='SITE_COUNT',
                y='SECTOR_COUNT',
                size='SECTORS_PER_SITE',
                color='REGION',
                hover_name='MARKET',
                title='Sites vs Sectors by Market (bubble size = sectors/site ratio)',
                color_discrete_sequence=px.colors.qualitative.Set2
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': '#fff'},
                height=450,
                xaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Site Count'),
                yaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Sector Count')
            )
            st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with tab7:
        st.markdown('<div class="section-title">Advanced Analytics & Statistics</div>', unsafe_allow_html=True)
        
        # Gauge charts row
        st.markdown("**Performance Indicators**")
        g1, g2, g3, g4 = st.columns(4)
        
        with g1:
            macro_pct = (macro_a_sites / total_sites * 100) if total_sites > 0 else 0
            fig = create_gauge_chart(macro_pct, "Macro (A) %", 100, "#e94560")
            st.plotly_chart(fig, use_container_width=True)
        
        with g2:
            fig = create_gauge_chart(avg_sectors_per_site, "Avg Sectors/Site", 5, "#00b4d8")
            st.plotly_chart(fig, use_container_width=True)
        
        with g3:
            market_coverage = (total_markets / 100 * 100) if total_markets > 0 else 0
            fig = create_gauge_chart(min(market_coverage, 100), "Market Coverage", 100, "#00d9a5")
            st.plotly_chart(fig, use_container_width=True)
        
        with g4:
            region_coverage = (total_regions / 10 * 100) if total_regions > 0 else 0
            fig = create_gauge_chart(min(region_coverage, 100), "Region Coverage", 100, "#f77f00")
            st.plotly_chart(fig, use_container_width=True)
        
        # Statistical summary
        st.markdown('<div class="section-title">Statistical Summary</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            st.markdown("**Site Count Statistics**")
            
            if 'SITE_COUNT' in filtered_df.columns:
                site_stats = calculate_statistics(filtered_df, 'SITE_COUNT')
                
                stat_col1, stat_col2, stat_col3 = st.columns(3)
                with stat_col1:
                    st.markdown(f"""
                    <div class="stat-box">
                        <div class="mini-metric">{site_stats['mean']:.1f}</div>
                        <div class="mini-label">Mean</div>
                    </div>
                    """, unsafe_allow_html=True)
                with stat_col2:
                    st.markdown(f"""
                    <div class="stat-box">
                        <div class="mini-metric">{site_stats['median']:.1f}</div>
                        <div class="mini-label">Median</div>
                    </div>
                    """, unsafe_allow_html=True)
                with stat_col3:
                    st.markdown(f"""
                    <div class="stat-box">
                        <div class="mini-metric">{site_stats['std']:.1f}</div>
                        <div class="mini-label">Std Dev</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                
                stat_col4, stat_col5, stat_col6 = st.columns(3)
                with stat_col4:
                    st.markdown(f"""
                    <div class="stat-box">
                        <div class="mini-metric">{site_stats['min']:,.0f}</div>
                        <div class="mini-label">Min</div>
                    </div>
                    """, unsafe_allow_html=True)
                with stat_col5:
                    st.markdown(f"""
                    <div class="stat-box">
                        <div class="mini-metric">{site_stats['max']:,.0f}</div>
                        <div class="mini-label">Max</div>
                    </div>
                    """, unsafe_allow_html=True)
                with stat_col6:
                    st.markdown(f"""
                    <div class="stat-box">
                        <div class="mini-metric">{site_stats['sum']:,.0f}</div>
                        <div class="mini-label">Total</div>
                    </div>
                    """, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            st.markdown("**Distribution Analysis**")
            
            if 'SITE_COUNT' in filtered_df.columns:
                fig = px.histogram(
                    filtered_df,
                    x='SITE_COUNT',
                    nbins=30,
                    title='Site Count Distribution',
                    color_discrete_sequence=['#e94560']
                )
                fig.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font={'color': '#fff'},
                    height=300,
                    xaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.1)')
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Box plots for comparison
        st.markdown('<div class="section-title">Distribution Comparison</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            if 'REGION' in filtered_df.columns and 'SITE_COUNT' in filtered_df.columns:
                fig = px.box(
                    filtered_df,
                    x='REGION',
                    y='SITE_COUNT',
                    color='REGION',
                    title='Site Count Distribution by Region',
                    color_discrete_sequence=px.colors.qualitative.Set2
                )
                fig.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font={'color': '#fff'},
                    height=350,
                    showlegend=False,
                    xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.1)')
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            if coverage_id_col in filtered_df.columns and 'SITE_COUNT' in filtered_df.columns:
                fig = px.box(
                    filtered_df,
                    x=coverage_id_col,
                    y='SITE_COUNT',
                    color=coverage_id_col,
                    title='Site Count Distribution by Coverage ID',
                    color_discrete_map={k: v[1] for k, v in COVERAGE_TYPES.items()}
                )
                fig.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font={'color': '#fff'},
                    height=350,
                    showlegend=False,
                    xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.1)')
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
    
    with tab8:
        st.markdown('<div class="section-title">Data Explorer</div>', unsafe_allow_html=True)
        
        # Search and filter section
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        search_col1, search_col2, search_col3 = st.columns([2, 1, 1])
        
        with search_col1:
            search_term = st.text_input("🔍 Search Markets", placeholder="Enter market name...")
        
        with search_col2:
            sort_by = st.selectbox("Sort By", ['SITE_COUNT', 'SECTOR_COUNT', 'MARKET', 'REGION'])
        
        with search_col3:
            sort_order = st.radio("Order", ['Descending', 'Ascending'], horizontal=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Apply search and sort
        display_df = filtered_df.copy()
        
        if search_term:
            if 'MARKET' in display_df.columns:
                display_df = display_df[display_df['MARKET'].str.contains(search_term, case=False, na=False)]
        
        if sort_by in display_df.columns:
            display_df = display_df.sort_values(sort_by, ascending=(sort_order == 'Ascending'))
        
        # Summary stats
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        summary_cols = st.columns(5)
        with summary_cols[0]:
            st.metric("Rows", f"{len(display_df):,}")
        with summary_cols[1]:
            st.metric("Total Sites", f"{display_df['SITE_COUNT'].sum():,}" if 'SITE_COUNT' in display_df.columns else "N/A")
        with summary_cols[2]:
            st.metric("Total Sectors", f"{display_df['SECTOR_COUNT'].sum():,}" if 'SECTOR_COUNT' in display_df.columns else "N/A")
        with summary_cols[3]:
            st.metric("Unique Markets", f"{display_df['MARKET'].nunique():,}" if 'MARKET' in display_df.columns else "N/A")
        with summary_cols[4]:
            st.metric("Unique Regions", f"{display_df['REGION'].nunique():,}" if 'REGION' in display_df.columns else "N/A")
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Data table with column selector
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        available_cols = display_df.columns.tolist()
        selected_cols = st.multiselect(
            "Select columns to display",
            options=available_cols,
            default=available_cols[:6] if len(available_cols) > 6 else available_cols
        )
        
        if selected_cols:
            st.dataframe(
                display_df[selected_cols],
                use_container_width=True,
                hide_index=True,
                height=400
            )
        else:
            st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)
        
        # Download buttons
        dl_col1, dl_col2, dl_col3 = st.columns(3)
        
        with dl_col1:
            csv = display_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name=f"macro_sites_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv"
            )
        
        with dl_col2:
            # Pivot summary
            if 'REGION' in display_df.columns and coverage_id_col in display_df.columns:
                pivot_csv = display_df.pivot_table(
                    index='REGION',
                    columns=coverage_id_col,
                    values='SITE_COUNT',
                    aggfunc='sum',
                    fill_value=0
                ).to_csv()
                st.download_button(
                    label="📥 Download Pivot (Region×Coverage)",
                    data=pivot_csv,
                    file_name=f"macro_sites_pivot_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )
        
        with dl_col3:
            # Summary by market
            if 'MARKET' in display_df.columns:
                market_summary = display_df.groupby('MARKET').agg({
                    'SITE_COUNT': 'sum',
                    'SECTOR_COUNT': 'sum'
                }).reset_index()
                market_csv = market_summary.to_csv(index=False)
                st.download_button(
                    label="📥 Download Market Summary",
                    data=market_csv,
                    file_name=f"market_summary_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Footer
    st.markdown("---")
    st.markdown(f"""
    <div style='text-align:center; color:#aaa; font-size:11px;'>
    Macro Sites Dashboard | Coverage ID 'A' = Macro | Sites: {total_sites:,} | Sectors: {total_sectors:,} | 
    Markets: {total_markets} | Regions: {total_regions} | 
    Data as of: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Powered by Snowflake Streamlit
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
