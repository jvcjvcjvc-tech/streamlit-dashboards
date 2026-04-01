"""
Macro Sites Dashboard - LOCAL TEST VERSION
Preview the dashboard with sample data before deploying to Snowflake
Run with: streamlit run app_macro_sites_local_test.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

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


@st.cache_data
def load_sample_data():
    """Generate sample data for testing"""
    np.random.seed(42)
    
    regions = ['WEST', 'EAST', 'CENTRAL', 'SOUTH', 'NORTHEAST', 'NORTHWEST']
    markets = [
        'Los Angeles', 'New York', 'Chicago', 'Dallas', 'Houston', 'Phoenix',
        'San Antonio', 'San Diego', 'San Jose', 'Austin', 'Jacksonville', 'Fort Worth',
        'Columbus', 'Charlotte', 'Seattle', 'Denver', 'Boston', 'Detroit',
        'Portland', 'Las Vegas', 'Miami', 'Atlanta', 'Philadelphia', 'Baltimore'
    ]
    coverage_ids = ['A', 'B', 'C', 'D', 'E', 'F']
    ring_descriptions = ['Urban Core', 'Suburban', 'Rural', 'Highway', 'Dense Urban']
    
    data = []
    for region in regions:
        region_markets = np.random.choice(markets, size=np.random.randint(3, 8), replace=False)
        for market in region_markets:
            for coverage_id in coverage_ids:
                for ring in ring_descriptions:
                    if np.random.random() > 0.3:
                        base_sites = 100 if coverage_id == 'A' else 30
                        site_count = int(np.random.exponential(base_sites) + np.random.randint(5, 50))
                        sector_count = site_count * np.random.randint(2, 5)
                        data.append({
                            'COVERAGE_ID': coverage_id,
                            'REGION': region,
                            'MARKET': market,
                            'RING_ID_DESCRIPTION': ring,
                            'SITE_COUNT': site_count,
                            'SECTOR_COUNT': sector_count
                        })
    
    return pd.DataFrame(data)


def format_number(num):
    if num >= 1e6:
        return f"{num/1e6:.1f}M"
    elif num >= 1e3:
        return f"{num/1e3:.1f}K"
    return f"{num:,.0f}"


def create_gauge_chart(value, title, max_value=100, color="#e94560"):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': title, 'font': {'size': 14, 'color': '#fff'}},
        number={'font': {'size': 28, 'color': '#fff'}},
        gauge={
            'axis': {'range': [0, max_value], 'tickcolor': '#fff'},
            'bar': {'color': color},
            'bgcolor': 'rgba(255,255,255,0.1)',
            'steps': [
                {'range': [0, max_value*0.33], 'color': 'rgba(255,107,107,0.2)'},
                {'range': [max_value*0.33, max_value*0.66], 'color': 'rgba(255,193,7,0.2)'},
                {'range': [max_value*0.66, max_value], 'color': 'rgba(0,217,165,0.2)'}
            ]
        }
    ))
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        font={'color': '#fff'},
        height=200,
        margin=dict(l=20, r=20, t=40, b=20)
    )
    return fig


def create_heatmap(df, x_col, y_col, value_col):
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
        margin=dict(l=20, r=20, t=30, b=20)
    )
    return fig


def main():
    st.markdown('<div class="main-header">📡 Macro Sites Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Coverage ID Analysis | LOCAL TEST VERSION with Sample Data</div>', unsafe_allow_html=True)
    
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
    
    df = load_sample_data()
    coverage_id_col = 'COVERAGE_ID'
    
    # Sidebar filters
    with st.sidebar:
        st.markdown("### 🎯 Filters")
        
        regions = ['All'] + sorted(df['REGION'].unique().tolist())
        selected_region = st.selectbox("Region", regions)
        
        coverage_ids = ['All'] + sorted(df[coverage_id_col].unique().tolist())
        selected_coverage = st.selectbox("Coverage ID", coverage_ids)
        
        ring_types = ['All'] + sorted(df['RING_ID_DESCRIPTION'].unique().tolist())
        selected_ring = st.selectbox("Ring Description", ring_types)
        
        markets = ['All'] + sorted(df['MARKET'].unique().tolist())
        selected_market = st.selectbox("Market", markets)
        
        st.markdown("---")
        st.markdown("### 📊 Info")
        st.markdown("**Coverage ID 'A' = Macro**")
        st.markdown(f"**Total Rows:** {len(df):,}")
        st.markdown(f"**Last Refresh:** {datetime.now().strftime('%H:%M')}")
        
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    
    # Apply filters
    filtered_df = df.copy()
    if selected_region != 'All':
        filtered_df = filtered_df[filtered_df['REGION'] == selected_region]
    if selected_coverage != 'All':
        filtered_df = filtered_df[filtered_df[coverage_id_col] == selected_coverage]
    if selected_ring != 'All':
        filtered_df = filtered_df[filtered_df['RING_ID_DESCRIPTION'] == selected_ring]
    if selected_market != 'All':
        filtered_df = filtered_df[filtered_df['MARKET'] == selected_market]
    
    # Metrics
    total_sites = filtered_df['SITE_COUNT'].sum()
    total_sectors = filtered_df['SECTOR_COUNT'].sum()
    total_markets = filtered_df['MARKET'].nunique()
    total_regions = filtered_df['REGION'].nunique()
    avg_sectors_per_site = total_sectors / total_sites if total_sites > 0 else 0
    
    macro_a_only = filtered_df[filtered_df[coverage_id_col] == 'A']
    macro_a_sites = macro_a_only['SITE_COUNT'].sum()
    
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
    
    # Tabs
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
        st.markdown('<div class="section-title">Coverage ID Distribution</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            coverage_data = filtered_df.groupby(coverage_id_col).agg({
                'SITE_COUNT': 'sum',
                'SECTOR_COUNT': 'sum'
            }).reset_index()
            coverage_data = coverage_data.sort_values('SITE_COUNT', ascending=False)
            coverage_data['Type_Name'] = coverage_data[coverage_id_col].apply(
                lambda x: f"{x} - {COVERAGE_TYPES.get(x, ('Unknown',))[0]}"
            )
            
            colors = [COVERAGE_TYPES.get(x, ('Unknown', '#888'))[1] for x in coverage_data[coverage_id_col]]
            
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
                xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                yaxis=dict(gridcolor='rgba(255,255,255,0.1)')
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
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
                font=dict(color='#fff')
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Summary table
        coverage_summary = coverage_data.copy()
        coverage_summary['Pct_of_Total'] = (coverage_summary['SITE_COUNT'] / coverage_summary['SITE_COUNT'].sum() * 100).round(2)
        coverage_summary['Avg_Sectors_Per_Site'] = (coverage_summary['SECTOR_COUNT'] / coverage_summary['SITE_COUNT']).round(1)
        coverage_summary.columns = ['Coverage ID', 'Site Count', 'Sector Count', 'Type Name', '% of Total', 'Avg Sectors/Site']
        
        st.markdown("**Coverage ID Summary**")
        st.dataframe(coverage_summary[['Coverage ID', 'Type Name', 'Site Count', 'Sector Count', '% of Total', 'Avg Sectors/Site']], 
                    use_container_width=True, hide_index=True)
    
    with tab2:
        st.markdown('<div class="section-title">Sites by Region</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
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
                xaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
                yaxis=dict(gridcolor='rgba(255,255,255,0.05)')
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
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
                xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                yaxis=dict(gridcolor='rgba(255,255,255,0.1)')
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        st.markdown('<div class="section-title">Top Markets by Site Count</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            market_data = filtered_df.groupby('MARKET').agg({
                'SITE_COUNT': 'sum',
                'SECTOR_COUNT': 'sum'
            }).reset_index()
            top_markets = market_data.nlargest(15, 'SITE_COUNT').sort_values('SITE_COUNT', ascending=True)
            
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
                xaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
                yaxis=dict(gridcolor='rgba(255,255,255,0.05)')
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            top_sectors = market_data.nlargest(15, 'SECTOR_COUNT').sort_values('SECTOR_COUNT', ascending=True)
            
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
                xaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
                yaxis=dict(gridcolor='rgba(255,255,255,0.05)')
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with tab4:
        st.markdown('<div class="section-title">Analysis by Ring ID Description</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
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
                showlegend=False,
                xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                yaxis=dict(gridcolor='rgba(255,255,255,0.1)')
            )
            fig.update_traces(texttemplate='%{text:,}', textposition='outside')
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
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
                font=dict(color='#fff')
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with tab5:
        st.markdown('<div class="section-title">Region vs Coverage ID Heatmap</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            heatmap_data = filtered_df.groupby(['REGION', coverage_id_col]).agg({
                'SITE_COUNT': 'sum'
            }).reset_index()
            
            fig = create_heatmap(heatmap_data, coverage_id_col, 'REGION', 'SITE_COUNT')
            fig.update_layout(title="Sites Distribution: Region × Coverage ID")
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.markdown("**Heatmap Insights**")
            
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
        
        # Market vs Ring
        st.markdown('<div class="section-title">Top Markets vs Ring Description</div>', unsafe_allow_html=True)
        
        market_ring_data = filtered_df.groupby(['MARKET', 'RING_ID_DESCRIPTION']).agg({
            'SITE_COUNT': 'sum'
        }).reset_index()
        
        top_markets_list = market_ring_data.groupby('MARKET')['SITE_COUNT'].sum().nlargest(10).index.tolist()
        market_ring_filtered = market_ring_data[market_ring_data['MARKET'].isin(top_markets_list)]
        
        fig = create_heatmap(market_ring_filtered, 'RING_ID_DESCRIPTION', 'MARKET', 'SITE_COUNT')
        fig.update_layout(title="Top 10 Markets × Ring Description")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab6:
        st.markdown('<div class="section-title">Hierarchical Data Visualization</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Treemap: Region → Market → Coverage ID**")
            
            treemap_data = filtered_df.groupby(['REGION', 'MARKET', coverage_id_col]).agg({
                'SITE_COUNT': 'sum'
            }).reset_index()
            
            fig = px.treemap(
                treemap_data,
                path=['REGION', 'MARKET', coverage_id_col],
                values='SITE_COUNT',
                color='SITE_COUNT',
                color_continuous_scale='Magenta'
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                font={'color': '#fff'},
                height=500
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.markdown("**Sunburst: Coverage ID → Region → Ring**")
            
            sunburst_data = filtered_df.groupby([coverage_id_col, 'REGION', 'RING_ID_DESCRIPTION']).agg({
                'SITE_COUNT': 'sum'
            }).reset_index()
            
            fig = px.sunburst(
                sunburst_data,
                path=[coverage_id_col, 'REGION', 'RING_ID_DESCRIPTION'],
                values='SITE_COUNT',
                color='SITE_COUNT',
                color_continuous_scale='Magenta'
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                font={'color': '#fff'},
                height=500
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Scatter plot
        st.markdown('<div class="section-title">Sector Density Analysis</div>', unsafe_allow_html=True)
        
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
            xaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
            yaxis=dict(gridcolor='rgba(255,255,255,0.1)')
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with tab7:
        st.markdown('<div class="section-title">Advanced Analytics & Statistics</div>', unsafe_allow_html=True)
        
        # Gauge charts
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
            market_pct = min((total_markets / 50) * 100, 100)
            fig = create_gauge_chart(market_pct, "Market Coverage", 100, "#00d9a5")
            st.plotly_chart(fig, use_container_width=True)
        
        with g4:
            region_pct = min((total_regions / 6) * 100, 100)
            fig = create_gauge_chart(region_pct, "Region Coverage", 100, "#f77f00")
            st.plotly_chart(fig, use_container_width=True)
        
        # Statistics
        st.markdown('<div class="section-title">Statistical Summary</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Site Count Statistics**")
            
            stats = {
                'Mean': filtered_df['SITE_COUNT'].mean(),
                'Median': filtered_df['SITE_COUNT'].median(),
                'Std Dev': filtered_df['SITE_COUNT'].std(),
                'Min': filtered_df['SITE_COUNT'].min(),
                'Max': filtered_df['SITE_COUNT'].max(),
                'Total': filtered_df['SITE_COUNT'].sum()
            }
            
            stat_cols = st.columns(3)
            for i, (label, value) in enumerate(stats.items()):
                with stat_cols[i % 3]:
                    st.markdown(f"""
                    <div class="stat-box">
                        <div class="mini-metric">{value:,.1f}</div>
                        <div class="mini-label">{label}</div>
                    </div>
                    """, unsafe_allow_html=True)
        
        with col2:
            st.markdown("**Distribution Analysis**")
            
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
        
        # Box plots
        st.markdown('<div class="section-title">Distribution Comparison</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            fig = px.box(
                filtered_df,
                x='REGION',
                y='SITE_COUNT',
                color='REGION',
                title='Site Count by Region',
                color_discrete_sequence=px.colors.qualitative.Set2
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': '#fff'},
                height=350,
                showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            fig = px.box(
                filtered_df,
                x=coverage_id_col,
                y='SITE_COUNT',
                color=coverage_id_col,
                title='Site Count by Coverage ID',
                color_discrete_map={k: v[1] for k, v in COVERAGE_TYPES.items()}
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': '#fff'},
                height=350,
                showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with tab8:
        st.markdown('<div class="section-title">Data Explorer</div>', unsafe_allow_html=True)
        
        # Search
        search_col1, search_col2, search_col3 = st.columns([2, 1, 1])
        
        with search_col1:
            search_term = st.text_input("🔍 Search Markets", placeholder="Enter market name...")
        
        with search_col2:
            sort_by = st.selectbox("Sort By", ['SITE_COUNT', 'SECTOR_COUNT', 'MARKET', 'REGION'])
        
        with search_col3:
            sort_order = st.radio("Order", ['Descending', 'Ascending'], horizontal=True)
        
        # Apply search
        display_df = filtered_df.copy()
        
        if search_term:
            display_df = display_df[display_df['MARKET'].str.contains(search_term, case=False, na=False)]
        
        display_df = display_df.sort_values(sort_by, ascending=(sort_order == 'Ascending'))
        
        # Summary
        summary_cols = st.columns(5)
        with summary_cols[0]:
            st.metric("Rows", f"{len(display_df):,}")
        with summary_cols[1]:
            st.metric("Total Sites", f"{display_df['SITE_COUNT'].sum():,}")
        with summary_cols[2]:
            st.metric("Total Sectors", f"{display_df['SECTOR_COUNT'].sum():,}")
        with summary_cols[3]:
            st.metric("Markets", f"{display_df['MARKET'].nunique():,}")
        with summary_cols[4]:
            st.metric("Regions", f"{display_df['REGION'].nunique():,}")
        
        # Data table
        st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)
        
        # Download
        csv = display_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name=f"macro_sites_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
    
    # Footer
    st.markdown("---")
    st.markdown(f"""
    <div style='text-align:center; color:#aaa; font-size:11px;'>
    Macro Sites Dashboard | LOCAL TEST VERSION | Sites: {total_sites:,} | Sectors: {total_sectors:,} | 
    Markets: {total_markets} | Regions: {total_regions} | 
    {datetime.now().strftime('%Y-%m-%d %H:%M')}
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
