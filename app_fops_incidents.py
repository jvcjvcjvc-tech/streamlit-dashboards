import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from glob import glob
import os
from datetime import datetime, timedelta

st.set_page_config(
    page_title="FOPS Incident Dashboard",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #0d1b2a 0%, #1b263b 50%, #415a77 100%);
    }
    .main-header {
        background: linear-gradient(90deg, #e63946, #f77f00);
        color: white;
        padding: 20px 30px;
        font-size: 28px;
        font-weight: bold;
        margin: -1rem -1rem 1.5rem -1rem;
        text-align: center;
        border-radius: 0 0 12px 12px;
        box-shadow: 0 4px 15px rgba(230,57,70,0.3);
    }
    .region-header {
        background: linear-gradient(90deg, #1d3557, #457b9d);
        color: white;
        padding: 12px 20px;
        font-size: 18px;
        font-weight: 600;
        border-radius: 8px;
        margin-bottom: 15px;
        text-align: center;
    }
    .kpi-card {
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.15);
        border-radius: 12px;
        padding: 18px;
        text-align: center;
        backdrop-filter: blur(10px);
        transition: transform 0.2s ease;
    }
    .kpi-card:hover {
        transform: translateY(-2px);
    }
    .kpi-value {
        font-size: 32px;
        font-weight: bold;
        color: #fff;
    }
    .kpi-value-red { font-size: 32px; font-weight: bold; color: #e63946; }
    .kpi-value-orange { font-size: 32px; font-weight: bold; color: #f77f00; }
    .kpi-value-green { font-size: 32px; font-weight: bold; color: #2a9d8f; }
    .kpi-value-blue { font-size: 32px; font-weight: bold; color: #4cc9f0; }
    .kpi-value-purple { font-size: 32px; font-weight: bold; color: #9d4edd; }
    .kpi-label {
        font-size: 10px;
        color: #a8dadc;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 6px;
    }
    .section-title {
        color: #fff;
        font-size: 16px;
        font-weight: 600;
        margin: 15px 0 12px 0;
        padding-left: 12px;
        border-left: 4px solid #e63946;
    }
    .glass-card {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 10px;
    }
    .table-title {
        color: #f1faee;
        font-size: 14px;
        font-weight: 600;
        margin-bottom: 10px;
        padding: 8px 12px;
        background: rgba(230,57,70,0.2);
        border-radius: 6px;
        border-left: 3px solid #e63946;
    }
    div[data-testid="stSidebar"] {
        background: rgba(13,27,42,0.95);
    }
    div[data-testid="stSidebar"] * {
        color: #fff !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
        background: rgba(255,255,255,0.05);
        padding: 8px;
        border-radius: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: rgba(255,255,255,0.08);
        border-radius: 8px;
        color: white;
        padding: 10px 16px;
        font-weight: 500;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(90deg, #e63946, #f77f00) !important;
    }
    .dataframe {
        font-size: 12px !important;
    }
    .summary-stat {
        display: inline-block;
        background: rgba(255,255,255,0.1);
        padding: 4px 10px;
        border-radius: 15px;
        margin-right: 8px;
        font-size: 11px;
        color: #a8dadc;
    }
</style>
""", unsafe_allow_html=True)

REGIONS = ['All Regions', 'West', 'Central', 'South', 'Northeast', 'Southeast', 'Northwest', 'Southwest']

@st.cache_data(ttl=300)
def load_fops_incident_data():
    sso_path = r"C:\Users\JChalap1\OneDrive - T-Mobile USA\Documents\AI_CURSOR\query_execution_agent_sso_auth 5\query_execution_agent_sso_auth"
    csv_files = glob(os.path.join(sso_path, "results_sso_*.csv"))
    
    for f in sorted(csv_files, key=os.path.getmtime, reverse=True):
        try:
            df = pd.read_csv(f, nrows=5, low_memory=False)
            if 'INCIDENT_NUMBER' in df.columns:
                full_df = pd.read_csv(f, low_memory=False)
                if 'ASSIGNMENT_GROUP' in full_df.columns:
                    fops_df = full_df[full_df['ASSIGNMENT_GROUP'].str.contains('FOPS|Field Operations|Field Ops', case=False, na=False)]
                    if len(fops_df) > 0:
                        return fops_df
                    return full_df
                return full_df
        except Exception:
            continue
    return None


def calculate_metrics(df):
    """Calculate key incident metrics"""
    if df is None or df.empty:
        return {}
    
    today = datetime.now()
    
    total = len(df)
    aged_30 = len(df[df['AGE_DAYS'] > 30]) if 'AGE_DAYS' in df.columns else 0
    aged_60 = len(df[df['AGE_DAYS'] > 60]) if 'AGE_DAYS' in df.columns else 0
    aged_90 = len(df[df['AGE_DAYS'] > 90]) if 'AGE_DAYS' in df.columns else 0
    
    aging_week = len(df[(df['AGE_DAYS'] >= 23) & (df['AGE_DAYS'] <= 30)]) if 'AGE_DAYS' in df.columns else 0
    no_worklog = len(df[df['DAYS_SINCE_UPDATE'] > 30]) if 'DAYS_SINCE_UPDATE' in df.columns else 0
    
    return {
        'total': total,
        'aged_30': aged_30,
        'aged_60': aged_60,
        'aged_90': aged_90,
        'aging_week': aging_week,
        'no_worklog': no_worklog
    }


def display_kpi_row(metrics):
    """Display KPI cards in a row"""
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    
    kpis = [
        (c1, metrics.get('total', 0), "Total INC", "kpi-value-blue"),
        (c2, metrics.get('aged_30', 0), "Aged > 30 Days", "kpi-value-red"),
        (c3, metrics.get('aged_60', 0), "Aged > 60 Days", "kpi-value-orange"),
        (c4, metrics.get('aged_90', 0), "Aged > 90 Days", "kpi-value-red"),
        (c5, metrics.get('aging_week', 0), "Aging This Week", "kpi-value-orange"),
        (c6, metrics.get('no_worklog', 0), "No Update 30d", "kpi-value-purple"),
    ]
    
    for col, value, label, css_class in kpis:
        with col:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="{css_class}">{value:,}</div>
                <div class="kpi-label">{label}</div>
            </div>
            """, unsafe_allow_html=True)


def display_incident_table(df, title, display_cols, sort_col='AGE_DAYS', height=350):
    """Display an incident table with title"""
    st.markdown(f'<div class="table-title">{title} ({len(df):,} incidents)</div>', unsafe_allow_html=True)
    
    if df.empty:
        st.info("No incidents found matching the criteria.")
        return
    
    available_cols = [c for c in display_cols if c in df.columns]
    
    if sort_col in df.columns:
        display_df = df[available_cols].sort_values(sort_col, ascending=False)
    else:
        display_df = df[available_cols]
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        height=height
    )


def create_category_chart(df):
    """Create category distribution chart"""
    if 'CATEGORY' not in df.columns or df.empty:
        return None
    
    cat_dist = df['CATEGORY'].value_counts().head(12).reset_index()
    cat_dist.columns = ['Category', 'Count']
    
    fig = px.bar(
        cat_dist, 
        y='Category', 
        x='Count', 
        orientation='h',
        color='Count',
        color_continuous_scale=['#457b9d', '#1d3557', '#e63946'],
        text='Count'
    )
    
    fig.update_layout(
        height=350,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#fff', size=10),
        xaxis=dict(gridcolor='rgba(255,255,255,0.1)', title=''),
        yaxis=dict(gridcolor='rgba(255,255,255,0.05)', title='', autorange='reversed'),
        coloraxis_showscale=False,
        margin=dict(l=10, r=10, t=10, b=10)
    )
    fig.update_traces(textposition='outside', textfont_size=10)
    
    return fig


def render_region_content(df, region_name):
    """Render content for a specific region tab"""
    
    display_cols = [
        'INCIDENT_NUMBER', 'SHORT_DESCRIPTION', 'STATE', 'PRIORITY', 
        'CATEGORY', 'ASSIGNMENT_GROUP', 'ASSIGNED_TO', 'AGE_DAYS', 
        'DAYS_SINCE_UPDATE', 'OPENED_DATE'
    ]
    
    metrics = calculate_metrics(df)
    display_kpi_row(metrics)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    tab_aged, tab_all, tab_aging, tab_nowork, tab_category = st.tabs([
        "🔴 Aged > 30 Days",
        "📋 All Incidents",
        "⚠️ Moving to >30d",
        "📵 No Work Log 30d",
        "📊 By Category"
    ])
    
    with tab_aged:
        st.markdown('<div class="section-title">Incidents Aged More Than 30 Days</div>', unsafe_allow_html=True)
        
        if 'AGE_DAYS' in df.columns:
            aged_df = df[df['AGE_DAYS'] > 30].copy()
            
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                if not aged_df.empty:
                    age_bins = [30, 45, 60, 90, 120, 180, 365, 9999]
                    age_labels = ['30-45d', '45-60d', '60-90d', '90-120d', '120-180d', '180-365d', '365d+']
                    aged_df['Age_Bucket'] = pd.cut(aged_df['AGE_DAYS'], bins=age_bins, labels=age_labels)
                    age_dist = aged_df['Age_Bucket'].value_counts().sort_index().reset_index()
                    age_dist.columns = ['Age Bucket', 'Count']
                    
                    fig = px.bar(age_dist, x='Age Bucket', y='Count', 
                                color='Count', color_continuous_scale='Reds',
                                text='Count')
                    fig.update_layout(
                        title="Age Distribution",
                        height=250,
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)',
                        font=dict(color='#fff', size=10),
                        xaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
                        yaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
                        coloraxis_showscale=False,
                        margin=dict(t=40, b=20)
                    )
                    st.plotly_chart(fig, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col2:
                st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                if not aged_df.empty and 'PRIORITY' in aged_df.columns:
                    priority_dist = aged_df['PRIORITY'].value_counts().reset_index()
                    priority_dist.columns = ['Priority', 'Count']
                    
                    fig = px.pie(priority_dist, values='Count', names='Priority',
                                color_discrete_sequence=['#e63946', '#f77f00', '#2a9d8f', '#4cc9f0'])
                    fig.update_layout(
                        title="By Priority",
                        height=250,
                        paper_bgcolor='rgba(0,0,0,0)',
                        font=dict(color='#fff', size=10),
                        margin=dict(t=40, b=20)
                    )
                    st.plotly_chart(fig, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            display_incident_table(aged_df, "Aged Incidents (>30 Days)", display_cols, 'AGE_DAYS', 350)
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.warning("AGE_DAYS column not found in data.")
    
    with tab_all:
        st.markdown('<div class="section-title">All FOPS Incidents</div>', unsafe_allow_html=True)
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f'<span class="summary-stat">Total: {len(df):,}</span>', unsafe_allow_html=True)
        with col2:
            if 'PRIORITY' in df.columns:
                p1_count = len(df[df['PRIORITY'].str.contains('1|Critical', case=False, na=False)])
                st.markdown(f'<span class="summary-stat">P1/Critical: {p1_count:,}</span>', unsafe_allow_html=True)
        with col3:
            if 'STATE' in df.columns:
                active = len(df[~df['STATE'].str.contains('Closed|Resolved|Cancelled', case=False, na=False)])
                st.markdown(f'<span class="summary-stat">Active: {active:,}</span>', unsafe_allow_html=True)
        with col4:
            if 'AGE_DAYS' in df.columns:
                avg_age = df['AGE_DAYS'].mean()
                st.markdown(f'<span class="summary-stat">Avg Age: {avg_age:.1f}d</span>', unsafe_allow_html=True)
        
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        display_incident_table(df, "All Incidents", display_cols, 'AGE_DAYS', 450)
        st.markdown('</div>', unsafe_allow_html=True)
    
    with tab_aging:
        st.markdown('<div class="section-title">Incidents Moving to 30+ Days This Week (23-30 Days Old)</div>', unsafe_allow_html=True)
        
        if 'AGE_DAYS' in df.columns:
            aging_df = df[(df['AGE_DAYS'] >= 23) & (df['AGE_DAYS'] <= 30)].copy()
            
            if not aging_df.empty:
                col1, col2 = st.columns([1, 1])
                
                with col1:
                    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                    if 'ASSIGNMENT_GROUP' in aging_df.columns:
                        group_dist = aging_df['ASSIGNMENT_GROUP'].value_counts().head(8).reset_index()
                        group_dist.columns = ['Assignment Group', 'Count']
                        
                        fig = px.bar(group_dist, y='Assignment Group', x='Count', orientation='h',
                                    color='Count', color_continuous_scale='YlOrRd',
                                    text='Count')
                        fig.update_layout(
                            title="At-Risk Groups",
                            height=250,
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            font=dict(color='#fff', size=10),
                            yaxis=dict(autorange='reversed'),
                            coloraxis_showscale=False,
                            margin=dict(t=40, b=20)
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
                
                with col2:
                    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                    aging_df['Days_Until_30'] = 30 - aging_df['AGE_DAYS']
                    days_dist = aging_df['Days_Until_30'].value_counts().sort_index().reset_index()
                    days_dist.columns = ['Days Until 30', 'Count']
                    
                    fig = px.bar(days_dist, x='Days Until 30', y='Count',
                                color='Count', color_continuous_scale='YlOrRd', text='Count')
                    fig.update_layout(
                        title="Days Until Aging",
                        height=250,
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)',
                        font=dict(color='#fff', size=10),
                        coloraxis_showscale=False,
                        margin=dict(t=40, b=20)
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
                
                st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                display_incident_table(aging_df, "Incidents Aging This Week", display_cols, 'AGE_DAYS', 350)
                st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.success("No incidents are moving into the 30+ day aging window this week!")
        else:
            st.warning("AGE_DAYS column not found in data.")
    
    with tab_nowork:
        st.markdown('<div class="section-title">No Work Log Entries in 30+ Days</div>', unsafe_allow_html=True)
        
        if 'DAYS_SINCE_UPDATE' in df.columns:
            nowork_df = df[df['DAYS_SINCE_UPDATE'] > 30].copy()
            
            if not nowork_df.empty:
                col1, col2 = st.columns([1, 1])
                
                with col1:
                    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                    if 'ASSIGNMENT_GROUP' in nowork_df.columns:
                        group_dist = nowork_df['ASSIGNMENT_GROUP'].value_counts().head(8).reset_index()
                        group_dist.columns = ['Assignment Group', 'Count']
                        
                        fig = px.bar(group_dist, y='Assignment Group', x='Count', orientation='h',
                                    color='Count', color_continuous_scale='Purples',
                                    text='Count')
                        fig.update_layout(
                            title="Groups with Stale Incidents",
                            height=250,
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            font=dict(color='#fff', size=10),
                            yaxis=dict(autorange='reversed'),
                            coloraxis_showscale=False,
                            margin=dict(t=40, b=20)
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
                
                with col2:
                    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                    update_bins = [30, 45, 60, 90, 120, 9999]
                    update_labels = ['30-45d', '45-60d', '60-90d', '90-120d', '120d+']
                    nowork_df['Update_Bucket'] = pd.cut(nowork_df['DAYS_SINCE_UPDATE'], 
                                                        bins=update_bins, labels=update_labels)
                    update_dist = nowork_df['Update_Bucket'].value_counts().sort_index().reset_index()
                    update_dist.columns = ['Days Since Update', 'Count']
                    
                    fig = px.pie(update_dist, values='Count', names='Days Since Update',
                                color_discrete_sequence=['#f77f00', '#e63946', '#9d4edd', '#7b2cbf', '#5a189a'])
                    fig.update_layout(
                        title="Update Gap Distribution",
                        height=250,
                        paper_bgcolor='rgba(0,0,0,0)',
                        font=dict(color='#fff', size=10),
                        margin=dict(t=40, b=20)
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
                
                st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                display_incident_table(nowork_df, "Incidents with No Activity", display_cols, 'DAYS_SINCE_UPDATE', 350)
                st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.success("All incidents have recent work log entries!")
        else:
            st.warning("DAYS_SINCE_UPDATE column not found in data.")
    
    with tab_category:
        st.markdown('<div class="section-title">All Incidents by Category</div>', unsafe_allow_html=True)
        
        if 'CATEGORY' in df.columns:
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                fig = create_category_chart(df)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col2:
                st.markdown('<div class="glass-card">', unsafe_allow_html=True)
                if 'AGE_DAYS' in df.columns:
                    cat_age = df.groupby('CATEGORY').agg({
                        'INCIDENT_NUMBER': 'count',
                        'AGE_DAYS': 'mean'
                    }).reset_index()
                    cat_age.columns = ['Category', 'Count', 'Avg Age']
                    cat_age = cat_age.nlargest(12, 'Count')
                    
                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        y=cat_age['Category'],
                        x=cat_age['Count'],
                        name='Count',
                        orientation='h',
                        marker_color='#4cc9f0'
                    ))
                    fig.add_trace(go.Scatter(
                        y=cat_age['Category'],
                        x=cat_age['Avg Age'],
                        name='Avg Age (days)',
                        mode='markers',
                        marker=dict(size=10, color='#e63946')
                    ))
                    fig.update_layout(
                        title="Count vs Avg Age by Category",
                        height=350,
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)',
                        font=dict(color='#fff', size=10),
                        yaxis=dict(autorange='reversed'),
                        legend=dict(orientation='h', y=1.15, x=0.5, xanchor='center'),
                        margin=dict(t=60, b=20)
                    )
                    st.plotly_chart(fig, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            cat_summary = df.groupby('CATEGORY').agg({
                'INCIDENT_NUMBER': 'count',
                'AGE_DAYS': ['mean', 'max'] if 'AGE_DAYS' in df.columns else ['count'],
                'DAYS_SINCE_UPDATE': 'mean' if 'DAYS_SINCE_UPDATE' in df.columns else 'count'
            }).reset_index()
            
            if 'AGE_DAYS' in df.columns and 'DAYS_SINCE_UPDATE' in df.columns:
                cat_summary.columns = ['Category', 'Count', 'Avg Age', 'Max Age', 'Avg Days Since Update']
                cat_summary['Avg Age'] = cat_summary['Avg Age'].round(1)
                cat_summary['Avg Days Since Update'] = cat_summary['Avg Days Since Update'].round(1)
            else:
                cat_summary.columns = ['Category', 'Count', 'Other1', 'Other2']
            
            cat_summary = cat_summary.sort_values('Count', ascending=False)
            
            st.markdown('<div class="table-title">Category Summary</div>', unsafe_allow_html=True)
            st.dataframe(cat_summary, use_container_width=True, hide_index=True, height=300)
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.warning("CATEGORY column not found in data.")


def main():
    st.markdown('<div class="main-header">🔧 FOPS Incident Dashboard</div>', unsafe_allow_html=True)
    
    df = load_fops_incident_data()
    
    if df is None or df.empty:
        st.error("No FOPS incident data available. Please ensure incident data with FOPS assignment groups is loaded.")
        st.info("Expected columns: INCIDENT_NUMBER, AGE_DAYS, DAYS_SINCE_UPDATE, ASSIGNMENT_GROUP, CATEGORY, etc.")
        return
    
    if 'OPENED_DATE' in df.columns:
        df['OPENED_DATE'] = pd.to_datetime(df['OPENED_DATE'], format='ISO8601', errors='coerce')
    if 'SYS_UPDATED_DATE' in df.columns:
        df['SYS_UPDATED_DATE'] = pd.to_datetime(df['SYS_UPDATED_DATE'], format='ISO8601', errors='coerce')
    
    with st.sidebar:
        st.markdown("### 🎯 Filters")
        
        if 'PRIORITY' in df.columns:
            priorities = ['All'] + sorted(df['PRIORITY'].dropna().unique().tolist())
            selected_priority = st.selectbox("Priority", priorities)
        else:
            selected_priority = 'All'
        
        if 'STATE' in df.columns:
            states = ['All'] + sorted(df['STATE'].dropna().unique().tolist())
            selected_state = st.selectbox("State", states)
        else:
            selected_state = 'All'
        
        if 'ASSIGNMENT_GROUP' in df.columns:
            groups = ['All'] + sorted(df['ASSIGNMENT_GROUP'].dropna().unique().tolist())
            selected_group = st.selectbox("Assignment Group", groups)
        else:
            selected_group = 'All'
        
        if 'CATEGORY' in df.columns:
            categories = ['All'] + sorted(df['CATEGORY'].dropna().unique().tolist())
            selected_category = st.selectbox("Category", categories)
        else:
            selected_category = 'All'
        
        st.markdown("---")
        st.markdown("### 📊 Data Info")
        st.markdown(f"**Total Records:** {len(df):,}")
        st.markdown(f"**Last Refresh:** {datetime.now().strftime('%H:%M')}")
    
    filtered_df = df.copy()
    if selected_priority != 'All' and 'PRIORITY' in df.columns:
        filtered_df = filtered_df[filtered_df['PRIORITY'] == selected_priority]
    if selected_state != 'All' and 'STATE' in df.columns:
        filtered_df = filtered_df[filtered_df['STATE'] == selected_state]
    if selected_group != 'All' and 'ASSIGNMENT_GROUP' in df.columns:
        filtered_df = filtered_df[filtered_df['ASSIGNMENT_GROUP'] == selected_group]
    if selected_category != 'All' and 'CATEGORY' in df.columns:
        filtered_df = filtered_df[filtered_df['CATEGORY'] == selected_category]
    
    if 'REGION' in filtered_df.columns:
        available_regions = ['All Regions'] + sorted(filtered_df['REGION'].dropna().unique().tolist())
    else:
        available_regions = REGIONS
    
    region_tabs = st.tabs(available_regions)
    
    for idx, region in enumerate(available_regions):
        with region_tabs[idx]:
            if region == 'All Regions':
                region_df = filtered_df
                st.markdown(f'<div class="region-header">📍 All Regions - {len(region_df):,} Incidents</div>', unsafe_allow_html=True)
            else:
                if 'REGION' in filtered_df.columns:
                    region_df = filtered_df[filtered_df['REGION'] == region]
                elif 'ASSIGNMENT_GROUP' in filtered_df.columns:
                    region_df = filtered_df[filtered_df['ASSIGNMENT_GROUP'].str.contains(region, case=False, na=False)]
                else:
                    region_df = filtered_df
                
                st.markdown(f'<div class="region-header">📍 {region} Region - {len(region_df):,} Incidents</div>', unsafe_allow_html=True)
            
            if region_df.empty:
                st.info(f"No incidents found for {region}.")
            else:
                render_region_content(region_df, region)
    
    st.markdown("---")
    st.markdown(f"""
    <div style='text-align:center; color:#a8dadc; font-size:11px;'>
    FOPS Incident Dashboard | Total: {len(filtered_df):,} | 
    Aged 30+: {len(filtered_df[filtered_df['AGE_DAYS'] > 30]) if 'AGE_DAYS' in filtered_df.columns else 'N/A'} | 
    Data as of: {datetime.now().strftime('%Y-%m-%d %H:%M')}
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
