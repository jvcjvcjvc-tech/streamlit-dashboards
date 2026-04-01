import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from glob import glob
import os

st.set_page_config(
    page_title="Strategic Availability Report",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS - Light theme with magenta accents
st.markdown("""
<style>
    .stApp {
        background-color: #ffffff;
    }
    .main-header {
        background: linear-gradient(90deg, #e20074, #ff4d94);
        color: white;
        padding: 15px 25px;
        font-size: 22px;
        font-weight: bold;
        margin: -1rem -1rem 1rem -1rem;
        text-align: center;
    }
    .section-header {
        background: #e20074;
        color: white;
        padding: 8px 15px;
        font-size: 13px;
        font-weight: bold;
        margin-bottom: 5px;
        border-radius: 3px;
    }
    .metric-card {
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 8px;
        padding: 20px;
        text-align: center;
        margin-bottom: 10px;
    }
    .metric-value {
        font-size: 32px;
        font-weight: bold;
        color: #e20074;
    }
    .metric-label {
        font-size: 12px;
        color: #6c757d;
        text-transform: uppercase;
        margin-top: 5px;
    }
    div[data-testid="stSidebar"] {
        background-color: #f8f9fa;
    }
    .dataframe {
        font-size: 11px !important;
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

def main():
    st.markdown('<div class="main-header">SINGLE OPERATING MODEL: STRATEGIC - AVAILABILITY Report</div>', unsafe_allow_html=True)
    
    df = load_data()
    
    if df is None or df.empty:
        st.error("No data available")
        return
    
    # Parse dates
    if 'LOCAL_START_TIMESTAMP' in df.columns:
        df['DATE'] = pd.to_datetime(df['LOCAL_START_TIMESTAMP'], format='ISO8601').dt.date
        df['MONTH'] = pd.to_datetime(df['LOCAL_START_TIMESTAMP'], format='ISO8601').dt.strftime('%Y-%m')
    
    # Derive region from market code
    if 'MKT_NAME' in df.columns:
        def get_region(mkt):
            mkt_str = str(mkt).upper()
            south = ['MEMPHIS', 'BIRMINGHAM', 'MOBILE', 'AUSTIN', 'HOUSTON', 'DALLAS', 'PUERTO', 'JACKSONVILLE', 'ATLANTA', 'ORLANDO', 'TAMPA', 'SOUTH']
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
        
        df['REGION'] = df['MKT_NAME'].apply(get_region)
    
    # Sidebar filters
    with st.sidebar:
        st.markdown("### 📊 Filters")
        
        regions = ['All'] + sorted(df['REGION'].dropna().unique().tolist()) if 'REGION' in df.columns else ['All']
        selected_region = st.selectbox("Region", regions)
        
        markets = ['All'] + sorted(df['MKT_NAME'].dropna().unique().tolist()) if 'MKT_NAME' in df.columns else ['All']
        selected_market = st.selectbox("Market", markets)
        
        if 'DATE' in df.columns:
            min_date = df['DATE'].min()
            max_date = df['DATE'].max()
            date_range = st.date_input("Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
        else:
            date_range = None
        
        st.markdown("---")
        st.markdown("### 📈 Target")
        target = st.slider("Availability Target %", 95.0, 100.0, 99.9, 0.01)
    
    # Apply filters
    filtered_df = df.copy()
    if selected_region != 'All' and 'REGION' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['REGION'] == selected_region]
    if selected_market != 'All' and 'MKT_NAME' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['MKT_NAME'] == selected_market]
    if date_range and 'DATE' in filtered_df.columns and len(date_range) == 2:
        filtered_df = filtered_df[(filtered_df['DATE'] >= date_range[0]) & (filtered_df['DATE'] <= date_range[1])]
    
    # Calculate availability per market (using outage duration)
    # Availability = 100 - (total_outage_mins / (total_sites * total_days * 1440)) * 100
    def calc_market_availability(group):
        total_outage = group['SERVICE_OUTAGE_DURATION'].sum() if 'SERVICE_OUTAGE_DURATION' in group.columns else 0
        n_sites = group['SITE_CD'].nunique() if 'SITE_CD' in group.columns else 1
        n_days = group['DATE'].nunique() if 'DATE' in group.columns else 1
        total_possible = n_sites * n_days * 1440  # minutes per day
        if total_possible > 0:
            avail = 100 - (total_outage / total_possible) * 100
            return max(0, min(100, avail))
        return 99.99
    
    def calc_site_availability(group):
        total_outage = group['SERVICE_OUTAGE_DURATION'].sum() if 'SERVICE_OUTAGE_DURATION' in group.columns else 0
        n_days = group['DATE'].nunique() if 'DATE' in group.columns else 1
        total_possible = n_days * 1440
        if total_possible > 0:
            avail = 100 - (total_outage / total_possible) * 100
            return max(0, min(100, avail))
        return 99.99
    
    # Layout - 3 columns
    col1, col2, col3 = st.columns([1.2, 1.5, 1.3])
    
    with col1:
        st.markdown('<div class="section-header">Markets by Availability</div>', unsafe_allow_html=True)
        
        if 'MKT_NAME' in filtered_df.columns:
            market_avail = filtered_df.groupby(['REGION', 'MKT_NAME']).apply(calc_market_availability).reset_index()
            market_avail.columns = ['Region', 'Market', 'Availability']
            market_avail = market_avail.sort_values('Availability')
            market_avail['Selected Period'] = 'Multiple/All'
            market_avail['Status'] = market_avail['Availability'].apply(lambda x: '🔴' if x < target else '🟢')
            
            display_df = market_avail[['Status', 'Region', 'Market', 'Availability']].copy()
            display_df['Availability'] = display_df['Availability'].apply(lambda x: f"{x:.2f}%")
            
            st.dataframe(display_df.head(30), use_container_width=True, hide_index=True, height=500)
    
    with col2:
        # Total Availability by Region
        st.markdown('<div class="section-header">Total Availability by Region</div>', unsafe_allow_html=True)
        
        if 'REGION' in filtered_df.columns:
            region_avail = filtered_df.groupby('REGION').apply(calc_market_availability).reset_index()
            region_avail.columns = ['Region', 'Availability']
            region_avail = region_avail.sort_values('Availability', ascending=True)
            
            colors = ['#e20074' if a < target else '#28a745' for a in region_avail['Availability']]
            
            fig = go.Figure(go.Bar(
                y=region_avail['Region'],
                x=region_avail['Availability'],
                orientation='h',
                marker_color=colors,
                text=region_avail['Availability'].apply(lambda x: f"{x:.2f}%"),
                textposition='inside',
                textfont=dict(color='white', size=12)
            ))
            fig.update_layout(
                height=180,
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis=dict(range=[99, 100], title='', showgrid=True, gridcolor='#eee'),
                yaxis=dict(title=''),
                paper_bgcolor='white',
                plot_bgcolor='white',
                font=dict(size=11)
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Top Sites - Lowest Availability
        st.markdown('<div class="section-header">Top Sites - Lowest Availability</div>', unsafe_allow_html=True)
        
        if 'SITE_CD' in filtered_df.columns:
            site_avail = filtered_df.groupby(['SITE_CD', 'REGION']).apply(calc_site_availability).reset_index()
            site_avail.columns = ['Site', 'Region', 'Availability']
            site_avail = site_avail.nsmallest(12, 'Availability')
            
            if not site_avail.empty:
                region_colors = {'CENTRAL': '#2196F3', 'NORTHEAST': '#4CAF50', 'SOUTH': '#FF9800', 'WEST': '#9C27B0', 'OTHER': '#607D8B'}
                colors = [region_colors.get(r, '#607D8B') for r in site_avail['Region']]
                
                min_val = site_avail['Availability'].min()
                y_min = max(0, min_val - 5)
                
                fig = go.Figure(go.Bar(
                    x=site_avail['Site'],
                    y=site_avail['Availability'],
                    marker_color=colors,
                    text=site_avail['Availability'].apply(lambda x: f"{x:.1f}%"),
                    textposition='outside',
                    textfont=dict(size=9)
                ))
                fig.update_layout(
                    height=220,
                    margin=dict(l=10, r=10, t=10, b=40),
                    yaxis=dict(range=[y_min, 105], title='Availability %', showgrid=True, gridcolor='#eee'),
                    xaxis=dict(title='', tickangle=45, tickfont=dict(size=8)),
                    paper_bgcolor='white',
                    plot_bgcolor='white',
                    showlegend=False
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # Legend
                legend_html = " ".join([f'<span style="color:{c}">●</span> {r}' for r, c in region_colors.items() if r in site_avail['Region'].values])
                st.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
    
    with col3:
        # Top Markets - Lowest Availability
        st.markdown('<div class="section-header">Top Markets - Lowest Availability</div>', unsafe_allow_html=True)
        
        if 'MKT_NAME' in filtered_df.columns:
            mkt_chart = filtered_df.groupby('MKT_NAME').apply(calc_market_availability).reset_index()
            mkt_chart.columns = ['Market', 'Availability']
            mkt_chart = mkt_chart.nsmallest(10, 'Availability')
            
            if not mkt_chart.empty:
                min_val = mkt_chart['Availability'].min()
                y_min = max(98, min_val - 1)
                
                # Color based on target
                colors = ['#e20074' if a < target else '#28a745' for a in mkt_chart['Availability']]
                
                fig = go.Figure(go.Bar(
                    x=mkt_chart['Market'],
                    y=mkt_chart['Availability'],
                    marker_color=colors,
                    text=mkt_chart['Availability'].apply(lambda x: f"{x:.2f}%"),
                    textposition='outside',
                    textfont=dict(size=9)
                ))
                fig.update_layout(
                    height=200,
                    margin=dict(l=10, r=10, t=10, b=50),
                    yaxis=dict(range=[y_min, 100.5], title='', showgrid=True, gridcolor='#eee'),
                    xaxis=dict(title='', tickangle=45, tickfont=dict(size=8)),
                    paper_bgcolor='white',
                    plot_bgcolor='white'
                )
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("<small>🔴 Below target | 🟢 Meets target</small>", unsafe_allow_html=True)
    
    # Bottom row - Tables
    st.markdown("---")
    t1, t2, t3 = st.columns(3)
    
    with t1:
        st.markdown('<div class="section-header">Top 10 - Lowest Availability Markets</div>', unsafe_allow_html=True)
        if 'MKT_NAME' in filtered_df.columns:
            mkt_table = filtered_df.groupby('MKT_NAME').apply(calc_market_availability).reset_index()
            mkt_table.columns = ['MARKET_ID', 'Availability']
            mkt_table = mkt_table.nsmallest(10, 'Availability')
            mkt_table['Selected Period'] = 'Multiple/All'
            mkt_table['Status'] = mkt_table['Availability'].apply(lambda x: '🔴' if x < target else '🟢')
            mkt_table['Availability'] = mkt_table['Availability'].apply(lambda x: f"{x:.2f}%")
            st.dataframe(mkt_table[['Status', 'MARKET_ID', 'Selected Period', 'Availability']], use_container_width=True, hide_index=True)
    
    with t2:
        st.markdown('<div class="section-header">Top 10 - Lowest Availability Sites</div>', unsafe_allow_html=True)
        if 'SITE_CD' in filtered_df.columns:
            site_table = filtered_df.groupby(['SITE_CD']).agg({
                'SERVICE_OUTAGE_DURATION': 'sum',
                'DATE': ['min', 'nunique']
            }).reset_index()
            site_table.columns = ['Site', 'TotalOutage', 'FirstDate', 'NumDays']
            site_table['Availability'] = site_table.apply(
                lambda x: max(0, 100 - (x['TotalOutage'] / (x['NumDays'] * 1440)) * 100), axis=1
            )
            site_table = site_table.nsmallest(10, 'Availability')
            site_table['Selected Period'] = site_table['FirstDate'].astype(str).str[:7]
            site_table['Status'] = site_table['Availability'].apply(lambda x: '🔴' if x < target else '🟢')
            site_table['Availability'] = site_table['Availability'].apply(lambda x: f"{x:.2f}%")
            st.dataframe(site_table[['Status', 'Site', 'Selected Period', 'Availability']], use_container_width=True, hide_index=True)
    
    with t3:
        st.markdown('<div class="section-header">All Site List Below Target</div>', unsafe_allow_html=True)
        search = st.text_input("🔍 Search for Site", "", key="site_search")
        
        if 'SITE_CD' in filtered_df.columns:
            all_sites = filtered_df.groupby(['REGION', 'MKT_NAME', 'SITE_CD', 'DATE']).agg({
                'SERVICE_OUTAGE_DURATION': 'sum'
            }).reset_index()
            all_sites['Availability'] = all_sites['SERVICE_OUTAGE_DURATION'].apply(
                lambda x: max(0, 100 - (x / 1440) * 100)
            )
            all_sites = all_sites[all_sites['Availability'] < target]
            all_sites = all_sites[['REGION', 'MKT_NAME', 'SITE_CD', 'DATE', 'Availability']]
            all_sites.columns = ['Region', 'Market', 'Site', 'Date', 'Availability']
            
            if search:
                all_sites = all_sites[all_sites['Site'].str.contains(search, case=False, na=False)]
            
            all_sites['Availability'] = all_sites['Availability'].apply(lambda x: f"{x:.2f}%")
            st.dataframe(all_sites.sort_values('Date', ascending=False).head(100), use_container_width=True, hide_index=True, height=200)
    
    # Footer
    st.markdown("---")
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        st.markdown(f"**Data Range:** {filtered_df['DATE'].min()} to {filtered_df['DATE'].max()}")
    with col_f2:
        st.markdown(f"**Total Records:** {len(filtered_df):,}")
    with col_f3:
        st.markdown(f"**Target:** {target}%")

if __name__ == "__main__":
    main()
