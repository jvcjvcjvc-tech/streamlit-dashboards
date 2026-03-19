import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from glob import glob
import os
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
    sso_path = r"C:\Users\JChalap1\OneDrive - T-Mobile USA\Documents\AI_CURSOR\query_execution_agent_sso_auth 5\query_execution_agent_sso_auth"
    csv_files = glob(os.path.join(sso_path, "results_sso_*.csv"))
    
    for f in sorted(csv_files, key=os.path.getmtime, reverse=True):
        try:
            df = pd.read_csv(f, nrows=5, low_memory=False)
            if 'COVERAGE_ID' in df.columns and 'SITE_COUNT' in df.columns:
                return pd.read_csv(f, low_memory=False)
            elif 'COVERAGE_TYPE' in df.columns and 'SITE_COUNT' in df.columns:
                return pd.read_csv(f, low_memory=False)
        except Exception:
            continue
    return None


def format_number(num):
    if num >= 1e6:
        return f"{num/1e6:.1f}M"
    elif num >= 1e3:
        return f"{num/1e3:.1f}K"
    return f"{num:,.0f}"


def main():
    st.markdown('<div class="main-header">📡 Macro Sites Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Coverage ID Analysis | Based on Atoll Naming Convention</div>', unsafe_allow_html=True)
    
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
        st.error("No macro sites data available. Please run the macro_sites_coverage_a.sql query first.")
        st.code("""
cd "C:\\Users\\JChalap1\\OneDrive - T-Mobile USA\\Documents\\AI_CURSOR\\query_execution_agent_sso_auth 5\\query_execution_agent_sso_auth"
python simple_agent_with_sso_auth.py macro_sites_coverage_a.sql
        """)
        return
    
    coverage_id_col = 'COVERAGE_ID' if 'COVERAGE_ID' in df.columns else 'COVERAGE_TYPE'
    
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
    
    filtered_df = df.copy()
    if selected_region != 'All' and 'REGION' in df.columns:
        filtered_df = filtered_df[filtered_df['REGION'] == selected_region]
    if selected_coverage != 'All' and coverage_id_col in df.columns:
        filtered_df = filtered_df[filtered_df[coverage_id_col] == selected_coverage]
    if selected_ring != 'All' and 'RING_ID_DESCRIPTION' in df.columns:
        filtered_df = filtered_df[filtered_df['RING_ID_DESCRIPTION'] == selected_ring]
    if selected_market != 'All' and 'MARKET' in df.columns:
        filtered_df = filtered_df[filtered_df['MARKET'] == selected_market]
    
    total_sites = filtered_df['SITE_COUNT'].sum() if 'SITE_COUNT' in filtered_df.columns else 0
    total_sectors = filtered_df['SECTOR_COUNT'].sum() if 'SECTOR_COUNT' in filtered_df.columns else 0
    total_markets = filtered_df['MARKET'].nunique() if 'MARKET' in filtered_df.columns else 0
    total_regions = filtered_df['REGION'].nunique() if 'REGION' in filtered_df.columns else 0
    avg_sectors_per_site = total_sectors / total_sites if total_sites > 0 else 0
    
    macro_a_only = filtered_df[filtered_df[coverage_id_col] == 'A'] if coverage_id_col in filtered_df.columns else filtered_df
    macro_a_sites = macro_a_only['SITE_COUNT'].sum() if 'SITE_COUNT' in macro_a_only.columns else 0
    
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
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🔤 Coverage ID Analysis",
        "🗺️ Regional View",
        "📊 Market Analysis",
        "🎯 Ring Description",
        "📋 Data Table"
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
        st.markdown('<div class="section-title">Detailed Data</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        st.markdown(f"**Showing {len(filtered_df):,} rows** | Total Sites: {total_sites:,} | Total Sectors: {total_sectors:,}")
        
        display_df = filtered_df.copy()
        if 'SITE_COUNT' in display_df.columns:
            display_df = display_df.sort_values('SITE_COUNT', ascending=False)
        
        st.dataframe(display_df, use_container_width=True, hide_index=True, height=450)
        
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Data (CSV)",
            data=csv,
            file_name=f"macro_sites_coverage_a_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
        st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    st.markdown(f"""
    <div style='text-align:center; color:#aaa; font-size:11px;'>
    Macro Sites Dashboard | Coverage ID 'A' = Macro | Sites: {total_sites:,} | Sectors: {total_sectors:,} | 
    Markets: {total_markets} | Regions: {total_regions} | 
    Data as of: {datetime.now().strftime('%Y-%m-%d %H:%M')}
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
