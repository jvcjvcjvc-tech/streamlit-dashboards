"""
Site Hourly Combo Availability Dashboard
Visualizes site availability metrics over time
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os

st.set_page_config(
    page_title="Site Availability Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #0f0f23 0%, #1a1a3e 50%, #0d1b2a 100%);
    }
    .main-header {
        background: linear-gradient(90deg, #00b4d8, #0077b6);
        color: white;
        padding: 25px 30px;
        font-size: 28px;
        font-weight: bold;
        margin: -1rem -1rem 1.5rem -1rem;
        text-align: center;
        border-radius: 0 0 15px 15px;
        box-shadow: 0 4px 20px rgba(0,180,216,0.3);
    }
    .sub-header {
        color: #00b4d8;
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
        font-size: 36px;
        font-weight: bold;
        color: #00b4d8;
    }
    .metric-value-green {
        font-size: 36px;
        font-weight: bold;
        color: #00d9a5;
    }
    .metric-value-red {
        font-size: 36px;
        font-weight: bold;
        color: #ff6b6b;
    }
    .metric-value-orange {
        font-size: 36px;
        font-weight: bold;
        color: #f77f00;
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
        border-left: 4px solid #00b4d8;
    }
    .glass-card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 15px;
        margin-bottom: 15px;
    }
    div[data-testid="stSidebar"] {
        background: rgba(13,27,42,0.95);
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
        background: linear-gradient(90deg, #00b4d8, #0077b6) !important;
    }
    .availability-high {
        color: #00d9a5;
        font-weight: bold;
    }
    .availability-medium {
        color: #f77f00;
        font-weight: bold;
    }
    .availability-low {
        color: #ff6b6b;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def load_availability_data():
    """Load site availability data from CSV or generate sample"""
    
    # Try loading from CSV
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        csv_file = os.path.join(script_dir, "site_availability.csv")
        if os.path.exists(csv_file):
            df = pd.read_csv(csv_file, low_memory=False)
            return df, False
    except Exception:
        pass
    
    # Generate sample data for demo
    np.random.seed(42)
    
    site_id = 'NO0157RA'
    start_date = datetime(2026, 3, 1)
    hours_data = []
    
    for day in range(20):  # 20 days of data
        current_date = start_date + timedelta(days=day)
        for hour in range(24):
            # Simulate availability with some variation
            base_avail = 99.5 if hour not in [2, 3, 4] else 98.0  # Lower at night maintenance
            combo_avail = base_avail + np.random.uniform(-2, 0.5)
            combo_avail = min(100, max(90, combo_avail))
            
            lte_avail = base_avail + np.random.uniform(-1, 0.5)
            lte_avail = min(100, max(92, lte_avail))
            
            nr_avail = base_avail + np.random.uniform(-1.5, 0.3)
            nr_avail = min(100, max(91, nr_avail))
            
            hours_data.append({
                'SITE_ID': site_id,
                'DATE': current_date.strftime('%Y-%m-%d'),
                'HOUR': hour,
                'COMBO_AVAIL': round(combo_avail, 2),
                'LTE_AVAIL': round(lte_avail, 2),
                'NR_AVAIL': round(nr_avail, 2),
                'REGION': 'NORTHEAST',
                'MARKET': 'NEW ORLEANS LA',
                'SITE_NAME': 'Sample Tower Site'
            })
    
    return pd.DataFrame(hours_data), True


def get_availability_color(value):
    if value >= 99:
        return "availability-high"
    elif value >= 95:
        return "availability-medium"
    else:
        return "availability-low"


def main():
    st.markdown('<div class="main-header">📊 Site Availability Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Hourly Combo Availability Analysis</div>', unsafe_allow_html=True)
    
    df, is_sample = load_availability_data()
    
    if df is None or df.empty:
        st.error("No availability data found. Please add site_availability.csv to the project folder.")
        return
    
    if is_sample:
        st.info("📊 **Demo Mode:** Displaying sample data. Upload site_availability.csv for real data.")
    
    # Parse date if needed
    if 'DATE' in df.columns:
        df['DATE'] = pd.to_datetime(df['DATE'])
    
    # Sidebar
    with st.sidebar:
        st.markdown("### 🎯 Filters")
        
        if 'SITE_ID' in df.columns:
            sites = df['SITE_ID'].unique().tolist()
            selected_site = st.selectbox("Site ID", sites)
            df = df[df['SITE_ID'] == selected_site]
        
        if 'DATE' in df.columns:
            min_date = df['DATE'].min().date()
            max_date = df['DATE'].max().date()
            date_range = st.date_input(
                "Date Range",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date
            )
            if len(date_range) == 2:
                df = df[(df['DATE'].dt.date >= date_range[0]) & (df['DATE'].dt.date <= date_range[1])]
        
        st.markdown("---")
        st.markdown(f"**Records:** {len(df):,}")
        st.markdown(f"**Last Updated:** {datetime.now().strftime('%H:%M')}")
        
        if st.button("🔄 Refresh"):
            st.cache_data.clear()
            st.rerun()
    
    # Calculate metrics
    combo_col = 'COMBO_AVAIL' if 'COMBO_AVAIL' in df.columns else None
    lte_col = 'LTE_AVAIL' if 'LTE_AVAIL' in df.columns else None
    nr_col = 'NR_AVAIL' if 'NR_AVAIL' in df.columns else None
    
    avg_combo = df[combo_col].mean() if combo_col else 0
    avg_lte = df[lte_col].mean() if lte_col else 0
    avg_nr = df[nr_col].mean() if nr_col else 0
    min_combo = df[combo_col].min() if combo_col else 0
    max_combo = df[combo_col].max() if combo_col else 0
    
    # Hours below threshold
    threshold = 99.0
    hours_below = len(df[df[combo_col] < threshold]) if combo_col else 0
    
    # KPI Cards
    st.markdown('<div class="section-title">📈 Key Metrics</div>', unsafe_allow_html=True)
    
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    
    with c1:
        color_class = "metric-value-green" if avg_combo >= 99 else "metric-value-orange" if avg_combo >= 95 else "metric-value-red"
        st.markdown(f"""
        <div class="metric-card">
            <div class="{color_class}">{avg_combo:.2f}%</div>
            <div class="metric-label">Avg Combo Avail</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value-green">{avg_lte:.2f}%</div>
            <div class="metric-label">Avg LTE Avail</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{avg_nr:.2f}%</div>
            <div class="metric-label">Avg NR Avail</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value-green">{max_combo:.2f}%</div>
            <div class="metric-label">Max Combo</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c5:
        color_class = "metric-value-red" if min_combo < 95 else "metric-value-orange"
        st.markdown(f"""
        <div class="metric-card">
            <div class="{color_class}">{min_combo:.2f}%</div>
            <div class="metric-label">Min Combo</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c6:
        color_class = "metric-value-red" if hours_below > 10 else "metric-value-orange" if hours_below > 0 else "metric-value-green"
        st.markdown(f"""
        <div class="metric-card">
            <div class="{color_class}">{hours_below}</div>
            <div class="metric-label">Hours Below 99%</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "📈 Trend Analysis",
        "🕐 Hourly Patterns",
        "📊 Distribution",
        "📋 Data Table"
    ])
    
    with tab1:
        st.markdown('<div class="section-title">Availability Over Time</div>', unsafe_allow_html=True)
        
        # Daily average trend
        if 'DATE' in df.columns and combo_col:
            daily_avg = df.groupby('DATE').agg({
                combo_col: 'mean',
                lte_col: 'mean' if lte_col else combo_col,
                nr_col: 'mean' if nr_col else combo_col
            }).reset_index()
            
            fig = go.Figure()
            
            fig.add_trace(go.Scatter(
                x=daily_avg['DATE'],
                y=daily_avg[combo_col],
                mode='lines+markers',
                name='Combo Availability',
                line=dict(color='#00b4d8', width=3),
                marker=dict(size=8)
            ))
            
            if lte_col:
                fig.add_trace(go.Scatter(
                    x=daily_avg['DATE'],
                    y=daily_avg[lte_col],
                    mode='lines+markers',
                    name='LTE Availability',
                    line=dict(color='#00d9a5', width=2),
                    marker=dict(size=6)
                ))
            
            if nr_col:
                fig.add_trace(go.Scatter(
                    x=daily_avg['DATE'],
                    y=daily_avg[nr_col],
                    mode='lines+markers',
                    name='NR Availability',
                    line=dict(color='#f77f00', width=2),
                    marker=dict(size=6)
                ))
            
            # Add threshold line
            fig.add_hline(y=99, line_dash="dash", line_color="red", 
                         annotation_text="99% Threshold")
            
            fig.update_layout(
                title="Daily Average Availability Trend",
                height=400,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#fff'),
                xaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Date'),
                yaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Availability %', range=[94, 100.5]),
                legend=dict(orientation='h', y=1.1),
                hovermode='x unified'
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        st.markdown('<div class="section-title">Hourly Availability Patterns</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            if 'HOUR' in df.columns and combo_col:
                hourly_avg = df.groupby('HOUR')[combo_col].mean().reset_index()
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=hourly_avg['HOUR'],
                    y=hourly_avg[combo_col],
                    marker_color=['#00d9a5' if v >= 99 else '#f77f00' if v >= 95 else '#ff6b6b' 
                                  for v in hourly_avg[combo_col]],
                    text=[f"{v:.1f}%" for v in hourly_avg[combo_col]],
                    textposition='outside'
                ))
                
                fig.add_hline(y=99, line_dash="dash", line_color="red")
                
                fig.update_layout(
                    title="Average Availability by Hour",
                    height=400,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    xaxis=dict(gridcolor='rgba(255,255,255,0.05)', title='Hour of Day', 
                              tickmode='linear', dtick=2),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Availability %', 
                              range=[94, 100.5])
                )
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Heatmap by date and hour
            if 'DATE' in df.columns and 'HOUR' in df.columns and combo_col:
                pivot_df = df.pivot_table(
                    index=df['DATE'].dt.strftime('%m-%d'),
                    columns='HOUR',
                    values=combo_col,
                    aggfunc='mean'
                ).fillna(0)
                
                fig = go.Figure(data=go.Heatmap(
                    z=pivot_df.values,
                    x=pivot_df.columns,
                    y=pivot_df.index,
                    colorscale=[[0, '#ff6b6b'], [0.5, '#f77f00'], [0.95, '#00d9a5'], [1, '#00b4d8']],
                    zmin=94,
                    zmax=100,
                    hovertemplate='Date: %{y}<br>Hour: %{x}<br>Availability: %{z:.2f}%<extra></extra>'
                ))
                
                fig.update_layout(
                    title="Availability Heatmap (Date × Hour)",
                    height=400,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    xaxis=dict(title='Hour of Day'),
                    yaxis=dict(title='Date')
                )
                st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        st.markdown('<div class="section-title">Availability Distribution</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            if combo_col:
                fig = px.histogram(
                    df,
                    x=combo_col,
                    nbins=50,
                    title='Combo Availability Distribution',
                    color_discrete_sequence=['#00b4d8']
                )
                fig.add_vline(x=99, line_dash="dash", line_color="red", 
                             annotation_text="99% Threshold")
                fig.update_layout(
                    height=350,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    xaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Availability %'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Count')
                )
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Box plot comparison
            if combo_col and lte_col and nr_col:
                box_data = pd.melt(df[[combo_col, lte_col, nr_col]], 
                                   var_name='Metric', value_name='Availability')
                
                fig = px.box(
                    box_data,
                    x='Metric',
                    y='Availability',
                    color='Metric',
                    title='Availability Comparison',
                    color_discrete_map={
                        combo_col: '#00b4d8',
                        lte_col: '#00d9a5',
                        nr_col: '#f77f00'
                    }
                )
                fig.update_layout(
                    height=350,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    showlegend=False,
                    xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.1)', title='Availability %')
                )
                st.plotly_chart(fig, use_container_width=True)
        
        # Statistics summary
        st.markdown('<div class="section-title">Statistical Summary</div>', unsafe_allow_html=True)
        
        if combo_col:
            stats_df = df[[combo_col, lte_col, nr_col]].describe() if lte_col and nr_col else df[[combo_col]].describe()
            stats_df = stats_df.round(2)
            st.dataframe(stats_df, use_container_width=True)
    
    with tab4:
        st.markdown('<div class="section-title">Raw Data</div>', unsafe_allow_html=True)
        
        # Sort options
        col1, col2 = st.columns([2, 1])
        with col1:
            sort_col = st.selectbox("Sort by", df.columns.tolist(), 
                                    index=df.columns.tolist().index('DATE') if 'DATE' in df.columns else 0)
        with col2:
            sort_order = st.radio("Order", ['Descending', 'Ascending'], horizontal=True)
        
        display_df = df.sort_values(sort_col, ascending=(sort_order == 'Ascending'))
        
        st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)
        
        # Download
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name=f"site_availability_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    
    # Footer
    st.markdown("---")
    site_id = df['SITE_ID'].iloc[0] if 'SITE_ID' in df.columns else 'Unknown'
    st.markdown(f"""
    <div style='text-align:center; color:#aaa; font-size:11px;'>
    Site Availability Dashboard | Site: {site_id} | Records: {len(df):,} | 
    Avg Combo: {avg_combo:.2f}% | {datetime.now().strftime('%Y-%m-%d %H:%M')}
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
