# Incident Analytics Dashboard

A Streamlit dashboard for visualizing ServiceNow incident data from Snowflake.

## Features

- **Overview Metrics**: Total incidents, daily average, high priority count, open incidents
- **Priority Analysis**: Pie chart showing distribution by priority
- **Status Analysis**: Bar chart showing distribution by status
- **Trend Analysis**: Monthly and weekly incident volume trends
- **Assignment Groups**: Top assignment groups by incident volume
- **Heatmap**: Priority vs Status matrix visualization
- **Custom Queries**: Run ad-hoc SQL queries with CSV export

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Snowflake Connection

Copy `.env.example` to `.env` and fill in your Snowflake credentials:

```bash
copy .env.example .env
```

Edit `.env` with your settings:

```
SNOWFLAKE_ACCOUNT=your_account
SNOWFLAKE_USER=your_username
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_WAREHOUSE=your_warehouse
SNOWFLAKE_DATABASE=BDM_ITSM_REPORTING_DB
SNOWFLAKE_SCHEMA=SN_ITSM_REPORTING_V
SNOWFLAKE_ROLE=your_role
```

### 3. Run the App

```bash
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`

## Usage

### Sidebar Controls

- **Time Period**: Filter data by last 7, 30, 90, 180, or 365 days
- **Chart Height**: Adjust visualization height
- **Show Data Tables**: Toggle raw data display below charts
- **Refresh Data**: Clear cache and reload data

### Custom Queries

Expand the "Custom Query" section at the bottom to:
- Write and execute custom SQL queries
- View results in a table
- Download results as CSV

## Data Source

The dashboard queries from:
```
BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_INCIDENT_ALL
```

## Caching

Data is cached for 5 minutes to improve performance. Use the "Refresh Data" button to force a reload.
