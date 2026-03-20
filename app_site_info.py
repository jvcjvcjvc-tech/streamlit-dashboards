"""
Site Information Dashboard
Comprehensive site details with FOPS, Power, Access information
Comprehensive site details with FOPS, Power, Access information
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from glob import glob
import os
from datetime import datetime, timedelta

st.set_page_config(
    page_title="Site Information Dashboard",
    page_icon="📍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    .stApp {
        background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 50%, #16213e 100%);
        font-family: 'Inter', sans-serif;
    }
    
    .main-header {
        background: linear-gradient(90deg, #e20074, #ff6b9d);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2.5rem;
        font-weight: 700;
        text-align: center;
        margin-bottom: 0.5rem;
    }
    
    .sub-header {
        color: #888;
        text-align: center;
        font-size: 1rem;
        margin-bottom: 2rem;
    }
    
    .metric-card {
        background: linear-gradient(145deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02));
        border: 1px solid rgba(226, 0, 116, 0.3);
        border-radius: 16px;
        padding: 1.5rem;
        text-align: center;
        backdrop-filter: blur(10px);
        transition: all 0.3s ease;
    }
    
    .metric-card:hover {
        border-color: rgba(226, 0, 116, 0.6);
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(226, 0, 116, 0.2);
    }
    
    .metric-value {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #e20074, #ff6b9d);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    .metric-label {
        color: #aaa;
        font-size: 0.9rem;
        margin-top: 0.5rem;
    }
    
    .section-header {
        color: #e20074;
        font-size: 1.3rem;
        font-weight: 600;
        margin: 2rem 0 1rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid rgba(226, 0, 116, 0.3);
    }
    
    .stDataFrame {
        background: rgba(255,255,255,0.02);
        border-radius: 12px;
    }
    
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: rgba(255,255,255,0.02);
        padding: 0.5rem;
        border-radius: 12px;
    }
    
    .stTabs [data-baseweb="tab"] {
        background: transparent;
        border-radius: 8px;
        color: #888;
        padding: 0.75rem 1.5rem;
    }
    
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #e20074, #ff6b9d);
        color: white !important;
    }
    
    div[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0d0d0d 0%, #1a1a2e 100%);
        border-right: 1px solid rgba(226, 0, 116, 0.2);
    }
    
    .access-hours-table {
        font-size: 0.85rem;
    }
    
    .highlight-yes {
        color: #00ff88;
        font-weight: 600;
    }
    
    .highlight-no {
        color: #ff6b6b;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def load_site_data():
    """Load site info data from bundled CSV, local files, or generate sample"""
    
    # Try loading from bundled CSV (for cloud deployment)
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        bundled_csv = os.path.join(script_dir, "site_data.csv")
        if os.path.exists(bundled_csv):
            df = pd.read_csv(bundled_csv, low_memory=False)
            if 'SITEID' in df.columns and 'REGION' in df.columns:
                return df
    except Exception:
        pass
    
    # Try loading from local SSO path (for local development)
    try:
        sso_path = r"C:\Users\JChalap1\OneDrive - T-Mobile USA\Documents\AI_CURSOR\query_execution_agent_sso_auth 5\query_execution_agent_sso_auth"
        csv_files = glob(os.path.join(sso_path, "results_sso_*.csv"))
        
        for f in sorted(csv_files, key=os.path.getmtime, reverse=True):
            try:
                df = pd.read_csv(f, nrows=5, low_memory=False)
                if 'SITEID' in df.columns and 'REGION' in df.columns:
                    return pd.read_csv(f, low_memory=False)
            except Exception:
                continue
    except Exception:
        pass
    
    return None


def create_metric_card(value, label, icon=""):
    return f"""
    <div class="metric-card">
        <div class="metric-value">{icon} {value:,}</div>
        <div class="metric-label">{label}</div>
    </div>
    """


def main():
    st.markdown('<h1 class="main-header">📍 Site Information Dashboard</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Comprehensive Site Details with FOPS, Power, and Access Information</p>', unsafe_allow_html=True)
    
    df = load_site_data()
    
    if df is None:
        st.error("No site data found. Please run the site_info_dashboard.sql query first.")
        return
    
    # Convert date column
    if 'OA_DATE' in df.columns:
        df['OA_DATE'] = pd.to_datetime(df['OA_DATE'], errors='coerce')
    
    # Sidebar filters
    st.sidebar.markdown("### 🎛️ Filters")
    
    regions = ['All'] + sorted(df['REGION'].dropna().unique().tolist())
    selected_region = st.sidebar.selectbox("Region", regions)
    
    if selected_region != 'All':
        filtered_df = df[df['REGION'] == selected_region]
    else:
        filtered_df = df.copy()
    
    markets = ['All'] + sorted(filtered_df['MARKET'].dropna().unique().tolist())
    selected_market = st.sidebar.selectbox("Market", markets)
    
    if selected_market != 'All':
        filtered_df = filtered_df[filtered_df['MARKET'] == selected_market]
    
    site_classes = ['All'] + sorted(filtered_df['SITE_CLASS'].dropna().unique().tolist())
    selected_class = st.sidebar.selectbox("Site Class", site_classes)
    
    if selected_class != 'All':
        filtered_df = filtered_df[filtered_df['SITE_CLASS'] == selected_class]
    
    # Date range filter
    if 'OA_DATE' in filtered_df.columns:
        st.sidebar.markdown("### 📅 On-Air Date Range")
        min_date = filtered_df['OA_DATE'].min()
        max_date = filtered_df['OA_DATE'].max()
        if pd.notna(min_date) and pd.notna(max_date):
            date_range = st.sidebar.date_input(
                "Select Date Range",
                value=(min_date.date(), max_date.date()),
                min_value=min_date.date(),
                max_value=max_date.date()
            )
            if len(date_range) == 2:
                filtered_df = filtered_df[
                    (filtered_df['OA_DATE'] >= pd.Timestamp(date_range[0])) &
                    (filtered_df['OA_DATE'] <= pd.Timestamp(date_range[1]))
                ]
    
    # Search
    st.sidebar.markdown("### 🔍 Search")
    search_term = st.sidebar.text_input("Search Site ID or Name")
    if search_term:
        filtered_df = filtered_df[
            filtered_df['SITEID'].astype(str).str.contains(search_term, case=False, na=False) |
            filtered_df['SITE_NAME'].astype(str).str.contains(search_term, case=False, na=False)
        ]
    
    # KPI Cards
    total_sites = len(filtered_df)
    regions_count = filtered_df['REGION'].nunique()
    markets_count = filtered_df['MARKET'].nunique()
    
    # 24x7 access metrics
    site_24x7 = filtered_df['SITE_24X7'].fillna('').str.upper().str.contains('YES|TRUE|Y', regex=True).sum()
    power_24x7 = filtered_df['POWER_24X7'].fillna('').str.upper().str.contains('YES|TRUE|Y', regex=True).sum()
    
    # Portable generator capable
    portable_gen = filtered_df['PORTABLE_GENERATOR_CAPABLE'].fillna('').str.upper().str.contains('YES|TRUE|Y', regex=True).sum()
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        st.markdown(create_metric_card(total_sites, "Total Sites", "📍"), unsafe_allow_html=True)
    with col2:
        st.markdown(create_metric_card(regions_count, "Regions", "🌐"), unsafe_allow_html=True)
    with col3:
        st.markdown(create_metric_card(markets_count, "Markets", "🏙️"), unsafe_allow_html=True)
    with col4:
        st.markdown(create_metric_card(site_24x7, "24/7 Site Access", "🔓"), unsafe_allow_html=True)
    with col5:
        st.markdown(create_metric_card(power_24x7, "24/7 Power Access", "⚡"), unsafe_allow_html=True)
    with col6:
        st.markdown(create_metric_card(portable_gen, "Portable Gen Capable", "🔌"), unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Main tabs
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Overview", "⚡ Power Info", "🔐 Access Details", 
        "📅 Access Hours", "📞 Telco Info", "📋 Full Data"
    ])
    
    with tab1:
        st.markdown('<div class="section-header">Regional Distribution</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            region_counts = filtered_df.groupby('REGION').size().reset_index(name='Count')
            fig_region = px.pie(
                region_counts, 
                values='Count', 
                names='REGION',
                title='Sites by Region',
                color_discrete_sequence=px.colors.sequential.Magenta
            )
            fig_region.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#888'
            )
            st.plotly_chart(fig_region, use_container_width=True)
        
        with col2:
            class_counts = filtered_df.groupby('SITE_CLASS').size().reset_index(name='Count')
            fig_class = px.bar(
                class_counts.sort_values('Count', ascending=True),
                x='Count',
                y='SITE_CLASS',
                orientation='h',
                title='Sites by Class',
                color='Count',
                color_continuous_scale='Magenta'
            )
            fig_class.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#888',
                showlegend=False
            )
            st.plotly_chart(fig_class, use_container_width=True)
        
        # On-Air Timeline
        st.markdown('<div class="section-header">On-Air Timeline</div>', unsafe_allow_html=True)
        
        if 'OA_DATE' in filtered_df.columns:
            timeline_df = filtered_df.dropna(subset=['OA_DATE']).copy()
            timeline_df['Month'] = timeline_df['OA_DATE'].dt.to_period('M').astype(str)
            monthly_counts = timeline_df.groupby('Month').size().reset_index(name='Sites')
            
            fig_timeline = px.area(
                monthly_counts.tail(24),
                x='Month',
                y='Sites',
                title='Sites On-Air by Month (Last 24 Months)',
                color_discrete_sequence=['#e20074']
            )
            fig_timeline.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#888',
                xaxis_tickangle=-45
            )
            st.plotly_chart(fig_timeline, use_container_width=True)
        
        # Top Markets
        st.markdown('<div class="section-header">Top 15 Markets by Site Count</div>', unsafe_allow_html=True)
        
        market_counts = filtered_df.groupby(['REGION', 'MARKET']).size().reset_index(name='Sites')
        top_markets = market_counts.nlargest(15, 'Sites')
        
        fig_markets = px.bar(
            top_markets,
            x='MARKET',
            y='Sites',
            color='REGION',
            title='',
            color_discrete_sequence=px.colors.qualitative.Set2
        )
        fig_markets.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font_color='#888',
            xaxis_tickangle=-45
        )
        st.plotly_chart(fig_markets, use_container_width=True)
    
    with tab2:
        st.markdown('<div class="section-header">Power Information</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Breaker Size Distribution
            if 'BREAKER_SIZE' in filtered_df.columns:
                breaker_counts = filtered_df['BREAKER_SIZE'].value_counts().head(10).reset_index()
                breaker_counts.columns = ['Breaker Size', 'Count']
                
                fig_breaker = px.bar(
                    breaker_counts,
                    x='Breaker Size',
                    y='Count',
                    title='Breaker Size Distribution',
                    color='Count',
                    color_continuous_scale='Magenta'
                )
                fig_breaker.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#888'
                )
                st.plotly_chart(fig_breaker, use_container_width=True)
        
        with col2:
            # Generator Plug Types
            if 'GEN_PLUG' in filtered_df.columns:
                gen_plug_counts = filtered_df['GEN_PLUG'].value_counts().head(10).reset_index()
                gen_plug_counts.columns = ['Generator Plug', 'Count']
                
                fig_gen = px.pie(
                    gen_plug_counts,
                    values='Count',
                    names='Generator Plug',
                    title='Generator Plug Types',
                    color_discrete_sequence=px.colors.sequential.Magenta
                )
                fig_gen.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#888'
                )
                st.plotly_chart(fig_gen, use_container_width=True)
        
        # Power Details Table
        st.markdown('<div class="section-header">Power Details</div>', unsafe_allow_html=True)
        
        power_cols = ['SITEID', 'SITE_NAME', 'REGION', 'MARKET', 'POWER_METER', 'BREAKER_SIZE', 
                      'GEN_PLUG', 'PORTABLE_GENERATOR_CAPABLE', 'PORTABLE_GEN_PLUG', 
                      'PORTABLE_GEN_CORD_LENGTH', 'POWER_24X7', 'POWER_ACCESS_NOTES']
        available_power_cols = [c for c in power_cols if c in filtered_df.columns]
        
        st.dataframe(
            filtered_df[available_power_cols].head(100),
            use_container_width=True,
            hide_index=True
        )
    
    with tab3:
        st.markdown('<div class="section-header">Access Combos & Security</div>', unsafe_allow_html=True)
        
        col1, col2, col3, col4 = st.columns(4)
        
        # 24/7 Access Summary
        with col1:
            site_24x7_pct = (site_24x7 / total_sites * 100) if total_sites > 0 else 0
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=site_24x7_pct,
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': "Site 24/7 Access %"},
                gauge={
                    'axis': {'range': [0, 100]},
                    'bar': {'color': "#e20074"},
                    'bgcolor': "rgba(255,255,255,0.1)",
                    'steps': [
                        {'range': [0, 50], 'color': 'rgba(255,107,107,0.3)'},
                        {'range': [50, 75], 'color': 'rgba(255,193,7,0.3)'},
                        {'range': [75, 100], 'color': 'rgba(0,255,136,0.3)'}
                    ]
                }
            ))
            fig_gauge.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                font_color='#888',
                height=250
            )
            st.plotly_chart(fig_gauge, use_container_width=True)
        
        with col2:
            power_24x7_pct = (power_24x7 / total_sites * 100) if total_sites > 0 else 0
            fig_gauge2 = go.Figure(go.Indicator(
                mode="gauge+number",
                value=power_24x7_pct,
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': "Power 24/7 Access %"},
                gauge={
                    'axis': {'range': [0, 100]},
                    'bar': {'color': "#ff6b9d"},
                    'bgcolor': "rgba(255,255,255,0.1)"
                }
            ))
            fig_gauge2.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                font_color='#888',
                height=250
            )
            st.plotly_chart(fig_gauge2, use_container_width=True)
        
        with col3:
            telco_24x7 = filtered_df['TELCO_24X7'].fillna('').str.upper().str.contains('YES|TRUE|Y', regex=True).sum()
            telco_24x7_pct = (telco_24x7 / total_sites * 100) if total_sites > 0 else 0
            fig_gauge3 = go.Figure(go.Indicator(
                mode="gauge+number",
                value=telco_24x7_pct,
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': "Telco 24/7 Access %"},
                gauge={
                    'axis': {'range': [0, 100]},
                    'bar': {'color': "#00ff88"},
                    'bgcolor': "rgba(255,255,255,0.1)"
                }
            ))
            fig_gauge3.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                font_color='#888',
                height=250
            )
            st.plotly_chart(fig_gauge3, use_container_width=True)
        
        with col4:
            other_24x7 = filtered_df['OTHER_24X7'].fillna('').str.upper().str.contains('YES|TRUE|Y', regex=True).sum()
            other_24x7_pct = (other_24x7 / total_sites * 100) if total_sites > 0 else 0
            fig_gauge4 = go.Figure(go.Indicator(
                mode="gauge+number",
                value=other_24x7_pct,
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': "Other 24/7 Access %"},
                gauge={
                    'axis': {'range': [0, 100]},
                    'bar': {'color': "#ffc107"},
                    'bgcolor': "rgba(255,255,255,0.1)"
                }
            ))
            fig_gauge4.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                font_color='#888',
                height=250
            )
            st.plotly_chart(fig_gauge4, use_container_width=True)
        
        # Access Details Table
        st.markdown('<div class="section-header">Access Combo Details</div>', unsafe_allow_html=True)
        
        access_cols = ['SITEID', 'SITE_NAME', 'REGION', 'MARKET', 'FACILITY_COMBO', 
                       'POWER_COMBO', 'TELCO_GATE_COMBO', 'TELCO_AAV_COMBO', 'OTHER_COMBO',
                       'SITE_24X7', 'ACCESS_DETAILS', 'SITE_SECURITY_ISSUES']
        available_access_cols = [c for c in access_cols if c in filtered_df.columns]
        
        st.dataframe(
            filtered_df[available_access_cols].head(100),
            use_container_width=True,
            hide_index=True
        )
    
    with tab4:
        st.markdown('<div class="section-header">Facility Access Hours by Day</div>', unsafe_allow_html=True)
        
        hours_cols = ['SITEID', 'SITE_NAME', 'REGION', 'MARKET', 
                      'MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 
                      'FRIDAY', 'SATURDAY', 'SUNDAY']
        available_hours_cols = [c for c in hours_cols if c in filtered_df.columns]
        
        if len(available_hours_cols) > 4:
            st.dataframe(
                filtered_df[available_hours_cols].head(100),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Access hours columns not available in the data.")
        
        # Notification Requirements
        st.markdown('<div class="section-header">Notification Requirements</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            if 'FACILITY_NOTIFICATION_REQUIRED' in filtered_df.columns:
                notif_counts = filtered_df['FACILITY_NOTIFICATION_REQUIRED'].value_counts().reset_index()
                notif_counts.columns = ['Required', 'Count']
                
                fig_notif = px.pie(
                    notif_counts,
                    values='Count',
                    names='Required',
                    title='Facility Notification Required',
                    color_discrete_sequence=['#00ff88', '#ff6b6b', '#ffc107']
                )
                fig_notif.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#888'
                )
                st.plotly_chart(fig_notif, use_container_width=True)
        
        with col2:
            notif_detail_cols = ['SITEID', 'SITE_NAME', 'FACILITY_NOTIFICATION_REQUIRED', 
                                 'FACILITY_NOTIFICATION_PERIOD', 'FACILITY_ACCESS_NOTES']
            available_notif_cols = [c for c in notif_detail_cols if c in filtered_df.columns]
            
            if available_notif_cols:
                st.dataframe(
                    filtered_df[available_notif_cols].head(50),
                    use_container_width=True,
                    hide_index=True
                )
    
    with tab5:
        st.markdown('<div class="section-header">Telco Information</div>', unsafe_allow_html=True)
        
        telco_cols = ['SITEID', 'SITE_NAME', 'REGION', 'MARKET',
                      'TELCO_DEMARC_LOCATION', 'TELCO_AAV_NID_LOCATION', 'TMO_NID_LOCATION',
                      'TELCO_ACCESS_NOTES', 'TELCO_NOTIFICATION_REQUIRED', 'TELCO_NOTIFICATION_PERIOD',
                      'TELCO_24X7', 'TELCO_GATE_COMBO', 'TELCO_AAV_COMBO']
        available_telco_cols = [c for c in telco_cols if c in filtered_df.columns]
        
        st.dataframe(
            filtered_df[available_telco_cols].head(100),
            use_container_width=True,
            hide_index=True
        )
        
        # EME Information
        st.markdown('<div class="section-header">EME Signage & Audit</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            if 'EME_SIGNAGE_VISIT_REQUIRED' in filtered_df.columns:
                eme_counts = filtered_df['EME_SIGNAGE_VISIT_REQUIRED'].value_counts().reset_index()
                eme_counts.columns = ['Required', 'Count']
                
                fig_eme = px.pie(
                    eme_counts,
                    values='Count',
                    names='Required',
                    title='EME Signage Visit Required',
                    color_discrete_sequence=px.colors.sequential.Magenta
                )
                fig_eme.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#888'
                )
                st.plotly_chart(fig_eme, use_container_width=True)
        
        with col2:
            eme_cols = ['SITEID', 'SITE_NAME', 'EME_SIGNAGE_VISIT_REQUIRED', 'EME_AUDIT_LAST_PERFORMED']
            available_eme_cols = [c for c in eme_cols if c in filtered_df.columns]
            
            if available_eme_cols:
                st.dataframe(
                    filtered_df[available_eme_cols].head(50),
                    use_container_width=True,
                    hide_index=True
                )
    
    with tab6:
        st.markdown('<div class="section-header">Full Site Data</div>', unsafe_allow_html=True)
        
        # Column selector
        all_columns = filtered_df.columns.tolist()
        default_cols = ['SITEID', 'SITE_NAME', 'REGION', 'MARKET', 'SITE_CLASS', 
                        'MAGENTABUILT_STATUS', 'OA_DATE', 'FOPS_ASSIGNEE', 'DEV_MANAGER']
        default_cols = [c for c in default_cols if c in all_columns]
        
        selected_columns = st.multiselect(
            "Select columns to display",
            options=all_columns,
            default=default_cols
        )
        
        if selected_columns:
            st.dataframe(
                filtered_df[selected_columns],
                use_container_width=True,
                hide_index=True
            )
        
        # Download button
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Filtered Data as CSV",
            data=csv,
            file_name=f"site_info_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime='text/csv'
        )
    
    # Footer
    st.markdown("---")
    st.markdown(
        f"""<div style="text-align: center; color: #666; font-size: 0.8rem;">
        Site Information Dashboard | Data refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 
        Total Records: {len(filtered_df):,}
        </div>""",
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()
