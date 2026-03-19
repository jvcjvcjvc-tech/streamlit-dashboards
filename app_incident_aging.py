import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from glob import glob
import os
from datetime import datetime, timedelta

st.set_page_config(
    page_title="Incident Aging Report",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
    }
    .main-header {
        background: linear-gradient(90deg, #ff416c, #ff4b2b);
        color: white;
        padding: 20px 30px;
        font-size: 26px;
        font-weight: bold;
        margin: -1rem -1rem 1.5rem -1rem;
        text-align: center;
        border-radius: 0 0 10px 10px;
    }
    .kpi-card {
        background: rgba(255,255,255,0.1);
        border: 1px solid rgba(255,255,255,0.2);
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        backdrop-filter: blur(10px);
    }
    .kpi-value {
        font-size: 36px;
        font-weight: bold;
        color: #fff;
    }
    .kpi-value-red { font-size: 36px; font-weight: bold; color: #ff6b6b; }
    .kpi-value-orange { font-size: 36px; font-weight: bold; color: #ffc107; }
    .kpi-value-green { font-size: 36px; font-weight: bold; color: #00d9a5; }
    .kpi-value-blue { font-size: 36px; font-weight: bold; color: #4cc9f0; }
    .kpi-label {
        font-size: 11px;
        color: #ccc;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 8px;
    }
    .section-title {
        color: #fff;
        font-size: 18px;
        font-weight: 600;
        margin: 20px 0 15px 0;
        padding-left: 12px;
        border-left: 4px solid #ff416c;
    }
    .glass-card {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 10px;
        padding: 15px;
    }
    div[data-testid="stSidebar"] {
        background: rgba(30,60,114,0.95);
    }
    div[data-testid="stSidebar"] * {
        color: #fff !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: rgba(255,255,255,0.1);
        border-radius: 8px;
        color: white;
        padding: 10px 20px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #ff416c !important;
    }
</style>
""", unsafe_allow_html=True)

@st.cache_data
def load_incident_data():
    sso_path = r"C:\Users\JChalap1\OneDrive - T-Mobile USA\Documents\AI_CURSOR\query_execution_agent_sso_auth 5\query_execution_agent_sso_auth"
    csv_files = glob(os.path.join(sso_path, "results_sso_*.csv"))
    
    # Find the incident aging file (most recent one with incident data)
    for f in sorted(csv_files, key=os.path.getmtime, reverse=True):
        df = pd.read_csv(f, nrows=5, low_memory=False)
        if 'INCIDENT_NUMBER' in df.columns and 'AGE_DAYS' in df.columns:
            return pd.read_csv(f, low_memory=False)
    return None

def main():
    st.markdown('<div class="main-header">📋 Incident Aging Report</div>', unsafe_allow_html=True)
    
    df = load_incident_data()
    
    if df is None or df.empty:
        st.error("No incident data available. Please run the incident_aging.sql query first.")
        return
    
    # Parse dates
    if 'OPENED_DATE' in df.columns:
        df['OPENED_DATE'] = pd.to_datetime(df['OPENED_DATE'], format='ISO8601')
    if 'SYS_UPDATED_DATE' in df.columns:
        df['SYS_UPDATED_DATE'] = pd.to_datetime(df['SYS_UPDATED_DATE'], format='ISO8601')
    
    # Sidebar filters
    with st.sidebar:
        st.markdown("### 📊 Filters")
        
        priorities = ['All'] + sorted(df['PRIORITY'].dropna().unique().tolist())
        selected_priority = st.selectbox("Priority", priorities)
        
        states = ['All'] + sorted(df['STATE'].dropna().unique().tolist())
        selected_state = st.selectbox("State", states)
        
        groups = ['All'] + sorted(df['ASSIGNMENT_GROUP'].dropna().unique().tolist())
        selected_group = st.selectbox("Assignment Group", groups)
        
        categories = ['All'] + sorted(df['CATEGORY'].dropna().unique().tolist())
        selected_category = st.selectbox("Category", categories)
    
    # Apply filters
    filtered_df = df.copy()
    if selected_priority != 'All':
        filtered_df = filtered_df[filtered_df['PRIORITY'] == selected_priority]
    if selected_state != 'All':
        filtered_df = filtered_df[filtered_df['STATE'] == selected_state]
    if selected_group != 'All':
        filtered_df = filtered_df[filtered_df['ASSIGNMENT_GROUP'] == selected_group]
    if selected_category != 'All':
        filtered_df = filtered_df[filtered_df['CATEGORY'] == selected_category]
    
    # Calculate key segments
    aged_30 = filtered_df[filtered_df['AGE_DAYS'] > 30]
    aged_60 = filtered_df[filtered_df['AGE_DAYS'] > 60]
    aged_90 = filtered_df[filtered_df['AGE_DAYS'] > 90]
    
    # Incidents aging into 30+ this week (currently 23-30 days old)
    aging_this_week = filtered_df[(filtered_df['AGE_DAYS'] >= 23) & (filtered_df['AGE_DAYS'] <= 30)]
    
    # No work log in 30 days
    no_worklogs_30 = filtered_df[filtered_df['DAYS_SINCE_UPDATE'] > 30]
    
    # ==================== KPI CARDS ====================
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    
    with c1:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value-blue">{len(filtered_df):,}</div>
            <div class="kpi-label">Total Open INC</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c2:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value-red">{len(aged_30):,}</div>
            <div class="kpi-label">Aged > 30 Days</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c3:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value-orange">{len(aging_this_week):,}</div>
            <div class="kpi-label">Aging This Week</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c4:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value-red">{len(no_worklogs_30):,}</div>
            <div class="kpi-label">No Update 30d</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c5:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value-orange">{len(aged_60):,}</div>
            <div class="kpi-label">Aged > 60 Days</div>
        </div>
        """, unsafe_allow_html=True)
    
    with c6:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value-red">{len(aged_90):,}</div>
            <div class="kpi-label">Aged > 90 Days</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ==================== TABS ====================
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🔴 Aged > 30 Days",
        "⚠️ Aging This Week",
        "📵 No Work Log 30d",
        "📊 By Category",
        "📥 Export Data"
    ])
    
    # Display columns for tables
    display_cols = ['INCIDENT_NUMBER', 'SHORT_DESCRIPTION', 'STATE', 'PRIORITY', 
                   'CATEGORY', 'ASSIGNMENT_GROUP', 'ASSIGNED_TO', 'AGE_DAYS', 
                   'DAYS_SINCE_UPDATE', 'OPENED_DATE']
    display_cols = [c for c in display_cols if c in filtered_df.columns]
    
    # ==================== TAB 1: Aged > 30 Days ====================
    with tab1:
        st.markdown('<div class="section-title">Incidents Aged More Than 30 Days</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            # Age distribution
            age_bins = [30, 45, 60, 90, 120, 180, 365, 999]
            age_labels = ['30-45d', '45-60d', '60-90d', '90-120d', '120-180d', '180-365d', '365d+']
            aged_30['Age_Bucket'] = pd.cut(aged_30['AGE_DAYS'], bins=age_bins, labels=age_labels)
            age_dist = aged_30['Age_Bucket'].value_counts().sort_index().reset_index()
            age_dist.columns = ['Age Bucket', 'Count']
            
            fig = px.bar(age_dist, x='Age Bucket', y='Count', 
                        color='Count', color_continuous_scale='Reds',
                        text='Count')
            fig.update_layout(
                title="Age Distribution (>30 days)",
                height=300,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#fff'),
                xaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
                yaxis=dict(gridcolor='rgba(255,255,255,0.1)')
            )
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            # By Priority
            priority_dist = aged_30['PRIORITY'].value_counts().reset_index()
            priority_dist.columns = ['Priority', 'Count']
            
            fig = px.pie(priority_dist, values='Count', names='Priority',
                        color_discrete_sequence=['#ff6b6b', '#ffc107', '#4cc9f0', '#00d9a5'])
            fig.update_layout(
                title="By Priority",
                height=300,
                paper_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#fff')
            )
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Data table
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown(f"**{len(aged_30):,} Incidents** | Sorted by Age (Oldest First)")
        st.dataframe(
            aged_30[display_cols].sort_values('AGE_DAYS', ascending=False),
            use_container_width=True,
            hide_index=True,
            height=400
        )
        st.markdown('</div>', unsafe_allow_html=True)
    
    # ==================== TAB 2: Aging This Week ====================
    with tab2:
        st.markdown('<div class="section-title">Incidents Moving to 30+ Days This Week (23-30 Days Old)</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            # By Assignment Group
            if not aging_this_week.empty:
                group_dist = aging_this_week['ASSIGNMENT_GROUP'].value_counts().head(10).reset_index()
                group_dist.columns = ['Assignment Group', 'Count']
                
                fig = px.bar(group_dist, y='Assignment Group', x='Count', orientation='h',
                            color='Count', color_continuous_scale='YlOrRd',
                            text='Count')
                fig.update_layout(
                    title="Top 10 Assignment Groups at Risk",
                    height=300,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    yaxis=dict(autorange='reversed')
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No incidents aging into 30+ days this week")
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            # Days until 30
            if not aging_this_week.empty:
                aging_this_week['Days_Until_30'] = 30 - aging_this_week['AGE_DAYS']
                days_dist = aging_this_week['Days_Until_30'].value_counts().sort_index().reset_index()
                days_dist.columns = ['Days Until 30', 'Count']
                
                fig = px.bar(days_dist, x='Days Until 30', y='Count',
                            color='Count', color_continuous_scale='YlOrRd')
                fig.update_layout(
                    title="Days Until Aging to 30+",
                    height=300,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff')
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Data table
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown(f"**{len(aging_this_week):,} Incidents** | Action needed to prevent aging")
        if not aging_this_week.empty:
            st.dataframe(
                aging_this_week[display_cols].sort_values('AGE_DAYS', ascending=False),
                use_container_width=True,
                hide_index=True,
                height=400
            )
        st.markdown('</div>', unsafe_allow_html=True)
    
    # ==================== TAB 3: No Work Log 30 Days ====================
    with tab3:
        st.markdown('<div class="section-title">No Work Log Entries in 30+ Days</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            # By Assignment Group
            if not no_worklogs_30.empty:
                group_dist = no_worklogs_30['ASSIGNMENT_GROUP'].value_counts().head(10).reset_index()
                group_dist.columns = ['Assignment Group', 'Count']
                
                fig = px.bar(group_dist, y='Assignment Group', x='Count', orientation='h',
                            color='Count', color_continuous_scale='Reds',
                            text='Count')
                fig.update_layout(
                    title="Top 10 Groups - No Activity 30+ Days",
                    height=300,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff'),
                    yaxis=dict(autorange='reversed')
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.success("All incidents have recent work log entries!")
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            # Days since update distribution
            if not no_worklogs_30.empty:
                update_bins = [30, 45, 60, 90, 120, 999]
                update_labels = ['30-45d', '45-60d', '60-90d', '90-120d', '120d+']
                no_worklogs_30['Update_Bucket'] = pd.cut(no_worklogs_30['DAYS_SINCE_UPDATE'], 
                                                         bins=update_bins, labels=update_labels)
                update_dist = no_worklogs_30['Update_Bucket'].value_counts().sort_index().reset_index()
                update_dist.columns = ['Days Since Update', 'Count']
                
                fig = px.pie(update_dist, values='Count', names='Days Since Update',
                            color_discrete_sequence=['#ffc107', '#ff9800', '#ff6b6b', '#e94560', '#b71c1c'])
                fig.update_layout(
                    title="Update Gap Distribution",
                    height=300,
                    paper_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#fff')
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Data table
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown(f"**{len(no_worklogs_30):,} Incidents** | Sorted by Days Since Last Update")
        if not no_worklogs_30.empty:
            st.dataframe(
                no_worklogs_30[display_cols].sort_values('DAYS_SINCE_UPDATE', ascending=False),
                use_container_width=True,
                hide_index=True,
                height=400
            )
        st.markdown('</div>', unsafe_allow_html=True)
    
    # ==================== TAB 4: By Category ====================
    with tab4:
        st.markdown('<div class="section-title">All Incidents by Category</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            # By Category
            cat_dist = filtered_df['CATEGORY'].value_counts().head(15).reset_index()
            cat_dist.columns = ['Category', 'Count']
            
            fig = px.bar(cat_dist, y='Category', x='Count', orientation='h',
                        color='Count', color_continuous_scale='Blues',
                        text='Count')
            fig.update_layout(
                title="Top 15 Categories",
                height=400,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#fff'),
                yaxis=dict(autorange='reversed')
            )
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            # Category with Avg Age
            cat_age = filtered_df.groupby('CATEGORY').agg({
                'INCIDENT_NUMBER': 'count',
                'AGE_DAYS': 'mean'
            }).reset_index()
            cat_age.columns = ['Category', 'Count', 'Avg Age']
            cat_age = cat_age.nlargest(15, 'Count')
            
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
                marker=dict(size=12, color='#ff6b6b')
            ))
            fig.update_layout(
                title="Category Count vs Avg Age",
                height=400,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#fff'),
                yaxis=dict(autorange='reversed'),
                legend=dict(orientation='h', y=1.1)
            )
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Category summary table
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        cat_summary = filtered_df.groupby('CATEGORY').agg({
            'INCIDENT_NUMBER': 'count',
            'AGE_DAYS': ['mean', 'max'],
            'DAYS_SINCE_UPDATE': 'mean'
        }).reset_index()
        cat_summary.columns = ['Category', 'Count', 'Avg Age', 'Max Age', 'Avg Days Since Update']
        cat_summary = cat_summary.sort_values('Count', ascending=False)
        cat_summary['Avg Age'] = cat_summary['Avg Age'].round(1)
        cat_summary['Avg Days Since Update'] = cat_summary['Avg Days Since Update'].round(1)
        
        st.dataframe(cat_summary, use_container_width=True, hide_index=True, height=300)
        st.markdown('</div>', unsafe_allow_html=True)
    
    # ==================== TAB 5: Export ====================
    with tab5:
        st.markdown('<div class="section-title">Export Raw Data</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        export_option = st.radio(
            "Select data to export:",
            ["All Open Incidents", "Aged > 30 Days", "Aging This Week", "No Work Log 30d", "Filtered Data"],
            horizontal=True
        )
        
        if export_option == "All Open Incidents":
            export_df = df
        elif export_option == "Aged > 30 Days":
            export_df = df[df['AGE_DAYS'] > 30]
        elif export_option == "Aging This Week":
            export_df = df[(df['AGE_DAYS'] >= 23) & (df['AGE_DAYS'] <= 30)]
        elif export_option == "No Work Log 30d":
            export_df = df[df['DAYS_SINCE_UPDATE'] > 30]
        else:
            export_df = filtered_df
        
        st.markdown(f"**Records to export: {len(export_df):,}**")
        
        # Preview
        st.markdown("**Preview (first 100 rows):**")
        st.dataframe(export_df.head(100), use_container_width=True, hide_index=True, height=400)
        
        # Download buttons
        col1, col2, col3 = st.columns(3)
        
        with col1:
            csv = export_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name=f"incident_aging_{export_option.replace(' ', '_').lower()}_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
        
        with col2:
            # Excel export
            try:
                from io import BytesIO
                buffer = BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    export_df.to_excel(writer, index=False, sheet_name='Data')
                excel_data = buffer.getvalue()
                st.download_button(
                    label="📥 Download Excel",
                    data=excel_data,
                    file_name=f"incident_aging_{export_option.replace(' ', '_').lower()}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            except ImportError:
                st.info("Install openpyxl for Excel export: pip install openpyxl")
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Footer
    st.markdown("---")
    st.markdown(f"""
    <div style='text-align:center; color:#aaa; font-size:12px;'>
    Incident Aging Report | Total Open: {len(filtered_df):,} | 
    Aged 30+: {len(aged_30):,} | Data as of: {datetime.now().strftime('%Y-%m-%d %H:%M')}
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
