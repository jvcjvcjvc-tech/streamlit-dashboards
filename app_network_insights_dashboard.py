"""
Network Insights Dashboard - Combined View
Analytics and visualizations for T-Mobile network operations
Combines: Availability, COTTR, and Customer Minutes
"""

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio
import plotly.colors as pc
import json
import os
import time
import pickle
import hashlib
from datetime import datetime, timedelta, date
from functools import lru_cache
import functools
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import re
import base64

# PERFORMANCE: Disable Plotly animations globally for faster rendering
pio.templates.default = "plotly_white"
pio.templates["plotly_white"].layout.transition = {'duration': 0}
pio.templates["plotly_white"].layout.uirevision = True  # Prevent UI resets

# PRODUCTION: Additional Plotly optimizations
# Default chart config for all st.plotly_chart calls
PLOTLY_CONFIG = {
    'displayModeBar': False,  # Hide mode bar for cleaner UI
    'staticPlot': False,  # Allow interactions but faster render
    'responsive': True,
    'scrollZoom': False,  # Disable scroll zoom for stability
}

# Streamlit chart rendering optimization
def render_chart(fig, use_container_width=True, config=None, key=None):
    """Optimized chart rendering with production settings"""
    if config is None:
        config = CHART_CONFIG
    fig.update_layout(
        margin=dict(l=20, r=20, t=40, b=20),
        autosize=True,
    )
    return st.plotly_chart(fig, use_container_width=use_container_width, config=config, key=key)

# ==================== PERFORMANCE OPTIMIZATION SYSTEM ====================
# Disk-based cache directory for data snapshots (local development only)
# Container runtime in Snowflake has read-only filesystem
CACHE_DIR = None
try:
    _cache_path = os.path.join(os.path.dirname(__file__), '.dashboard_cache')
    os.makedirs(_cache_path, exist_ok=True)
    CACHE_DIR = _cache_path
except (OSError, PermissionError):
    pass  # Running in SiS container with read-only filesystem

def get_cache_key(*args):
    """Generate a unique cache key from arguments"""
    key_str = str(args)
    return hashlib.md5(key_str.encode()).hexdigest()

def save_to_disk_cache(key, data, max_age_hours=4):
    """Save DataFrame to disk cache with timestamp"""
    if CACHE_DIR is None:
        return  # Skip disk cache in SiS container
    try:
        cache_file = os.path.join(CACHE_DIR, f"{key}.pkl")
        with open(cache_file, 'wb') as f:
            pickle.dump({'data': data, 'timestamp': datetime.now()}, f)
    except Exception:
        pass  # Silently fail - disk cache is optional

def load_from_disk_cache(key, max_age_hours=4):
    """Load DataFrame from disk cache if fresh enough"""
    if CACHE_DIR is None:
        return None  # Skip disk cache in SiS container
    try:
        cache_file = os.path.join(CACHE_DIR, f"{key}.pkl")
        if os.path.exists(cache_file):
            with open(cache_file, 'rb') as f:
                cached = pickle.load(f)
            age = datetime.now() - cached['timestamp']
            if age.total_seconds() < max_age_hours * 3600:
                return cached['data']
    except Exception:
        pass
    return None

def init_session_state_cache():
    """Initialize session state for data caching"""
    if 'data_cache' not in st.session_state:
        st.session_state.data_cache = {}
    if 'cache_timestamps' not in st.session_state:
        st.session_state.cache_timestamps = {}
    if 'preload_complete' not in st.session_state:
        st.session_state.preload_complete = False

def cache_data_in_session(key, data):
    """Store data in session state for instant access"""
    init_session_state_cache()
    st.session_state.data_cache[key] = data
    st.session_state.cache_timestamps[key] = datetime.now()

def get_cached_data(key, max_age_minutes=60):
    """Get data from session cache if available and fresh (default 60 min for better performance)"""
    init_session_state_cache()
    if key in st.session_state.data_cache:
        if key in st.session_state.cache_timestamps:
            age = datetime.now() - st.session_state.cache_timestamps[key]
            if age.total_seconds() < max_age_minutes * 60:
                return st.session_state.data_cache[key]
    return None

# OPTIMIZATION: Fast normalized data cache (avoids re-normalizing same data)
_normalized_cache = {}

def get_normalized_df(df, column_name, source, cache_key):
    """Get normalized DataFrame from cache or normalize and cache it"""
    global _normalized_cache
    if cache_key in _normalized_cache:
        return _normalized_cache[cache_key]
    result = normalize_market_column(df, column_name, source)
    _normalized_cache[cache_key] = result
    return result

def clear_normalized_cache():
    """Clear the normalized data cache"""
    global _normalized_cache
    _normalized_cache = {}

def clear_old_cache():
    """Clean up old cache files (run periodically)"""
    if CACHE_DIR is None:
        return  # Skip disk cache in SiS container
    try:
        for filename in os.listdir(CACHE_DIR):
            filepath = os.path.join(CACHE_DIR, filename)
            if os.path.isfile(filepath):
                age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(filepath))
                if age.total_seconds() > 48 * 3600:  # 48 hours (increased from 24)
                    os.remove(filepath)
    except Exception:
        pass

def clear_market_caches():
    """Clear all market-related caches (call when market mappings change)"""
    global _market_ids_cache, _filter_clause_cache
    _market_ids_cache = {}
    _filter_clause_cache = {}

# Check if running in Snowflake's native Streamlit (SiS)
IS_RUNNING_IN_SIS = False
try:
    from snowflake.snowpark.context import get_active_session
    # Test if we can get an active session (only works in SiS)
    _test_session = get_active_session()
    IS_RUNNING_IN_SIS = True
except:
    pass

# Import appropriate connector based on environment
if not IS_RUNNING_IN_SIS:
    import snowflake.connector

# ==================== PRODUCTION CONFIGURATION ====================
# Cache TTL (Time To Live) in seconds
# Data cache: 24 hours - for query results that don't change frequently (extended for better performance)
# Short cache: 1 hour - for semi-frequently changing data
DATA_CACHE_TTL = 86400  # 24 hours (production - extended cache for faster repeated access)
SHORT_CACHE_TTL = 3600  # 1 hour

# Production settings - OPTIMIZED for stability and speed
MAX_QUERY_RETRIES = 2  # Allow 1 retry for transient failures
QUERY_RETRY_DELAY = 0.1  # Small retry delay
MAX_CONCURRENT_QUERIES = 12  # Balanced for connection pool limits (Snowflake default ~10-20)
PRELOAD_WORKERS = 8  # Reduced to prevent connection exhaustion

# OPTIMIZATION: Memoization cache for expensive lookups
_market_ids_cache = {}  # Cache for get_market_ids_for_filter results
_filter_clause_cache = {}  # Cache for build_filter_clause results

# OPTIMIZATION: Query result deduplication within single page render
_query_cache = {}

def get_query_cached(cache_key, query_func, *args, **kwargs):
    """Memoize query results within single page render to prevent duplicate queries"""
    global _query_cache
    if cache_key in _query_cache:
        return _query_cache[cache_key]
    result = query_func(*args, **kwargs)
    _query_cache[cache_key] = result
    return result

def clear_render_cache():
    """Clear the per-render cache at start of each page load"""
    global _query_cache, _normalized_cache
    _query_cache = {}
    # Don't clear normalized cache on every render - it persists across renders for speed

_thread_local = threading.local()

def run_queries_parallel(query_funcs):
    """
    Execute multiple query functions in parallel.
    query_funcs: list of (cache_key, func, args, kwargs) tuples
    Returns: dict of {cache_key: result}
    """
    results = {}
    
    # First check what's already cached
    uncached = []
    for cache_key, func, args, kwargs in query_funcs:
        cached = get_cached_data(cache_key)
        if cached is not None:
            results[cache_key] = cached
        else:
            uncached.append((cache_key, func, args, kwargs))
    
    # Run uncached queries in parallel (max 6 threads to prevent connection exhaustion)
    if uncached:
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_key = {}
            for cache_key, func, args, kwargs in uncached:
                future = executor.submit(func, *args, **kwargs)
                future_to_key[future] = cache_key
            
            for future in as_completed(future_to_key):
                cache_key = future_to_key[future]
                try:
                    result = future.result()
                    results[cache_key] = result
                    cache_data_in_session(cache_key, result)
                except Exception as e:
                    results[cache_key] = None
    
    return results

# Plotly chart config - optimized for fast rendering (main charts with hover)
# Keeps essential buttons: resetScale, autoScale, toImage for full screen navigation
CHART_CONFIG = {
    'displayModeBar': True,  # Always show toolbar for easy access
    'displaylogo': False,
    'modeBarButtonsToRemove': ['lasso2d', 'select2d'],  # Keep zoom/pan for better UX
    'modeBarButtonsToAdd': ['toImage', 'resetScale2d', 'autoScale2d'],  # Download, reset, autoscale
    'staticPlot': False,
    'scrollZoom': False,
    'toImageButtonOptions': {
        'format': 'png',
        'filename': 'network_insights_chart',
        'height': 800,
        'width': 1200,
        'scale': 2
    }
}

# Fast chart config for charts that don't need interactivity
FAST_CHART_CONFIG = {
    'displayModeBar': False,
    'staticPlot': True,  # Static = fastest rendering (no JS event handlers)
}

# Sparkline config - hover enabled, no toolbar (for KPI sparklines)
SPARKLINE_CHART_CONFIG = {
    'displayModeBar': False,  # No toolbar
    'staticPlot': False,  # Enable hover interactivity
    'scrollZoom': False,
    'doubleClick': False,
}

# T-Mobile themed color palette for Hardware dashboard charts
# Solid colors based on T-Mobile magenta + complementary tones
TMOBILE_BAR_COLOR = '#e20074'           # Primary magenta for single-color bars
TMOBILE_BAR_COLOR_ALT = '#b8005c'       # Darker magenta alternate
TMOBILE_COLORSCALE = [                  # Gradient: dark magenta → bright magenta
    [0.0, '#6b0037'], [0.25, '#9e0057'], [0.5, '#c9006a'],
    [0.75, '#e20074'], [1.0, '#ff3399'],
]
TMOBILE_COLORSCALE_WARM = [             # Gradient: deep berry → coral
    [0.0, '#7a0041'], [0.25, '#b3005e'], [0.5, '#e20074'],
    [0.75, '#ff4d8d'], [1.0, '#ff80aa'],
]

# Global hover label style for consistent tooltips across all charts
HOVER_LABEL_STYLE = dict(
    bgcolor='rgba(200, 200, 210, 0.95)',
    bordercolor='#e20074',
    font=dict(color='#333333', size=13, family='Arial'),
    namelength=-1,
)

# Medium chart config - always visible toolbar with download
MEDIUM_CHART_CONFIG = {
    'displayModeBar': True,  # Always show toolbar
    'displaylogo': False,
    'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
    'modeBarButtonsToAdd': ['toImage', 'resetScale2d'],  # Download and reset
    'staticPlot': False,  # Keep hover tooltips
    'scrollZoom': False,
    'toImageButtonOptions': {
        'format': 'png',
        'filename': 'network_insights_chart',
        'height': 800,
        'width': 1200,
        'scale': 2
    }
}

_icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard_icon.png')
st.set_page_config(
    page_title="Network Insights Dashboard",
    page_icon=_icon if os.path.isfile(_icon) else '📊',
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for T-Mobile branding + Performance optimizations
st.markdown("""
<style>
    /* PERFORMANCE: Disable all CSS animations/transitions for faster rendering */
    *, *::before, *::after {
        animation-duration: 0.001s !important;
        transition-duration: 0.001s !important;
    }
    /* PERFORMANCE: Reduce repaints and optimize rendering */
    .stTabs [data-baseweb="tab-panel"] {
        will-change: auto;
        contain: layout style;
    }
    /* PERFORMANCE: GPU acceleration for smooth scrolling */
    .main, .block-container {
        transform: translateZ(0);
        backface-visibility: hidden;
    }
    /* PERFORMANCE: Reduce layout thrashing */
    .stPlotlyChart {
        contain: layout;
    }
    .modebar {
        opacity: 0 !important;
        pointer-events: none !important;
        background: transparent !important;
        border-radius: 4px !important;
        padding: 4px 8px !important;
        right: 10px !important;
        top: 10px !important;
    }
    .js-plotly-plot:hover .modebar,
    .plotly:hover .modebar,
    .stPlotlyChart:hover .modebar {
        opacity: 1 !important;
        pointer-events: auto !important;
    }
    .modebar-btn {
        color: #ffffff !important;
        font-size: 16px !important;
    }
    .modebar-btn:hover {
        color: #e20074 !important;
    }
    .modebar-btn.active {
        color: #e20074 !important;
    }
    .modebar-group {
        background: transparent !important;
        padding: 0 4px !important;
    }
    /* MODEBAR: Download button - white, magenta on hover */
    .modebar-btn[data-title="Download plot as a png"] {
        color: #ffffff !important;
    }
    .modebar-btn[data-title="Download plot as a png"]:hover {
        color: #e20074 !important;
    }
    /* FULLSCREEN: Ensure fullscreen button is visible and positioned in top right */
    [data-testid="StyledFullScreenButton"] {
        color: white !important;
        background-color: rgba(226, 0, 116, 0.85) !important;
        border-radius: 4px !important;
        z-index: 1000 !important;
        opacity: 1 !important;
        visibility: visible !important;
        top: 5px !important;
        right: 5px !important;
        padding: 4px 8px !important;
        transition: all 0.2s ease !important;
    }
    [data-testid="StyledFullScreenButton"]:hover {
        background-color: rgba(226, 0, 116, 1) !important;
        transform: scale(1.05) !important;
    }
    /* FULLSCREEN: Tooltip styling for fullscreen button */
    [data-testid="StyledFullScreenButton"]::after {
        content: attr(title);
        position: absolute;
        right: 100%;
        top: 50%;
        transform: translateY(-50%);
        margin-right: 8px;
        padding: 6px 10px;
        background-color: rgba(200, 200, 210, 0.98);
        color: #333333;
        border: 1px solid #e20074;
        border-radius: 4px;
        font-size: 12px;
        white-space: nowrap;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.2s ease;
    }
    [data-testid="StyledFullScreenButton"]:hover::after {
        opacity: 1;
    }
    /* Ensure element containers show fullscreen button */
    .element-container:hover [data-testid="StyledFullScreenButton"],
    .stDataFrame:hover [data-testid="StyledFullScreenButton"],
    [data-testid="stDataFrame"]:hover [data-testid="StyledFullScreenButton"] {
        opacity: 1 !important;
        visibility: visible !important;
    }
    /* FULLSCREEN: Force expanded modal to start from top */
    [data-testid="stFullScreenFrame"] {
        display: flex !important;
        flex-direction: column !important;
        align-items: flex-start !important;
        justify-content: flex-start !important;
    }
    [data-testid="stFullScreenFrame"] > div {
        align-self: flex-start !important;
        margin-top: 0 !important;
    }
    /* FULLSCREEN: Ensure chart container aligns to top */
    [data-testid="stFullScreenFrame"] .stPlotlyChart,
    [data-testid="stFullScreenFrame"] .js-plotly-plot {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    /* FULLSCREEN: Dataframe starts from top and scrolls to top */
    [data-testid="stFullScreenFrame"] .stDataFrame,
    [data-testid="stFullScreenFrame"] [data-testid="stDataFrame"] {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    [data-testid="stFullScreenFrame"] .stDataFrame > div:first-child {
        scroll-behavior: auto !important;
    }
    /* DATAFRAME: Single scrollbar fix - let internal grid handle scrolling */
    .stDataFrame > div:first-child,
    [data-testid="stDataFrame"] > div:first-child {
        overflow: hidden !important;
    }
    /* Only the inner data grid should scroll */
    .stDataFrame [data-testid="stDataFrameResizable"] {
        overflow: visible !important;
    }
    .stDataFrame .dvn-scroller {
        overflow: auto !important;
    }
    /* Hide any extra scrollbars from containers */
    .element-container:has(.stDataFrame) {
        overflow: visible !important;
    }
    div[data-testid="column"] .stDataFrame {
        overflow: visible !important;
    }
    /* Ensure stVerticalBlock doesn't create extra scroll */
    .stVerticalBlock:has(.stDataFrame) {
        overflow: visible !important;
    }
    /* Expander content should not add its own scrollbar around dataframes */
    [data-testid="stExpander"] .stDataFrame,
    [data-testid="stExpander"] [data-testid="stDataFrame"] {
        overflow: visible !important;
    }
    [data-testid="stExpander"] [data-testid="stDataFrame"] > div:first-child {
        overflow: hidden !important;
    }
    /* DATAFRAME: Tooltip styling for better visibility */
    .stDataFrame [data-testid="glideDataEditor"] [role="tooltip"],
    .stDataFrame .gdg-tooltip,
    [data-testid="stDataFrame"] .gdg-tooltip,
    .dvn-scroller + div,
    div[class*="tooltip"],
    .gdg-bubble-menu {
        background-color: rgba(200, 200, 210, 0.98) !important;
        color: #333333 !important;
        border: 1px solid #e20074 !important;
        border-radius: 6px !important;
        padding: 8px 12px !important;
        font-size: 13px !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3) !important;
        max-width: 400px !important;
        z-index: 9999 !important;
    }
    /* DATAFRAME: Glide portal tooltip (rendered outside main container) */
    div[data-radix-popper-content-wrapper] {
        z-index: 99999 !important;
    }
    div[data-radix-popper-content-wrapper] > div {
        background-color: rgba(200, 200, 210, 0.98) !important;
        color: #333333 !important;
        border: 1px solid #e20074 !important;
        border-radius: 6px !important;
        padding: 8px 12px !important;
        font-size: 13px !important;
    }
    /* DATAFRAME: Cell hover tooltip - native title attribute styling not possible, but positioning fix */
    .stDataFrame div[title],
    [data-testid="stDataFrame"] div[title] {
        position: relative;
    }
    /* FULLSCREEN: Force scroll to top on entry */
    [data-testid="stFullScreenFrame"] {
        overflow-y: auto !important;
        scroll-behavior: smooth !important;
    }
    [data-testid="stFullScreenFrame"] > div:first-child {
        scroll-margin-top: 0 !important;
    }
    /* PERFORMANCE: Optimize font rendering */
    body {
        text-rendering: optimizeSpeed;
        -webkit-font-smoothing: antialiased;
    }
    .main-header {
        color: #e20074;
        font-size: 1.8rem;
        font-weight: bold;
        margin-bottom: 0.3rem;
    }
    .sub-header {
        color: #666;
        font-size: 0.85rem;
        margin-bottom: 1rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
        padding: 0.8rem;
        border-radius: 8px;
        border-left: 3px solid #e20074;
        margin: 0.3rem 0;
        min-height: 80px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        color: #f8f9fa;
    }
    .metric-card-green {
        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
        padding: 0.8rem;
        border-radius: 8px;
        border-left: 3px solid #22c55e;
        color: #f8f9fa;
        margin: 0.3rem 0;
        min-height: 80px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .metric-card-orange {
        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
        padding: 0.8rem;
        border-radius: 8px;
        border-left: 3px solid #f59e0b;
        margin: 0.3rem 0;
        min-height: 80px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .metric-value-magenta {
        color: #e20074;
        font-size: 1.4rem;
        font-weight: bold;
    }
    .metric-value-green {
        color: #22c55e;
        font-size: 1.4rem;
        font-weight: bold;
    }
    .metric-value-orange {
        color: #f59e0b;
        font-size: 1.4rem;
        font-weight: bold;
    }
    .metric-label {
        color: #888;
        font-size: 0.75rem;
        margin-top: 0.3rem;
    }
    .metric-source {
        color: #555;
        font-size: 0.75rem;
        margin-top: 0.3rem;
        font-style: italic;
    }
    .insight-box {
        background-color: #E8E8E8;
        padding: 0.5rem;
        border-radius: 6px;
        border-left: 3px solid #e20074;
        margin: 0.25rem 0;
        color: #f8f9fa;
        font-size: 0.8rem;
    }
    .warning-box {
        background-color: #E8E8E8;
        padding: 0.5rem;
        border-radius: 6px;
        border-left: 3px solid #e20074;
        margin: 0.25rem 0;
        color: #f8f9fa;
        font-size: 0.8rem;
    }
    .market-box {
        background-color: #E8E8E8;
        padding: 0.4rem 0.5rem;
        border-radius: 6px;
        border-left: 3px solid #e20074;
        margin: 0.15rem 0;
        color: #1a1a2e;
        height: 58px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        box-sizing: border-box;
        font-size: 0.75rem;
    }
    .market-box-tall {
        background-color: #E8E8E8;
        padding: 0.4rem 0.5rem;
        border-radius: 6px;
        border-left: 3px solid #e20074;
        margin: 0.15rem 0;
        color: #1a1a2e;
        min-height: 75px;
        box-sizing: border-box;
        font-size: 0.75rem;
    }
    .category-section {
        min-height: 85px;
        margin-bottom: 0.5rem;
    }
    .success-box {
        background-color: #1e5f3a;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #22c55e;
        margin: 0.5rem 0;
        color: white;
    }
    .section-header {
        color: #e20074;
        font-size: 1rem;
        font-weight: bold;
        margin: 0.5rem 0 0.3rem 0;
        padding-bottom: 0.3rem;
        border-bottom: 2px solid #333;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #2d2d2d;
        border-radius: 8px;
        padding: 10px 20px;
        color: white !important;
    }
    .stTabs [data-baseweb="tab"] p {
        color: white !important;
    }
    .stTabs [data-baseweb="tab"] span {
        color: white !important;
    }
    .stTabs [aria-selected="true"] {
        background-color: #e20074 !important;
        color: white !important;
    }
    .stTabs [aria-selected="true"] p {
        color: white !important;
    }
    .stTabs button[data-baseweb="tab"] {
        color: white !important;
    }
    /* Remove border from scrollable containers */
    [data-testid="stVerticalBlock"] > div[style*="overflow"] {
        border: none !important;
        box-shadow: none !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border: none !important;
        box-shadow: none !important;
        background: transparent !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        border: none !important;
        box-shadow: none !important;
    }
    .stElementContainer > div[style*="height"] {
        border: none !important;
        box-shadow: none !important;
    }
    /* Target fixed height containers */
    div[style*="height: 420px"] {
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
    }
    div[style*="height: 400px"] {
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
    }
    /* Remove all container borders */
    .element-container > div > div[style*="overflow"] {
        border: none !important;
    }
    [data-testid="element-container"] div[style*="overflow-y: auto"] {
        border: none !important;
        box-shadow: none !important;
    }
    
    /* ===== RESPONSIVE FONT SIZING ===== */
    /* Auto-adjust fonts based on viewport width */
    
    /* Main headers - scale with viewport */
    .main-header {
        font-size: clamp(1.2rem, 2vw, 1.8rem) !important;
    }
    .sub-header {
        font-size: clamp(0.65rem, 1vw, 0.85rem) !important;
    }
    .section-header {
        font-size: clamp(0.8rem, 1.2vw, 1rem) !important;
    }
    
    /* Metric values - responsive */
    .metric-value-magenta, .metric-value-green, .metric-value-orange {
        font-size: clamp(1rem, 1.5vw, 1.4rem) !important;
    }
    .metric-label, .metric-source {
        font-size: clamp(0.6rem, 0.9vw, 0.75rem) !important;
    }
    
    /* Market boxes - responsive text */
    .market-box, .market-box-tall {
        font-size: clamp(0.55rem, 0.85vw, 0.75rem) !important;
    }
    .market-box strong, .market-box-tall strong {
        font-size: clamp(0.6rem, 0.9vw, 0.8rem) !important;
    }
    
    /* Insight and warning boxes */
    .insight-box, .warning-box {
        font-size: clamp(0.65rem, 0.95vw, 0.8rem) !important;
    }
    
    /* Plotly chart text responsiveness */
    .js-plotly-plot .plotly text {
        font-size: clamp(8px, 1vw, 12px) !important;
    }
    
    /* Table text - responsive */
    table {
        font-size: clamp(0.6rem, 0.9vw, 0.75rem) !important;
    }
    table th, table td {
        padding: clamp(4px, 0.5vw, 8px) !important;
        font-size: clamp(0.55rem, 0.85vw, 0.75rem) !important;
    }
    
    /* Media queries for specific breakpoints */
    @media screen and (max-width: 1400px) {
        .metric-card, .metric-card-green, .metric-card-orange {
            padding: 0.5rem !important;
            min-height: 65px !important;
        }
        .market-box {
            height: 50px !important;
            padding: 0.3rem 0.4rem !important;
        }
        .market-box-tall {
            min-height: 60px !important;
        }
    }
    
    @media screen and (max-width: 1200px) {
        .metric-value-magenta, .metric-value-green, .metric-value-orange {
            font-size: 1rem !important;
        }
        .metric-label, .metric-source {
            font-size: 0.6rem !important;
        }
        .market-box, .market-box-tall {
            font-size: 0.6rem !important;
        }
        .section-header {
            font-size: 0.85rem !important;
        }
    }
    
    @media screen and (max-width: 1000px) {
        .main-header {
            font-size: 1.2rem !important;
        }
        .metric-value-magenta, .metric-value-green, .metric-value-orange {
            font-size: 0.9rem !important;
        }
        .metric-card, .metric-card-green, .metric-card-orange {
            padding: 0.4rem !important;
            min-height: 55px !important;
        }
        .market-box {
            height: 45px !important;
            font-size: 0.55rem !important;
        }
    }
    
    @media screen and (max-width: 800px) {
        .metric-value-magenta, .metric-value-green, .metric-value-orange {
            font-size: 0.8rem !important;
        }
        .metric-label, .metric-source {
            font-size: 0.55rem !important;
        }
        .market-box, .market-box-tall {
            font-size: 0.5rem !important;
        }
        table th, table td {
            padding: 3px !important;
            font-size: 0.5rem !important;
        }
    }
    
    /* Prevent text overflow */
    .market-box, .market-box-tall, .metric-card, .metric-card-green, .metric-card-orange {
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    
    /* Word break for long text */
    .market-box span, .market-box-tall span {
        word-break: break-word !important;
        overflow-wrap: break-word !important;
    }
    
    /* Override inline font sizes in market boxes */
    .market-box div[style*="font-size"], .market-box-tall div[style*="font-size"] {
        font-size: clamp(0.55rem, 0.85vw, 0.8rem) !important;
    }
    .market-box div[style*="font-size:1rem"], .market-box-tall div[style*="font-size:1rem"] {
        font-size: clamp(0.75rem, 1.1vw, 1rem) !important;
    }
    .market-box span[style*="font-size"], .market-box-tall span[style*="font-size"] {
        font-size: clamp(0.5rem, 0.75vw, 0.7rem) !important;
    }
    
    /* Target avail/budget boxes inside market cards */
    .market-box div[style*="text-align:center"] div {
        font-size: clamp(0.7rem, 1vw, 1rem) !important;
    }
    .market-box div[style*="text-align:center"] div[style*="font-size:0.65rem"] {
        font-size: clamp(0.5rem, 0.7vw, 0.65rem) !important;
    }
    
    /* Category bar text */
    .market-box div[style*="height:22px"] span,
    .market-box-tall div[style*="height:22px"] span {
        font-size: clamp(0.5rem, 0.75vw, 0.7rem) !important;
    }
    
    /* Responsive bar height */
    @media screen and (max-width: 1200px) {
        .market-box div[style*="height:22px"],
        .market-box-tall div[style*="height:22px"] {
            height: 18px !important;
        }
    }
    @media screen and (max-width: 1000px) {
        .market-box div[style*="height:22px"],
        .market-box-tall div[style*="height:22px"] {
            height: 15px !important;
        }
    }
    
    /* Legend text responsive */
    div[style*="font-size:0.75rem"] span,
    div[style*="font-size: 0.75rem"] span {
        font-size: clamp(0.55rem, 0.8vw, 0.75rem) !important;
    }
    
    /* Plotly treemap labels */
    .js-plotly-plot .textpoint text,
    .js-plotly-plot .slicetext text {
        font-size: clamp(8px, 1vw, 12px) !important;
    }
</style>
""", unsafe_allow_html=True)

# JavaScript injection for fullscreen scroll-to-top behavior
components.html("""
<script>
(function() {
    // Function to scroll fullscreen modals to top
    function scrollFullscreenToTop() {
        const fullscreenFrames = document.querySelectorAll('[data-testid="stFullScreenFrame"]');
        fullscreenFrames.forEach(frame => {
            frame.scrollTop = 0;
            const scrollableChild = frame.querySelector('.stDataFrame, .stPlotlyChart, [data-testid="stDataFrame"]');
            if (scrollableChild) {
                scrollableChild.scrollTop = 0;
            }
        });
    }
    
    // Observer to detect when fullscreen is opened
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.addedNodes.length > 0) {
                mutation.addedNodes.forEach(function(node) {
                    if (node.nodeType === 1) {
                        if (node.matches && (node.matches('[data-testid="stFullScreenFrame"]') || 
                            node.querySelector && node.querySelector('[data-testid="stFullScreenFrame"]'))) {
                            setTimeout(scrollFullscreenToTop, 50);
                            setTimeout(scrollFullscreenToTop, 150);
                        }
                    }
                });
            }
        });
    });
    
    // Start observing the document
    observer.observe(document.body, { childList: true, subtree: true });
    
    // Also handle click on fullscreen buttons
    document.addEventListener('click', function(e) {
        if (e.target.closest('[data-testid="StyledFullScreenButton"]')) {
            setTimeout(scrollFullscreenToTop, 100);
            setTimeout(scrollFullscreenToTop, 300);
        }
    });
})();
</script>
""", height=0)

# Markets to exclude from all queries (non-market entries in MARKET_TRACKER)
EXCLUDED_MARKET_IDS = [
    'EMERGENCY MANAGEMENT',
    'NATIONAL PROGRAMS',
    'National',
    'Not Matched',
    'TEST - LAB MARKET',
]

# Table definitions - QTM Environment (WORKING)
TABLES = {
    "customer_minutes": "BDM_QTM_PRESENTATION_SH.PRTS.V_NOA_NDS_NTWK_OUTAGE_IMPACTED_SUBS_SUMMARY_BY_SITE_V2",
    "customer_minutes_v1": "BDM_QTM_PRESENTATION_SH.PRTS.V_NOA_NDS_NTWK_OUTAGE_IMPACTED_SUBS_SUMMARY_BY_SITE",
    "availability": "BDM_QTM_PRESENTATION_SH.QI_SHARED.VQTM_RAN_AVAILABILITY_CATEGORY_SITE_DAILY",
    "cottr": "BDM_NDW_NTWK_CI_OPS_DB.NEP_DATAMART_V.V_NEP_SERVICELEVEL_DAY_VIEW_WITH_QTM_CATEGORY",
    "sector_tracker": "BDM_NDW_MAGENTABUILT_REFERENCE_DB.MAGENTABUILT_REFERENCE.SECTOR_TRACKER",
    "site_tracker": "BDM_NDW_MAGENTABUILT_REFERENCE_DB.MAGENTABUILT_REFERENCE.SITE_TRACKER",
    "ring_tracker": "BDM_NDW_MAGENTABUILT_REFERENCE_DB.MAGENTABUILT_REFERENCE.RING_TRACKER",
    "market_tracker": "BDM_NDW_MAGENTABUILT_REFERENCE_DB.MAGENTABUILT_REFERENCE.MARKET_TRACKER",
    "change_record": "BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_CR",
    "incident_all": "BDM_ITSM_REPORTING_DB.SN_ITSM_REPORTING_V.V_INCIDENT_ALL",
    "nest_state_change": "BDM_NDW_NTWK_CI_OPS_DB.NEST_V.V_CONFIGITEMSTATECHANGEREQUEST",
}

# Consistent color mapping for focus categories across all charts
# Using magenta/pink shades and grays only (matching dashboard legend)
FOCUS_CATEGORY_COLORS = {
    # Transport-related (grey - matching Summary Category)
    "Transport - AAV": "#666666",
    "Transport": "#666666",
    "Internal Transport Upgrades": "#555555",
    "Internal Transport Expansion": "#555555",
    "Interconnection": "#4a4a4a",
    "Centralized Backhaul": "#3f3f3f",
    "RingFed": "#343434",
    
    # Software/Site (lighter magenta/pink shades)
    "Software": "#ff4d9a",
    "Site Mod": "#ff66a8",
    "SW Mod": "#ff80b6",
    "Power": "#000000",  # Black for contrast with Hardware
    "Weather Power Event": "#000000",  # Same as Power
    "Protect": "#ffb3d2",
    
    # Hardware-related (dark maroon shades)
    "Hardware": "#8b0045",
    "Router": "#6b0035",
    "Headend": "#5a002d",
    "RAN": "#4a0025",
    
    # Microwave (dark magenta)
    "Microwave": "#5c0030",
    
    # Damage (dark maroon)
    "Vandalized/Damage": "#4a002a",
    "Vandalized": "#4a002a",
    
    # Gray shades (maintenance, process, weather, etc.)
    "Maintenance": "#9ca3af",
    "Process/Other": "#8b95a5",
    "Weather": "#a8b2c1",
    "Unaccounted": "#a0a0a0",
    "Uncategorized": "#b0b0b0",
    "Unknown": "#a0a0a0",
    "Decommission": "#95a0ad",
    "No Outage": "#c0c0c0",
    "Other": "#8b95a5",
}

DEFAULT_FOCUS_COLOR = "#6b7280"

# Region colors for market-level charts
REGION_COLORS = {
    'Central': '#000000',      # Black
    'Northeast': '#e20074',    # Magenta
    'South': '#4a0e4e',        # Dark purple
    'West': '#888888',         # Gray
}
DEFAULT_REGION_COLOR = "#6b7280"

# Summary Category colors (SITE_ID_SUMMARY_CATEGORY) - Global colors for charts
SUMMARY_CATEGORY_COLORS = {
    'RAN': '#e20074',           # T-Mobile Magenta
    'Power': '#000000',         # Black (matching Focus Category)
    'Transport': '#666666',     # Grey
    'Uncategorized': '#999999', # Light Grey
}
DEFAULT_SUMMARY_COLOR = "#444444"

# OEM and Cohort mappings - loaded dynamically from MARKET_TRACKER
# These will be populated by load_oem_cohort_mappings() when connection is available
MARKET_TO_OEM = {}
MARKET_TO_COHORT = {}
_OEM_MAPPINGS_LOADED = False

# Mapping from Availability MARKET_ID (no spaces) to MARKET_TRACKER M_CAPITAL_MARKET
# Based on Master Market mapping file - Column B (Global Market) → M_CAPITAL_MARKET
AVAIL_TO_MT_MARKET_MAP = {
    # Markets with different naming conventions
    'NewJersey': 'NJMetro',
    'NewYork': 'NYMetro', 
    'SouthernCalifornia': 'SoCal',
    'St.Louis': 'StLouis',
    # Combined markets in MARKET_TRACKER
    'Birmingham': 'BirMem',
    'Memphis': 'BirMem',
    'Tampa': 'TampaOrlando',
    'Orlando': 'TampaOrlando',
    'DesMoines': 'Iowa',
    'Omaha': 'Iowa',
    'Mobile': 'NOMO',
    'Arkansas': 'NOMO',
    'NewOrleans': 'NOMO',
    'WestVirginia': 'Virginia',
}

def get_market_case_sql():
    """Generate SQL CASE statement for market name normalization"""
    cases = []
    for avail_name, mt_name in AVAIL_TO_MT_MARKET_MAP.items():
        cases.append(f"WHEN REPLACE(a.MARKET_ID, ' ', '') = '{avail_name}' THEN '{mt_name}'")
    case_sql = "CASE " + " ".join(cases) + " ELSE REPLACE(a.MARKET_ID, ' ', '') END"
    return case_sql

def load_oem_cohort_mappings(conn):
    """Load OEM and Cohort mappings from CONSOLIDATED_MARKET_MAP"""
    global MARKET_TO_OEM, MARKET_TO_COHORT, _OEM_MAPPINGS_LOADED
    
    if _OEM_MAPPINGS_LOADED:
        return
    
    # Load from CONSOLIDATED_MARKET_MAP (always available, no DB query needed)
    for market_id, data in CONSOLIDATED_MARKET_MAP.items():
        tracker_id = data['market_tracker_id']
        MARKET_TO_OEM[tracker_id] = data['oem']
        MARKET_TO_COHORT[tracker_id] = data['cohort']
        # Also add Global Market ID format
        MARKET_TO_OEM[market_id] = data['oem']
        MARKET_TO_COHORT[market_id] = data['cohort']
    
    # Add Alaska as special case (not in 59 Global Markets but may exist in some data)
    MARKET_TO_OEM['ALASKA'] = 'Nokia'
    MARKET_TO_OEM['Alaska'] = 'Nokia'
    
    _OEM_MAPPINGS_LOADED = True

# Get markets by OEM (returns Global Market IDs)
def get_markets_by_oem(oem):
    return [market_id for market_id, data in CONSOLIDATED_MARKET_MAP.items() if data['oem'] == oem]

# Get markets by cohort (returns Global Market IDs)
def get_markets_by_cohort(cohort):
    return [market_id for market_id, data in CONSOLIDATED_MARKET_MAP.items() if data['cohort'] == cohort]

# Get markets by OEM and cohort (returns Global Market IDs)
def get_markets_by_oem_and_cohort(oem=None, cohort=None):
    markets = []
    for market_id, data in CONSOLIDATED_MARKET_MAP.items():
        if oem and data['oem'] != oem:
            continue
        if cohort and data['cohort'] != cohort:
            continue
        markets.append(market_id)
    return sorted(markets)

def load_config():
    """Load Snowflake configuration"""
    here = os.path.dirname(os.path.abspath(__file__))
    for config_path in (
        os.path.join(here, 'config_sso.json'),
        os.path.join(here, '..', 'config_sso.json'),
    ):
        if os.path.exists(config_path):
            with open(config_path, encoding='utf-8') as f:
                return json.load(f)
    return None

@st.cache_resource
def get_connection(user_email=None):
    """Get cached Snowflake connection
    
    In Snowflake's native Streamlit (SiS), uses the active session.
    For local development, uses externalbrowser authentication.
    """
    # If running in Snowflake's native Streamlit, use the active session
    if IS_RUNNING_IN_SIS:
        try:
            session = get_active_session()
            return session.connection
        except Exception as e:
            st.error(f"Failed to get Snowflake session: {str(e)}")
            return None
    
    # Local development: use externalbrowser auth
    config = load_config()
    if not config:
        return None
    
    env_config = config.get('environments', {}).get('PROD', {})
    sf = env_config.get('snowflake', {})
    
    try:
        conn = snowflake.connector.connect(
            user=user_email,
            account=sf.get('account', 'tmobile.west-us-2.privatelink'),
            authenticator='externalbrowser',
            warehouse=sf.get('warehouse'),
            database=sf.get('database'),
            schema=sf.get('schema'),
            client_session_keep_alive=True,
            client_prefetch_threads=8,
            network_timeout=120,
            login_timeout=60,
            client_store_temporary_credential=True,
        )
        return conn
    except Exception as e:
        st.error(f"Connection failed: {str(e)}")
        return None

# Markets to exclude from dropdowns
EXCLUDED_MARKETS = [
    'Labmarket', 'LABMARKET', 
    'Emergency Management', 'EMERGENCY MANAGEMENT',
    'NATIONAL PROGRAMS', 'National Programs',
    'National', 'NATIONAL',
    'Not Matched', 'NOT MATCHED',
    'TEST - LAB MARKET', 'Test - Lab Market',
]

# Consolidated Market ID Mapping Table
# Maps market names across all three data sources to a canonical display name
# Key = Canonical display name (used in UI)
# Value = dict with source-specific names for 'availability', 'cottr', 'customer_minutes'
# 59 Global Market IDs - consolidated from mkt mapping reference
# Sub-markets roll up: El Paso→Albuquerque, Dakotas→Minneapolis, Tulsa/Wichita→Oklahoma City
# OEM: 27 Ericsson markets, 32 Nokia markets
# Cohorts: 1=Major Metro, 2=Mid-Size, 3=Smaller/Rural
CONSOLIDATED_MARKET_MAP = {
    # Ericsson Markets (27) - Cohort 1: 12, Cohort 2: 8, Cohort 3: 7
    'Albuquerque': {'availability': 'Albuquerque', 'cottr': 'ALBUQUERQUE NM', 'customer_minutes': 'Albuquerque', 'market_tracker_id': 'ALBUQUERQUE NM', 'oem': 'Ericsson', 'cohort': 3},
    'Atlanta': {'availability': 'Atlanta', 'cottr': 'ATLANTA', 'customer_minutes': 'Atlanta', 'market_tracker_id': 'ATLANTA', 'oem': 'Ericsson', 'cohort': 1},
    'Central PA': {'availability': 'Central PA', 'cottr': 'CENTRAL PA', 'customer_minutes': 'Central PA', 'market_tracker_id': 'CENTRAL PA', 'oem': 'Ericsson', 'cohort': 3},
    'Connecticut': {'availability': 'Connecticut', 'cottr': 'CONNECTICUT', 'customer_minutes': 'Connecticut', 'market_tracker_id': 'CONNECTICUT', 'oem': 'Ericsson', 'cohort': 3},
    'Hawaii': {'availability': 'Hawaii', 'cottr': 'HAWAII HI', 'customer_minutes': 'Hawaii', 'market_tracker_id': 'HAWAII HI', 'oem': 'Ericsson', 'cohort': 3},
    'Jacksonville': {'availability': 'Jacksonville', 'cottr': 'JACKSONVILLE', 'customer_minutes': 'Jacksonville', 'market_tracker_id': 'JACKSONVILLE', 'oem': 'Ericsson', 'cohort': 2},
    'LA North': {'availability': 'LA North', 'cottr': 'LA NORTH', 'customer_minutes': 'LA North', 'market_tracker_id': 'LA NORTH', 'oem': 'Ericsson', 'cohort': 2},
    'Las Vegas': {'availability': 'Las Vegas', 'cottr': 'LAS VEGAS', 'customer_minutes': 'Las Vegas', 'market_tracker_id': 'LAS VEGAS', 'oem': 'Ericsson', 'cohort': 3},
    'Long Island': {'availability': 'Long Island', 'cottr': 'LONG ISLAND - NY', 'customer_minutes': 'Long Island', 'market_tracker_id': 'LONG ISLAND - NY', 'oem': 'Ericsson', 'cohort': 3},
    'Los Angeles': {'availability': 'Los Angeles', 'cottr': 'LOS ANGELES', 'customer_minutes': 'Los Angeles', 'market_tracker_id': 'LOS ANGELES', 'oem': 'Ericsson', 'cohort': 1},
    'Miami': {'availability': 'Miami', 'cottr': 'MIAMI FL', 'customer_minutes': 'Miami', 'market_tracker_id': 'MIAMI FL', 'oem': 'Ericsson', 'cohort': 1},
    'New England': {'availability': 'New England', 'cottr': 'NEW ENGLAND MARKET', 'customer_minutes': 'New England', 'market_tracker_id': 'NEW ENGLAND MARKET', 'oem': 'Ericsson', 'cohort': 1},
    'New Jersey': {'availability': 'New Jersey', 'cottr': 'NEW JERSEY NJ', 'customer_minutes': 'New Jersey', 'market_tracker_id': 'NEW JERSEY NJ', 'oem': 'Ericsson', 'cohort': 1},
    'New York': {'availability': 'New York', 'cottr': 'NEW YORK NY', 'customer_minutes': 'New York', 'market_tracker_id': 'NEW YORK NY', 'oem': 'Ericsson', 'cohort': 1},
    'North Carolina': {'availability': 'North Carolina', 'cottr': 'NORTH CAROLINA', 'customer_minutes': 'North Carolina', 'market_tracker_id': 'NORTH CAROLINA', 'oem': 'Ericsson', 'cohort': 1},
    'Orlando': {'availability': 'Orlando', 'cottr': 'ORLANDO', 'customer_minutes': 'Orlando', 'market_tracker_id': 'ORLANDO', 'oem': 'Ericsson', 'cohort': 2},
    'Philadelphia': {'availability': 'Philadelphia', 'cottr': 'PHILADELPHIA PA', 'customer_minutes': 'Philadelphia', 'market_tracker_id': 'PHILADELPHIA PA', 'oem': 'Ericsson', 'cohort': 1},
    'Sacramento': {'availability': 'Sacramento', 'cottr': 'SACRAMENTO', 'customer_minutes': 'Sacramento', 'market_tracker_id': 'SACRAMENTO', 'oem': 'Ericsson', 'cohort': 2},
    'Salt Lake City': {'availability': 'Salt Lake City', 'cottr': 'SALT LAKE CITY UT', 'customer_minutes': 'Salt Lake City', 'market_tracker_id': 'SALT LAKE CITY UT', 'oem': 'Ericsson', 'cohort': 1},
    'San Diego': {'availability': 'San Diego', 'cottr': 'SAN DIEGO', 'customer_minutes': 'San Diego', 'market_tracker_id': 'SAN DIEGO', 'oem': 'Ericsson', 'cohort': 3},
    'San Francisco': {'availability': 'San Francisco', 'cottr': 'SAN FRANCISCO', 'customer_minutes': 'San Francisco', 'market_tracker_id': 'SAN FRANCISCO', 'oem': 'Ericsson', 'cohort': 1},
    'South Carolina': {'availability': 'South Carolina', 'cottr': 'SOUTH CAROLINA', 'customer_minutes': 'South Carolina', 'market_tracker_id': 'SOUTH CAROLINA', 'oem': 'Ericsson', 'cohort': 2},
    'Southern California': {'availability': 'Southern California', 'cottr': 'SOUTHERN CALIFORNIA', 'customer_minutes': 'Southern California', 'market_tracker_id': 'SOUTHERN CALIFORNIA', 'oem': 'Ericsson', 'cohort': 1},
    'Tampa': {'availability': 'Tampa', 'cottr': 'TAMPA FL', 'customer_minutes': 'Tampa', 'market_tracker_id': 'TAMPA FL', 'oem': 'Ericsson', 'cohort': 2},
    'Upstate NY': {'availability': 'Upstate NY', 'cottr': 'NY (UPSTATE)', 'customer_minutes': 'Upstate NY', 'market_tracker_id': 'NY (UPSTATE)', 'oem': 'Ericsson', 'cohort': 2},
    'Virginia': {'availability': 'Virginia', 'cottr': 'VIRGINIA', 'customer_minutes': 'Virginia', 'market_tracker_id': 'VIRGINIA', 'oem': 'Ericsson', 'cohort': 2},
    'Washington DC': {'availability': 'Washington DC', 'cottr': 'WASHINGTON DC', 'customer_minutes': 'Washington DC', 'market_tracker_id': 'WASHINGTON DC', 'oem': 'Ericsson', 'cohort': 1},
    # Nokia Markets (32) - Cohort 1: 13, Cohort 2: 10, Cohort 3: 9
    'Arkansas': {'availability': 'Arkansas', 'cottr': 'ARKANSAS', 'customer_minutes': 'Arkansas', 'market_tracker_id': 'ARKANSAS', 'oem': 'Nokia', 'cohort': 2},
    'Austin': {'availability': 'Austin', 'cottr': 'AUSTIN TX', 'customer_minutes': 'Austin', 'market_tracker_id': 'AUSTIN TX', 'oem': 'Nokia', 'cohort': 1},
    'Birmingham': {'availability': 'Birmingham', 'cottr': 'BIRMINGHAM', 'customer_minutes': 'Birmingham', 'market_tracker_id': 'BIRMINGHAM', 'oem': 'Nokia', 'cohort': 3},
    'Chicago': {'availability': 'Chicago', 'cottr': 'CHICAGO', 'customer_minutes': 'Chicago', 'market_tracker_id': 'CHICAGO', 'oem': 'Nokia', 'cohort': 1},
    'Cincinnati': {'availability': 'Cincinnati', 'cottr': 'CINCINNATI', 'customer_minutes': 'Cincinnati', 'market_tracker_id': 'CINCINNATI', 'oem': 'Nokia', 'cohort': 3},
    'Cleveland': {'availability': 'Cleveland', 'cottr': 'CLEVELAND', 'customer_minutes': 'Cleveland', 'market_tracker_id': 'CLEVELAND', 'oem': 'Nokia', 'cohort': 3},
    'Columbus': {'availability': 'Columbus', 'cottr': 'COLUMBUS', 'customer_minutes': 'Columbus', 'market_tracker_id': 'COLUMBUS', 'oem': 'Nokia', 'cohort': 3},
    'Dallas': {'availability': 'Dallas', 'cottr': 'DALLAS TX', 'customer_minutes': 'Dallas', 'market_tracker_id': 'DALLAS TX', 'oem': 'Nokia', 'cohort': 1},
    'Denver': {'availability': 'Denver', 'cottr': 'DENVER CO', 'customer_minutes': 'Denver', 'market_tracker_id': 'DENVER CO', 'oem': 'Nokia', 'cohort': 1},
    'Des Moines': {'availability': 'Des Moines', 'cottr': 'DES MOINES IA', 'customer_minutes': 'Des Moines', 'market_tracker_id': 'DES MOINES IA', 'oem': 'Nokia', 'cohort': 2},
    'Detroit': {'availability': 'Detroit', 'cottr': 'DETROIT MI', 'customer_minutes': 'Detroit', 'market_tracker_id': 'DETROIT MI', 'oem': 'Nokia', 'cohort': 1},
    'Houston': {'availability': 'Houston', 'cottr': 'HOUSTON TX', 'customer_minutes': 'Houston', 'market_tracker_id': 'HOUSTON TX', 'oem': 'Nokia', 'cohort': 1},
    'Indianapolis': {'availability': 'Indianapolis', 'cottr': 'INDIANAPOLIS IN', 'customer_minutes': 'Indianapolis', 'market_tracker_id': 'INDIANAPOLIS IN', 'oem': 'Nokia', 'cohort': 3},
    'Kansas City': {'availability': 'Kansas City', 'cottr': 'KANSAS CITY KS', 'customer_minutes': 'Kansas City', 'market_tracker_id': 'KANSAS CITY KS', 'oem': 'Nokia', 'cohort': 1},
    'Knoxville': {'availability': 'Knoxville', 'cottr': 'KNOXVILLE TN', 'customer_minutes': 'Knoxville', 'market_tracker_id': 'KNOXVILLE TN', 'oem': 'Nokia', 'cohort': 2},
    'Louisville': {'availability': 'Louisville', 'cottr': 'LOUISVILLE', 'customer_minutes': 'Louisville', 'market_tracker_id': 'LOUISVILLE', 'oem': 'Nokia', 'cohort': 2},
    'Memphis': {'availability': 'Memphis', 'cottr': 'MEMPHIS', 'customer_minutes': 'Memphis', 'market_tracker_id': 'MEMPHIS', 'oem': 'Nokia', 'cohort': 3},
    'Milwaukee': {'availability': 'Milwaukee', 'cottr': 'MILWAUKEE', 'customer_minutes': 'Milwaukee', 'market_tracker_id': 'MILWAUKEE', 'oem': 'Nokia', 'cohort': 2},
    'Minneapolis': {'availability': 'Minneapolis', 'cottr': 'MINNEAPOLIS MN', 'customer_minutes': 'Minneapolis', 'market_tracker_id': 'MINNEAPOLIS MN', 'oem': 'Nokia', 'cohort': 1},
    'Mobile': {'availability': 'Mobile', 'cottr': 'MOBILE', 'customer_minutes': 'Mobile', 'market_tracker_id': 'MOBILE', 'oem': 'Nokia', 'cohort': 1},
    'Montana': {'availability': 'Montana', 'cottr': 'MONTANA', 'customer_minutes': 'Montana', 'market_tracker_id': 'MONTANA', 'oem': 'Nokia', 'cohort': 3},
    'Nashville': {'availability': 'Nashville', 'cottr': 'NASHVILLE', 'customer_minutes': 'Nashville', 'market_tracker_id': 'NASHVILLE', 'oem': 'Nokia', 'cohort': 2},
    'Oklahoma City': {'availability': 'Oklahoma City', 'cottr': 'OKLAHOMA CITY OK', 'customer_minutes': 'Oklahoma City', 'market_tracker_id': 'OKLAHOMA CITY OK', 'oem': 'Nokia', 'cohort': 1},
    'Omaha': {'availability': 'Omaha', 'cottr': 'OMAHA', 'customer_minutes': 'Omaha', 'market_tracker_id': 'OMAHA', 'oem': 'Nokia', 'cohort': 2},
    'Phoenix': {'availability': 'Phoenix', 'cottr': 'PHOENIX', 'customer_minutes': 'Phoenix', 'market_tracker_id': 'PHOENIX', 'oem': 'Nokia', 'cohort': 1},
    'Pittsburgh': {'availability': 'Pittsburgh', 'cottr': 'PITTSBURGH PA', 'customer_minutes': 'Pittsburgh', 'market_tracker_id': 'PITTSBURGH PA', 'oem': 'Nokia', 'cohort': 2},
    'Portland': {'availability': 'Portland', 'cottr': 'PORTLAND OR', 'customer_minutes': 'Portland', 'market_tracker_id': 'PORTLAND OR', 'oem': 'Nokia', 'cohort': 2},
    'Puerto Rico': {'availability': 'Puerto Rico', 'cottr': 'PUERTO RICO', 'customer_minutes': 'Puerto Rico', 'market_tracker_id': 'PUERTO RICO', 'oem': 'Nokia', 'cohort': 3},
    'Seattle': {'availability': 'Seattle', 'cottr': 'SEATTLE WA', 'customer_minutes': 'Seattle', 'market_tracker_id': 'SEATTLE WA', 'oem': 'Nokia', 'cohort': 1},
    'Spokane': {'availability': 'Spokane', 'cottr': 'SPOKANE WA', 'customer_minutes': 'Spokane', 'market_tracker_id': 'SPOKANE WA', 'oem': 'Nokia', 'cohort': 2},
    'St. Louis': {'availability': 'St. Louis', 'cottr': 'ST. LOUIS', 'customer_minutes': 'St. Louis', 'market_tracker_id': 'ST. LOUIS', 'oem': 'Nokia', 'cohort': 1},
    'West Virginia': {'availability': 'West Virginia', 'cottr': 'WEST VIRGINIA', 'customer_minutes': 'West Virginia', 'market_tracker_id': 'WEST VIRGINIA', 'oem': 'Nokia', 'cohort': 3},
}

# Cohort lookup from CONSOLIDATED_MARKET_MAP (Global Market ID → Cohort)
# Cohorts: 1=Major Metro (25 markets), 2=Mid-Size (18 markets), 3=Smaller/Rural (16 markets)
MARKET_TO_COHORT_MAP = {k: v['cohort'] for k, v in CONSOLIDATED_MARKET_MAP.items()}

# Sub-market to Global Market ID mapping (for data that comes in with sub-market names)
SUB_MARKET_TO_GLOBAL = {
    # El Paso → Albuquerque
    'EL PASO': 'Albuquerque',
    'EL PASO TX': 'Albuquerque',
    'El Paso': 'Albuquerque',
    # Dakotas → Minneapolis
    'DAKOTAS': 'Minneapolis',
    'Dakotas': 'Minneapolis',
    # Tulsa → Oklahoma City
    'TULSA': 'Oklahoma City',
    'TULSA OK': 'Oklahoma City',
    'Tulsa': 'Oklahoma City',
    # Wichita → Oklahoma City
    'WICHITA': 'Oklahoma City',
    'WICHITA KS': 'Oklahoma City',
    'Wichita': 'Oklahoma City',
}

# Reverse lookup maps for quick conversion (database format → Global Market ID)
AVAIL_TO_CANONICAL = {v['availability'].upper(): k for k, v in CONSOLIDATED_MARKET_MAP.items()}
COTTR_TO_CANONICAL = {v['cottr'].upper(): k for k, v in CONSOLIDATED_MARKET_MAP.items()}
CM_TO_CANONICAL = {v['customer_minutes'].upper(): k for k, v in CONSOLIDATED_MARKET_MAP.items()}
TRACKER_TO_CANONICAL = {v['market_tracker_id'].upper(): k for k, v in CONSOLIDATED_MARKET_MAP.items()}

# Add sub-market mappings to reverse lookups (uppercase keys)
SUB_MARKET_UPPER = {k.upper(): v for k, v in SUB_MARKET_TO_GLOBAL.items()}

# Combined reverse lookup for any source format → Global Market ID
ALL_TO_CANONICAL = {}
ALL_TO_CANONICAL.update(AVAIL_TO_CANONICAL)
ALL_TO_CANONICAL.update(COTTR_TO_CANONICAL)
ALL_TO_CANONICAL.update(CM_TO_CANONICAL)
ALL_TO_CANONICAL.update(TRACKER_TO_CANONICAL)
ALL_TO_CANONICAL.update(SUB_MARKET_UPPER)

# Global Market ID to all MARKET_TRACKER IDs (includes sub-markets)
# When querying by Global Market ID, include all sub-market MARKET_TRACKER IDs
GLOBAL_MARKET_TO_TRACKER_IDS = {
    'Albuquerque': ['ALBUQUERQUE NM', 'EL PASO TX'],  # Includes El Paso
    'Minneapolis': ['MINNEAPOLIS MN', 'DAKOTAS'],      # Includes Dakotas
    'Oklahoma City': ['OKLAHOMA CITY OK', 'TULSA OK', 'WICHITA KS'],  # Includes Tulsa, Wichita
}

def get_market_tracker_ids_for_global_market(global_market_id):
    """Get all MARKET_TRACKER IDs for a Global Market ID (including sub-markets).
    Returns a list of MARKET_TRACKER IDs to use in SQL IN clauses.
    """
    if global_market_id in GLOBAL_MARKET_TO_TRACKER_IDS:
        return GLOBAL_MARKET_TO_TRACKER_IDS[global_market_id]
    elif global_market_id in CONSOLIDATED_MARKET_MAP:
        return [CONSOLIDATED_MARKET_MAP[global_market_id]['market_tracker_id']]
    return [global_market_id]  # Fallback

def get_canonical_market_name(market_name, source='availability'):
    """Convert any market name to canonical Global Market ID format.
    Handles sub-markets (El Paso→Albuquerque, Dakotas→Minneapolis, Tulsa/Wichita→Oklahoma City)
    
    Args:
        market_name: Market name in any format (e.g., "DALLAS TX", "Dallas", "dallas")
        source: Hint for which table the name came from ('availability', 'cottr', 'customer_minutes', 'any')
    
    Returns:
        Canonical Global Market ID (e.g., "Dallas")
    """
    if not market_name:
        return market_name
    market_upper = str(market_name).strip().upper()
    
    # First check if it's a sub-market that should roll up
    if market_upper in SUB_MARKET_UPPER:
        return SUB_MARKET_UPPER[market_upper]
    
    # Check ALL_TO_CANONICAL first (covers all sources)
    if market_upper in ALL_TO_CANONICAL:
        return ALL_TO_CANONICAL[market_upper]
    
    # Then check the source-specific mapping
    if source == 'availability':
        return AVAIL_TO_CANONICAL.get(market_upper, market_name)
    elif source == 'cottr':
        return COTTR_TO_CANONICAL.get(market_upper, market_name)
    elif source == 'customer_minutes':
        return CM_TO_CANONICAL.get(market_upper, market_name)
    
    return market_name

def normalize_market_column(df, column_name='MARKET_ID', source='any'):
    """Normalize market names in a DataFrame column to Global Market ID format.
    
    OPTIMIZED: Uses vectorized map() instead of apply() for 5-10x speedup.
    
    Args:
        df: pandas DataFrame
        column_name: Name of the column containing market names
        source: Hint for which table the data came from
    
    Returns:
        DataFrame with normalized market names
    """
    if df is None or df.empty or column_name not in df.columns:
        return df
    
    df = df.copy()
    
    # OPTIMIZATION: Use vectorized str.upper() + map() instead of apply()
    # This is 5-10x faster for large DataFrames
    upper_col = df[column_name].fillna('').str.upper()
    
    # Map using the combined lookup dictionary (fastest approach)
    mapped = upper_col.map(ALL_TO_CANONICAL)
    
    # For unmapped values, check sub-markets, then fall back to original
    unmapped_mask = mapped.isna() & df[column_name].notna()
    if unmapped_mask.any():
        # Check sub-market mappings
        sub_mapped = upper_col[unmapped_mask].map(SUB_MARKET_UPPER)
        mapped.loc[unmapped_mask] = sub_mapped.where(sub_mapped.notna(), df.loc[unmapped_mask, column_name])
    
    # Keep original nulls as null
    mapped = mapped.where(df[column_name].notna(), None)
    df[column_name] = mapped
    
    return df

# Legacy mapping for backward compatibility
# Key = Availability market name (case-insensitive lookup)
# Value = dict with 'cottr' and 'customer_minutes' mappings
MARKET_NAME_MAPPINGS = {
    canonical: {'cottr': data['cottr'], 'customer_minutes': data['customer_minutes']}
    for canonical, data in CONSOLIDATED_MARKET_MAP.items()
}

def normalize_cottr_market_name(cottr_market):
    """Normalize COTTR market names to match global market format (availability table format)
    Examples:
    - 'DETROIT MI' → 'DETROIT'
    - 'NEW ENGLAND MARKET' → 'NEW ENGLAND'
    - 'HOUSTON TX' → 'HOUSTON'
    - 'NY (UPSTATE)' → 'UPSTATE NY'
    """
    if not cottr_market:
        return cottr_market
    
    name = str(cottr_market).strip()
    
    # Remove common suffixes
    suffixes_to_remove = [' MARKET', ' MKT']
    for suffix in suffixes_to_remove:
        if name.upper().endswith(suffix):
            name = name[:-len(suffix)].strip()
    
    # Remove state abbreviations at the end (2 uppercase letters)
    # Common patterns: "DETROIT MI", "HOUSTON TX", "PHILADELPHIA PA"
    # Match pattern: word(s) followed by space and 2 uppercase letters at end
    state_pattern = re.compile(r'^(.+?)\s+([A-Z]{2})$')
    match = state_pattern.match(name.upper())
    if match:
        # Check if it's a state abbreviation (not part of the name like "LA" in "LA NORTH")
        potential_state = match.group(2)
        us_states = ['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID', 
                     'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 
                     'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 
                     'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 
                     'WI', 'WY', 'DC']
        base_name = match.group(1).strip()
        # Only remove if it looks like a state AND the base name is substantial
        if potential_state in us_states and len(base_name) > 2:
            name = base_name
    
    # Handle special cases
    special_mappings = {
        'NY (UPSTATE)': 'UPSTATE NY',
        'LA NORTH': 'LA NORTH',  # Keep as is (LA is Los Angeles, not Louisiana)
    }
    
    name_upper = name.upper()
    if name_upper in special_mappings:
        return special_mappings[name_upper]
    
    return name.upper()

def filters_to_hashable(filters):
    """Convert filters dict to a hashable tuple for caching"""
    if filters is None:
        return None
    result = []
    for k, v in sorted(filters.items()):
        if v is None:
            result.append((k, None))
        elif k in ('cohort_markets', 'market') and isinstance(v, (list, tuple)):
            # Convert list to tuple for hashability, mark with prefix for reconstruction
            result.append((k, ('__LIST__',) + tuple(v)))
        else:
            result.append((k, str(v)))
    return tuple(result)

def hashable_to_filters(filters_hash):
    """Convert hashable tuple back to filters dict"""
    if filters_hash is None:
        return None
    result = {}
    for k, v in filters_hash:
        if v is None:
            result[k] = None
        elif isinstance(v, tuple) and len(v) > 0 and v[0] == '__LIST__':
            # Reconstruct list from marked tuple
            result[k] = list(v[1:])
        else:
            result[k] = v
    return result

def get_session_cache_key(prefix, days, filters):
    """Generate a cache key for session state storage"""
    filters_hash = filters_to_hashable(filters)
    return f"{prefix}_{days}_{hash(filters_hash)}"

def preload_common_data(conn, days, filters):
    """
    Preload commonly used data into session state to avoid redundant queries.
    This runs once per filter change and caches results for all tabs.
    OPTIMIZED: Parallel execution on cold cache cuts load from ~20s to ~4-6s.
    All 12 Executive Summary queries are pre-warmed here.
    """
    cache_key = get_session_cache_key("preload", days, filters)
    
    if st.session_state.get('preload_cache_key') == cache_key:
        return
    
    st.session_state['preload_cache_key'] = cache_key
    
    filters_hash = filters_to_hashable(filters)
    
    # Executive Summary queries
    preload_fns = [
        lambda: get_combined_daily_data_cached(conn, days, filters_hash),
        lambda: get_focus_category_totals_cached(conn, days, filters_hash),
        lambda: get_focus_category_totals_cottr_cached(conn, days, filters_hash),
        lambda: get_market_totals_cached(conn, days, filters_hash),
        lambda: get_market_by_summary_category_cached(conn, days, filters_hash),
        lambda: get_market_by_focus_category_cached(conn, days, filters_hash),
        lambda: get_cottr_market_by_focus_category_cached(conn, days, filters_hash),
        lambda: get_cottr_by_summary_category_cached(conn, days, filters_hash),
        lambda: get_availability_with_downtime_by_summary_cached(conn, days, filters_hash),
        lambda: get_impacted_subs_by_market_cached(conn, days, filters_hash),
        lambda: get_impacted_subs_by_market_and_category_cached(conn, days, filters_hash),
        lambda: get_market_daily_availability_cached(conn, days, filters_hash),
    ]
    
    # Unavailability tab queries (derive params from filters)
    site_type = filters.get('site_type') if filters else 'Macro'
    sel_site_types = (site_type,) if site_type else ('Macro', 'Non-Macro')
    avail_filter = build_filter_clause(filters, 'availability')
    p_start = filters.get('start_date') if filters else None
    p_end = filters.get('end_date') if filters else None
    p_oem = filters.get('oem') if filters else None
    preload_fns.extend([
        lambda: get_unavailability_data(conn, p_start, p_end, days, sel_site_types, avail_filter, p_oem),
        lambda: get_unavailability_all_sites_data(conn, p_start, p_end, days, sel_site_types, avail_filter, p_oem),
    ])
    
    with ThreadPoolExecutor(max_workers=min(len(preload_fns), MAX_CONCURRENT_QUERIES)) as executor:
        futures = [executor.submit(fn) for fn in preload_fns]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_combined_daily_data_cached(_conn, days, filters_hash):
    """Cached version of get_combined_daily_data"""
    # Reconstruct filters from hash
    filters = hashable_to_filters(filters_hash)
    
    cm_filter = build_filter_clause(filters, 'customer_minutes')
    avail_filter = build_filter_clause(filters, 'availability')
    cottr_filter = build_filter_clause(filters, 'cottr')
    
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    oem_filter = filters.get('oem') if filters else None
    site_type = filters.get('site_type') if filters else None
    
    date_filter_cm = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_cottr = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Customer Minutes query - join with availability for site_type filtering
    site_type_join = ""
    site_type_join_condition = ""
    if site_type:
        site_type_sql = get_site_type_sql_filter(site_type)
        site_type_join = f"""
        INNER JOIN (
            SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
            WHERE {date_filter_avail} AND {site_type_sql}
        ) st_filter ON cm.SITE_ID = st_filter.SITE_ID"""
        site_type_join_condition = "cm."
        cm_filter = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
    
    if oem_filter:
        if site_type:
            cm_query = f"""
            SELECT 
                cm.LOCAL_DATE_PART as DATE_VALUE,
                SUM(cm.IMPACT_DURATION_IN_MINS) as CUSTOMER_MINUTES,
                SUM(cm.TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
            FROM {TABLES['customer_minutes']} cm
            {site_type_join}
            WHERE {date_filter_cm.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')} AND cm.OEM = '{oem_filter}'
            {cm_filter}
            GROUP BY cm.LOCAL_DATE_PART
            """
        else:
            cm_query = f"""
            SELECT 
                LOCAL_DATE_PART as DATE_VALUE,
                SUM(IMPACT_DURATION_IN_MINS) as CUSTOMER_MINUTES,
                SUM(TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
            FROM {TABLES['customer_minutes']}
            WHERE {date_filter_cm} AND OEM = '{oem_filter}'
            {cm_filter}
            GROUP BY LOCAL_DATE_PART
            """
    else:
        if site_type:
            cm_query = f"""
            SELECT 
                cm.LOCAL_DATE_PART as DATE_VALUE,
                SUM(cm.IMPACT_DURATION_IN_MINS) as CUSTOMER_MINUTES,
                SUM(cm.TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
            FROM {TABLES['customer_minutes']} cm
            {site_type_join}
            WHERE {date_filter_cm.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')}
            {cm_filter}
            GROUP BY cm.LOCAL_DATE_PART
            """
        else:
            cm_query = f"""
            SELECT 
                LOCAL_DATE_PART as DATE_VALUE,
                SUM(IMPACT_DURATION_IN_MINS) as CUSTOMER_MINUTES,
                SUM(TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
            FROM {TABLES['customer_minutes']}
            WHERE {date_filter_cm}
            {cm_filter}
            GROUP BY LOCAL_DATE_PART
            """
    
    # Availability query - join to MARKET_TRACKER for OEM
    # Get site type filter for availability
    site_type_filter_avail = get_site_type_sql_filter(site_type, 'a.') if oem_filter else get_site_type_sql_filter(site_type)
    
    if oem_filter:
        # Replace MARKET_ID with a.MARKET_ID in filter clause to avoid ambiguity
        avail_filter_aliased = avail_filter.replace('MARKET_ID', 'a.MARKET_ID') if avail_filter else ''
        avail_query = f"""
        SELECT 
            a.DATE_VALUE,
            SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
            SUM(a.TOTAL_AVAILABILITY_N) as TOTAL_AVAILABILITY_N,
            SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_AVAILABILITY_D,
            SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY_PCT
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter_avail}
          AND {site_type_filter_avail}
          AND mt.M_OEM = '{oem_filter}'
        {avail_filter_aliased}
        GROUP BY a.DATE_VALUE
        """
    else:
        avail_query = f"""
        SELECT 
            DATE_VALUE,
            SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
            SUM(TOTAL_AVAILABILITY_N) as TOTAL_AVAILABILITY_N,
            SUM(TOTAL_AVAILABILITY_D) as TOTAL_AVAILABILITY_D,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY_PCT
        FROM {TABLES['availability']}
        WHERE {date_filter_avail}
          AND {site_type_filter_avail}
        {avail_filter}
        GROUP BY DATE_VALUE
        """
    
    # COTTR query - join to MARKET_TRACKER for OEM
    if oem_filter:
        # Replace column refs with aliased versions to avoid ambiguity
        cottr_filter_aliased = cottr_filter.replace('MKT_NAME', 'c.MKT_NAME').replace('SITE_CD', 'c.SITE_CD') if cottr_filter else ''
        cottr_query = f"""
        SELECT 
            c.PER_DAY_LOCAL_DATE as DATE_VALUE,
            COUNT(*) as OUTAGE_COUNT,
            SUM(c.PER_DAY_OUTAGE_MINUTES) as OUTAGE_MINUTES
        FROM {TABLES['cottr']} c
        JOIN {TABLES['market_tracker']} mt ON UPPER(c.MKT_NAME) = UPPER(mt.MARKET_ID)
        WHERE {date_filter_cottr}
          AND c.SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
          AND c.SITE_CD NOT LIKE 'USC%'
          AND mt.M_OEM = '{oem_filter}'
        {cottr_filter_aliased}
        GROUP BY c.PER_DAY_LOCAL_DATE
        """
    else:
        cottr_query = f"""
        SELECT 
            PER_DAY_LOCAL_DATE as DATE_VALUE,
            COUNT(*) as OUTAGE_COUNT,
            SUM(PER_DAY_OUTAGE_MINUTES) as OUTAGE_MINUTES
        FROM {TABLES['cottr']}
        WHERE {date_filter_cottr}
          AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
          AND SITE_CD NOT LIKE 'USC%'
        {cottr_filter}
        GROUP BY PER_DAY_LOCAL_DATE
        """
    
    results = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_query, _conn, cm_query): 'cm',
            executor.submit(run_query, _conn, avail_query): 'avail',
            executor.submit(run_query, _conn, cottr_query): 'cottr',
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = pd.DataFrame()
    
    return results.get('cm', pd.DataFrame()), results.get('avail', pd.DataFrame()), results.get('cottr', pd.DataFrame())

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_focus_category_totals_cached(_conn, days, filters_hash):
    """Cached version of get_focus_category_totals"""
    filters = hashable_to_filters(filters_hash)
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    oem_filter = filters.get('oem') if filters else None
    site_type = filters.get('site_type') if filters else None
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    if oem_filter:
        avail_filter_aliased = avail_filter.replace('MARKET_ID', 'a.MARKET_ID') if avail_filter else ''
        site_type_filter = get_site_type_sql_filter(site_type, 'a.')
        query = f"""
        SELECT a.SITE_ID_FOCUS_CATEGORY, SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME, COUNT(DISTINCT a.SITE_ID) as SITE_COUNT
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter} AND mt.M_OEM = '{oem_filter}' {avail_filter_aliased}
        GROUP BY a.SITE_ID_FOCUS_CATEGORY
        ORDER BY TOTAL_DOWNTIME DESC
        """
    else:
        site_type_filter = get_site_type_sql_filter(site_type)
        query = f"""
        SELECT SITE_ID_FOCUS_CATEGORY, SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME, COUNT(DISTINCT SITE_ID) as SITE_COUNT
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY SITE_ID_FOCUS_CATEGORY
        ORDER BY TOTAL_DOWNTIME DESC
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_focus_category_totals_cottr_cached(_conn, days, filters_hash):
    """Cached version of get_focus_category_totals_cottr"""
    filters = hashable_to_filters(filters_hash)
    cottr_filter = build_filter_clause(filters, 'cottr')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    oem_filter = filters.get('oem') if filters else None
    date_filter = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    if oem_filter:
        # Replace column refs with aliased versions to avoid ambiguity
        cottr_filter_aliased = cottr_filter.replace('MKT_NAME', 'c.MKT_NAME').replace('SITE_CD', 'c.SITE_CD') if cottr_filter else ''
        query = f"""
        SELECT c.SITE_ID_FOCUS_CATEGORY, SUM(c.PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINUTES, COUNT(DISTINCT c.SITE_CD) as SITE_COUNT
        FROM {TABLES['cottr']} c
        JOIN {TABLES['market_tracker']} mt ON UPPER(c.MKT_NAME) = UPPER(mt.MARKET_ID)
        WHERE {date_filter.replace('LOCAL_START_TIMESTAMP', 'c.LOCAL_START_TIMESTAMP')} AND c.SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' AND c.SITE_CD NOT LIKE 'USC%' AND mt.M_OEM = '{oem_filter}' {cottr_filter_aliased}
        GROUP BY c.SITE_ID_FOCUS_CATEGORY
        ORDER BY TOTAL_OUTAGE_MINUTES DESC
        """
    else:
        query = f"""
        SELECT SITE_ID_FOCUS_CATEGORY, SUM(PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINUTES, COUNT(DISTINCT SITE_CD) as SITE_COUNT
        FROM {TABLES['cottr']}
        WHERE {date_filter} AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'  {cottr_filter}
        GROUP BY SITE_ID_FOCUS_CATEGORY
        ORDER BY TOTAL_OUTAGE_MINUTES DESC
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_market_totals_cached(_conn, days, filters_hash):
    """Cached version of get_market_totals"""
    filters = hashable_to_filters(filters_hash)
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Add OEM filter via join to MARKET_TRACKER if OEM is selected
    oem_filter = filters.get('oem') if filters else None
    if oem_filter:
        # Replace MARKET_ID with a.MARKET_ID in filter clause to avoid ambiguity
        avail_filter_aliased = avail_filter.replace('MARKET_ID', 'a.MARKET_ID') if avail_filter else ''
        site_type_filter = get_site_type_sql_filter(site_type, 'a.')
        query = f"""
        SELECT a.MARKET_ID, 
               SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
               SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY,
               SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_D,
               SUM(a.TOTAL_AVAILABILITY_D) * 0.0015 as SECONDS_BUDGET,
               SUM(a.TOTAL_DOWNTIME) - (SUM(a.TOTAL_AVAILABILITY_D) * 0.0015) as OVER_UNDER
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter} AND mt.M_OEM = '{oem_filter}' {avail_filter_aliased}
        GROUP BY a.MARKET_ID
        ORDER BY TOTAL_DOWNTIME DESC
        """
    else:
        site_type_filter = get_site_type_sql_filter(site_type)
        query = f"""
        SELECT MARKET_ID, 
               SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
               SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY,
               SUM(TOTAL_AVAILABILITY_D) as TOTAL_D,
               SUM(TOTAL_AVAILABILITY_D) * 0.0015 as SECONDS_BUDGET,
               SUM(TOTAL_DOWNTIME) - (SUM(TOTAL_AVAILABILITY_D) * 0.0015) as OVER_UNDER
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY MARKET_ID
        ORDER BY TOTAL_DOWNTIME DESC
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_market_by_summary_category_cached(_conn, days, filters_hash):
    """Cached version of get_market_by_summary_category"""
    filters = hashable_to_filters(filters_hash)
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Add OEM filter via join to MARKET_TRACKER if OEM is selected
    oem_filter = filters.get('oem') if filters else None
    if oem_filter:
        # Replace MARKET_ID with a.MARKET_ID in filter clause to avoid ambiguity
        avail_filter_aliased = avail_filter.replace('MARKET_ID', 'a.MARKET_ID') if avail_filter else ''
        site_type_filter = get_site_type_sql_filter(site_type, 'a.')
        query = f"""
        SELECT a.MARKET_ID, a.SITE_ID_SUMMARY_CATEGORY, SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter} AND mt.M_OEM = '{oem_filter}' {avail_filter_aliased}
        GROUP BY a.MARKET_ID, a.SITE_ID_SUMMARY_CATEGORY
        ORDER BY a.MARKET_ID, TOTAL_DOWNTIME DESC
        """
    else:
        site_type_filter = get_site_type_sql_filter(site_type)
        query = f"""
        SELECT MARKET_ID, SITE_ID_SUMMARY_CATEGORY, SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY MARKET_ID, SITE_ID_SUMMARY_CATEGORY
        ORDER BY MARKET_ID, TOTAL_DOWNTIME DESC
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_cottr_by_summary_category_cached(_conn, days, filters_hash):
    """Cached version of get_cottr_by_summary_category"""
    filters = hashable_to_filters(filters_hash)
    cottr_filter = build_filter_clause(filters, 'cottr')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    date_filter = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    query = f"""
    SELECT 
        PER_DAY_LOCAL_DATE as DATE_VALUE,
        COALESCE(SITE_ID_SUMMARY_CATEGORY, 'Uncategorized') as SITE_ID_SUMMARY_CATEGORY,
        SUM(PER_DAY_OUTAGE_MINUTES) as OUTAGE_MINUTES
    FROM {TABLES['cottr']}
    WHERE {date_filter}
      AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
      {cottr_filter}
    GROUP BY PER_DAY_LOCAL_DATE, COALESCE(SITE_ID_SUMMARY_CATEGORY, 'Uncategorized')
    ORDER BY PER_DAY_LOCAL_DATE
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL)
def get_market_abbreviation_cached(_conn, market):
    """Cached market abbreviation lookup"""
    if not market:
        return market
    
    query = f"""
    SELECT M_MARKET_ABBREVATION
    FROM BDM_NDW_MAGENTABUILT_REFERENCE_DB.MAGENTABUILT_REFERENCE.MARKET_TRACKER
    WHERE M_MARKET_ABBREVATION IS NOT NULL AND M_MARKET_ABBREVATION != ''
      AND (UPPER(TRIM(MARKET_ID)) = UPPER(TRIM('{market}'))
           OR UPPER('{market}') LIKE UPPER(TRIM(MARKET_ID)) || '%'
           OR UPPER(TRIM(MARKET_ID)) LIKE UPPER('{market}') || '%'
           OR UPPER(TRIM(MARKET_ID)) LIKE '%' || UPPER('{market}') || '%'
           OR UPPER('{market}') LIKE '%' || UPPER(TRIM(MARKET_ID)) || '%')
    LIMIT 1
    """
    try:
        result = run_query(_conn, query)
        if result is not None and not result.empty and pd.notna(result['M_MARKET_ABBREVATION'].iloc[0]):
            abbrev_val = str(result['M_MARKET_ABBREVATION'].iloc[0]).strip()
            if abbrev_val:
                return abbrev_val
    except:
        pass
    return market

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_impacted_subs_by_market_cached(_conn, days, filters_hash):
    """Cached version of get_impacted_subs_by_market"""
    filters = hashable_to_filters(filters_hash)
    cm_filter = build_filter_clause(filters, 'customer_minutes')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    date_filter = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    if site_type:
        cm_filter_aliased = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
        query = f"""
        SELECT 
            cm.MARKET,
            SUM(cm.TOTAL_IMPACTED_SUB_CNT) as TOTAL_IMPACTED_SUBS,
            SUM(cm.IMPACT_DURATION_IN_MINS) as TOTAL_CUSTOMER_MINUTES
        FROM {TABLES['customer_minutes']} cm
        INNER JOIN (
            SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
            WHERE {date_filter_avail} AND {get_site_type_sql_filter(site_type)}
        ) st ON cm.SITE_ID = st.SITE_ID
        WHERE {date_filter.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')}
          AND cm.MARKET IS NOT NULL
          {cm_filter_aliased}
        GROUP BY cm.MARKET
        ORDER BY TOTAL_IMPACTED_SUBS DESC
        """
    else:
        query = f"""
        SELECT 
            MARKET,
            SUM(TOTAL_IMPACTED_SUB_CNT) as TOTAL_IMPACTED_SUBS,
            SUM(IMPACT_DURATION_IN_MINS) as TOTAL_CUSTOMER_MINUTES
        FROM {TABLES['customer_minutes']}
        WHERE {date_filter}
          AND MARKET IS NOT NULL
          {cm_filter}
        GROUP BY MARKET
        ORDER BY TOTAL_IMPACTED_SUBS DESC
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_impacted_subs_by_market_and_category_cached(_conn, days, filters_hash):
    """Cached version of get_impacted_subs_by_market_and_category"""
    filters = hashable_to_filters(filters_hash)
    cm_filter = build_filter_clause(filters, 'customer_minutes')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    date_filter = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    if site_type:
        cm_filter_aliased = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
        query = f"""
        SELECT 
            cm.MARKET,
            cm.OEM as CATEGORY,
            SUM(cm.TOTAL_IMPACTED_SUB_CNT) as TOTAL_IMPACTED_SUBS
        FROM {TABLES['customer_minutes']} cm
        INNER JOIN (
            SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
            WHERE {date_filter_avail} AND {get_site_type_sql_filter(site_type)}
        ) st ON cm.SITE_ID = st.SITE_ID
        WHERE {date_filter.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')}
          AND cm.MARKET IS NOT NULL
          AND cm.OEM IS NOT NULL
          {cm_filter_aliased}
        GROUP BY cm.MARKET, cm.OEM
        ORDER BY cm.MARKET, TOTAL_IMPACTED_SUBS DESC
        """
    else:
        query = f"""
        SELECT 
            MARKET,
            OEM as CATEGORY,
            SUM(TOTAL_IMPACTED_SUB_CNT) as TOTAL_IMPACTED_SUBS
        FROM {TABLES['customer_minutes']}
        WHERE {date_filter}
          AND MARKET IS NOT NULL
          AND OEM IS NOT NULL
          {cm_filter}
        GROUP BY MARKET, OEM
        ORDER BY MARKET, TOTAL_IMPACTED_SUBS DESC
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_market_by_focus_category_cached(_conn, days, filters_hash):
    """Cached version of get_market_by_focus_category"""
    filters = hashable_to_filters(filters_hash)
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    oem_filter = filters.get('oem') if filters else None
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Handle OEM filter by joining with MARKET_TRACKER
    if oem_filter:
        site_type_filter = get_site_type_sql_filter(site_type, 'a.')
        avail_filter_aliased = avail_filter.replace('MARKET_ID', 'a.MARKET_ID').replace('SITE_ID', 'a.SITE_ID') if avail_filter else ''
        query = f"""
        SELECT a.MARKET_ID, a.SITE_ID_FOCUS_CATEGORY, SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter} AND a.SITE_ID_FOCUS_CATEGORY IS NOT NULL AND mt.M_OEM = '{oem_filter}' {avail_filter_aliased}
        GROUP BY a.MARKET_ID, a.SITE_ID_FOCUS_CATEGORY
        ORDER BY a.MARKET_ID, TOTAL_DOWNTIME DESC
        """
    else:
        site_type_filter = get_site_type_sql_filter(site_type)
        query = f"""
        SELECT MARKET_ID, SITE_ID_FOCUS_CATEGORY, SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} AND SITE_ID_FOCUS_CATEGORY IS NOT NULL {avail_filter}
        GROUP BY MARKET_ID, SITE_ID_FOCUS_CATEGORY
        ORDER BY MARKET_ID, TOTAL_DOWNTIME DESC
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_market_daily_availability_cached(_conn, days, filters_hash):
    """Cached version of get_market_daily_availability"""
    filters = hashable_to_filters(filters_hash)
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    oem_filter = filters.get('oem') if filters else None
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Handle OEM filter by joining with MARKET_TRACKER
    if oem_filter:
        site_type_filter = get_site_type_sql_filter(site_type, 'a.')
        avail_filter_aliased = avail_filter.replace('MARKET_ID', 'a.MARKET_ID').replace('SITE_ID', 'a.SITE_ID') if avail_filter else ''
        query = f"""
        SELECT 
            a.MARKET_ID,
            a.REGION_ID,
            a.DATE_VALUE,
            SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as DAILY_AVAILABILITY,
            SUM(a.TOTAL_DOWNTIME) as DAILY_DOWNTIME
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter} AND mt.M_OEM = '{oem_filter}' {avail_filter_aliased}
        GROUP BY a.MARKET_ID, a.REGION_ID, a.DATE_VALUE
        ORDER BY a.MARKET_ID, a.DATE_VALUE
        """
    else:
        site_type_filter = get_site_type_sql_filter(site_type)
        query = f"""
        SELECT 
            MARKET_ID,
            REGION_ID,
            DATE_VALUE,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as DAILY_AVAILABILITY,
            SUM(TOTAL_DOWNTIME) as DAILY_DOWNTIME
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY MARKET_ID, REGION_ID, DATE_VALUE
        ORDER BY MARKET_ID, DATE_VALUE
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_cottr_market_by_focus_category_cached(_conn, days, filters_hash):
    """Cached version of get_cottr_market_by_focus_category"""
    filters = hashable_to_filters(filters_hash)
    cottr_filter = build_filter_clause(filters, 'cottr')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    date_filter = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Add OEM filter via join to MARKET_TRACKER if OEM is selected
    oem_filter = filters.get('oem') if filters else None
    if oem_filter:
        # Replace column refs with aliased versions to avoid ambiguity
        cottr_filter_aliased = cottr_filter.replace('MKT_NAME', 'c.MKT_NAME').replace('SITE_CD', 'c.SITE_CD') if cottr_filter else ''
        date_filter_aliased = date_filter.replace('LOCAL_START_TIMESTAMP', 'c.LOCAL_START_TIMESTAMP')
        query = f"""
        SELECT 
            c.MKT_NAME as MARKET_ID,
            c.SITE_ID_FOCUS_CATEGORY,
            SUM(c.PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINUTES
        FROM {TABLES['cottr']} c
        JOIN {TABLES['market_tracker']} mt ON UPPER(c.MKT_NAME) = UPPER(mt.MARKET_ID)
        WHERE {date_filter_aliased}
          AND c.SITE_ID_FOCUS_CATEGORY IS NOT NULL
          AND c.SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
          AND c.SITE_CD NOT LIKE 'USC%'
          AND mt.M_OEM = '{oem_filter}'
          {cottr_filter_aliased}
        GROUP BY c.MKT_NAME, c.SITE_ID_FOCUS_CATEGORY
        ORDER BY c.MKT_NAME, TOTAL_OUTAGE_MINUTES DESC
        """
    else:
        query = f"""
        SELECT 
            MKT_NAME as MARKET_ID,
            SITE_ID_FOCUS_CATEGORY,
            SUM(PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINUTES
        FROM {TABLES['cottr']}
        WHERE {date_filter}
          AND SITE_ID_FOCUS_CATEGORY IS NOT NULL
          AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
          {cottr_filter}
        GROUP BY MKT_NAME, SITE_ID_FOCUS_CATEGORY
        ORDER BY MKT_NAME, TOTAL_OUTAGE_MINUTES DESC
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_availability_with_downtime_by_summary_cached(_conn, days, filters_hash):
    """Cached version of get_availability_with_downtime_by_summary"""
    filters = hashable_to_filters(filters_hash)
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    oem_filter = filters.get('oem') if filters else None
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Handle OEM filter by joining with MARKET_TRACKER
    if oem_filter:
        site_type_filter = get_site_type_sql_filter(site_type, 'a.')
        avail_filter_aliased = avail_filter.replace('MARKET_ID', 'a.MARKET_ID').replace('SITE_ID', 'a.SITE_ID') if avail_filter else ''
        avail_query = f"""
        SELECT 
            a.DATE_VALUE,
            SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY_PCT
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter} AND mt.M_OEM = '{oem_filter}'
        {avail_filter_aliased}
        GROUP BY a.DATE_VALUE
        ORDER BY a.DATE_VALUE
        """
        
        downtime_query = f"""
        SELECT 
            a.DATE_VALUE,
            a.SITE_ID_SUMMARY_CATEGORY,
            SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter} AND mt.M_OEM = '{oem_filter}'
          AND a.SITE_ID_SUMMARY_CATEGORY IS NOT NULL
          {avail_filter_aliased}
        GROUP BY a.DATE_VALUE, a.SITE_ID_SUMMARY_CATEGORY
        ORDER BY a.DATE_VALUE
        """
    else:
        site_type_filter = get_site_type_sql_filter(site_type)
        avail_query = f"""
        SELECT 
            DATE_VALUE,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY_PCT
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter}
        {avail_filter}
        GROUP BY DATE_VALUE
        ORDER BY DATE_VALUE
        """
        
        downtime_query = f"""
        SELECT 
            DATE_VALUE,
            SITE_ID_SUMMARY_CATEGORY,
            SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter}
          AND SITE_ID_SUMMARY_CATEGORY IS NOT NULL
          {avail_filter}
        GROUP BY DATE_VALUE, SITE_ID_SUMMARY_CATEGORY
        ORDER BY DATE_VALUE
        """
    
    avail_df = run_query(_conn, avail_query)
    downtime_df = run_query(_conn, downtime_query)
    return avail_df, downtime_df

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_top_sites_cottr_cached(_conn, days, filters_hash):
    """Cached version of top sites COTTR query for market selection"""
    filters = hashable_to_filters(filters_hash)
    cottr_filter = build_filter_clause(filters, 'cottr')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    oem_filter = filters.get('oem') if filters else None
    date_filter_cottr = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Handle OEM filter by joining with MARKET_TRACKER
    if oem_filter:
        query = f"""
        SELECT c.SITE_CD as SITE_ID, c.SITE_ID_SUMMARY_CATEGORY, c.SITE_ID_FOCUS_CATEGORY,
               SUM(c.PER_DAY_OUTAGE_MINUTES) as OUTAGE_MINUTES,
               COUNT(DISTINCT c.PER_DAY_LOCAL_DATE) as COTTR_OUTAGE_DAYS
        FROM {TABLES['cottr']} c
        JOIN {TABLES['market_tracker']} mt ON UPPER(c.MKT_NAME) = UPPER(mt.MARKET_ID)
        WHERE {date_filter_cottr.replace('LOCAL_START_TIMESTAMP', 'c.LOCAL_START_TIMESTAMP')} AND c.SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' AND c.SITE_CD NOT LIKE 'USC%' AND mt.M_OEM = '{oem_filter}' {cottr_filter.replace('SITE_CD', 'c.SITE_CD').replace('MKT_NAME', 'c.MKT_NAME')}
        GROUP BY c.SITE_CD, c.SITE_ID_SUMMARY_CATEGORY, c.SITE_ID_FOCUS_CATEGORY
        ORDER BY OUTAGE_MINUTES DESC
        LIMIT 200
        """
    else:
        query = f"""
        SELECT SITE_CD as SITE_ID, SITE_ID_SUMMARY_CATEGORY, SITE_ID_FOCUS_CATEGORY,
               SUM(PER_DAY_OUTAGE_MINUTES) as OUTAGE_MINUTES,
               COUNT(DISTINCT PER_DAY_LOCAL_DATE) as COTTR_OUTAGE_DAYS
        FROM {TABLES['cottr']}
        WHERE {date_filter_cottr} AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'  {cottr_filter}
        GROUP BY SITE_CD, SITE_ID_SUMMARY_CATEGORY, SITE_ID_FOCUS_CATEGORY
        ORDER BY OUTAGE_MINUTES DESC
        LIMIT 200
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_avail_days_and_vendor_cached(_conn, days, filters_hash):
    """Cached version of availability days and AAV vendor query"""
    filters = hashable_to_filters(filters_hash)
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    oem_filter = filters.get('oem') if filters else None
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Handle OEM filter by joining with MARKET_TRACKER
    if oem_filter:
        site_type_filter = get_site_type_sql_filter(site_type, 'a.')
        query = f"""
        SELECT a.SITE_ID, 
               COUNT(DISTINCT CASE WHEN a.TOTAL_DOWNTIME > 0 THEN a.DATE_VALUE END) as AVAIL_DOWNTIME_DAYS,
               MAX(a.MB_PRIMARY_AAV_VENDOR_NAME) as AAV_VENDOR
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter_avail.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter} AND mt.M_OEM = '{oem_filter}' {avail_filter.replace('MARKET_ID', 'a.MARKET_ID').replace('SITE_ID', 'a.SITE_ID')}
        GROUP BY a.SITE_ID
        """
    else:
        site_type_filter = get_site_type_sql_filter(site_type)
        query = f"""
        SELECT SITE_ID, 
               COUNT(DISTINCT CASE WHEN TOTAL_DOWNTIME > 0 THEN DATE_VALUE END) as AVAIL_DOWNTIME_DAYS,
               MAX(MB_PRIMARY_AAV_VENDOR_NAME) as AAV_VENDOR
        FROM {TABLES['availability']}
        WHERE {date_filter_avail} AND {site_type_filter} {avail_filter}
        GROUP BY SITE_ID
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_site_availability_cached(_conn, days, filters_hash):
    """Cached version of site-level availability query"""
    filters = hashable_to_filters(filters_hash)
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    oem_filter = filters.get('oem') if filters else None
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Handle OEM filter by joining with MARKET_TRACKER
    if oem_filter:
        site_type_filter = get_site_type_sql_filter(site_type, 'a.')
        query = f"""
        SELECT a.SITE_ID, 
               SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter_avail.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter} AND mt.M_OEM = '{oem_filter}' {avail_filter.replace('MARKET_ID', 'a.MARKET_ID').replace('SITE_ID', 'a.SITE_ID')}
        GROUP BY a.SITE_ID
        """
    else:
        site_type_filter = get_site_type_sql_filter(site_type)
        query = f"""
        SELECT SITE_ID, 
               SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY
        FROM {TABLES['availability']}
        WHERE {date_filter_avail} AND {site_type_filter} {avail_filter}
        GROUP BY SITE_ID
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_cottr_site_daily_cached(_conn, days, filters_hash):
    """Cached version of COTTR site daily data for sparklines"""
    filters = hashable_to_filters(filters_hash)
    cottr_filter = build_filter_clause(filters, 'cottr')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    oem_filter = filters.get('oem') if filters else None
    date_filter_cottr = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Handle OEM filter by joining with MARKET_TRACKER
    if oem_filter:
        query = f"""
        SELECT c.SITE_CD as SITE_ID, c.PER_DAY_LOCAL_DATE as DATE_VALUE, SUM(c.PER_DAY_OUTAGE_MINUTES) as DAILY_OUTAGE_MINS
        FROM {TABLES['cottr']} c
        JOIN {TABLES['market_tracker']} mt ON UPPER(c.MKT_NAME) = UPPER(mt.MARKET_ID)
        WHERE {date_filter_cottr.replace('LOCAL_START_TIMESTAMP', 'c.LOCAL_START_TIMESTAMP')} AND c.SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' AND c.SITE_CD NOT LIKE 'USC%' AND mt.M_OEM = '{oem_filter}' {cottr_filter.replace('SITE_CD', 'c.SITE_CD').replace('MKT_NAME', 'c.MKT_NAME')}
        GROUP BY c.SITE_CD, c.PER_DAY_LOCAL_DATE
        ORDER BY c.SITE_CD, c.PER_DAY_LOCAL_DATE
        """
    else:
        query = f"""
        SELECT SITE_CD as SITE_ID, PER_DAY_LOCAL_DATE as DATE_VALUE, SUM(PER_DAY_OUTAGE_MINUTES) as DAILY_OUTAGE_MINS
        FROM {TABLES['cottr']}
        WHERE {date_filter_cottr} AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'  {cottr_filter}
        GROUP BY SITE_CD, PER_DAY_LOCAL_DATE
        ORDER BY SITE_CD, PER_DAY_LOCAL_DATE
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_top_sites_avail_cached(_conn, days, filters_hash):
    """Cached version of top sites availability query for market selection"""
    filters = hashable_to_filters(filters_hash)
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    oem_filter = filters.get('oem') if filters else None
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    site_type_filter = get_site_type_sql_filter(site_type, 'a.')
    
    # Handle OEM filter by joining with MARKET_TRACKER
    if oem_filter:
        query = f"""
        SELECT a.SITE_ID, a.SITE_ID_SUMMARY_CATEGORY, a.SITE_ID_FOCUS_CATEGORY,
               SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
               SUM(a.TOTAL_AVAILABILITY_N) as TOTAL_N,
               SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_D,
               COUNT(DISTINCT CASE WHEN a.TOTAL_DOWNTIME > 0 THEN a.DATE_VALUE END) as AVAIL_DOWNTIME_DAYS,
               MAX(a.MB_PRIMARY_AAV_VENDOR_NAME) as AAV_VENDOR
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter_avail.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter} AND mt.M_OEM = '{oem_filter}' {avail_filter.replace('MARKET_ID', 'a.MARKET_ID').replace('SITE_ID', 'a.SITE_ID')}
        GROUP BY a.SITE_ID, a.SITE_ID_SUMMARY_CATEGORY, a.SITE_ID_FOCUS_CATEGORY
        ORDER BY TOTAL_DOWNTIME DESC
        LIMIT 200
        """
    else:
        site_type_filter_plain = get_site_type_sql_filter(site_type)
        query = f"""
        SELECT SITE_ID, SITE_ID_SUMMARY_CATEGORY, SITE_ID_FOCUS_CATEGORY,
               SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
               SUM(TOTAL_AVAILABILITY_N) as TOTAL_N,
               SUM(TOTAL_AVAILABILITY_D) as TOTAL_D,
               COUNT(DISTINCT CASE WHEN TOTAL_DOWNTIME > 0 THEN DATE_VALUE END) as AVAIL_DOWNTIME_DAYS,
               MAX(MB_PRIMARY_AAV_VENDOR_NAME) as AAV_VENDOR
        FROM {TABLES['availability']}
        WHERE {date_filter_avail} AND {site_type_filter_plain} {avail_filter}
        GROUP BY SITE_ID, SITE_ID_SUMMARY_CATEGORY, SITE_ID_FOCUS_CATEGORY
        ORDER BY TOTAL_DOWNTIME DESC
        LIMIT 200
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_cottr_days_cached(_conn, days, filters_hash):
    """Cached version of COTTR outage days per site"""
    filters = hashable_to_filters(filters_hash)
    cottr_filter = build_filter_clause(filters, 'cottr')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    oem_filter = filters.get('oem') if filters else None
    date_filter_cottr = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Handle OEM filter by joining with MARKET_TRACKER
    if oem_filter:
        query = f"""
        SELECT c.SITE_CD as SITE_ID, COUNT(DISTINCT c.PER_DAY_LOCAL_DATE) as COTTR_OUTAGE_DAYS
        FROM {TABLES['cottr']} c
        JOIN {TABLES['market_tracker']} mt ON UPPER(c.MKT_NAME) = UPPER(mt.MARKET_ID)
        WHERE {date_filter_cottr.replace('LOCAL_START_TIMESTAMP', 'c.LOCAL_START_TIMESTAMP')} AND c.SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' AND c.SITE_CD NOT LIKE 'USC%' AND mt.M_OEM = '{oem_filter}' {cottr_filter.replace('SITE_CD', 'c.SITE_CD').replace('MKT_NAME', 'c.MKT_NAME')}
        GROUP BY c.SITE_CD
        """
    else:
        query = f"""
        SELECT SITE_CD as SITE_ID, COUNT(DISTINCT PER_DAY_LOCAL_DATE) as COTTR_OUTAGE_DAYS
        FROM {TABLES['cottr']}
        WHERE {date_filter_cottr} AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'  {cottr_filter}
        GROUP BY SITE_CD
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_site_daily_avail_cached(_conn, days, filters_hash):
    """Cached version of site daily availability and downtime for sparklines"""
    filters = hashable_to_filters(filters_hash)
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    oem_filter = filters.get('oem') if filters else None
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Handle OEM filter by joining with MARKET_TRACKER
    if oem_filter:
        site_type_filter = get_site_type_sql_filter(site_type, 'a.')
        query = f"""
        SELECT a.SITE_ID, a.DATE_VALUE, 
               SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as DAILY_AVAILABILITY, 
               SUM(a.TOTAL_DOWNTIME) as DAILY_DOWNTIME
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter_avail.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter} AND mt.M_OEM = '{oem_filter}' {avail_filter.replace('MARKET_ID', 'a.MARKET_ID').replace('SITE_ID', 'a.SITE_ID')}
        GROUP BY a.SITE_ID, a.DATE_VALUE
        ORDER BY a.SITE_ID, a.DATE_VALUE
        """
    else:
        site_type_filter = get_site_type_sql_filter(site_type)
        query = f"""
        SELECT SITE_ID, DATE_VALUE, 
               SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as DAILY_AVAILABILITY, 
               SUM(TOTAL_DOWNTIME) as DAILY_DOWNTIME
        FROM {TABLES['availability']}
        WHERE {date_filter_avail} AND {site_type_filter} {avail_filter}
        GROUP BY SITE_ID, DATE_VALUE
        ORDER BY SITE_ID, DATE_VALUE
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL)
def get_market_list(_conn):
    """Get list of 59 Global Market IDs for filter dropdown with OEM"""
    # Return markets with OEM suffix for display: "Dallas (Ericsson)"
    markets_with_oem = []
    for market_id, data in CONSOLIDATED_MARKET_MAP.items():
        oem = data.get('oem', 'Unknown')
        markets_with_oem.append(f"{market_id} ({oem})")
    return sorted(markets_with_oem)

def extract_market_from_display(display_value):
    """Extract market ID from display format 'Market (OEM)' -> 'Market'"""
    if display_value and ' (' in display_value:
        return display_value.rsplit(' (', 1)[0]
    return display_value

@st.cache_data(ttl=DATA_CACHE_TTL)
def get_filter_options(_conn):
    """Get filter options for dropdowns - OPTIMIZED: run all queries in parallel"""
    def run_filter_query(query):
        try:
            cursor = _conn.cursor()
            cursor.execute(query)
            result = [row[0] for row in cursor.fetchall()]
            cursor.close()
            return result
        except:
            return []
    
    queries = {
        'outage_type': f"SELECT DISTINCT OUTAGE_TYPE FROM {TABLES['availability']} WHERE OUTAGE_TYPE IS NOT NULL ORDER BY OUTAGE_TYPE LIMIT 100",
        'focus_category': f"SELECT DISTINCT SITE_ID_FOCUS_CATEGORY FROM {TABLES['availability']} WHERE SITE_ID_FOCUS_CATEGORY IS NOT NULL ORDER BY SITE_ID_FOCUS_CATEGORY LIMIT 100",
        'vendor': f"SELECT DISTINCT VENDOR FROM {TABLES['availability']} WHERE VENDOR IS NOT NULL ORDER BY VENDOR LIMIT 100",
        'top_source': f"SELECT DISTINCT TOP_SOURCE_NAME FROM {TABLES['availability']} WHERE TOP_SOURCE_NAME IS NOT NULL ORDER BY TOP_SOURCE_NAME LIMIT 100",
    }
    
    filters = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(run_filter_query, query): key for key, query in queries.items()}
        for future in as_completed(futures):
            key = futures[future]
            filters[key] = future.result()
    
    return filters

# Spares data: env NETWORK_INSIGHTS_SPARES_XLSX, then repo-local filename, then legacy path
_here = os.path.dirname(os.path.abspath(__file__))
SPARES_FILE_PATH = (
    os.environ.get('NETWORK_INSIGHTS_SPARES_XLSX', '').strip()
    or next(
        (p for p in (
            os.path.join(_here, 'Spares_3.27.26.xlsx'),
            os.path.join(_here, 'spares_data.xlsx'),
        ) if os.path.isfile(p)),
        r"C:\Users\SRivera12\Cursor\query_execution_agent_sso_auth\snowflake_assistant\Spare Data\Spares_3.27.26.xlsx",
    )
)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def load_spares_data():
    """Load Spares data from Excel file"""
    try:
        if os.path.exists(SPARES_FILE_PATH):
            df = pd.read_excel(SPARES_FILE_PATH)
            # Ensure ORDER CREATE DATE is datetime
            if 'ORDER CREATE DATE' in df.columns:
                df['ORDER CREATE DATE'] = pd.to_datetime(df['ORDER CREATE DATE'], errors='coerce')
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        st.warning(f"Could not load Spares data: {e}")
        return pd.DataFrame()

def get_hardware_spares_data(conn, start_date, end_date, market_selection=None, site_type=None):
    """Get Spares data joined with Availability for Hardware focus categories"""
    # Load spares data
    spares_df = load_spares_data()
    if spares_df.empty:
        return pd.DataFrame()
    
    # Build market filter for availability query
    market_filter = ""
    if market_selection:
        if isinstance(market_selection, str):
            market_selection = [market_selection]
        all_avail_ids = []
        for m in market_selection:
            all_avail_ids.extend(get_market_ids_for_filter(m, 'availability'))
        all_avail_ids = list(dict.fromkeys(all_avail_ids))
        if len(all_avail_ids) == 1:
            market_filter = f" AND UPPER(MARKET_ID) = '{all_avail_ids[0].upper()}'"
        else:
            avail_list = "', '".join([m.upper() for m in all_avail_ids])
            market_filter = f" AND UPPER(MARKET_ID) IN ('{avail_list}')"
    
    # Build site type filter
    site_type_filter = ""
    if site_type == 'Non-Macro':
        site_type_filter = " AND (SITE_TYPE != 'Macro' OR SITE_TYPE IS NULL)"
    elif site_type and site_type != '(All)':
        site_type_filter = f" AND SITE_TYPE = '{site_type}'"
    
    extended_end_date = pd.Timestamp(end_date) + timedelta(days=1)
    extended_end_date_str = extended_end_date.strftime('%Y-%m-%d')
    
    hw_query = f"""
    SELECT DISTINCT a.TOP_RECORDID, a.SITE_ID, a.MARKET_ID, a.DATE_VALUE, a.SITE_ID_FOCUS_CATEGORY, a.TOTAL_DOWNTIME,
           COALESCE(mt1.M_OEM, mt2.M_OEM, mt3.M_OEM, mt4.M_OEM, 'Unknown') as OEM
    FROM {TABLES['availability']} a
    LEFT JOIN {TABLES['market_tracker']} mt1 ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt1.M_CAPITAL_MARKET)
    LEFT JOIN {TABLES['market_tracker']} mt2 ON UPPER(a.MARKET_ID) = UPPER(mt2.MARKET_ID)
    LEFT JOIN {TABLES['market_tracker']} mt3 ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(REPLACE(mt3.MARKET_ID, ' ', ''))
    LEFT JOIN {TABLES['market_tracker']} mt4 ON a.MARKET_ID ILIKE mt4.MARKET_ID || '%' OR mt4.MARKET_ID ILIKE a.MARKET_ID || '%'
    WHERE a.DATE_VALUE >= '{start_date}' AND a.DATE_VALUE <= '{extended_end_date_str}'
      AND a.SITE_ID_FOCUS_CATEGORY IN ('Hardware', 'Hardware - Antenna System')
      AND a.TOP_RECORDID IS NOT NULL
      {market_filter.replace('MARKET_ID', 'a.MARKET_ID').replace('SITE_TYPE', 'a.SITE_TYPE')}
      {site_type_filter.replace('SITE_TYPE', 'a.SITE_TYPE')}
    """
    
    try:
        hw_df = run_query(conn, hw_query)
        if hw_df.empty:
            return pd.DataFrame()
        
        # Normalize TOP_RECORDID for joining
        hw_df['TOP_RECORDID'] = hw_df['TOP_RECORDID'].astype(str).str.strip().str.upper()
        
        # Aggregate availability to one row per ticket to prevent duplicate spare rows
        # Capture both first and last outage dates for full-duration window
        hw_agg = hw_df.groupby('TOP_RECORDID').agg({
            'SITE_ID': 'first',
            'MARKET_ID': 'first',
            'DATE_VALUE': ['min', 'max'],
            'SITE_ID_FOCUS_CATEGORY': 'first',
            'TOTAL_DOWNTIME': 'sum',
            'OEM': 'first'
        }).reset_index()
        hw_agg.columns = ['TOP_RECORDID', 'SITE_ID', 'MARKET_ID', 'FIRST_OUTAGE_DATE', 'LAST_OUTAGE_DATE',
                          'SITE_ID_FOCUS_CATEGORY', 'TOTAL_DOWNTIME', 'OEM']
        
        # Filter spares to only those with TROUBLE TICKET matching Hardware outages
        spares_df['TROUBLE TICKET'] = spares_df['TROUBLE TICKET'].astype(str).str.strip().str.upper()
        
        # Join spares with aggregated hardware availability records (1 row per ticket)
        merged = spares_df.merge(
            hw_agg,
            left_on='TROUBLE TICKET',
            right_on='TOP_RECORDID',
            how='inner'
        )
        
        if not merged.empty and 'ORDER CREATE DATE' in merged.columns:
            merged['ORDER CREATE DATE'] = pd.to_datetime(merged['ORDER CREATE DATE'], errors='coerce')
        
        return merged
    except Exception as e:
        st.warning(f"Error fetching hardware spares: {e}")
        return pd.DataFrame()

def get_hardware_spares_cottr_data(conn, start_date, end_date, market_selection=None, site_type=None):
    """Get Spares data joined with COTTR for Hardware focus categories"""
    # Load spares data
    spares_df = load_spares_data()
    if spares_df.empty:
        return pd.DataFrame()
    
    # Build market filter for COTTR query
    market_filter = ""
    if market_selection:
        if isinstance(market_selection, str):
            market_selection = [market_selection]
        all_cottr_ids = []
        for m in market_selection:
            all_cottr_ids.extend(get_market_ids_for_filter(m, 'cottr'))
        all_cottr_ids = list(dict.fromkeys(all_cottr_ids))
        if len(all_cottr_ids) == 1:
            market_filter = f" AND UPPER(MKT_NAME) = '{all_cottr_ids[0].upper()}'"
        else:
            cottr_list = "', '".join([m.upper() for m in all_cottr_ids])
            market_filter = f" AND UPPER(MKT_NAME) IN ('{cottr_list}')"
    
    # Build site type filter for COTTR
    site_type_filter = ""
    if site_type == 'Non-Macro':
        site_type_filter = " AND (SECTOR_TYPE_CATEGORY != 'Macro' OR SECTOR_TYPE_CATEGORY IS NULL)"
    elif site_type and site_type != '(All)':
        site_type_filter = f" AND SECTOR_TYPE_CATEGORY = '{site_type}'"
    
    extended_end_date = pd.Timestamp(end_date) + timedelta(days=1)
    extended_end_date_str = extended_end_date.strftime('%Y-%m-%d')
    
    cottr_query = f"""
    SELECT DISTINCT c.TOP_RECORDID, c.SITE_CD as SITE_ID, c.MKT_NAME as MARKET_ID, c.PER_DAY_LOCAL_DATE as DATE_VALUE, 
           c.SITE_ID_FOCUS_CATEGORY, c.PER_DAY_OUTAGE_MINUTES as OUTAGE_MINUTES,
           COALESCE(mt1.M_OEM, mt2.M_OEM, mt3.M_OEM, mt4.M_OEM, 'Unknown') as OEM
    FROM {TABLES['cottr']} c
    LEFT JOIN {TABLES['market_tracker']} mt1 ON UPPER(c.MKT_NAME) = UPPER(mt1.MARKET_ID)
    LEFT JOIN {TABLES['market_tracker']} mt2 ON UPPER(REPLACE(c.MKT_NAME, ' ', '')) = UPPER(mt2.M_CAPITAL_MARKET)
    LEFT JOIN {TABLES['market_tracker']} mt3 ON UPPER(REPLACE(c.MKT_NAME, ' ', '')) = UPPER(REPLACE(mt3.MARKET_ID, ' ', ''))
    LEFT JOIN {TABLES['market_tracker']} mt4 ON c.MKT_NAME ILIKE mt4.MARKET_ID || '%' OR mt4.MARKET_ID ILIKE c.MKT_NAME || '%'
    WHERE c.PER_DAY_LOCAL_DATE >= '{start_date}' AND c.PER_DAY_LOCAL_DATE <= '{extended_end_date_str}'
      AND c.SITE_ID_FOCUS_CATEGORY IN ('Hardware', 'Hardware - Antenna System')
      AND c.SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
      AND c.TOP_RECORDID IS NOT NULL
      AND c.SITE_CD NOT LIKE 'USC%'
      {market_filter.replace('MKT_NAME', 'c.MKT_NAME').replace('SECTOR_TYPE_CATEGORY', 'c.SECTOR_TYPE_CATEGORY')}
      {site_type_filter.replace('SECTOR_TYPE_CATEGORY', 'c.SECTOR_TYPE_CATEGORY')}
    """
    
    try:
        cottr_df = run_query(conn, cottr_query)
        if cottr_df.empty:
            return pd.DataFrame()
        
        # Normalize TOP_RECORDID for joining
        cottr_df['TOP_RECORDID'] = cottr_df['TOP_RECORDID'].astype(str).str.strip().str.upper()
        
        # Aggregate COTTR to one row per ticket to prevent duplicate spare rows
        # Capture both first and last outage dates for full-duration window
        cottr_agg = cottr_df.groupby('TOP_RECORDID').agg({
            'SITE_ID': 'first',
            'MARKET_ID': 'first',
            'DATE_VALUE': ['min', 'max'],
            'SITE_ID_FOCUS_CATEGORY': 'first',
            'OUTAGE_MINUTES': 'sum',
            'OEM': 'first'
        }).reset_index()
        cottr_agg.columns = ['TOP_RECORDID', 'SITE_ID', 'MARKET_ID', 'FIRST_OUTAGE_DATE', 'LAST_OUTAGE_DATE',
                             'SITE_ID_FOCUS_CATEGORY', 'OUTAGE_MINUTES', 'OEM']
        
        # Filter spares to only those with TROUBLE TICKET matching COTTR outages
        spares_df['TROUBLE TICKET'] = spares_df['TROUBLE TICKET'].astype(str).str.strip().str.upper()
        
        # Join spares with aggregated COTTR records (1 row per ticket)
        merged = spares_df.merge(
            cottr_agg,
            left_on='TROUBLE TICKET',
            right_on='TOP_RECORDID',
            how='inner'
        )
        
        if not merged.empty and 'ORDER CREATE DATE' in merged.columns:
            merged['ORDER CREATE DATE'] = pd.to_datetime(merged['ORDER CREATE DATE'], errors='coerce')
        
        return merged
    except Exception as e:
        st.warning(f"Error fetching COTTR hardware spares: {e}")
        return pd.DataFrame()

# Query cache with TTL - uses session state to persist across reruns
QUERY_CACHE_TTL = DATA_CACHE_TTL  # Match the main cache TTL (24 hours)

def get_query_hash(query):
    """Generate a hash for the query string"""
    return hashlib.md5(query.encode()).hexdigest()

def get_query_cache():
    """Get or initialize the query cache from session state"""
    if 'query_cache' not in st.session_state:
        st.session_state['query_cache'] = {}
    if 'query_cache_timestamps' not in st.session_state:
        st.session_state['query_cache_timestamps'] = {}
    return st.session_state['query_cache'], st.session_state['query_cache_timestamps']

def run_query(_conn, query, use_cache=True):
    """Run query with caching, retry logic, and fetch_pandas_all for speed"""
    query_hash = get_query_hash(query)
    current_time = time.time()
    cache, timestamps = get_query_cache()
    
    if use_cache and query_hash in cache:
        cache_time = timestamps.get(query_hash, 0)
        if current_time - cache_time < QUERY_CACHE_TTL:
            return cache[query_hash]
    
    def execute_query(conn):
        cursor = conn.cursor()
        cursor.execute(query)
        try:
            df = cursor.fetch_pandas_all()
        except Exception:
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            df = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)
        finally:
            cursor.close()
        return df
    
    last_error = None
    for attempt in range(MAX_QUERY_RETRIES):
        try:
            df = execute_query(_conn)
            break
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            
            if IS_RUNNING_IN_SIS and ('invalid argument' in error_str or 'connection' in error_str or 'errno' in error_str):
                try:
                    from snowflake.snowpark.context import get_active_session
                    fresh_conn = get_active_session().connection
                    st.session_state['connection'] = fresh_conn
                    _conn = fresh_conn
                except Exception:
                    pass
            
            if attempt < MAX_QUERY_RETRIES - 1:
                time.sleep(QUERY_RETRY_DELAY * (attempt + 1))
            else:
                st.error(f"Query failed after {MAX_QUERY_RETRIES} attempts: {str(last_error)}")
                return pd.DataFrame()
    
    _NUMERIC_COLS = frozenset([
        'TOTAL_DOWNTIME', 'TOTAL_AVAILABILITY_N', 'TOTAL_AVAILABILITY_D', 
        'AVG_AVAILABILITY_PCT', 'CUSTOMER_MINUTES', 'IMPACTED_SUBS',
        'OUTAGE_COUNT', 'OUTAGE_MINUTES', 'TOTAL_OUTAGE_MINUTES',
        'TOTAL_OUTAGE_MINS', 'PER_DAY_OUTAGE_MINUTES', 'SITE_COUNT',
        'TOTAL_DOWNTIME_SECS', 'TOTAL_N', 'TOTAL_D', 'SITE_UNAVAIL_SECONDS',
        'COTTR_MINUTES', 'COTTR_DAYS', 'DAYS_WITH_DOWNTIME', 'COUNT_OF_TKTS',
        'DAILY_DOWNTIME', 'ORDER_COUNT', 'COUNT', 'SITES_AFFECTED',
        'PCT_OF_UNAVAIL', 'SITE_UNAVAIL_CONTRIBUTION', 'NEW_AVAIL_IF_FIXED',
        'DAYS_IMPACTED', 'OUTAGE_DAYS', 'UNAVAILABILITY_PCT',
    ])
    cols_to_convert = [col for col in df.columns if col in _NUMERIC_COLS]
    if cols_to_convert:
        df[cols_to_convert] = df[cols_to_convert].apply(pd.to_numeric, errors='coerce').fillna(0)
    
    if use_cache:
        cache[query_hash] = df
        timestamps[query_hash] = current_time
    
    return df

def clear_query_cache():
    """Clear the query cache"""
    if 'query_cache' in st.session_state:
        st.session_state['query_cache'] = {}
    if 'query_cache_timestamps' in st.session_state:
        st.session_state['query_cache_timestamps'] = {}

def get_mapped_market_name(market, table_type):
    """Get the mapped market name for COTTR/Customer Minutes tables"""
    if not market:
        return market
    
    # Check if there's a specific mapping for this market (case-insensitive lookup)
    mapping = None
    for key in MARKET_NAME_MAPPINGS:
        if key.upper() == market.upper():
            mapping = MARKET_NAME_MAPPINGS[key]
            break
    
    if mapping:
        # Return the table-specific mapping if available
        if isinstance(mapping, dict):
            return mapping.get(table_type, mapping.get('cottr', market))
        else:
            # Legacy format: single string value
            return mapping
    return market

def qualify_filter_clause(filter_clause, alias, table_type='availability'):
    """Add table alias to column names in a filter clause to avoid ambiguity in JOINs"""
    if not filter_clause:
        return filter_clause
    
    result = filter_clause
    if table_type == 'availability':
        columns = ['SITE_ID', 'MARKET_ID', 'OUTAGE_TYPE', 'VENDOR', 'SITE_ID_FOCUS_CATEGORY', 'TOP_SOURCE_NAME', 'DATE_VALUE', 'SITE_TYPE']
        for col in columns:
            result = result.replace(f' {col} ', f' {alias}.{col} ')
            result = result.replace(f' {col}=', f' {alias}.{col}=')
            result = result.replace(f'({col} ', f'({alias}.{col} ')
            result = result.replace(f' {col})', f' {alias}.{col})')
            if result.startswith(col + ' ') or result.startswith(col + '='):
                result = f'{alias}.' + result
    return result

def get_site_type_sql_filter(site_type, column_prefix=''):
    """
    Generate SQL filter for site type.
    Non-Macro means SITE_TYPE != 'Macro' (includes DAS, Micro, Pico, NULL, etc.)
    
    Args:
        site_type: 'Macro', 'Non-Macro', or None/(All)
        column_prefix: Optional prefix like 'a.' for aliased tables
    
    Returns:
        SQL condition string
    """
    col = f"{column_prefix}SITE_TYPE" if column_prefix else "SITE_TYPE"
    
    if not site_type or site_type == '(All)':
        return "1=1"
    elif site_type == 'Non-Macro':
        return f"({col} != 'Macro' OR {col} IS NULL)"
    else:
        return f"{col} = '{site_type}'"

def get_market_display_name(market_filter):
    """Get display name for market filter (single, multiple, or all).
    
    Returns:
    - Single market: market name
    - Multiple markets: "X markets"
    - No filter: None
    """
    if not market_filter:
        return None
    if isinstance(market_filter, str):
        return market_filter
    if len(market_filter) == 1:
        return market_filter[0]
    return f"{len(market_filter)} markets"

# ==================== DATA VALIDATION SYSTEM ====================
# Automated checks to flag data inconsistencies

class DataValidator:
    """Validates data accuracy and flags inconsistencies"""
    
    def __init__(self):
        self.warnings = []
        self.errors = []
        self.info = []
    
    def clear(self):
        """Clear all messages"""
        self.warnings = []
        self.errors = []
        self.info = []
    
    def add_warning(self, message, category="General"):
        """Add a warning message"""
        self.warnings.append({"category": category, "message": message})
    
    def add_error(self, message, category="General"):
        """Add an error message"""
        self.errors.append({"category": category, "message": message})
    
    def add_info(self, message, category="General"):
        """Add an info message"""
        self.info.append({"category": category, "message": message})
    
    def validate_percentage_range(self, df, column, name="Value"):
        """Check if percentage values are in valid range (0-100)"""
        if df is None or df.empty or column not in df.columns:
            return True
        invalid = df[(df[column] < 0) | (df[column] > 100)]
        if not invalid.empty:
            self.add_warning(f"{name}: {len(invalid)} values outside 0-100% range", "Data Range")
            return False
        return True
    
    def validate_non_negative(self, df, column, name="Value"):
        """Check if values are non-negative"""
        if df is None or df.empty or column not in df.columns:
            return True
        invalid = df[df[column] < 0]
        if not invalid.empty:
            self.add_warning(f"{name}: {len(invalid)} negative values found", "Data Range")
            return False
        return True
    
    def validate_totals_match(self, total_value, breakdown_df, breakdown_column, tolerance=0.01, name="Total"):
        """Check if total matches sum of breakdown"""
        if breakdown_df is None or breakdown_df.empty or breakdown_column not in breakdown_df.columns:
            return True
        breakdown_sum = breakdown_df[breakdown_column].sum()
        if total_value == 0 and breakdown_sum == 0:
            return True
        if total_value == 0:
            self.add_warning(f"{name}: Total is 0 but breakdown sum is {breakdown_sum:,.0f}", "Data Consistency")
            return False
        diff_pct = abs(total_value - breakdown_sum) / total_value
        if diff_pct > tolerance:
            self.add_warning(f"{name}: Total ({total_value:,.0f}) differs from breakdown sum ({breakdown_sum:,.0f}) by {diff_pct*100:.1f}%", "Data Consistency")
            return False
        return True
    
    def validate_category_percentages_sum(self, df, pct_column, group_column=None, tolerance=1.0, name="Categories"):
        """Check if category percentages sum to ~100% (per group if grouped)"""
        if df is None or df.empty or pct_column not in df.columns:
            return True
        
        if group_column and group_column in df.columns:
            # Check per group
            issues = []
            for group, group_df in df.groupby(group_column):
                pct_sum = group_df[pct_column].sum()
                if abs(pct_sum - 100) > tolerance:
                    issues.append(f"{group}: {pct_sum:.1f}%")
            if issues:
                self.add_warning(f"{name}: Percentages don't sum to 100% for: {', '.join(issues[:3])}{'...' if len(issues) > 3 else ''}", "Data Consistency")
                return False
        else:
            # Check overall
            pct_sum = df[pct_column].sum()
            if abs(pct_sum - 100) > tolerance:
                self.add_warning(f"{name}: Percentages sum to {pct_sum:.1f}% (expected ~100%)", "Data Consistency")
                return False
        return True
    
    def validate_no_duplicates(self, df, key_columns, name="Data"):
        """Check for duplicate rows based on key columns"""
        if df is None or df.empty:
            return True
        if isinstance(key_columns, str):
            key_columns = [key_columns]
        for col in key_columns:
            if col not in df.columns:
                return True
        duplicates = df[df.duplicated(subset=key_columns, keep=False)]
        if not duplicates.empty:
            self.add_warning(f"{name}: {len(duplicates)} duplicate rows found on {key_columns}", "Data Quality")
            return False
        return True
    
    def validate_date_range_logic(self, shorter_value, longer_value, shorter_days, longer_days, name="Value"):
        """Check that shorter date range has fewer/equal totals than longer range"""
        if shorter_value is None or longer_value is None:
            return True
        if shorter_value > longer_value * 1.05:  # 5% tolerance for timing differences
            self.add_warning(f"{name}: {shorter_days}-day value ({shorter_value:,.0f}) > {longer_days}-day value ({longer_value:,.0f})", "Data Logic")
            return False
        return True
    
    def validate_filter_reduces_data(self, unfiltered_count, filtered_count, filter_name):
        """Check that applying a filter reduces or maintains data count"""
        if unfiltered_count is None or filtered_count is None:
            return True
        if filtered_count > unfiltered_count:
            self.add_warning(f"Filter '{filter_name}': Filtered count ({filtered_count}) > unfiltered ({unfiltered_count})", "Filter Logic")
            return False
        return True
    
    def validate_market_names(self, df, column, name="Markets"):
        """Check if all market names are valid Global Market IDs (59 canonical names).
        
        This validates that market normalization is working correctly.
        Unknown markets indicate a new market name that needs to be added to CONSOLIDATED_MARKET_MAP.
        """
        if df is None or df.empty or column not in df.columns:
            return True
        
        # Get the 59 canonical Global Market IDs
        valid_markets = set(CONSOLIDATED_MARKET_MAP.keys())
        
        # Get unique markets in the data (excluding None/NaN)
        data_markets = set(df[column].dropna().unique())
        
        # Find markets not in the valid list
        unknown_markets = data_markets - valid_markets
        
        # Filter out obvious non-markets (empty strings, 'Unknown', etc.)
        unknown_markets = {m for m in unknown_markets if m and str(m).strip() and str(m).strip().lower() not in ('unknown', 'n/a', 'none', '')}
        
        if unknown_markets:
            # Show first 5 unknown markets
            sample = sorted(list(unknown_markets))[:5]
            more = f" (+{len(unknown_markets)-5} more)" if len(unknown_markets) > 5 else ""
            self.add_warning(
                f"{name}: {len(unknown_markets)} market name(s) not in Global Market ID list: {sample}{more}. "
                f"Add to CONSOLIDATED_MARKET_MAP if this is a new market.", 
                "Market Normalization"
            )
            return False
        return True
    
    def validate_data_source_markets(self, df, column, source_name, expected_source_type):
        """Validate that a new data source's market names can be mapped to Global Market IDs.
        
        Use this when adding a new Snowflake table to verify market name compatibility.
        
        Args:
            df: DataFrame with market data
            column: Column containing market names
            source_name: Name of the data source (e.g., "NEW_AVAILABILITY_TABLE")
            expected_source_type: Type hint for mapping ('availability', 'cottr', 'customer_minutes')
        """
        if df is None or df.empty or column not in df.columns:
            return True
        
        # Get unique markets in the data
        data_markets = df[column].dropna().unique()
        
        unmapped = []
        for market in data_markets:
            if not market or not str(market).strip():
                continue
            market_upper = str(market).strip().upper()
            # Try to find in ALL_TO_CANONICAL
            if market_upper not in ALL_TO_CANONICAL:
                unmapped.append(str(market))
        
        if unmapped:
            sample = unmapped[:10]
            more = f" (+{len(unmapped)-10} more)" if len(unmapped) > 10 else ""
            self.add_error(
                f"NEW TABLE '{source_name}': {len(unmapped)} market name(s) cannot be mapped to Global Market IDs: {sample}{more}. "
                f"These need to be added to CONSOLIDATED_MARKET_MAP with '{expected_source_type}' key.",
                "New Data Source"
            )
            return False
        
        self.add_info(f"✓ '{source_name}': All {len(data_markets)} market names can be mapped to Global Market IDs.", "New Data Source")
        return True
    
    def display_messages(self, show_info=False):
        """Display all validation messages in Streamlit"""
        if self.errors:
            for err in self.errors:
                st.error(f"❌ [{err['category']}] {err['message']}")
        if self.warnings:
            with st.expander(f"⚠️ Data Validation: {len(self.warnings)} warning(s)", expanded=False):
                for warn in self.warnings:
                    st.warning(f"[{warn['category']}] {warn['message']}")
        if show_info and self.info:
            for info in self.info:
                st.info(f"ℹ️ [{info['category']}] {info['message']}")
    
    def has_issues(self):
        """Check if any warnings or errors exist"""
        return len(self.warnings) > 0 or len(self.errors) > 0
    
    def get_summary(self):
        """Get summary of validation results"""
        return {
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "info": len(self.info)
        }

# Global validator instance
data_validator = DataValidator()

def validate_executive_summary_data(cm_daily, avail_daily, cottr_daily, focus_cat_totals, market_by_cat):
    """Validate Executive Summary dashboard data"""
    data_validator.clear()
    
    # Validate availability percentages are in range
    if not avail_daily.empty and 'AVG_AVAILABILITY_PCT' in avail_daily.columns:
        data_validator.validate_percentage_range(avail_daily, 'AVG_AVAILABILITY_PCT', "Daily Availability %")
    
    # Validate downtime is non-negative
    if not avail_daily.empty and 'TOTAL_DOWNTIME' in avail_daily.columns:
        data_validator.validate_non_negative(avail_daily, 'TOTAL_DOWNTIME', "Daily Downtime")
    
    # Validate focus category totals match daily totals
    if not avail_daily.empty and not focus_cat_totals.empty:
        if 'TOTAL_DOWNTIME' in avail_daily.columns and 'TOTAL_DOWNTIME' in focus_cat_totals.columns:
            daily_total = avail_daily['TOTAL_DOWNTIME'].sum()
            data_validator.validate_totals_match(daily_total, focus_cat_totals, 'TOTAL_DOWNTIME', 0.05, "Downtime Total vs Categories")
    
    # Validate market breakdown sums match
    if not market_by_cat.empty and 'TOTAL_DOWNTIME' in market_by_cat.columns:
        data_validator.validate_non_negative(market_by_cat, 'TOTAL_DOWNTIME', "Market Downtime")
    
    # Validate COTTR data
    if not cottr_daily.empty:
        if 'OUTAGE_MINUTES' in cottr_daily.columns:
            data_validator.validate_non_negative(cottr_daily, 'OUTAGE_MINUTES', "COTTR Outage Minutes")
        if 'OUTAGE_COUNT' in cottr_daily.columns:
            data_validator.validate_non_negative(cottr_daily, 'OUTAGE_COUNT', "COTTR Outage Count")
    
    # Validate customer minutes data
    if not cm_daily.empty:
        if 'CUSTOMER_MINUTES' in cm_daily.columns:
            data_validator.validate_non_negative(cm_daily, 'CUSTOMER_MINUTES', "Customer Minutes")
        if 'IMPACTED_SUBS' in cm_daily.columns:
            data_validator.validate_non_negative(cm_daily, 'IMPACTED_SUBS', "Impacted Subscribers")
    
    return data_validator

def validate_market_comparison_data(market_by_cat, cottr_market_by_cat):
    """Validate Market Comparison chart data"""
    
    # Validate market names are normalized (instead of duplicate check which happens before aggregation)
    if not market_by_cat.empty and 'MARKET_ID' in market_by_cat.columns:
        data_validator.validate_market_names(market_by_cat, 'MARKET_ID', "Availability Markets")
    
    if not cottr_market_by_cat.empty and 'MARKET_ID' in cottr_market_by_cat.columns:
        data_validator.validate_market_names(cottr_market_by_cat, 'MARKET_ID', "COTTR Markets")
    
    return data_validator

def validate_site_scatter_data(avail_sites, cottr_sites):
    """Validate Availability vs COTTR scatter chart data"""
    
    if not avail_sites.empty:
        if 'TOTAL_DOWNTIME' in avail_sites.columns:
            data_validator.validate_non_negative(avail_sites, 'TOTAL_DOWNTIME', "Site Availability Downtime")
    
    if not cottr_sites.empty:
        if 'OUTAGE_MINUTES' in cottr_sites.columns:
            data_validator.validate_non_negative(cottr_sites, 'OUTAGE_MINUTES', "Site COTTR Minutes")
    
    return data_validator

# ==================== END DATA VALIDATION SYSTEM ====================

def is_single_market_selected(market_filter):
    """Check if exactly one market is selected (for conditional UI logic)."""
    if not market_filter:
        return False
    if isinstance(market_filter, str):
        return True
    return len(market_filter) == 1

def get_first_market(market_filter):
    """Get first market from filter (for single-market specific logic)."""
    if not market_filter:
        return None
    if isinstance(market_filter, str):
        return market_filter
    return market_filter[0] if market_filter else None

def get_market_ids_for_filter(global_market_id, table_type='availability'):
    """Get all database market IDs for a Global Market ID (including sub-markets).
    
    OPTIMIZED: Results are memoized for speed since this is called frequently.
    
    For example:
    - 'Albuquerque' returns ['Albuquerque', 'El Paso'] for availability
    - 'Oklahoma City' returns ['OKLAHOMA CITY OK', 'TULSA OK', 'WICHITA KS'] for cottr
    """
    # OPTIMIZATION: Check memoization cache first
    cache_key = (global_market_id, table_type)
    if cache_key in _market_ids_cache:
        return _market_ids_cache[cache_key]
    
    if global_market_id not in CONSOLIDATED_MARKET_MAP:
        result = [global_market_id]
        _market_ids_cache[cache_key] = result
        return result
    
    # Get the primary market ID for this table type
    market_data = CONSOLIDATED_MARKET_MAP[global_market_id]
    if table_type == 'availability':
        primary_id = market_data['availability']
    elif table_type == 'cottr':
        primary_id = market_data['cottr']
    elif table_type == 'customer_minutes':
        primary_id = market_data['customer_minutes']
    else:
        primary_id = market_data['market_tracker_id']
    
    market_ids = [primary_id]
    
    # Check if this Global Market ID has sub-markets that roll up
    if global_market_id in GLOBAL_MARKET_TO_TRACKER_IDS:
        # For markets with sub-markets, include all sub-market IDs
        tracker_ids = GLOBAL_MARKET_TO_TRACKER_IDS[global_market_id]
        for tracker_id in tracker_ids:
            # Find the sub-market's ID for this table type
            for sub_market, sub_data in CONSOLIDATED_MARKET_MAP.items():
                if sub_data['market_tracker_id'] == tracker_id and sub_market != global_market_id:
                    if table_type == 'availability':
                        market_ids.append(sub_data['availability'])
                    elif table_type == 'cottr':
                        market_ids.append(sub_data['cottr'])
                    elif table_type == 'customer_minutes':
                        market_ids.append(sub_data['customer_minutes'])
    
    # Remove duplicates and filter out None/empty values
    seen = set()
    unique_ids = []
    for mid in market_ids:
        if mid and mid not in seen:
            seen.add(mid)
            unique_ids.append(mid)
    
    result = unique_ids if unique_ids else [global_market_id]
    _market_ids_cache[cache_key] = result
    return result

def build_market_sql_filter(market, table_type='availability', column_name='MARKET_ID', alias=''):
    """OPTIMIZED: Build SQL market filter clause for single or multiple markets.
    
    This is a fast helper that consolidates multi-market handling logic.
    Results are memoized for repeated calls with same parameters.
    """
    if not market:
        return ""
    
    # Create cache key
    if isinstance(market, list):
        cache_key = (tuple(market), table_type, column_name, alias)
    else:
        cache_key = (market, table_type, column_name, alias)
    
    # Check cache
    if cache_key in _filter_clause_cache:
        return _filter_clause_cache[cache_key]
    
    # Build the filter
    col = f"{alias}{column_name}" if alias else column_name
    
    if isinstance(market, str):
        market_list = [market]
    else:
        market_list = list(market)
    
    # Get all market IDs (uses memoized get_market_ids_for_filter)
    all_ids = []
    for m in market_list:
        if m:
            all_ids.extend(get_market_ids_for_filter(m, table_type))
    
    # Dedupe and filter empties
    all_ids = [mid for mid in dict.fromkeys(all_ids) if mid]
    
    if not all_ids:
        result = ""
    elif len(all_ids) == 1:
        result = f" AND UPPER({col}) = '{all_ids[0].upper()}'"
    else:
        id_list = "', '".join([mid.upper() for mid in all_ids])
        result = f" AND UPPER({col}) IN ('{id_list}')"
    
    _filter_clause_cache[cache_key] = result
    return result

def build_filter_clause(filters, table_type='availability'):
    """Build SQL WHERE clause from filters dict using Global Market ID mapping"""
    clauses = []
    
    # Global filters that always apply (even if no other filters)
    if table_type == 'customer_minutes':
        # Always exclude sites starting with 'USC'
        clauses.append("SITE_ID NOT LIKE 'USC%'")
    elif table_type == 'cottr':
        # Always exclude sites starting with 'USC'
        clauses.append("SITE_CD NOT LIKE 'USC%'")
    
    if not filters:
        return " AND " + " AND ".join(clauses) if clauses else ""
    
    if table_type == 'availability':
        if filters.get('market'):
            # Handle both single market (string) and multiple markets (list)
            market_selection = filters['market']
            if isinstance(market_selection, str):
                market_selection = [market_selection]
            
            # Collect all market IDs for all selected markets
            all_market_ids = []
            for market in market_selection:
                if market:  # Skip None/empty
                    all_market_ids.extend(get_market_ids_for_filter(market, 'availability'))
            # Remove duplicates and empty values
            all_market_ids = [m for m in dict.fromkeys(all_market_ids) if m]
            
            if all_market_ids:
                if len(all_market_ids) == 1:
                    clauses.append(f"UPPER(MARKET_ID) = '{all_market_ids[0].upper()}'")
                else:
                    # Uppercase all values for case-insensitive IN clause
                    market_list = "', '".join([m.upper() for m in all_market_ids])
                    clauses.append(f"UPPER(MARKET_ID) IN ('{market_list}')")
        if filters.get('site'):
            clauses.append(f"SITE_ID = '{filters['site']}'")
        if filters.get('outage_type'):
            clauses.append(f"OUTAGE_TYPE = '{filters['outage_type']}'")
        if filters.get('vendor'):
            clauses.append(f"VENDOR = '{filters['vendor']}'")
        if filters.get('focus_category'):
            clauses.append(f"SITE_ID_FOCUS_CATEGORY = '{filters['focus_category']}'")
        if filters.get('top_source'):
            clauses.append(f"TOP_SOURCE_NAME = '{filters['top_source']}'")
        # Note: site_type is handled separately in query functions to support Non-Macro = SITE_TYPE != 'Macro'
        # OEM/Cohort filter - apply market list
        if filters.get('cohort_markets') and not filters.get('market'):
            market_list = "', '".join(filters['cohort_markets'])
            clauses.append(f"MARKET_ID IN ('{market_list}')")
    elif table_type == 'customer_minutes':
        if filters.get('market'):
            # Handle both single market (string) and multiple markets (list)
            market_selection = filters['market']
            if isinstance(market_selection, str):
                market_selection = [market_selection]
            
            # Collect all market IDs for all selected markets
            all_market_ids = []
            for market in market_selection:
                if market:  # Skip None/empty
                    all_market_ids.extend(get_market_ids_for_filter(market, 'customer_minutes'))
            # Remove duplicates and empty values
            all_market_ids = [m for m in dict.fromkeys(all_market_ids) if m]
            
            if all_market_ids:
                if len(all_market_ids) == 1:
                    clauses.append(f"UPPER(MARKET) = '{all_market_ids[0].upper()}'")
                else:
                    # Uppercase all values for case-insensitive IN clause
                    market_list = "', '".join([m.upper() for m in all_market_ids])
                    clauses.append(f"UPPER(MARKET) IN ('{market_list}')")
        if filters.get('site'):
            clauses.append(f"SITE_ID = '{filters['site']}'")
        # Note: OEM filter is handled explicitly in query functions that need it
        # Customer_minutes table has OEM column but queries handle it directly
    elif table_type == 'cottr':
        if filters.get('market'):
            # Handle both single market (string) and multiple markets (list)
            market_selection = filters['market']
            if isinstance(market_selection, str):
                market_selection = [market_selection]
            
            # Collect all market IDs for all selected markets
            all_market_ids = []
            for market in market_selection:
                if market:  # Skip None/empty
                    all_market_ids.extend(get_market_ids_for_filter(market, 'cottr'))
            # Remove duplicates and empty values
            all_market_ids = [m for m in dict.fromkeys(all_market_ids) if m]
            
            if all_market_ids:
                if len(all_market_ids) == 1:
                    clauses.append(f"UPPER(MKT_NAME) = '{all_market_ids[0].upper()}'")
                else:
                    # Uppercase all values for case-insensitive IN clause
                    market_list = "', '".join([m.upper() for m in all_market_ids])
                    clauses.append(f"UPPER(MKT_NAME) IN ('{market_list}')")
        if filters.get('site'):
            clauses.append(f"SITE_CD = '{filters['site']}'")
        if filters.get('focus_category'):
            clauses.append(f"SITE_ID_FOCUS_CATEGORY = '{filters['focus_category']}'")
        if filters.get('vendor'):
            clauses.append(f"OEM = '{filters['vendor']}'")
        if filters.get('site_type'):
            site_type = filters['site_type']
            if site_type == 'Non-Macro':
                clauses.append("(SECTOR_TYPE_CATEGORY != 'Macro' OR SECTOR_TYPE_CATEGORY IS NULL)")
            elif site_type != '(All)':
                clauses.append(f"SECTOR_TYPE_CATEGORY = '{site_type}'")
        # OEM/Cohort filter - apply market list (MKT_NAME matches MARKET_ID in MARKET_TRACKER)
        if filters.get('cohort_markets') and not filters.get('market'):
            market_list = "', '".join(filters['cohort_markets'])
            clauses.append(f"MKT_NAME IN ('{market_list}')")
    
    return " AND " + " AND ".join(clauses) if clauses else ""

def get_cottr_by_focus_category(conn, days=7, filters=None):
    """Get COTTR outage minutes by focus category daily"""
    cottr_filter = build_filter_clause(filters, 'cottr')
    
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    date_filter = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    query = f"""
    SELECT 
        PER_DAY_LOCAL_DATE as DATE_VALUE,
        COALESCE(SITE_ID_FOCUS_CATEGORY, 'Uncategorized') as SITE_ID_FOCUS_CATEGORY,
        SUM(PER_DAY_OUTAGE_MINUTES) as OUTAGE_MINUTES
    FROM {TABLES['cottr']}
    WHERE {date_filter}
      AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
      {cottr_filter}
    GROUP BY PER_DAY_LOCAL_DATE, COALESCE(SITE_ID_FOCUS_CATEGORY, 'Uncategorized')
    ORDER BY PER_DAY_LOCAL_DATE
    """
    return run_query(conn, query)

def get_customer_minutes_daily(conn, days=7, filters=None):
    """Get daily impacted subscribers from customer minutes"""
    cm_filter = build_filter_clause(filters, 'customer_minutes')
    
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    date_filter = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    if site_type:
        cm_filter_aliased = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
        query = f"""
        SELECT 
            cm.LOCAL_DATE_PART as DATE_VALUE,
            SUM(cm.TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
        FROM {TABLES['customer_minutes']} cm
        INNER JOIN (
            SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
            WHERE {date_filter_avail} AND {get_site_type_sql_filter(site_type)}
        ) st ON cm.SITE_ID = st.SITE_ID
        WHERE {date_filter.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')}
        {cm_filter_aliased}
        GROUP BY cm.LOCAL_DATE_PART
        ORDER BY cm.LOCAL_DATE_PART
        """
    else:
        query = f"""
        SELECT 
            LOCAL_DATE_PART as DATE_VALUE,
            SUM(TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
        FROM {TABLES['customer_minutes']}
        WHERE {date_filter}
        {cm_filter}
        GROUP BY LOCAL_DATE_PART
        ORDER BY LOCAL_DATE_PART
        """
    return run_query(conn, query)

def get_availability_with_downtime_by_category(conn, days=7, filters=None):
    """Get availability % and downtime by focus category daily"""
    avail_filter = build_filter_clause(filters, 'availability')
    
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    oem_filter = filters.get('oem') if filters else None
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Handle OEM filter by joining with MARKET_TRACKER
    if oem_filter:
        site_type_filter = get_site_type_sql_filter(site_type, 'a.')
        avail_filter_aliased = avail_filter.replace('MARKET_ID', 'a.MARKET_ID').replace('SITE_ID', 'a.SITE_ID') if avail_filter else ''
        avail_query = f"""
        SELECT 
            a.DATE_VALUE,
            SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY_PCT
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter} AND mt.M_OEM = '{oem_filter}'
        {avail_filter_aliased}
        GROUP BY a.DATE_VALUE
        ORDER BY a.DATE_VALUE
        """
        
        downtime_query = f"""
        SELECT 
            a.DATE_VALUE,
            a.SITE_ID_FOCUS_CATEGORY,
            SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter} AND mt.M_OEM = '{oem_filter}'
          AND a.SITE_ID_FOCUS_CATEGORY IS NOT NULL
          {avail_filter_aliased}
        GROUP BY a.DATE_VALUE, a.SITE_ID_FOCUS_CATEGORY
        ORDER BY a.DATE_VALUE
        """
    else:
        avail_query = f"""
        SELECT 
            DATE_VALUE,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY_PCT
        FROM {TABLES['availability']}
        WHERE {date_filter}
        {avail_filter}
        GROUP BY DATE_VALUE
        ORDER BY DATE_VALUE
        """
        
        downtime_query = f"""
        SELECT 
            DATE_VALUE,
            SITE_ID_FOCUS_CATEGORY,
            SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME
        FROM {TABLES['availability']}
        WHERE {date_filter}
          AND SITE_ID_FOCUS_CATEGORY IS NOT NULL
          {avail_filter}
        GROUP BY DATE_VALUE, SITE_ID_FOCUS_CATEGORY
        ORDER BY DATE_VALUE
        """
    
    avail_df = run_query(conn, avail_query)
    downtime_df = run_query(conn, downtime_query)
    
    return avail_df, downtime_df

def get_cottr_by_summary_category(conn, days=7, filters=None):
    """Get COTTR outage minutes by SITE_ID_SUMMARY_CATEGORY - uses cached version"""
    filters_hash = filters_to_hashable(filters)
    return get_cottr_by_summary_category_cached(conn, days, filters_hash)

def get_availability_with_downtime_by_summary(conn, days=7, filters=None):
    """Get availability % and downtime by SITE_ID_SUMMARY_CATEGORY daily - uses cached version"""
    filters_hash = filters_to_hashable(filters)
    return get_availability_with_downtime_by_summary_cached(conn, days, filters_hash)

def get_combined_daily_data(conn, days=7, filters=None):
    """Get combined daily metrics from all three sources - uses cached version"""
    filters_hash = filters_to_hashable(filters)
    return get_combined_daily_data_cached(conn, days, filters_hash)

COMBINED_DAILY_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'network_insights_combined_daily.csv')


def export_combined_daily_csv(conn, days, filters) -> str | None:
    """Merge CM / availability / COTTR daily frames and write ``network_insights_combined_daily.csv``."""
    try:
        cm_daily, avail_daily, cottr_daily = get_combined_daily_data(conn, days, filters)
        parts = []
        for df, prefix in (
            (cm_daily, 'cm'),
            (avail_daily, 'avail'),
            (cottr_daily, 'cottr'),
        ):
            if df is None or df.empty or 'DATE_VALUE' not in df.columns:
                continue
            d = df.copy()
            rename = {'DATE_VALUE': 'DATE_VALUE'}
            for c in d.columns:
                if c == 'DATE_VALUE':
                    continue
                rename[c] = f'{prefix}_{c}'
            d = d.rename(columns=rename)
            parts.append(d)
        if not parts:
            return None
        merged = parts[0]
        for d in parts[1:]:
            merged = merged.merge(d, on='DATE_VALUE', how='outer')
        merged = merged.sort_values('DATE_VALUE')
        merged.to_csv(COMBINED_DAILY_CSV, index=False)
        return COMBINED_DAILY_CSV
    except Exception:
        return None

def get_combined_daily_data_prior_year(conn, days=7, filters=None):
    """Get combined daily metrics from the prior year (same date range shifted back 1 year)"""
    
    cm_filter = build_filter_clause(filters, 'customer_minutes')
    avail_filter = build_filter_clause(filters, 'availability')
    cottr_filter = build_filter_clause(filters, 'cottr')
    
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    
    # Shift dates back 1 year
    if start_date and end_date:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        prior_start = (start_dt - timedelta(days=365)).strftime('%Y-%m-%d')
        prior_end = (end_dt - timedelta(days=365)).strftime('%Y-%m-%d')
        date_filter_cm = f"LOCAL_START_TIMESTAMP >= '{prior_start}' AND LOCAL_START_TIMESTAMP <= '{prior_end} 23:59:59'"
        date_filter_avail = f"DATE_VALUE >= '{prior_start}' AND DATE_VALUE <= '{prior_end}'"
        date_filter_cottr = f"LOCAL_START_TIMESTAMP >= '{prior_start}' AND LOCAL_START_TIMESTAMP <= '{prior_end} 23:59:59'"
    else:
        # Use DATEADD to shift back 1 year from the same relative period
        date_filter_cm = f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, DATEADD(year, -1, CURRENT_DATE())) AND LOCAL_START_TIMESTAMP <= DATEADD(year, -1, CURRENT_DATE())"
        date_filter_avail = f"DATE_VALUE >= DATEADD(day, -{days}, DATEADD(year, -1, CURRENT_DATE())) AND DATE_VALUE <= DATEADD(year, -1, CURRENT_DATE())"
        date_filter_cottr = f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, DATEADD(year, -1, CURRENT_DATE())) AND LOCAL_START_TIMESTAMP <= DATEADD(year, -1, CURRENT_DATE())"
    
    if site_type:
        cm_filter_aliased = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
        cm_query = f"""
        SELECT 
            cm.LOCAL_DATE_PART as DATE_VALUE,
            SUM(cm.IMPACT_DURATION_IN_MINS) as CUSTOMER_MINUTES,
            SUM(cm.TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
        FROM {TABLES['customer_minutes']} cm
        INNER JOIN (
            SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
            WHERE {date_filter_avail} AND {get_site_type_sql_filter(site_type)}
        ) st ON cm.SITE_ID = st.SITE_ID
        WHERE {date_filter_cm.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')}
        {cm_filter_aliased}
        GROUP BY cm.LOCAL_DATE_PART
        """
    else:
        cm_query = f"""
        SELECT 
            LOCAL_DATE_PART as DATE_VALUE,
            SUM(IMPACT_DURATION_IN_MINS) as CUSTOMER_MINUTES,
            SUM(TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
        FROM {TABLES['customer_minutes']}
        WHERE {date_filter_cm}
        {cm_filter}
        GROUP BY LOCAL_DATE_PART
        """
    
    avail_query = f"""
    SELECT 
        DATE_VALUE,
        SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
        SUM(TOTAL_AVAILABILITY_N) as TOTAL_AVAILABILITY_N,
        SUM(TOTAL_AVAILABILITY_D) as TOTAL_AVAILABILITY_D,
        SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY_PCT
    FROM {TABLES['availability']}
    WHERE {date_filter_avail}
    {avail_filter}
    GROUP BY DATE_VALUE
    """
    
    cottr_query = f"""
    SELECT 
        PER_DAY_LOCAL_DATE as DATE_VALUE,
        COUNT(*) as OUTAGE_COUNT,
        SUM(PER_DAY_OUTAGE_MINUTES) as OUTAGE_MINUTES
    FROM {TABLES['cottr']}
    WHERE {date_filter_cottr}
      AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
    {cottr_filter}
    GROUP BY PER_DAY_LOCAL_DATE
    """
    
    results = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_query, conn, cm_query): 'cm',
            executor.submit(run_query, conn, avail_query): 'avail',
            executor.submit(run_query, conn, cottr_query): 'cottr',
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = pd.DataFrame()
    
    cm_df = results.get('cm', pd.DataFrame())
    avail_df = results.get('avail', pd.DataFrame())
    cottr_df = results.get('cottr', pd.DataFrame())
    
    return cm_df, avail_df, cottr_df

def format_number(num):
    """Format large numbers to human-readable format"""
    if num is None or pd.isna(num):
        return "0"
    num = float(num)
    if abs(num) >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}B"
    elif abs(num) >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    elif abs(num) >= 1_000:
        return f"{num / 1_000:.1f}K"
    else:
        return f"{num:,.0f}"

def shorten_aav_vendor(vendor_name, max_length=20):
    """Shorten long AAV vendor names to prevent text wrapping"""
    if not vendor_name or pd.isna(vendor_name):
        return ''
    
    vendor_name = str(vendor_name).strip()
    
    # Known mappings for long vendor names
    vendor_mappings = {
        'Shenandoah Cable Television, LLC dba Shentel Communications': 'Shentel',
        'EVERSTREAM SOLUTIONS': 'Everstream',
        'TIME WARNER CABLE': 'TWC',
        'HAWAIIAN TELCOM': 'Hawaiian Telcom',
        'CHARTER COMMUNICATIONS': 'Charter',
        'COMCAST CABLE COMMUNICATIONS': 'Comcast',
        'COX COMMUNICATIONS': 'Cox',
        'FRONTIER COMMUNICATIONS': 'Frontier',
        'CENTURYLINK': 'CenturyLink',
        'WINDSTREAM': 'Windstream',
        'CONSOLIDATED COMMUNICATIONS': 'Consolidated',
        'ZAYO GROUP': 'Zayo',
        'CROWN CASTLE': 'Crown Castle',
        'LUMEN TECHNOLOGIES': 'Lumen',
    }
    
    # Check for exact match first
    if vendor_name in vendor_mappings:
        return vendor_mappings[vendor_name]
    
    # Check for partial match (case-insensitive)
    vendor_upper = vendor_name.upper()
    for long_name, short_name in vendor_mappings.items():
        if long_name.upper() in vendor_upper or vendor_upper in long_name.upper():
            return short_name
    
    # If no mapping found, truncate if too long
    if len(vendor_name) > max_length:
        return vendor_name[:max_length-2].strip() + '..'
    
    return vendor_name

def render_metric_card(label, value, source=None, color="magenta", format_large=True):
    """Render a styled metric card"""
    card_class = f"metric-card-{color}" if color != "magenta" else "metric-card"
    value_class = f"metric-value-{color}" if color != "magenta" else "metric-value-magenta"
    source_html = f'<div class="metric-source">Source: {source}</div>' if source else ''
    
    # Always try to format numeric values
    if format_large:
        try:
            numeric_val = float(value)
            display_value = format_number(numeric_val)
        except (ValueError, TypeError):
            display_value = value
    else:
        display_value = value
    
    st.markdown(f"""
    <div class="{card_class}">
        <div class="metric-value {value_class}">{display_value}</div>
        <div class="metric-label">{label}</div>
        {source_html}
    </div>
    """, unsafe_allow_html=True)

def render_kpi_card_with_sparkline(label, value, df, x_col, y_col, source=None, color="magenta", format_large=True, goal_value=None, goal_label=None, key_prefix="kpi", show_sparkline=True, top_right_stats=None, bottom_right_stats=None):
    """Render a KPI card matching Site-Level Analysis layout with optional sparkline
    
    Uses exact same HTML/CSS styling as Site Analysis tiles:
    - Label: clamp(1rem, 1.4vw, 1.3rem)
    - Value: clamp(2.5rem, 4vw, 3.5rem)
    - Stats: clamp(0.85rem, 1.1vw, 1rem)
    
    bottom_right_stats: dict with 'line1', 'line2', 'color1', 'color2' for text below sparkline
    """
    
    color_map = {
        "magenta": {"border": "#e20074", "value": "#e20074", "line": "#e20074"},
        "green": {"border": "#22c55e", "value": "#22c55e", "line": "#22c55e"},
        "orange": {"border": "#f59e0b", "value": "#f59e0b", "line": "#f59e0b"},
    }
    colors = color_map.get(color, color_map["magenta"])
    
    # Format the value
    if format_large:
        try:
            numeric_val = float(value)
            display_value = format_number(numeric_val)
        except (ValueError, TypeError):
            display_value = value
    else:
        display_value = value
    
    # Build stats HTML for top right (matching Site Analysis)
    # Always include placeholder to maintain consistent height
    if top_right_stats:
        line1_html = ""
        line2_html = ""
        line3_html = ""
        if top_right_stats.get('line1'):
            color1 = top_right_stats.get('color1', '#888888')
            line1_html = f'<div style="font-size:clamp(0.75rem, 1vw, 0.85rem);color:{color1};">{top_right_stats["line1"]}</div>'
        if top_right_stats.get('line2'):
            color2 = top_right_stats.get('color2', '#888888')
            line2_html = f'<div style="font-size:clamp(0.65rem, 0.9vw, 0.75rem);color:{color2};margin-top:2px;">{top_right_stats["line2"]}</div>'
        if top_right_stats.get('line3'):
            color3 = top_right_stats.get('color3', '#888888')
            line3_html = f'<div style="font-size:clamp(0.6rem, 0.85vw, 0.7rem);color:{color3};margin-top:2px;">{top_right_stats["line3"]}</div>'
        if top_right_stats.get('line4'):
            color4 = top_right_stats.get('color4', '#888888')
            line4_html = f'<div style="font-size:clamp(0.6rem, 0.85vw, 0.7rem);color:{color4};margin-top:1px;">{top_right_stats["line4"]}</div>'
        else:
            line4_html = ""
        stats_html = f'<div style="min-height:40px;max-height:65px;overflow:hidden;">{line1_html}{line2_html}{line3_html}{line4_html}</div>'
    else:
        # Empty placeholder to maintain consistent height
        stats_html = '<div style="min-height:40px;max-height:65px;">&nbsp;</div>'
    
    # Render HTML tile with fixed height - VALUE on top, label below (matching Site Analysis)
    st.markdown(f"""
    <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:12px;padding:clamp(14px, 2vw, 20px);text-align:left;border-left:4px solid {colors['border']};height:130px;position:relative;display:flex;flex-direction:column;justify-content:space-between;">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;flex:1;">
            <div style="font-size:clamp(2rem, 3.5vw, 3rem);font-weight:bold;color:{colors['value']};line-height:1;">{display_value}</div>
            <div style="text-align:right;">{stats_html}</div>
        </div>
        <div style="font-size:clamp(0.85rem, 1.2vw, 1.1rem);color:#aaa;margin-top:auto;">{label}</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Add sparkline chart below the tile if enabled
    if show_sparkline and df is not None and not df.empty:
        fig = go.Figure()
        df_sorted = df.copy()
        df_sorted['DATE'] = pd.to_datetime(df_sorted[x_col]).dt.date
        df_sorted = df_sorted.sort_values('DATE')
        
        y_vals = df_sorted[y_col].values
        y_min = min(y_vals)
        y_max = max(y_vals)
        
        if goal_value is not None:
            y_min = min(y_min, goal_value)
            y_max = max(y_max, goal_value)
        
        # OPTIMIZATION: For percentage values (like availability %), add padding to show variation
        # This ensures the sparkline shows meaningful variation instead of flat line at top
        y_range = y_max - y_min
        if y_range > 0:
            y_padding = y_range * 0.15  # 15% padding
        else:
            y_padding = abs(y_max) * 0.05 if y_max != 0 else 1  # 5% of max value
        
        # For availability % (values near 100), set fill baseline to show actual variation
        is_percentage_near_100 = y_min > 90 and y_max <= 100
        fill_baseline = y_min - y_padding if is_percentage_near_100 else 0
        
        # Store original values for hover
        original_dates = df_sorted['DATE'].astype(str).tolist()
        original_values = df_sorted[y_col].tolist()
        
        hover_texts = []
        for d, v in zip(original_dates, original_values):
            try:
                if isinstance(v, (int, float)):
                    if abs(v) >= 1000000:
                        formatted_v = f"{v/1000000:.2f}M"
                    elif abs(v) >= 1000:
                        formatted_v = f"{v/1000:.1f}K"
                    elif isinstance(v, float) and v < 100:
                        formatted_v = f"{v:.2f}%"
                    else:
                        formatted_v = f"{v:,.0f}"
                else:
                    formatted_v = str(v)
            except:
                formatted_v = str(v)
            hover_texts.append(f"<b>{d}</b><br>{label}: {formatted_v}")
        
        # Add goal line if provided
        if goal_value is not None and (y_max - y_min) > 0:
            fig.add_hline(
                y=goal_value,
                line=dict(color='#f59e0b', width=1.5, dash='dot'),
                annotation_text=goal_label if goal_label else f"{goal_value}%",
                annotation_font_size=10,
                annotation_font_color='#f59e0b',
            )
        
        # For percentage values near 100%, add a baseline trace to create proper fill
        if is_percentage_near_100:
            # Add baseline trace for fill reference
            fig.add_trace(go.Scatter(
                x=df_sorted['DATE'],
                y=[fill_baseline] * len(df_sorted),
                mode='lines',
                line=dict(color='rgba(0,0,0,0)', width=0),
                showlegend=False,
                hoverinfo='skip',
            ))
            
            fig.add_trace(go.Scatter(
                x=df_sorted['DATE'],
                y=df_sorted[y_col],
                mode='lines',
                line=dict(color=colors['line'], width=2),
                fill='tonexty',  # Fill to the baseline trace
                fillcolor=f'rgba{tuple(list(int(colors["line"].lstrip("#")[i:i+2], 16) for i in (0, 2, 4)) + [0.3])}',
                hovertemplate='%{text}<extra></extra>',
                text=hover_texts,
                showlegend=False,
            ))
        else:
            fig.add_trace(go.Scatter(
                x=df_sorted['DATE'],
                y=df_sorted[y_col],
                mode='lines',
                line=dict(color=colors['line'], width=2),
                fill='tozeroy',
                fillcolor=f'rgba{tuple(list(int(colors["line"].lstrip("#")[i:i+2], 16) for i in (0, 2, 4)) + [0.2])}',
                hovertemplate='%{text}<extra></extra>',
                text=hover_texts,
                showlegend=False,
            ))
        
        # Set y-axis range to show actual data variation
        fig.update_layout(
            height=60,
            margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            showlegend=False,
            hovermode='x unified',
            hoverlabel=HOVER_LABEL_STYLE,
            xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            yaxis=dict(
                showgrid=False, 
                showticklabels=False, 
                zeroline=False,
                range=[fill_baseline - y_padding, y_max + y_padding] if is_percentage_near_100 else None
            ),
        )
        
        # Use unique key to avoid duplicate element ID errors
        clean_label = label.replace(' ', '_').replace('%', 'pct').replace('(', '').replace(')', '')
        chart_key = f"spark_{key_prefix}_{clean_label}_{y_col}"
        st.plotly_chart(fig, use_container_width=True, config=SPARKLINE_CHART_CONFIG, key=chart_key)
    
    # Add bottom right stats below sparkline if provided
    if bottom_right_stats:
        line1 = bottom_right_stats.get('line1', '')
        line2 = bottom_right_stats.get('line2', '')
        color1 = bottom_right_stats.get('color1', '#888888')
        color2 = bottom_right_stats.get('color2', '#888888')
        st.markdown(f"""
        <div style="text-align:right;margin-top:-8px;padding-right:4px;">
            <span style="font-size:0.75rem;color:{color1};">{line1}</span>
            <span style="font-size:0.75rem;color:{color2};margin-left:8px;">{line2}</span>
        </div>
        """, unsafe_allow_html=True)
    
    # Return early - no need for the old Plotly-only approach
    return

# Legacy code below kept for reference but not executed
def _old_render_kpi_card_with_sparkline():
    """Old implementation - kept for reference"""
    fig = go.Figure()
    fig.add_shape(
        type="line",
        x0=0, y0=0, x1=0, y1=1,
        xref="paper", yref="paper",
        line=dict(color=colors['border'], width=4),
    )
    
    st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key=f"{key_prefix}_{label}")

def get_combined_site_data(conn, days=7, top_n=20, filters=None):
    """Get combined site-level metrics"""
    cm_filter = build_filter_clause(filters, 'customer_minutes')
    avail_filter = build_filter_clause(filters, 'availability')
    cottr_filter = build_filter_clause(filters, 'cottr')
    
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    
    date_filter_cm = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_cottr = f"PER_DAY_LOCAL_DATE >= '{start_date}' AND PER_DAY_LOCAL_DATE <= '{end_date}'" if start_date and end_date else f"PER_DAY_LOCAL_DATE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Customer Minutes: Join with availability to filter by site_type since CM table doesn't have site_type
    if site_type:
        # Build aliased filter and date filter for CM table (prefix columns with 'cm.')
        cm_filter_aliased = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
        date_filter_cm_aliased = date_filter_cm.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')
        cm_query = f"""
        SELECT cm.SITE_ID, cm.MARKET, 
               COALESCE(SUM(COALESCE(cm.IMPACT_DURATION_IN_MINS, 0)), 0) as CUSTOMER_MINUTES, 
               COALESCE(SUM(COALESCE(cm.TOTAL_IMPACTED_SUB_CNT, 0)), 0) as IMPACTED_SUBS
        FROM {TABLES['customer_minutes']} cm
        INNER JOIN (
            SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
            WHERE {date_filter_avail} AND {get_site_type_sql_filter(site_type)}
        ) a ON cm.SITE_ID = a.SITE_ID
        WHERE {date_filter_cm_aliased} {cm_filter_aliased}
        GROUP BY cm.SITE_ID, cm.MARKET 
        HAVING SUM(COALESCE(cm.TOTAL_IMPACTED_SUB_CNT, 0)) > 0 OR SUM(COALESCE(cm.IMPACT_DURATION_IN_MINS, 0)) > 0
        ORDER BY IMPACTED_SUBS DESC LIMIT {top_n}
        """
    else:
        cm_query = f"""
        SELECT SITE_ID, MARKET, 
               COALESCE(SUM(COALESCE(IMPACT_DURATION_IN_MINS, 0)), 0) as CUSTOMER_MINUTES, 
               COALESCE(SUM(COALESCE(TOTAL_IMPACTED_SUB_CNT, 0)), 0) as IMPACTED_SUBS
        FROM {TABLES['customer_minutes']}
        WHERE {date_filter_cm} {cm_filter}
        GROUP BY SITE_ID, MARKET 
        HAVING SUM(COALESCE(TOTAL_IMPACTED_SUB_CNT, 0)) > 0 OR SUM(COALESCE(IMPACT_DURATION_IN_MINS, 0)) > 0
        ORDER BY IMPACTED_SUBS DESC LIMIT {top_n}
        """
    
    # Add site_type filter for availability
    site_type_filter = get_site_type_sql_filter(site_type)
    
    avail_query = f"""
    SELECT SITE_ID, MARKET_ID as MARKET, SITE_ID_FOCUS_CATEGORY, 
           SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
           COUNT(DISTINCT CASE WHEN TOTAL_DOWNTIME > 0 THEN DATE_VALUE END) as DOWNTIME_DAYS,
           SUM(TOTAL_AVAILABILITY_N) as TOTAL_AVAILABILITY_N,
           SUM(TOTAL_AVAILABILITY_D) as TOTAL_AVAILABILITY_D,
           SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY,
           MAX(FIELD_OPS_ASSIGNEE) as FIELD_OPS_ASSIGNEE,
           MAX(TOP_RECORDID) as TOP_RECORDID,
           MAX(DESCRIPTION_1) as DESCRIPTION_1,
           MAX(DESCRIPTION_2) as DESCRIPTION_2,
           MAX(DESCRIPTION_3) as DESCRIPTION_3
    FROM {TABLES['availability']}
    WHERE {date_filter_avail} AND {site_type_filter} {avail_filter}
    GROUP BY SITE_ID, MARKET_ID, SITE_ID_FOCUS_CATEGORY ORDER BY TOTAL_DOWNTIME DESC LIMIT {top_n * 3}
    """
    
    cottr_query = f"""
    SELECT SITE_CD as SITE_ID, MKT_NAME as MARKET, SITE_ID_FOCUS_CATEGORY, 
           COUNT(DISTINCT PER_DAY_LOCAL_DATE) as OUTAGE_DAYS,
           SUM(PER_DAY_OUTAGE_MINUTES) as OUTAGE_MINUTES
    FROM {TABLES['cottr']}
    WHERE {date_filter_cottr} AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'  {cottr_filter}
    GROUP BY SITE_CD, MKT_NAME, SITE_ID_FOCUS_CATEGORY ORDER BY OUTAGE_DAYS DESC LIMIT {top_n * 3}
    """
    
    # OPTIMIZATION: Run all 3 queries in parallel for faster loading
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_cm = executor.submit(run_query, conn, cm_query, use_cache=True)
        future_avail = executor.submit(run_query, conn, avail_query, use_cache=True)
        future_cottr = executor.submit(run_query, conn, cottr_query, use_cache=True)
        return future_cm.result(), future_avail.result(), future_cottr.result()

def get_site_summary_data(conn, days=7, top_n=100, filters=None):
    """Get site-level summary with distinct day counts - combined query to ensure all sites are included"""
    avail_filter = build_filter_clause(filters, 'availability')
    cottr_filter = build_filter_clause(filters, 'cottr')
    cm_filter = build_filter_clause(filters, 'customer_minutes')
    
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_cottr = f"PER_DAY_LOCAL_DATE >= '{start_date}' AND PER_DAY_LOCAL_DATE <= '{end_date}'" if start_date and end_date else f"PER_DAY_LOCAL_DATE >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_cm = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Build CM CTE with site_type filtering if needed
    if site_type:
        cm_filter_aliased = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
        cm_cte = f"""
    cm_data AS (
        SELECT cm.SITE_ID,
               MAX(cm.MARKET) as CM_MARKET,
               COUNT(DISTINCT CASE WHEN cm.TOTAL_IMPACTED_SUB_CNT > 0 THEN CAST(cm.LOCAL_START_TIMESTAMP AS DATE) END) as CM_DAYS,
               SUM(cm.IMPACT_DURATION_IN_MINS) as IMPACT_DURATION_MINS,
               COUNT(DISTINCT cm.LOCAL_DATE_PART) as CM_DAY_COUNT
        FROM {TABLES['customer_minutes']} cm
        INNER JOIN (
            SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
            WHERE {date_filter_avail} AND {get_site_type_sql_filter(site_type)}
        ) st ON cm.SITE_ID = st.SITE_ID
        WHERE {date_filter_cm.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')} {cm_filter_aliased}
        GROUP BY cm.SITE_ID
    ),"""
    else:
        cm_cte = f"""
    cm_data AS (
        SELECT SITE_ID,
               MAX(MARKET) as CM_MARKET,
               COUNT(DISTINCT CASE WHEN TOTAL_IMPACTED_SUB_CNT > 0 THEN CAST(LOCAL_START_TIMESTAMP AS DATE) END) as CM_DAYS,
               SUM(IMPACT_DURATION_IN_MINS) as IMPACT_DURATION_MINS,
               COUNT(DISTINCT LOCAL_DATE_PART) as CM_DAY_COUNT
        FROM {TABLES['customer_minutes']}
        WHERE {date_filter_cm} {cm_filter}
        GROUP BY SITE_ID
    ),"""
    
    # Add site_type filter for availability
    site_type_filter = get_site_type_sql_filter(site_type)
    
    # Combined query using CTEs to get all sites with any data, then join metrics
    combined_query = f"""
    WITH avail_combined AS (
        SELECT SITE_ID,
               MAX(MARKET_ID) as MARKET_ID,
               COUNT(DISTINCT CASE WHEN TOTAL_DOWNTIME > 0 THEN DATE_VALUE END) as AVAIL_DOWNTIME_DAYS,
               SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME_SUM,
               COUNT(DISTINCT CASE WHEN TOTAL_DOWNTIME > 0 THEN TOP_RECORDID END) as AVAIL_RECORD_COUNT,
               MAX(FIELD_OPS_ASSIGNEE) as FIELD_OPS_ASSIGNEE,
               MAX(FIELD_OPS_ASSIGNMENT_GROUP) as FIELD_OPS_ASSIGNMENT_GROUP,
               MAX(FIELD_OPS_MGR) as FIELD_OPS_MGR,
               MAX(MB_MKT_AREA) as MB_MKT_AREA,
               MAX(CASE WHEN TOTAL_DOWNTIME > 0 THEN DATE_VALUE END) as LAST_OUTAGE_DATE
        FROM {TABLES['availability']}
        WHERE {date_filter_avail} AND {site_type_filter} {avail_filter}
        GROUP BY SITE_ID
    ),
    last_outage_category AS (
        SELECT SITE_ID,
               SITE_ID_FOCUS_CATEGORY,
               DESCRIPTION_3
        FROM (
            SELECT SITE_ID, SITE_ID_FOCUS_CATEGORY, DESCRIPTION_3, DATE_VALUE,
                   ROW_NUMBER() OVER (PARTITION BY SITE_ID ORDER BY DATE_VALUE DESC) as rn
            FROM {TABLES['availability']}
            WHERE {date_filter_avail} AND {site_type_filter} AND TOTAL_DOWNTIME > 0 {avail_filter}
        ) ranked
        WHERE rn = 1
    ),
    cottr_data AS (
        SELECT SITE_CD as SITE_ID,
               MAX(MKT_NAME) as COTTR_MARKET,
               COUNT(DISTINCT PER_DAY_LOCAL_DATE) as COTTR_OUTAGE_DAYS,
               SUM(PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINUTES_SUM,
               COUNT(DISTINCT TOP_RECORDID) as COTTR_RECORD_COUNT,
               MAX(PER_DAY_LOCAL_DATE) as LAST_COTTR_OUTAGE_DATE
        FROM {TABLES['cottr']}
        WHERE {date_filter_cottr} AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' {cottr_filter}
        GROUP BY SITE_CD
    ),
    last_cottr_outage_category AS (
        SELECT SITE_CD as SITE_ID,
               SITE_ID_FOCUS_CATEGORY as COTTR_FOCUS_CATEGORY
        FROM (
            SELECT SITE_CD, SITE_ID_FOCUS_CATEGORY, PER_DAY_LOCAL_DATE,
                   ROW_NUMBER() OVER (PARTITION BY SITE_CD ORDER BY PER_DAY_LOCAL_DATE DESC) as rn
            FROM {TABLES['cottr']}
            WHERE {date_filter_cottr} AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' {cottr_filter}
        ) ranked
        WHERE rn = 1
    ),
    {cm_cte}
    all_sites AS (
        SELECT SITE_ID FROM avail_combined
        UNION
        SELECT SITE_ID FROM cottr_data
        UNION
        SELECT SITE_ID FROM cm_data
    )
    SELECT 
        s.SITE_ID,
        COALESCE(a.MARKET_ID, c.COTTR_MARKET, m.CM_MARKET) as MARKET_ID,
        COALESCE(a.AVAIL_DOWNTIME_DAYS, 0) as AVAIL_DOWNTIME_DAYS,
        COALESCE(a.TOTAL_DOWNTIME_SUM, 0) as TOTAL_DOWNTIME_SEC,
        COALESCE(a.AVAIL_RECORD_COUNT, 0) as AVAIL_RECORD_COUNT,
        COALESCE(c.COTTR_OUTAGE_DAYS, 0) as COTTR_OUTAGE_DAYS,
        COALESCE(c.TOTAL_OUTAGE_MINUTES_SUM, 0) as TOTAL_OUTAGE_MINS,
        COALESCE(c.COTTR_RECORD_COUNT, 0) as COTTR_RECORD_COUNT,
        COALESCE(m.CM_DAYS, 0) as CM_DAYS,
        COALESCE(m.IMPACT_DURATION_MINS, 0) as IMPACT_DURATION_MINS,
        COALESCE(m.CM_DAY_COUNT, 0) as CM_DAY_COUNT,
        a.FIELD_OPS_ASSIGNEE,
        a.FIELD_OPS_ASSIGNMENT_GROUP,
        a.FIELD_OPS_MGR,
        a.MB_MKT_AREA,
        a.LAST_OUTAGE_DATE as LAST_AVAIL_OUTAGE_DATE,
        loc.SITE_ID_FOCUS_CATEGORY as LAST_AVAIL_FOCUS_CATEGORY,
        loc.DESCRIPTION_3 as LAST_AVAIL_OUTAGE_DESCRIPTION,
        c.LAST_COTTR_OUTAGE_DATE,
        cloc.COTTR_FOCUS_CATEGORY as LAST_COTTR_FOCUS_CATEGORY,
        stf.S_COVERAGE_CLASSIFICATION as COVERAGE_CLASSIFICATION
    FROM all_sites s
    LEFT JOIN avail_combined a ON s.SITE_ID = a.SITE_ID
    LEFT JOIN last_outage_category loc ON s.SITE_ID = loc.SITE_ID
    LEFT JOIN cottr_data c ON s.SITE_ID = c.SITE_ID
    LEFT JOIN last_cottr_outage_category cloc ON s.SITE_ID = cloc.SITE_ID
    LEFT JOIN cm_data m ON s.SITE_ID = m.SITE_ID
    LEFT JOIN BDM_NDW_MAGENTABUILT_REFERENCE_DB.MAGENTABUILT_REFERENCE.SITE_TRACKER_FOPS stf ON s.SITE_ID = stf.SITE_ID
    WHERE COALESCE(a.AVAIL_DOWNTIME_DAYS, 0) > 0 
       OR COALESCE(c.COTTR_OUTAGE_DAYS, 0) > 0 
       OR COALESCE(m.CM_DAYS, 0) > 0
    ORDER BY (COALESCE(a.AVAIL_DOWNTIME_DAYS, 0) + COALESCE(c.COTTR_OUTAGE_DAYS, 0) + COALESCE(m.CM_DAYS, 0)) DESC
    LIMIT {top_n}
    """
    
    return run_query(conn, combined_query)

def get_focus_category_totals(conn, days=7, filters=None):
    """Get focus category totals for insights - uses cached version"""
    filters_hash = filters_to_hashable(filters)
    return get_focus_category_totals_cached(conn, days, filters_hash)

def get_focus_category_totals_cottr(conn, days=7, filters=None):
    """Get COTTR outage minutes by focus category - uses cached version"""
    filters_hash = filters_to_hashable(filters)
    return get_focus_category_totals_cottr_cached(conn, days, filters_hash)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_availability_by_field_ops_group(_conn, days=7, filters=None):
    """Get availability data grouped by Field Ops Assignment Group"""
    conn = _conn
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    site_type_filter = get_site_type_sql_filter(site_type)
    site_type_filter_a = get_site_type_sql_filter(site_type, 'a.')
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_a = f"a.DATE_VALUE >= '{start_date}' AND a.DATE_VALUE <= '{end_date}'" if start_date and end_date else f"a.DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    avail_filter_a = avail_filter.replace('DATE_VALUE', 'a.DATE_VALUE').replace('MARKET_ID', 'a.MARKET_ID').replace('SITE_ID', 'a.SITE_ID').replace('SITE_TYPE', 'a.SITE_TYPE') if avail_filter else ''
    
    query = f"""
    WITH daily_avail AS (
        SELECT 
            COALESCE(FIELD_OPS_ASSIGNMENT_GROUP, 'Unassigned') as FIELD_OPS_ASSIGNMENT_GROUP,
            DATE_VALUE,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as DAILY_AVAIL_PCT
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY FIELD_OPS_ASSIGNMENT_GROUP, DATE_VALUE
    )
    SELECT 
        COALESCE(a.FIELD_OPS_ASSIGNMENT_GROUP, 'Unassigned') as FIELD_OPS_ASSIGNMENT_GROUP,
        SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
        SUM(a.TOTAL_AVAILABILITY_N) as TOTAL_N,
        SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_D,
        SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY,
        COUNT(DISTINCT a.SITE_ID) as SITE_COUNT,
        COUNT(DISTINCT a.DATE_VALUE) as TOTAL_DAYS,
        COUNT(DISTINCT CASE WHEN d.DAILY_AVAIL_PCT >= 99.85 THEN a.DATE_VALUE END) as DAYS_MEETING_GOAL
    FROM {TABLES['availability']} a
    LEFT JOIN daily_avail d ON COALESCE(a.FIELD_OPS_ASSIGNMENT_GROUP, 'Unassigned') = d.FIELD_OPS_ASSIGNMENT_GROUP AND a.DATE_VALUE = d.DATE_VALUE
    WHERE {date_filter_a} AND {site_type_filter_a} {avail_filter_a}
    GROUP BY a.FIELD_OPS_ASSIGNMENT_GROUP
    ORDER BY TOTAL_DOWNTIME DESC
    """
    return run_query(conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_availability_by_field_ops_mgr(_conn, days=7, filters=None):
    """Get availability data grouped by Field Ops Manager"""
    conn = _conn
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    site_type_filter = get_site_type_sql_filter(site_type)
    site_type_filter_a = get_site_type_sql_filter(site_type, 'a.')
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_a = f"a.DATE_VALUE >= '{start_date}' AND a.DATE_VALUE <= '{end_date}'" if start_date and end_date else f"a.DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    avail_filter_a = avail_filter.replace('DATE_VALUE', 'a.DATE_VALUE').replace('MARKET_ID', 'a.MARKET_ID').replace('SITE_ID', 'a.SITE_ID').replace('SITE_TYPE', 'a.SITE_TYPE') if avail_filter else ''
    
    query = f"""
    WITH daily_avail AS (
        SELECT 
            COALESCE(FIELD_OPS_MGR, 'Unassigned') as FIELD_OPS_MGR,
            DATE_VALUE,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as DAILY_AVAIL_PCT
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY FIELD_OPS_MGR, DATE_VALUE
    )
    SELECT 
        COALESCE(a.FIELD_OPS_MGR, 'Unassigned') as FIELD_OPS_MGR,
        SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
        SUM(a.TOTAL_AVAILABILITY_N) as TOTAL_N,
        SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_D,
        SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY,
        COUNT(DISTINCT a.SITE_ID) as SITE_COUNT,
        COUNT(DISTINCT a.DATE_VALUE) as TOTAL_DAYS,
        COUNT(DISTINCT CASE WHEN d.DAILY_AVAIL_PCT >= 99.85 THEN a.DATE_VALUE END) as DAYS_MEETING_GOAL
    FROM {TABLES['availability']} a
    LEFT JOIN daily_avail d ON COALESCE(a.FIELD_OPS_MGR, 'Unassigned') = d.FIELD_OPS_MGR AND a.DATE_VALUE = d.DATE_VALUE
    WHERE {date_filter_a} AND {site_type_filter_a} {avail_filter_a}
    GROUP BY a.FIELD_OPS_MGR
    ORDER BY TOTAL_DOWNTIME DESC
    """
    return run_query(conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_availability_by_field_ops_assignee(_conn, days=7, filters=None):
    """Get availability data grouped by Field Ops Assignee"""
    conn = _conn
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    site_type_filter = get_site_type_sql_filter(site_type)
    site_type_filter_a = get_site_type_sql_filter(site_type, 'a.')
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_a = f"a.DATE_VALUE >= '{start_date}' AND a.DATE_VALUE <= '{end_date}'" if start_date and end_date else f"a.DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    avail_filter_a = avail_filter.replace('DATE_VALUE', 'a.DATE_VALUE').replace('MARKET_ID', 'a.MARKET_ID').replace('SITE_ID', 'a.SITE_ID').replace('SITE_TYPE', 'a.SITE_TYPE') if avail_filter else ''
    
    query = f"""
    WITH daily_avail AS (
        SELECT 
            COALESCE(FIELD_OPS_ASSIGNEE, 'Unassigned') as FIELD_OPS_ASSIGNEE,
            DATE_VALUE,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as DAILY_AVAIL_PCT
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY FIELD_OPS_ASSIGNEE, DATE_VALUE
    )
    SELECT 
        COALESCE(a.FIELD_OPS_ASSIGNEE, 'Unassigned') as FIELD_OPS_ASSIGNEE,
        SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
        SUM(a.TOTAL_AVAILABILITY_N) as TOTAL_N,
        SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_D,
        SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY,
        COUNT(DISTINCT a.SITE_ID) as SITE_COUNT,
        COUNT(DISTINCT a.DATE_VALUE) as TOTAL_DAYS,
        COUNT(DISTINCT CASE WHEN d.DAILY_AVAIL_PCT >= 99.85 THEN a.DATE_VALUE END) as DAYS_MEETING_GOAL
    FROM {TABLES['availability']} a
    LEFT JOIN daily_avail d ON COALESCE(a.FIELD_OPS_ASSIGNEE, 'Unassigned') = d.FIELD_OPS_ASSIGNEE AND a.DATE_VALUE = d.DATE_VALUE
    WHERE {date_filter_a} AND {site_type_filter_a} {avail_filter_a}
    GROUP BY a.FIELD_OPS_ASSIGNEE
    ORDER BY TOTAL_DOWNTIME DESC
    """
    return run_query(conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_site_map_data(_conn, days=7, filters=None):
    """Get site locations with focus category for map visualization"""
    conn = _conn
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    site_type_filter = get_site_type_sql_filter(site_type)
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    query = f"""
    WITH site_data AS (
        SELECT 
            SITE_ID,
            SITE_ID_FOCUS_CATEGORY,
            SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
            MAX(SITE_LATITUDE) as LATITUDE,
            MAX(SITE_LONGITUDE) as LONGITUDE,
            MAX(MARKET_ID) as MARKET_ID,
            MAX(FIELD_OPS_ASSIGNEE) as FIELD_OPS_ASSIGNEE,
            MAX(FIELD_OPS_MGR) as FIELD_OPS_MGR,
            MAX(CASE WHEN TOTAL_DOWNTIME > 0 THEN DATE_VALUE END) as LAST_OUTAGE_DATE
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} AND TOTAL_DOWNTIME > 0 {avail_filter}
        GROUP BY SITE_ID, SITE_ID_FOCUS_CATEGORY
    ),
    dominant_category AS (
        SELECT 
            SITE_ID,
            SITE_ID_FOCUS_CATEGORY,
            TOTAL_DOWNTIME,
            LATITUDE,
            LONGITUDE,
            MARKET_ID,
            FIELD_OPS_ASSIGNEE,
            FIELD_OPS_MGR,
            LAST_OUTAGE_DATE,
            ROW_NUMBER() OVER (PARTITION BY SITE_ID ORDER BY TOTAL_DOWNTIME DESC) as rn
        FROM site_data
    )
    SELECT 
        SITE_ID,
        SITE_ID_FOCUS_CATEGORY as FOCUS_CATEGORY,
        TOTAL_DOWNTIME,
        LATITUDE,
        LONGITUDE,
        MARKET_ID,
        COALESCE(FIELD_OPS_ASSIGNEE, 'Unassigned') as FIELD_OPS_ASSIGNEE,
        COALESCE(FIELD_OPS_MGR, 'Unassigned') as FIELD_OPS_MGR,
        LAST_OUTAGE_DATE
    FROM dominant_category
    WHERE rn = 1 AND LATITUDE IS NOT NULL AND LONGITUDE IS NOT NULL
    ORDER BY TOTAL_DOWNTIME DESC
    """
    return run_query(conn, query)

def get_market_totals(conn, days=7, filters=None):
    """Get market totals for insights - uses cached version"""
    filters_hash = filters_to_hashable(filters)
    return get_market_totals_cached(conn, days, filters_hash)

def get_market_daily_availability(conn, days=7, filters=None):
    """Get market-level daily availability data - uses cached version"""
    filters_hash = filters_to_hashable(filters)
    return get_market_daily_availability_cached(conn, days, filters_hash)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_rolling_availability_data(_conn, filters=None):
    """Get daily regional availability data for rolling 30-day goal tracking charts"""
    conn = _conn
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    site_type_filter = get_site_type_sql_filter(site_type)
    
    # Need extra 30 days before start_date for rolling calculation
    if start_date and end_date:
        date_filter = f"DATE_VALUE >= DATEADD(day, -30, '{start_date}') AND DATE_VALUE <= '{end_date}'"
    else:
        date_filter = f"DATE_VALUE >= DATEADD(day, -60, CURRENT_DATE())"
    
    # Get daily availability by region
    query = f"""
    SELECT 
        REGION_ID,
        DATE_VALUE,
        SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as DAILY_AVAILABILITY
    FROM {TABLES['availability']}
    WHERE {date_filter} AND {site_type_filter} {avail_filter}
    GROUP BY REGION_ID, DATE_VALUE
    ORDER BY REGION_ID, DATE_VALUE
    """
    return run_query(conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_availability_scatter_data(_conn, days=7, filters=None, by_site=False):
    """Get data for availability scatter chart - markets or sites with downtime vs availability %"""
    conn = _conn
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Build filter clauses with table alias for queries with joins
    filter_clauses = []
    if filters:
        if filters.get('market'):
            # Handle multi-market selection
            market_selection = filters['market']
            if isinstance(market_selection, str):
                market_selection = [market_selection]
            all_market_ids = []
            for m in market_selection:
                if m:  # Skip None/empty
                    all_market_ids.extend(get_market_ids_for_filter(m, 'availability'))
            # Remove duplicates and empty values
            all_market_ids = [mid for mid in dict.fromkeys(all_market_ids) if mid]
            if all_market_ids:
                if len(all_market_ids) == 1:
                    filter_clauses.append(f"UPPER(MARKET_ID) = '{all_market_ids[0].upper()}'")
                else:
                    market_list = "', '".join([mid.upper() for mid in all_market_ids])
                    filter_clauses.append(f"UPPER(MARKET_ID) IN ('{market_list}')")
        if filters.get('site'):
            filter_clauses.append(f"SITE_ID = '{filters['site']}'")
        if filters.get('outage_type'):
            filter_clauses.append(f"OUTAGE_TYPE = '{filters['outage_type']}'")
        if filters.get('vendor'):
            filter_clauses.append(f"VENDOR = '{filters['vendor']}'")
        if filters.get('focus_category'):
            filter_clauses.append(f"SITE_ID_FOCUS_CATEGORY = '{filters['focus_category']}'")
    base_filter = " AND " + " AND ".join(filter_clauses) if filter_clauses else ""
    
    if by_site:
        # Get site-level data when a market is selected - include dominant focus category
        query = f"""
        WITH base_data AS (
            SELECT SITE_ID, SITE_ID_FOCUS_CATEGORY, TOTAL_DOWNTIME, 
                   TOTAL_AVAILABILITY_N, TOTAL_AVAILABILITY_D
            FROM {TABLES['availability']}
            WHERE {date_filter}  {base_filter}
        ),
        site_data AS (
            SELECT SITE_ID,
                   SITE_ID_FOCUS_CATEGORY,
                   SUM(TOTAL_DOWNTIME) as CATEGORY_DOWNTIME
            FROM base_data
            GROUP BY SITE_ID, SITE_ID_FOCUS_CATEGORY
        ),
        dominant_category AS (
            SELECT SITE_ID,
                   SITE_ID_FOCUS_CATEGORY as FOCUS_CATEGORY,
                   ROW_NUMBER() OVER (PARTITION BY SITE_ID ORDER BY CATEGORY_DOWNTIME DESC) as rn
            FROM site_data
        )
        SELECT b.SITE_ID as ENTITY_ID, b.SITE_ID as ENTITY_NAME,
               SUM(b.TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
               SUM(b.TOTAL_AVAILABILITY_N) / NULLIF(SUM(b.TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY,
               MAX(dc.FOCUS_CATEGORY) as FOCUS_CATEGORY
        FROM base_data b
        LEFT JOIN dominant_category dc ON b.SITE_ID = dc.SITE_ID AND dc.rn = 1
        GROUP BY b.SITE_ID
        HAVING SUM(b.TOTAL_DOWNTIME) > 0
        ORDER BY TOTAL_DOWNTIME DESC
        LIMIT 100
        """
    else:
        # Get market-level data with region
        query = f"""
        SELECT MARKET_ID as ENTITY_ID, MARKET_ID as ENTITY_NAME,
               SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
               SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVG_AVAILABILITY,
               MAX(REGION_ID) as REGION_ID
        FROM {TABLES['availability']}
        WHERE {date_filter}  {base_filter}
        GROUP BY MARKET_ID
        HAVING SUM(TOTAL_DOWNTIME) > 0
        ORDER BY TOTAL_DOWNTIME DESC
        """
    return run_query(conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_cottr_scatter_data(_conn, days=7, filters=None, by_site=False):
    """Get data for COTTR scatter chart - markets or sites with outage minutes and impacted subs"""
    conn = _conn
    cottr_filter = build_filter_clause(filters, 'cottr')
    cm_filter = build_filter_clause(filters, 'customer_minutes')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    date_filter_cottr = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_cm = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Build CM CTE with site_type filtering
    if site_type:
        cm_filter_aliased = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
        site_type_sql = get_site_type_sql_filter(site_type)
        cm_site_cte = f"""
        cm_data AS (
            SELECT cm.SITE_ID as ENTITY_ID,
                   SUM(cm.TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
            FROM {TABLES['customer_minutes']} cm
            INNER JOIN (
                SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
                WHERE {date_filter_avail} AND {site_type_sql}
            ) st ON cm.SITE_ID = st.SITE_ID
            WHERE {date_filter_cm.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')} {cm_filter_aliased}
            GROUP BY cm.SITE_ID
        )"""
        cm_market_cte = f"""
        cm_data AS (
            SELECT cm.MARKET as ENTITY_ID,
                   SUM(cm.TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
            FROM {TABLES['customer_minutes']} cm
            INNER JOIN (
                SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
                WHERE {date_filter_avail} AND {site_type_sql}
            ) st ON cm.SITE_ID = st.SITE_ID
            WHERE {date_filter_cm.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')} {cm_filter_aliased}
            GROUP BY cm.MARKET
        )"""
    else:
        cm_site_cte = f"""
        cm_data AS (
            SELECT SITE_ID as ENTITY_ID,
                   SUM(TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
            FROM {TABLES['customer_minutes']}
            WHERE {date_filter_cm} {cm_filter}
            GROUP BY SITE_ID
        )"""
        cm_market_cte = f"""
        cm_data AS (
            SELECT MARKET as ENTITY_ID,
                   SUM(TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
            FROM {TABLES['customer_minutes']}
            WHERE {date_filter_cm} {cm_filter}
            GROUP BY MARKET
        )"""
    
    if by_site:
        # Get site-level data when a market is selected - join COTTR with Customer Minutes and include focus category
        query = f"""
        WITH cottr_data AS (
            SELECT SITE_CD as ENTITY_ID,
                   SITE_ID_FOCUS_CATEGORY,
                   SUM(PER_DAY_OUTAGE_MINUTES) as CATEGORY_OUTAGE_MINUTES
            FROM {TABLES['cottr']}
            WHERE {date_filter_cottr}
              AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
              {cottr_filter}
            GROUP BY SITE_CD, SITE_ID_FOCUS_CATEGORY
        ),
        cottr_totals AS (
            SELECT ENTITY_ID,
                   SUM(CATEGORY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINUTES
            FROM cottr_data
            GROUP BY ENTITY_ID
            HAVING SUM(CATEGORY_OUTAGE_MINUTES) > 0
        ),
        dominant_category AS (
            SELECT ENTITY_ID,
                   SITE_ID_FOCUS_CATEGORY as FOCUS_CATEGORY,
                   ROW_NUMBER() OVER (PARTITION BY ENTITY_ID ORDER BY CATEGORY_OUTAGE_MINUTES DESC) as rn
            FROM cottr_data
        ),
        {cm_site_cte}
        SELECT c.ENTITY_ID, c.ENTITY_ID as ENTITY_NAME,
               c.TOTAL_OUTAGE_MINUTES,
               COALESCE(cm.IMPACTED_SUBS, 0) as IMPACTED_SUBS,
               dc.FOCUS_CATEGORY
        FROM cottr_totals c
        LEFT JOIN cm_data cm ON c.ENTITY_ID = cm.ENTITY_ID
        LEFT JOIN dominant_category dc ON c.ENTITY_ID = dc.ENTITY_ID AND dc.rn = 1
        ORDER BY c.TOTAL_OUTAGE_MINUTES DESC
        LIMIT 100
        """
    else:
        # Get market-level data with region - need to map market names between tables
        # Use aggregation after join to prevent duplicates from fuzzy matching
        query = f"""
        WITH cottr_data AS (
            SELECT MKT_NAME as ENTITY_ID,
                   MAX(REGION_ID) as REGION_ID,
                   SUM(PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINUTES
            FROM {TABLES['cottr']}
            WHERE {date_filter_cottr}
              AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
              {cottr_filter}
            GROUP BY MKT_NAME
            HAVING SUM(PER_DAY_OUTAGE_MINUTES) > 0
        ),
        {cm_market_cte},
        joined_data AS (
            SELECT c.ENTITY_ID, c.ENTITY_ID as ENTITY_NAME,
                   c.REGION_ID,
                   c.TOTAL_OUTAGE_MINUTES,
                   cm.IMPACTED_SUBS
            FROM cottr_data c
            LEFT JOIN cm_data cm ON UPPER(c.ENTITY_ID) LIKE '%' || UPPER(SPLIT_PART(cm.ENTITY_ID, ' ', 1)) || '%'
               OR UPPER(cm.ENTITY_ID) LIKE '%' || UPPER(SPLIT_PART(c.ENTITY_ID, ' ', 1)) || '%'
        )
        SELECT ENTITY_ID, ENTITY_NAME,
               MAX(TOTAL_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINUTES,
               MAX(COALESCE(IMPACTED_SUBS, 0)) as IMPACTED_SUBS,
               MAX(REGION_ID) as REGION_ID
        FROM joined_data
        GROUP BY ENTITY_ID, ENTITY_NAME
        ORDER BY TOTAL_OUTAGE_MINUTES DESC
        """
    return run_query(conn, query)

def get_market_by_focus_category(conn, days=7, filters=None):
    """Get availability market data broken down by focus category - uses cached version"""
    filters_hash = filters_to_hashable(filters)
    return get_market_by_focus_category_cached(conn, days, filters_hash)

def get_market_by_summary_category(conn, days=7, filters=None):
    """Get availability market data broken down by summary category - uses cached version"""
    filters_hash = filters_to_hashable(filters)
    return get_market_by_summary_category_cached(conn, days, filters_hash)

def get_cottr_market_by_focus_category(conn, days=7, filters=None):
    """Get COTTR market data broken down by focus category - uses cached version"""
    filters_hash = filters_to_hashable(filters)
    return get_cottr_market_by_focus_category_cached(conn, days, filters_hash)

def get_impacted_subs_by_market(conn, days=7, filters=None):
    """Get impacted subscribers by market - uses cached version"""
    filters_hash = filters_to_hashable(filters)
    return get_impacted_subs_by_market_cached(conn, days, filters_hash)

def get_impacted_subs_by_market_and_category(conn, days=7, filters=None):
    """Get impacted subscribers by market and OEM - uses cached version"""
    filters_hash = filters_to_hashable(filters)
    return get_impacted_subs_by_market_and_category_cached(conn, days, filters_hash)

def get_top_sites_impacted_subs(conn, days=7, filters=None):
    """Get top sites by impacted subs with focus category and daily data for sparklines"""
    cm_filter = build_filter_clause(filters, 'customer_minutes')
    avail_filter = build_filter_clause(filters, 'availability')
    # For COTTR category lookup by site, don't apply site_type or market filters 
    # since we're already filtering by specific site IDs - we want ALL category data for those sites
    cottr_filters_for_sites = {k: v for k, v in (filters or {}).items() if k not in ('site_type', 'market')}
    cottr_filter = build_filter_clause(cottr_filters_for_sites, 'cottr')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    date_filter_cm = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_cottr = f"PER_DAY_LOCAL_DATE >= '{start_date}' AND PER_DAY_LOCAL_DATE <= '{end_date}'" if start_date and end_date else f"PER_DAY_LOCAL_DATE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Get top sites by impacted subs - with site_type filtering
    if site_type:
        cm_filter_aliased = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
        query = f"""
        SELECT 
            cm.SITE_ID,
            SUM(cm.TOTAL_IMPACTED_SUB_CNT) as TOTAL_IMPACTED_SUBS,
            SUM(cm.IMPACT_DURATION_IN_MINS) as TOTAL_CUSTOMER_MINUTES
        FROM {TABLES['customer_minutes']} cm
        INNER JOIN (
            SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
            WHERE {date_filter_avail} AND {get_site_type_sql_filter(site_type)}
        ) st ON cm.SITE_ID = st.SITE_ID
        WHERE {date_filter_cm.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')}
          AND cm.SITE_ID IS NOT NULL
          {cm_filter_aliased}
        GROUP BY cm.SITE_ID
        HAVING SUM(cm.TOTAL_IMPACTED_SUB_CNT) > 0
        ORDER BY TOTAL_IMPACTED_SUBS DESC
        LIMIT 10
        """
    else:
        query = f"""
        SELECT 
            SITE_ID,
            SUM(TOTAL_IMPACTED_SUB_CNT) as TOTAL_IMPACTED_SUBS,
            SUM(IMPACT_DURATION_IN_MINS) as TOTAL_CUSTOMER_MINUTES
        FROM {TABLES['customer_minutes']}
        WHERE {date_filter_cm}
          AND SITE_ID IS NOT NULL
          {cm_filter}
        GROUP BY SITE_ID
        HAVING SUM(TOTAL_IMPACTED_SUB_CNT) > 0
        ORDER BY TOTAL_IMPACTED_SUBS DESC
        LIMIT 10
        """
    top_sites = run_query(conn, query)
    
    # Get daily data and category breakdowns for top sites
    if not top_sites.empty:
        site_list = "', '".join(top_sites['SITE_ID'].tolist())
        
        # Daily data for sparklines - no site_type filter needed since we already filtered top sites
        daily_query = f"""
        SELECT 
            SITE_ID,
            LOCAL_DATE_PART as DATE_VALUE,
            SUM(TOTAL_IMPACTED_SUB_CNT) as DAILY_IMPACTED_SUBS,
            SUM(IMPACT_DURATION_IN_MINS) as DAILY_CUSTOMER_MINUTES
        FROM {TABLES['customer_minutes']}
        WHERE {date_filter_cm}
          AND SITE_ID IN ('{site_list}')
          {cm_filter}
        GROUP BY SITE_ID, LOCAL_DATE_PART
        ORDER BY SITE_ID, LOCAL_DATE_PART
        """
        daily_data = run_query(conn, daily_query)
        
        # Get availability summary category breakdown per site
        avail_cat_query = f"""
        SELECT SITE_ID,
               SITE_ID_SUMMARY_CATEGORY,
               SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME
        FROM {TABLES['availability']}
        WHERE {date_filter_avail} 
          AND SITE_ID IN ('{site_list}')
          {avail_filter}
        GROUP BY SITE_ID, SITE_ID_SUMMARY_CATEGORY
        """
        avail_cat_data = run_query(conn, avail_cat_query)
        
        # Get COTTR summary category breakdown per site
        cottr_cat_query = f"""
        SELECT SITE_CD as SITE_ID,
               SITE_ID_FOCUS_CATEGORY,
               SUM(PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINS
        FROM {TABLES['cottr']}
        WHERE {date_filter_cottr} 
          AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
          AND SITE_CD IN ('{site_list}')
          {cottr_filter}
        GROUP BY SITE_CD, SITE_ID_FOCUS_CATEGORY
        """
        cottr_cat_data = run_query(conn, cottr_cat_query)
        
        return top_sites, daily_data, avail_cat_data, cottr_cat_data
    return top_sites, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def get_top_sites_customer_minutes(conn, days=7, filters=None):
    """Get top sites by customer minutes with focus category and daily data for sparklines"""
    cm_filter = build_filter_clause(filters, 'customer_minutes')
    avail_filter = build_filter_clause(filters, 'availability')
    # For COTTR category lookup by site, don't apply site_type or market filters 
    # since we're already filtering by specific site IDs - we want ALL category data for those sites
    cottr_filters_for_sites = {k: v for k, v in (filters or {}).items() if k not in ('site_type', 'market')}
    cottr_filter = build_filter_clause(cottr_filters_for_sites, 'cottr')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    date_filter_cm = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_cottr = f"PER_DAY_LOCAL_DATE >= '{start_date}' AND PER_DAY_LOCAL_DATE <= '{end_date}'" if start_date and end_date else f"PER_DAY_LOCAL_DATE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Get top sites by customer minutes - with site_type filtering
    if site_type:
        cm_filter_aliased = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
        query = f"""
        SELECT 
            cm.SITE_ID,
            SUM(cm.IMPACT_DURATION_IN_MINS) as TOTAL_CUSTOMER_MINUTES,
            SUM(cm.TOTAL_IMPACTED_SUB_CNT) as TOTAL_IMPACTED_SUBS
        FROM {TABLES['customer_minutes']} cm
        INNER JOIN (
            SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
            WHERE {date_filter_avail} AND {get_site_type_sql_filter(site_type)}
        ) st ON cm.SITE_ID = st.SITE_ID
        WHERE {date_filter_cm.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')}
          AND cm.SITE_ID IS NOT NULL
          {cm_filter_aliased}
        GROUP BY cm.SITE_ID
        HAVING SUM(cm.IMPACT_DURATION_IN_MINS) > 0
        ORDER BY TOTAL_CUSTOMER_MINUTES DESC
        LIMIT 10
        """
    else:
        query = f"""
        SELECT 
            SITE_ID,
            SUM(IMPACT_DURATION_IN_MINS) as TOTAL_CUSTOMER_MINUTES,
            SUM(TOTAL_IMPACTED_SUB_CNT) as TOTAL_IMPACTED_SUBS
        FROM {TABLES['customer_minutes']}
        WHERE {date_filter_cm}
          AND SITE_ID IS NOT NULL
          {cm_filter}
        GROUP BY SITE_ID
        HAVING SUM(IMPACT_DURATION_IN_MINS) > 0
        ORDER BY TOTAL_CUSTOMER_MINUTES DESC
        LIMIT 10
        """
    top_sites = run_query(conn, query)
    
    # Get daily data for sparklines and category breakdowns for top sites
    if not top_sites.empty:
        site_list = "', '".join(top_sites['SITE_ID'].tolist())
        
        # Daily customer minutes data - no site_type filter needed since we already filtered top sites
        daily_query = f"""
        SELECT 
            SITE_ID,
            LOCAL_DATE_PART as DATE_VALUE,
            SUM(IMPACT_DURATION_IN_MINS) as DAILY_CUSTOMER_MINUTES,
            SUM(TOTAL_IMPACTED_SUB_CNT) as DAILY_IMPACTED_SUBS
        FROM {TABLES['customer_minutes']}
        WHERE {date_filter_cm}
          AND SITE_ID IN ('{site_list}')
          {cm_filter}
        GROUP BY SITE_ID, LOCAL_DATE_PART
        ORDER BY SITE_ID, LOCAL_DATE_PART
        """
        daily_data = run_query(conn, daily_query)
        
        # Get availability summary category breakdown per site
        avail_cat_query = f"""
        SELECT SITE_ID,
               SITE_ID_SUMMARY_CATEGORY,
               SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME
        FROM {TABLES['availability']}
        WHERE {date_filter_avail} 
          AND SITE_ID IN ('{site_list}')
          {avail_filter}
        GROUP BY SITE_ID, SITE_ID_SUMMARY_CATEGORY
        """
        avail_cat_data = run_query(conn, avail_cat_query)
        
        # Get COTTR summary category breakdown per site (map focus to summary)
        cottr_cat_query = f"""
        SELECT SITE_CD as SITE_ID,
               SITE_ID_FOCUS_CATEGORY,
               SUM(PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINS
        FROM {TABLES['cottr']}
        WHERE {date_filter_cottr} 
          AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
          AND SITE_CD IN ('{site_list}')
          {cottr_filter}
        GROUP BY SITE_CD, SITE_ID_FOCUS_CATEGORY
        """
        cottr_cat_data = run_query(conn, cottr_cat_query)
        
        return top_sites, daily_data, avail_cat_data, cottr_cat_data
    return top_sites, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def get_market_comparison(conn):
    """Compare market names across all three data sources"""
    
    # Build exclusion list for SQL
    excluded_list = "', '".join(EXCLUDED_MARKETS)
    
    # Get distinct markets from each table (excluding Labmarket and Emergency Management)
    avail_query = f"""
    SELECT DISTINCT MARKET_ID as MARKET_NAME, 'Availability' as SOURCE
    FROM {TABLES['availability']}
    WHERE MARKET_ID IS NOT NULL
      AND UPPER(MARKET_ID) NOT IN (SELECT UPPER(val) FROM (VALUES {', '.join([f"('{m}')" for m in EXCLUDED_MARKETS])} AS t(val)))
    """
    
    cottr_query = f"""
    SELECT DISTINCT MKT_NAME as MARKET_NAME, 'COTTR' as SOURCE
    FROM {TABLES['cottr']}
    WHERE MKT_NAME IS NOT NULL
    """
    
    cm_query = f"""
    SELECT DISTINCT MARKET as MARKET_NAME, 'Customer_Minutes' as SOURCE
    FROM {TABLES['customer_minutes']}
    WHERE MARKET IS NOT NULL
    """
    
    avail_markets = run_query(conn, avail_query)
    cottr_markets = run_query(conn, cottr_query)
    cm_markets = run_query(conn, cm_query)
    
    # Filter out excluded markets from availability results (in case SQL didn't catch all)
    if not avail_markets.empty:
        avail_markets = avail_markets[~avail_markets['MARKET_NAME'].str.upper().isin([m.upper() for m in EXCLUDED_MARKETS])]
    
    return avail_markets, cottr_markets, cm_markets

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_exec_summary_kpis_fast(_conn, start_date, end_date, days, site_type, market_filter_sql, oem_filter):
    """FAST KPI query - single query for all 3 KPI totals"""
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    site_type_filter = get_site_type_sql_filter(site_type) if site_type else "1=1"
    
    # Single fast query for availability KPIs
    if oem_filter:
        avail_query = f"""
        SELECT SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME, SUM(TOTAL_AVAILABILITY_N) as TOTAL_N, SUM(TOTAL_AVAILABILITY_D) as TOTAL_D
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter.replace('DATE_VALUE', 'a.DATE_VALUE')} AND {site_type_filter.replace('SITE_TYPE', 'a.SITE_TYPE')} AND mt.M_OEM = '{oem_filter}' {market_filter_sql}
        """
    else:
        avail_query = f"""
        SELECT SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME, SUM(TOTAL_AVAILABILITY_N) as TOTAL_N, SUM(TOTAL_AVAILABILITY_D) as TOTAL_D
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {market_filter_sql}
        """
    return run_query(_conn, avail_query)

def executive_summary_dashboard_v2(conn, days, filters=None):
    """Executive Summary V2 - Experimental version for testing changes
    
    This is a duplicate of the Executive Summary dashboard for testing modifications.
    Changes made here won't affect the original Executive Summary tab.
    """
    
    market = get_market_display_name(filters.get('market') if filters else None)
    
    # Get market abbreviation using cached lookup (single query instead of 4)
    market_display = get_market_abbreviation_cached(conn, market) if market else market
    oem_filter = filters.get('oem') if filters else None
    
    # Build header with V2 indicator
    if market:
        header_text = f"🧪 Executive Summary V2 - {market}"
    elif oem_filter:
        header_text = f"🧪 Executive Summary V2 - All Markets <span style='color: #e20074; font-size: 0.8em;'>({oem_filter})</span>"
    else:
        header_text = "🧪 Executive Summary V2 - All Markets"
    st.markdown(f'<div class="section-header">{header_text}</div>', unsafe_allow_html=True)
    
    st.info("📝 **V2 Experimental Dashboard** - Tell me what changes you'd like to test here. This won't affect the original Executive Summary.")
    
    filters_no_focus = {k: v for k, v in (filters or {}).items() if k != 'focus_category'}
    selected_focus_category = filters.get('focus_category') if filters else None
    
    with st.spinner("Loading data..."):
        cm_daily, avail_daily, cottr_daily = get_combined_daily_data(conn, days, filters)
        focus_cat_totals = get_focus_category_totals(conn, days, filters)
        focus_cottr_totals = get_focus_category_totals_cottr(conn, days, filters)
        market_by_cat = get_market_by_focus_category(conn, days, filters)
        market_by_summary_cat = get_market_by_summary_category(conn, days, filters)
        cottr_market_by_cat = get_cottr_market_by_focus_category(conn, days, filters)
        
        if selected_focus_category:
            focus_cat_totals_unfiltered = get_focus_category_totals(conn, days, filters_no_focus)
            focus_cottr_totals_unfiltered = get_focus_category_totals_cottr(conn, days, filters_no_focus)
            market_by_summary_cat_unfiltered = get_market_by_summary_category(conn, days, filters_no_focus)
            cottr_market_by_cat_unfiltered = get_cottr_market_by_focus_category(conn, days, filters_no_focus)
    
    # ===== V2 KPI SECTION - MODIFY AS NEEDED =====
    st.markdown("### 🎯 Key Performance Indicators")
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    total_cm = float(cm_daily['CUSTOMER_MINUTES'].sum()) if not cm_daily.empty else 0
    total_subs = float(cm_daily['IMPACTED_SUBS'].sum()) if not cm_daily.empty else 0
    
    # Calculate aggregate availability
    total_d = 0
    if not avail_daily.empty and 'TOTAL_AVAILABILITY_N' in avail_daily.columns and 'TOTAL_AVAILABILITY_D' in avail_daily.columns:
        total_n = float(avail_daily['TOTAL_AVAILABILITY_N'].sum())
        total_d = float(avail_daily['TOTAL_AVAILABILITY_D'].sum())
        avg_avail = (total_n / total_d * 100) if total_d > 0 else 0
    else:
        avg_avail = float(avail_daily['AVG_AVAILABILITY_PCT'].mean()) if not avail_daily.empty else 0
    
    total_downtime = float(avail_daily['TOTAL_DOWNTIME'].sum()) if not avail_daily.empty else 0
    total_outages = float(cottr_daily['OUTAGE_COUNT'].sum()) if not cottr_daily.empty else 0
    total_outage_mins = float(cottr_daily['OUTAGE_MINUTES'].sum()) if not cottr_daily.empty else 0
    
    # Calculate unavailability %
    unavail_pct = 100 - avg_avail
    
    with col1:
        render_kpi_card_with_sparkline("Daily Availability %", f"{avg_avail:.2f}%", avail_daily, 'DATE_VALUE', 'AVG_AVAILABILITY_PCT', "All In Availability", "green", format_large=False, goal_value=99.85, key_prefix="v2_kpi", show_sparkline=True)
    with col2:
        render_kpi_card_with_sparkline("Unavailability", f"{unavail_pct:.2f}%", avail_daily, 'DATE_VALUE', 'TOTAL_DOWNTIME', "All In Availability", "green", format_large=False, key_prefix="v2_kpi", show_sparkline=True)
    with col3:
        render_kpi_card_with_sparkline("Service Outage Events", total_outages, cottr_daily, 'DATE_VALUE', 'OUTAGE_COUNT', "COTTR", "orange", key_prefix="v2_kpi", show_sparkline=True)
    with col4:
        render_kpi_card_with_sparkline("Service Outage Minutes", total_outage_mins, cottr_daily, 'DATE_VALUE', 'OUTAGE_MINUTES', "COTTR", "orange", key_prefix="v2_kpi", show_sparkline=True)
    with col5:
        render_kpi_card_with_sparkline("Customer Minutes", total_cm, cm_daily, 'DATE_VALUE', 'CUSTOMER_MINUTES', "Customer Minutes V2", "magenta", key_prefix="v2_kpi", show_sparkline=True)
    with col6:
        render_kpi_card_with_sparkline("Impacted Subscribers", total_subs, cm_daily, 'DATE_VALUE', 'IMPACTED_SUBS', "Customer Minutes V2", "magenta", key_prefix="v2_kpi", show_sparkline=True)
    
    st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)
    
    # ===== V2 PLACEHOLDER FOR ADDITIONAL CONTENT =====
    st.markdown("---")
    st.markdown("### 📊 Additional V2 Content")
    st.markdown("*Tell me what changes or new sections you'd like to add here.*")
    
    # Show data summary for reference
    with st.expander("📋 Data Summary (for reference)"):
        data_cols = st.columns(3)
        with data_cols[0]:
            st.markdown("**Availability Data**")
            if not avail_daily.empty:
                st.dataframe(avail_daily.head(10), use_container_width=True)
            else:
                st.info("No availability data")
        with data_cols[1]:
            st.markdown("**COTTR Data**")
            if not cottr_daily.empty:
                st.dataframe(cottr_daily.head(10), use_container_width=True)
            else:
                st.info("No COTTR data")
        with data_cols[2]:
            st.markdown("**Customer Minutes Data**")
            if not cm_daily.empty:
                st.dataframe(cm_daily.head(10), use_container_width=True)
            else:
                st.info("No customer minutes data")

def executive_summary_dashboard(conn, days, filters=None):
    """Combined Executive Summary with all 3 KPIs"""
    
    market = get_market_display_name(filters.get('market') if filters else None)
    
    # Get market abbreviation using cached lookup (single query instead of 4)
    market_display = get_market_abbreviation_cached(conn, market) if market else market
    oem_filter = filters.get('oem') if filters else None
    
    # Build header with OEM indicator if filtered
    if market:
        header_text = f"📊 Executive Summary - {market}"
    elif oem_filter:
        header_text = f"📊 Executive Summary - All Markets <span style='color: #e20074; font-size: 0.8em;'>({oem_filter})</span>"
    else:
        header_text = "📊 Executive Summary - All Markets"
    st.markdown(f'<div class="section-header">{header_text}</div>', unsafe_allow_html=True)
    
    filters_no_focus = {k: v for k, v in (filters or {}).items() if k != 'focus_category'}
    selected_focus_category = filters.get('focus_category') if filters else None
    
    with st.spinner("Loading data..."):
        cm_daily, avail_daily, cottr_daily = get_combined_daily_data(conn, days, filters)
        focus_cat_totals = get_focus_category_totals(conn, days, filters)
        focus_cottr_totals = get_focus_category_totals_cottr(conn, days, filters)
        market_by_cat = get_market_by_focus_category(conn, days, filters)
        market_by_summary_cat = get_market_by_summary_category(conn, days, filters)
        cottr_market_by_cat = get_cottr_market_by_focus_category(conn, days, filters)
        cottr_by_summary = get_cottr_by_summary_category(conn, days, filters)
        avail_summary_df, downtime_by_summary_df = get_availability_with_downtime_by_summary(conn, days, filters)

        if selected_focus_category:
            focus_cat_totals_unfiltered = get_focus_category_totals(conn, days, filters_no_focus)
            focus_cottr_totals_unfiltered = get_focus_category_totals_cottr(conn, days, filters_no_focus)
            market_by_summary_cat_unfiltered = get_market_by_summary_category(conn, days, filters_no_focus)
            cottr_market_by_cat_unfiltered = get_cottr_market_by_focus_category(conn, days, filters_no_focus)
        else:
            focus_cat_totals_unfiltered = focus_cat_totals
            focus_cottr_totals_unfiltered = focus_cottr_totals
            market_by_summary_cat_unfiltered = market_by_summary_cat
            cottr_market_by_cat_unfiltered = None

        # Normalize market names
        if not market_by_cat.empty and 'MARKET_ID' in market_by_cat.columns:
            market_by_cat = normalize_market_column(market_by_cat, 'MARKET_ID', 'availability')
        if not market_by_summary_cat.empty and 'MARKET_ID' in market_by_summary_cat.columns:
            market_by_summary_cat = normalize_market_column(market_by_summary_cat, 'MARKET_ID', 'availability')
        if not cottr_market_by_cat.empty and 'MARKET_ID' in cottr_market_by_cat.columns:
            cottr_market_by_cat = normalize_market_column(cottr_market_by_cat, 'MARKET_ID', 'cottr')
        if selected_focus_category and cottr_market_by_cat_unfiltered is not None and not cottr_market_by_cat_unfiltered.empty and 'MARKET_ID' in cottr_market_by_cat_unfiltered.columns:
            cottr_market_by_cat_unfiltered = normalize_market_column(cottr_market_by_cat_unfiltered, 'MARKET_ID', 'cottr')

    if market:
        market_totals = pd.DataFrame()
        market_totals_unfiltered = pd.DataFrame()
        impacted_subs_by_market = pd.DataFrame()
        impacted_subs_by_market_cat = pd.DataFrame()
        market_daily_avail = pd.DataFrame()

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_cm = executor.submit(get_top_sites_customer_minutes, conn, days, filters)
            future_impacted = executor.submit(get_top_sites_impacted_subs, conn, days, filters)
            top_sites_cm, top_sites_cm_daily, top_sites_cm_avail_cat, top_sites_cm_cottr_cat = future_cm.result()
            top_sites_impacted, top_sites_impacted_daily, top_sites_impacted_avail_cat, top_sites_impacted_cottr_cat = future_impacted.result()
    else:
        market_totals = get_market_totals(conn, days, filters)
        impacted_subs_by_market = get_impacted_subs_by_market(conn, days, filters)
        impacted_subs_by_market_cat = get_impacted_subs_by_market_and_category(conn, days, filters)
        market_daily_avail = get_market_daily_availability(conn, days, filters)

        if not market_totals.empty and 'MARKET_ID' in market_totals.columns:
            market_totals = normalize_market_column(market_totals, 'MARKET_ID', 'availability')
        if not market_daily_avail.empty and 'MARKET_ID' in market_daily_avail.columns:
            market_daily_avail = normalize_market_column(market_daily_avail, 'MARKET_ID', 'availability')
        if not impacted_subs_by_market.empty and 'MARKET' in impacted_subs_by_market.columns:
            impacted_subs_by_market = normalize_market_column(impacted_subs_by_market, 'MARKET', 'customer_minutes')
        if not impacted_subs_by_market_cat.empty and 'MARKET' in impacted_subs_by_market_cat.columns:
            impacted_subs_by_market_cat = normalize_market_column(impacted_subs_by_market_cat, 'MARKET', 'customer_minutes')

        if selected_focus_category:
            market_totals_unfiltered = get_market_totals(conn, days, filters_no_focus)
        else:
            market_totals_unfiltered = market_totals
        top_sites_cm, top_sites_cm_daily, top_sites_cm_avail_cat, top_sites_cm_cottr_cat = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        top_sites_impacted, top_sites_impacted_daily, top_sites_impacted_avail_cat, top_sites_impacted_cottr_cat = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    # ===== DATA VALIDATION =====
    # Run automated checks to flag any data inconsistencies
    validate_executive_summary_data(cm_daily, avail_daily, cottr_daily, focus_cat_totals, market_by_cat)
    validate_market_comparison_data(market_by_cat, cottr_market_by_cat)
    if data_validator.has_issues():
        data_validator.display_messages()
    
    # KPI Cards with Sparklines
    st.markdown("### 🎯 Key Performance Indicators")
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    total_cm = float(cm_daily['CUSTOMER_MINUTES'].sum()) if not cm_daily.empty else 0
    total_subs = float(cm_daily['IMPACTED_SUBS'].sum()) if not cm_daily.empty else 0
    # Calculate aggregate availability: SUM(N) / SUM(D) * 100
    total_d = 0
    if not avail_daily.empty and 'TOTAL_AVAILABILITY_N' in avail_daily.columns and 'TOTAL_AVAILABILITY_D' in avail_daily.columns:
        total_n = float(avail_daily['TOTAL_AVAILABILITY_N'].sum())
        total_d = float(avail_daily['TOTAL_AVAILABILITY_D'].sum())
        avg_avail = (total_n / total_d * 100) if total_d > 0 else 0
    else:
        avg_avail = float(avail_daily['AVG_AVAILABILITY_PCT'].mean()) if not avail_daily.empty else 0
    total_downtime = float(avail_daily['TOTAL_DOWNTIME'].sum()) if not avail_daily.empty else 0
    total_outages = float(cottr_daily['OUTAGE_COUNT'].sum()) if not cottr_daily.empty else 0
    total_outage_mins = float(cottr_daily['OUTAGE_MINUTES'].sum()) if not cottr_daily.empty else 0
    
    # Calculate daily downtime threshold for 99.85% availability (0.15% of daily availability denominator)
    # Use average daily TOTAL_AVAILABILITY_D to calculate the daily threshold
    if not avail_daily.empty and 'TOTAL_AVAILABILITY_D' in avail_daily.columns:
        avg_daily_d = float(avail_daily['TOTAL_AVAILABILITY_D'].mean())
        daily_downtime_threshold = 0.0015 * avg_daily_d if avg_daily_d > 0 else None
        total_seconds_allowed = 0.0015 * total_d if total_d > 0 else 0
        over_under = total_downtime - total_seconds_allowed
    else:
        daily_downtime_threshold = None
        total_seconds_allowed = 0
        over_under = 0
    downtime_threshold_label = f"Goal: {format_number(daily_downtime_threshold)}" if daily_downtime_threshold else None
    
    # Calculate days meeting goal for availability stats
    days_meeting_goal = 0
    total_days = 0
    if not avail_daily.empty and 'AVG_AVAILABILITY_PCT' in avail_daily.columns:
        total_days = len(avail_daily)
        days_meeting_goal = (avail_daily['AVG_AVAILABILITY_PCT'] >= 99.85).sum()
    goal_pct = (days_meeting_goal / total_days * 100) if total_days > 0 else 0
    
    # Order: Availability (left), COTTR (middle), Customer Mins (right)
    # Show sparklines for all views (including when market is selected)
    show_spark = True
    
    # Build top-right stats (always show days met and budget info)
    goal_color = "#22c55e" if goal_pct >= 80 else "#f59e0b" if goal_pct >= 50 else "#ef4444"
    avail_stats = {
        'line1': f"<b>{days_meeting_goal}/{total_days}</b> = {goal_pct:.0f}%",
        'line2': "Days ≥ 99.85%",
        'color1': goal_color
    }
    is_over = over_under > 0
    indicator_color = "#ef4444" if is_over else "#22c55e"
    over_under_label = f"+{format_number(over_under)}" if is_over else f"{format_number(over_under)}"
    
    # Calculate unavailability %
    unavail_pct = 100 - avg_avail
    unavail_goal = 0.15  # 100 - 99.85
    unavail_over = unavail_pct > unavail_goal
    unavail_color = "#ef4444" if unavail_over else "#22c55e"
    unavail_indicator = "Over" if unavail_over else "Under"
    
    downtime_stats = {
        'line1': f"Downtime: <b>{format_number(total_downtime)}</b> sec",
        'line2': f"<span style='color:#888888;'>Goal: 0.15%</span> <span style='color:{unavail_color}'>{unavail_indicator}</span>",
        'line3': f"Budget: <b>{format_number(total_seconds_allowed)}</b>",
        'line4': f"<b>{over_under_label}</b> {'🔴 Over' if is_over else '🟢 Under'}",
        'color1': '#22c55e',
        'color2': '#888888',
        'color4': indicator_color
    }
    
    with col1:
        render_kpi_card_with_sparkline("Daily Availability %", f"{avg_avail:.2f}%", avail_daily, 'DATE_VALUE', 'AVG_AVAILABILITY_PCT', "All In Availability", "green", format_large=False, goal_value=99.85, show_sparkline=show_spark, top_right_stats=avail_stats)
    with col2:
        render_kpi_card_with_sparkline("Unavailability", f"{unavail_pct:.2f}%", avail_daily, 'DATE_VALUE', 'TOTAL_DOWNTIME', "All In Availability", "green", format_large=False, goal_value=daily_downtime_threshold, goal_label=downtime_threshold_label, show_sparkline=show_spark, top_right_stats=downtime_stats)
    with col3:
        render_kpi_card_with_sparkline("Service Outage Events", total_outages, cottr_daily, 'DATE_VALUE', 'OUTAGE_COUNT', "COTTR", "orange", show_sparkline=show_spark)
    with col4:
        render_kpi_card_with_sparkline("Service Outage Minutes", total_outage_mins, cottr_daily, 'DATE_VALUE', 'OUTAGE_MINUTES', "COTTR", "orange", show_sparkline=show_spark)
    with col5:
        render_kpi_card_with_sparkline("Customer Minutes", total_cm, cm_daily, 'DATE_VALUE', 'CUSTOMER_MINUTES', "Customer Minutes V2", "magenta", show_sparkline=show_spark)
    with col6:
        render_kpi_card_with_sparkline("Impacted Subscribers", total_subs, cm_daily, 'DATE_VALUE', 'IMPACTED_SUBS', "Customer Minutes V2", "magenta", show_sparkline=show_spark)
    
    # Add spacing after KPI tiles (especially needed when sparklines are shown)
    st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)
    
    # ===== KEY INSIGHTS (sorted by largest, with % impact) =====
    # Add columns for insights - include Customer Minutes column
    # When market filtered: 4 columns (Avail Top Sites, COTTR Top Sites, Cust Mins Top Sites, Impacted Subs Top Sites)
    # When unfiltered: 4 columns (Availability, COTTR, Customer Minutes, Impacted Subs)
    if market:
        insight_col2, insight_col3, insight_col_cm, insight_col4 = st.columns(4)
        insight_col1 = None  # Not used when market filtered
    else:
        insight_col1, insight_col3, insight_col_cm, insight_col4 = st.columns(4)
        insight_col2 = None  # Not used when unfiltered
    
    # When a market filter is selected, show Top Sites
    # When no filter, show Focus Categories first, then Degraded Markets
    
    if insight_col1 is not None:
        with insight_col1:
            # UNFILTERED: Show Focus Categories as Treemap
            # Calculate summary category percentages for display
            summary_text = ""
            if not market_by_summary_cat.empty:
                summary_totals = market_by_summary_cat.groupby('SITE_ID_SUMMARY_CATEGORY')['TOTAL_DOWNTIME'].sum()
                summary_total = summary_totals.sum()
                if summary_total > 0:
                    pwr_pct = (summary_totals.get('Power', 0) / summary_total * 100)
                    ran_pct = (summary_totals.get('RAN', 0) / summary_total * 100)
                    trn_pct = (summary_totals.get('Transport', 0) / summary_total * 100)
                    summary_text = f"<div style='font-size:1rem;color:#000000;font-weight:600;margin-top:2px;'>Summary Categories: Power: {pwr_pct:.0f}% | RAN: {ran_pct:.0f}% | Transport: {trn_pct:.0f}%</div>"
            st.markdown(f"<div style='margin-bottom:5px;'><b>📉 Availability - Categories</b>{summary_text}</div>", unsafe_allow_html=True)
            
            # Build treemap data from focus categories
            if not focus_cat_totals.empty:
                focus_filtered = focus_cat_totals[~focus_cat_totals['SITE_ID_FOCUS_CATEGORY'].str.lower().str.contains('no outage', na=False)]
                focus_total = focus_filtered['TOTAL_DOWNTIME'].sum()
                
                if not focus_filtered.empty and focus_total > 0:
                    treemap_data = []
                    for _, row in focus_filtered.iterrows():
                        cat = row['SITE_ID_FOCUS_CATEGORY']
                        dt = float(row['TOTAL_DOWNTIME'])
                        cat_pct = (dt / focus_total * 100)
                        color = FOCUS_CATEGORY_COLORS.get(cat, DEFAULT_FOCUS_COLOR)
                        treemap_data.append({
                            'category': cat,
                            'value': dt,
                            'pct': cat_pct,
                            'color': color
                        })
                    
                    fig_treemap = go.Figure(go.Treemap(
                        labels=[f"{r['category']}<br>{r['pct']:.0f}%" for r in treemap_data],
                        parents=[''] * len(treemap_data),
                        values=[r['value'] for r in treemap_data],
                        marker=dict(colors=[r['color'] for r in treemap_data]),
                        textinfo='label',
                        textfont=dict(size=14, color='white'),
                        hovertemplate='<b>%{label}</b><br>Downtime: %{value:,.0f}<extra></extra>'
                    ))
                    fig_treemap.update_layout(
                        margin=dict(t=5, l=5, r=5, b=5),
                        height=250,
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)'
                    )
                    st.markdown("<div style='font-size:1rem;color:#000000;font-weight:600;margin-top:2px;margin-bottom:-15px;'>Focus Categories</div>", unsafe_allow_html=True)
                    st.plotly_chart(fig_treemap, use_container_width=True, config=CHART_CONFIG)
                else:
                    st.info("No category data available.")
            
            # Add Availability - Degraded Markets below Focus Categories (unfiltered only)
            # Add legend at top
            legend_html = '<div style="display:flex;gap:12px;margin-bottom:6px;font-size:0.75rem;">'
            legend_html += f'<span style="display:flex;align-items:center;"><span style="width:12px;height:12px;background:{SUMMARY_CATEGORY_COLORS["Power"]};border-radius:2px;margin-right:4px;"></span>Power</span>'
            legend_html += f'<span style="display:flex;align-items:center;"><span style="width:12px;height:12px;background:{SUMMARY_CATEGORY_COLORS["RAN"]};border-radius:2px;margin-right:4px;"></span>RAN</span>'
            legend_html += f'<span style="display:flex;align-items:center;"><span style="width:12px;height:12px;background:{SUMMARY_CATEGORY_COLORS["Transport"]};border-radius:2px;margin-right:4px;"></span>Transport</span>'
            legend_html += '</div>'
            st.markdown(f"**📍 Availability - Degraded Markets** {legend_html}", unsafe_allow_html=True)
            if not market_totals.empty and not market_by_summary_cat.empty:
                total_mkt_dt_for_pct = market_totals_unfiltered['TOTAL_DOWNTIME'].sum() if not market_totals_unfiltered.empty else market_totals['TOTAL_DOWNTIME'].sum()
                top_mkts = market_totals.head(20)
                display_categories = ['Power', 'RAN', 'Transport']
                
                # Collect all market HTML for scrollable container
                all_markets_html = '<div style="max-height:460px;overflow-y:auto;padding-right:5px;padding-bottom:15px;">'
                
                for _, row in top_mkts.iterrows():
                    mkt = row['MARKET_ID']
                    dt = float(row['TOTAL_DOWNTIME']) if row['TOTAL_DOWNTIME'] else 0
                    avail = float(row['AVG_AVAILABILITY']) if row['AVG_AVAILABILITY'] else 0
                    budget = float(row['SECONDS_BUDGET']) if 'SECONDS_BUDGET' in row and row['SECONDS_BUDGET'] else 0
                    over_under = float(row['OVER_UNDER']) if 'OVER_UNDER' in row and row['OVER_UNDER'] else 0
                    pct = (dt / total_mkt_dt_for_pct * 100) if total_mkt_dt_for_pct > 0 else 0
                    avail_color = "#22c55e" if avail >= 99.85 else "#f59e0b"
                    
                    mkt_all_cats_unfiltered = market_by_summary_cat_unfiltered[market_by_summary_cat_unfiltered['MARKET_ID'] == mkt]
                    mkt_total_unfiltered = mkt_all_cats_unfiltered['TOTAL_DOWNTIME'].sum()
                    
                    cat_pcts = {}
                    cat_colors = SUMMARY_CATEGORY_COLORS
                    for display_cat in display_categories:
                        cat_data = mkt_all_cats_unfiltered[mkt_all_cats_unfiltered['SITE_ID_SUMMARY_CATEGORY'] == display_cat]
                        if not cat_data.empty:
                            cat_dt = cat_data['TOTAL_DOWNTIME'].values[0]
                            cat_pcts[display_cat] = (cat_dt / mkt_total_unfiltered * 100) if mkt_total_unfiltered > 0 else 0
                        else:
                            cat_pcts[display_cat] = 0
                    
                    # Bar chart with % only (legend is at top of section)
                    bar_html = '<div style="display:flex;width:100%;height:22px;border-radius:4px;overflow:hidden;margin-top:4px;">'
                    for display_cat in display_categories:
                        pct_val = cat_pcts[display_cat]
                        color = cat_colors[display_cat]
                        inner_html = f'<span style="font-size:0.7rem;font-weight:600;">{pct_val:.0f}%</span>' if pct_val >= 10 else ''
                        bar_html += f'<div style="width:{pct_val}%;background:{color};display:flex;align-items:center;justify-content:center;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,0.5);" title="{display_cat}: {pct_val:.0f}%">{inner_html}</div>'
                    bar_html += '</div>'
                    
                    # Avail % display box (same format as COTTR)
                    avail_box_html = f'<div style="text-align:center;padding:6px 10px;background:#fff;border-radius:6px;border:1px solid #ddd;"><div style="font-size:1rem;font-weight:bold;color:{avail_color};">{avail:.2f}%</div><div style="font-size:0.65rem;color:#555;">Avail</div></div>'
                    
                    # Build complete HTML (same format as COTTR - no sparklines)
                    market_html = '<div class="market-box">'
                    market_html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">'
                    market_html += '<div style="flex:1;">'
                    over_under_color = "#ef4444" if over_under > 0 else "#22c55e"
                    over_under_sign = "+" if over_under > 0 else ""
                    market_html += f'<div style="font-size:0.8rem;">📍 <b>{mkt}</b>: ({pct:.1f}%) <span style="color:#666;font-size:0.7rem;">Budget: {format_number(budget)} | <span style="color:{over_under_color};">{over_under_sign}{format_number(over_under)}</span></span></div>'
                    market_html += bar_html
                    market_html += '</div>'
                    market_html += avail_box_html
                    market_html += '</div></div>'
                    
                    all_markets_html += market_html
                
                all_markets_html += '</div>'
                st.markdown(all_markets_html, unsafe_allow_html=True)
            else:
                st.info("No market data available.")
    
    # insight_col2 is only used when a market is selected
    if insight_col2 is not None:
        with insight_col2:
            if market:
                # FILTERED: Show Focus Categories as Treemap
                # Calculate summary category percentages for filtered market
                mkt_summary_text = ""
                if not market_by_summary_cat.empty:
                    mkt_summary_totals = market_by_summary_cat.groupby('SITE_ID_SUMMARY_CATEGORY')['TOTAL_DOWNTIME'].sum()
                    mkt_summary_total = mkt_summary_totals.sum()
                    if mkt_summary_total > 0:
                        pwr_pct = (mkt_summary_totals.get('Power', 0) / mkt_summary_total * 100)
                        ran_pct = (mkt_summary_totals.get('RAN', 0) / mkt_summary_total * 100)
                        trn_pct = (mkt_summary_totals.get('Transport', 0) / mkt_summary_total * 100)
                        mkt_summary_text = f"<div style='font-size:1rem;color:#000000;font-weight:600;margin-top:2px;'>Summary Categories: Power: {pwr_pct:.0f}% | RAN: {ran_pct:.0f}% | Transport: {trn_pct:.0f}%</div>"
                st.markdown(f"<div style='margin-bottom:5px;'><b>📉 Availability - Categories ({market_display})</b>{mkt_summary_text}</div>", unsafe_allow_html=True)
                
                # Build treemap data from focus categories
                if not focus_cat_totals.empty:
                    focus_filtered_mkt = focus_cat_totals[~focus_cat_totals['SITE_ID_FOCUS_CATEGORY'].str.lower().str.contains('no outage', na=False)]
                    focus_total_mkt = focus_filtered_mkt['TOTAL_DOWNTIME'].sum()
                    
                    if not focus_filtered_mkt.empty and focus_total_mkt > 0:
                        mkt_treemap_data = []
                        for _, row in focus_filtered_mkt.iterrows():
                            cat = row['SITE_ID_FOCUS_CATEGORY']
                            dt = float(row['TOTAL_DOWNTIME'])
                            cat_pct = (dt / focus_total_mkt * 100)
                            color = FOCUS_CATEGORY_COLORS.get(cat, DEFAULT_FOCUS_COLOR)
                            mkt_treemap_data.append({
                                'category': cat,
                                'value': dt,
                                'pct': cat_pct,
                                'color': color
                            })
                        
                        fig_mkt_treemap = go.Figure(go.Treemap(
                            labels=[f"{r['category']}<br>{r['pct']:.0f}%" for r in mkt_treemap_data],
                            parents=[''] * len(mkt_treemap_data),
                            values=[r['value'] for r in mkt_treemap_data],
                            marker=dict(colors=[r['color'] for r in mkt_treemap_data]),
                            textinfo='label',
                            textfont=dict(size=14, color='white'),
                            hovertemplate='<b>%{label}</b><br>Downtime: %{value:,.0f}<extra></extra>'
                        ))
                        fig_mkt_treemap.update_layout(
                            margin=dict(t=5, l=5, r=5, b=5),
                            height=350,
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)'
                        )
                        st.markdown("<div style='font-size:1rem;color:#000000;font-weight:600;margin-top:2px;margin-bottom:-15px;'>Focus Categories</div>", unsafe_allow_html=True)
                        st.plotly_chart(fig_mkt_treemap, use_container_width=True, config=CHART_CONFIG)
                    else:
                        st.info("No category data available.")
                else:
                    st.info("No category data available.")
                
                # Add Top 5 Sites by Availability Downtime when market is filtered
                start_date = filters.get('start_date') if filters else None
                end_date = filters.get('end_date') if filters else None
                
                # Calculate total days in the date range
                if start_date and end_date:
                    total_period_days = (datetime.strptime(end_date, '%Y-%m-%d') - datetime.strptime(start_date, '%Y-%m-%d')).days + 1
                else:
                    total_period_days = days
                
                # Use cached queries for better performance
                filters_hash = filters_to_hashable(filters)
                top_sites_avail_data = get_top_sites_avail_cached(conn, days, filters_hash)
                cottr_days_data = get_cottr_days_cached(conn, days, filters_hash)
                cottr_days_dict = dict(zip(cottr_days_data['SITE_ID'], cottr_days_data['COTTR_OUTAGE_DAYS'])) if not cottr_days_data.empty else {}
                
                site_avail_data = get_site_availability_cached(conn, days, filters_hash)
                site_avail_dict = dict(zip(site_avail_data['SITE_ID'], site_avail_data['AVG_AVAILABILITY'])) if not site_avail_data.empty else {}
                
                site_daily_data = get_site_daily_avail_cached(conn, days, filters_hash)
                
                if not top_sites_avail_data.empty:
                    # Aggregate by site and get total
                    site_totals = top_sites_avail_data.groupby('SITE_ID').agg({
                        'TOTAL_DOWNTIME': 'sum',
                        'AVAIL_DOWNTIME_DAYS': 'max',
                        'TOTAL_N': 'sum',
                        'TOTAL_D': 'sum'
                    }).reset_index()
                    site_totals = site_totals.sort_values('TOTAL_DOWNTIME', ascending=False)
                    total_all_sites = site_totals['TOTAL_DOWNTIME'].sum()
                    
                    # Calculate unavailability contribution for each site
                    main_total_d = site_totals['TOTAL_D'].sum()
                    if main_total_d > 0:
                        site_totals['SITE_UNAVAIL_SECONDS'] = site_totals['TOTAL_D'] - site_totals['TOTAL_N']
                        site_totals['UNAVAIL_CONTRIBUTION'] = site_totals['SITE_UNAVAIL_SECONDS'] / main_total_d * 100
                    else:
                        site_totals['UNAVAIL_CONTRIBUTION'] = 0
                    
                    top_5_sites = site_totals.head(5)
                    
                    # Calculate combined percentage of top 5 sites
                    top_5_total = top_5_sites['TOTAL_DOWNTIME'].sum()
                    top_5_pct = (top_5_total / total_all_sites * 100) if total_all_sites > 0 else 0
                    top_5_unavail_contrib = top_5_sites['UNAVAIL_CONTRIBUTION'].sum() if 'UNAVAIL_CONTRIBUTION' in top_5_sites.columns else 0
                    
                    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
                    st.markdown(f"**🔥 Top 5 Sites - Downtime ({top_5_pct:.1f}%)** <span style='font-size:0.85rem;color:#e20074;'>| Unavail Contribution: {top_5_unavail_contrib:.3f}%</span>", unsafe_allow_html=True)
                    for _, site_row in top_5_sites.iterrows():
                        site_id = site_row['SITE_ID']
                        site_dt = float(site_row['TOTAL_DOWNTIME']) if pd.notna(site_row['TOTAL_DOWNTIME']) else 0.0
                        site_pct = (site_dt / total_all_sites * 100) if total_all_sites > 0 else 0
                        site_unavail_contrib = float(site_row['UNAVAIL_CONTRIBUTION']) if 'UNAVAIL_CONTRIBUTION' in site_row and pd.notna(site_row['UNAVAIL_CONTRIBUTION']) else 0
                        avail_days = int(site_row['AVAIL_DOWNTIME_DAYS']) if pd.notna(site_row['AVAIL_DOWNTIME_DAYS']) else 0
                        cottr_days = int(cottr_days_dict.get(site_id, 0) or 0)
                        
                        # Get site availability percentage (handle None values)
                        site_avail_val = site_avail_dict.get(site_id, 0)
                        site_avail = float(site_avail_val) if site_avail_val is not None else 0.0
                        avail_color = "#22c55e" if site_avail >= 99.85 else "#f59e0b"
                        
                        # Get summary category breakdown for this site
                        site_cats = top_sites_avail_data[top_sites_avail_data['SITE_ID'] == site_id]
                        site_total = site_cats['TOTAL_DOWNTIME'].sum()
                        cat_pcts = {'Power': 0, 'RAN': 0, 'Transport': 0}
                        for _, cat_row in site_cats.iterrows():
                            summary_cat = cat_row['SITE_ID_SUMMARY_CATEGORY']
                            cat_dt = cat_row['TOTAL_DOWNTIME']
                            if summary_cat in cat_pcts:
                                cat_pcts[summary_cat] = (cat_dt / site_total * 100) if site_total > 0 else 0
                        
                        # Get dominant focus category (highest downtime)
                        site_focus_totals = site_cats.groupby('SITE_ID_FOCUS_CATEGORY')['TOTAL_DOWNTIME'].sum()
                        dominant_focus_cat = site_focus_totals.idxmax() if not site_focus_totals.empty else 'Unknown'
                        
                        # Get AAV vendor if focus category is Transport - AAV
                        aav_vendor = ''
                        if dominant_focus_cat == 'Transport - AAV':
                            aav_rows = site_cats[site_cats['SITE_ID_FOCUS_CATEGORY'] == 'Transport - AAV']
                            if not aav_rows.empty and 'AAV_VENDOR' in aav_rows.columns:
                                raw_vendor = aav_rows['AAV_VENDOR'].iloc[0] if pd.notna(aav_rows['AAV_VENDOR'].iloc[0]) else ''
                                aav_vendor = shorten_aav_vendor(raw_vendor)
                        
                        # Build focus category display with AAV vendor if applicable
                        focus_display = dominant_focus_cat
                        if aav_vendor:
                            focus_display = f"{dominant_focus_cat} ({aav_vendor})"
                        
                        # Create mini bar
                        bar_html = '<div style="display:flex;width:100%;height:6px;border-radius:3px;overflow:hidden;margin-top:3px;">'
                        for cat in ['Power', 'RAN', 'Transport']:
                            pct_val = cat_pcts[cat]
                            color = SUMMARY_CATEGORY_COLORS[cat]
                            bar_html += f'<div style="width:{pct_val}%;background:{color};" title="{cat}: {pct_val:.0f}%"></div>'
                        bar_html += '</div>'
                        
                        # Find dominant summary category (highest percentage)
                        dominant_summary_cat = max(cat_pcts, key=cat_pcts.get) if any(cat_pcts.values()) else None
                        
                        # Legend line with colored squares - highlight dominant category
                        legend_items = []
                        for cat in ['Power', 'RAN', 'Transport']:
                            pct_val = cat_pcts[cat]
                            color = SUMMARY_CATEGORY_COLORS[cat]
                            if cat == dominant_summary_cat and pct_val > 0:
                                legend_items.append(f'<span style="display:inline-flex;align-items:center;margin-right:4px;background:#fff;padding:1px 4px;border-radius:3px;"><span style="display:inline-block;width:7px;height:7px;background:{color};border-radius:1px;margin-right:2px;"></span><span style="color:#f8f9fa;font-weight:600;">{cat}:{pct_val:.0f}%</span></span>')
                            else:
                                legend_items.append(f'<span style="display:inline-flex;align-items:center;margin-right:4px;"><span style="display:inline-block;width:7px;height:7px;background:{color};border-radius:1px;margin-right:2px;"></span>{cat}:{pct_val:.0f}%</span>')
                        
                        legend_html = f'<div style="display:flex;font-size:0.85rem;margin-top:2px;color:#f8f9fa;">{"".join(legend_items)}</div>'
                        focus_html = f'<div style="font-size:0.85rem;color:#f8f9fa;font-weight:500;margin-top:2px;">{focus_display}</div>'
                        
                        # Days info for top right corner
                        days_html = f'<div style="text-align:right;font-size:0.85rem;color:#f8f9fa;line-height:1.3;"><div>Avail: {avail_days}/{total_period_days} days</div><div>COTTR: {cottr_days}/{total_period_days} days</div></div>'
                        
                        # Availability % box
                        avail_box_html = f'<div style="text-align:center;padding:8px 12px;background:#fff;border-radius:6px;border:1px solid #ddd;"><div style="font-size:1.3rem;font-weight:bold;color:{avail_color};">{site_avail:.2f}%</div><div style="font-size:0.8rem;color:#555;">Avail</div></div>'
                        
                        # Create sparklines (daily availability dots + downtime bars) - show for short date ranges
                        sparklines_html = ''
                        if total_period_days <= 14:
                            site_daily = site_daily_data[site_daily_data['SITE_ID'] == site_id].sort_values('DATE_VALUE') if not site_daily_data.empty else pd.DataFrame()
                            if not site_daily.empty and len(site_daily) > 0:
                                total_days_spark = len(site_daily)
                                days_meeting_goal = len(site_daily[site_daily['DAILY_AVAILABILITY'] >= 99.85])
                                daily_downtime = site_daily['DAILY_DOWNTIME'].tolist()
                                daily_avail = site_daily['DAILY_AVAILABILITY'].tolist()
                                max_downtime = max(daily_downtime) if daily_downtime else 1
                                
                                # Days meeting goal dots
                                goal_color = '#22c55e' if days_meeting_goal == total_days_spark else ('#f59e0b' if days_meeting_goal > 0 else '#ef4444')
                                dots_html = f'<div style="display:flex;gap:2px;align-items:center;justify-content:flex-end;"><span style="font-size:0.55rem;color:{goal_color};margin-right:3px;">{days_meeting_goal}/{total_days_spark}</span>'
                                for i, av in enumerate(daily_avail):
                                    dot_color = '#22c55e' if av >= 99.85 else '#ef4444'
                                    dots_html += f'<div style="width:5px;height:5px;border-radius:50%;background:{dot_color};" title="Day {i+1}: {av:.2f}%"></div>'
                                dots_html += '</div>'
                                
                                # Downtime bar chart
                                bars_html = '<div style="display:flex;align-items:flex-end;gap:1px;height:16px;margin-top:3px;justify-content:flex-end;">'
                                for i, (dtime, av) in enumerate(zip(daily_downtime, daily_avail)):
                                    height_pct = (dtime / max_downtime * 100) if max_downtime > 0 else 0
                                    height_pct = max(8, min(100, height_pct))
                                    bar_color = '#22c55e' if av >= 99.85 else '#f59e0b'
                                    bars_html += f'<div style="width:6px;height:{height_pct}%;background:{bar_color};border-radius:1px;" title="Day {i+1}: {format_number(dtime)} sec"></div>'
                                bars_html += '</div>'
                                
                                sparklines_html = f'<div style="display:flex;flex-direction:column;align-items:flex-end;min-width:70px;padding:3px;background:#fff;border:1px solid #ddd;border-radius:4px;">{dots_html}{bars_html}</div>'
                        
                        # Focus display with colored background tag
                        focus_bg_color = FOCUS_CATEGORY_COLORS.get(dominant_focus_cat, DEFAULT_FOCUS_COLOR)
                        focus_html_display = f'<div style="margin-top:3px;"><span style="display:inline-block;padding:2px 8px;background:{focus_bg_color};color:#fff;font-size:0.7rem;font-weight:bold;border-radius:4px;">{focus_display}</span></div>'
                        
                        # Avail box
                        avail_box_display = f'<div style="text-align:center;padding:6px 10px;background:#fff;border-radius:5px;border:1px solid #ddd;min-width:65px;"><div style="font-size:1.1rem;font-weight:bold;color:{avail_color};">{site_avail:.2f}%</div><div style="font-size:0.65rem;color:#555;">Avail</div></div>'
                        
                        # Downtime value and days info combined (downtime on top)
                        downtime_days_display = f'<div style="text-align:right;min-width:90px;"><div style="font-size:0.9rem;font-weight:bold;color:#e20074;margin-bottom:2px;">{format_number(site_dt)} sec</div><div style="font-size:0.7rem;color:#555;line-height:1.3;"><div>Avail: {avail_days}/{total_period_days} days</div><div>COTTR: {cottr_days}/{total_period_days} days</div></div></div>'
                        
                        # Build complete HTML as single string
                        site_html = '<div class="market-box" style="height:auto;min-height:55px;padding:8px 10px;">'
                        site_html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">'
                        site_html += '<div style="flex:1;min-width:0;">'
                        site_html += f'<div style="font-size:0.9rem;font-weight:500;"><b>{site_id}</b>: ({site_pct:.1f}%) <span style="color:#e20074;font-size:0.8rem;">Unavail: {site_unavail_contrib:.3f}%</span></div>'
                        site_html += focus_html_display
                        site_html += '</div>'
                        site_html += avail_box_display
                        site_html += downtime_days_display
                        site_html += '</div></div>'
                        
                        st.markdown(site_html, unsafe_allow_html=True)
                
                if focus_cat_totals.empty and market_by_summary_cat.empty:
                    st.info("No availability data for selected filters.")
    
    with insight_col3:
        # Calculate COTTR summary category percentages for display
        cottr_summary_text = ""
        if not cottr_by_summary.empty:
            cottr_summary_totals = cottr_by_summary.groupby('SITE_ID_SUMMARY_CATEGORY')['OUTAGE_MINUTES'].sum()
            cottr_summary_total = cottr_summary_totals.sum()
            if cottr_summary_total > 0:
                pwr_pct = (cottr_summary_totals.get('Power', 0) / cottr_summary_total * 100)
                ran_pct = (cottr_summary_totals.get('RAN', 0) / cottr_summary_total * 100)
                trn_pct = (cottr_summary_totals.get('Transport', 0) / cottr_summary_total * 100)
                cottr_summary_text = f"<div style='font-size:1rem;color:#000000;font-weight:600;margin-top:2px;'>Summary Categories: Power: {pwr_pct:.0f}% | RAN: {ran_pct:.0f}% | Transport: {trn_pct:.0f}%</div>"
        col3_title = f"🚨 COTTR - Categories ({market_display})" if market else "🚨 COTTR - Categories"
        st.markdown(f"<div style='margin-bottom:5px;'><b>{col3_title}</b>{cottr_summary_text}</div>", unsafe_allow_html=True)
        
        # Build treemap data from focus categories
        if not focus_cottr_totals.empty:
            cottr_focus_filtered = focus_cottr_totals[~focus_cottr_totals['SITE_ID_FOCUS_CATEGORY'].str.lower().str.contains('no outage', na=False)]
            cottr_focus_total = cottr_focus_filtered['TOTAL_OUTAGE_MINUTES'].sum()
            
            if not cottr_focus_filtered.empty and cottr_focus_total > 0:
                cottr_treemap_data = []
                for _, row in cottr_focus_filtered.iterrows():
                    cat = row['SITE_ID_FOCUS_CATEGORY']
                    mins = float(row['TOTAL_OUTAGE_MINUTES'])
                    cat_pct = (mins / cottr_focus_total * 100)
                    color = FOCUS_CATEGORY_COLORS.get(cat, DEFAULT_FOCUS_COLOR)
                    cottr_treemap_data.append({
                        'category': cat,
                        'value': mins,
                        'pct': cat_pct,
                        'color': color
                    })
                
                fig_cottr_treemap = go.Figure(go.Treemap(
                    labels=[f"{r['category']}<br>{r['pct']:.0f}%" for r in cottr_treemap_data],
                    parents=[''] * len(cottr_treemap_data),
                    values=[r['value'] for r in cottr_treemap_data],
                    marker=dict(colors=[r['color'] for r in cottr_treemap_data]),
                    textinfo='label',
                    textfont=dict(size=14, color='white'),
                    hovertemplate='<b>%{label}</b><br>Outage Mins: %{value:,.0f}<extra></extra>'
                ))
                # Use taller height when market is selected
                treemap_height = 350 if market else 250
                fig_cottr_treemap.update_layout(
                    margin=dict(t=5, l=5, r=5, b=5),
                    height=treemap_height,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)'
                )
                st.markdown("<div style='font-size:1rem;color:#000000;font-weight:600;margin-top:2px;margin-bottom:-15px;'>Focus Categories</div>", unsafe_allow_html=True)
                st.plotly_chart(fig_cottr_treemap, use_container_width=True, config=CHART_CONFIG)
            else:
                st.info("No category data available.")
        
        # Add Top 5 Sites by COTTR Outage Minutes when market is filtered
        if market:
            start_date = filters.get('start_date') if filters else None
            end_date = filters.get('end_date') if filters else None
            
            # Calculate total days in the date range
            if start_date and end_date:
                total_period_days_cottr = (datetime.strptime(end_date, '%Y-%m-%d') - datetime.strptime(start_date, '%Y-%m-%d')).days + 1
            else:
                total_period_days_cottr = days
            
            # Use cached queries for better performance
            filters_hash = filters_to_hashable(filters)
            top_sites_cottr_data = get_top_sites_cottr_cached(conn, days, filters_hash)
            avail_days_data = get_avail_days_and_vendor_cached(conn, days, filters_hash)
            avail_days_dict = dict(zip(avail_days_data['SITE_ID'], avail_days_data['AVAIL_DOWNTIME_DAYS'])) if not avail_days_data.empty else {}
            aav_vendor_dict = dict(zip(avail_days_data['SITE_ID'], avail_days_data['AAV_VENDOR'])) if not avail_days_data.empty and 'AAV_VENDOR' in avail_days_data.columns else {}
            
            cottr_site_avail_data = get_site_availability_cached(conn, days, filters_hash)
            cottr_site_avail_dict = dict(zip(cottr_site_avail_data['SITE_ID'], cottr_site_avail_data['AVG_AVAILABILITY'])) if not cottr_site_avail_data.empty else {}
            
            cottr_site_daily_data = get_cottr_site_daily_cached(conn, days, filters_hash)
            
            if not top_sites_cottr_data.empty:
                # Aggregate by site and get total
                site_totals_cottr = top_sites_cottr_data.groupby('SITE_ID').agg({
                    'OUTAGE_MINUTES': 'sum',
                    'COTTR_OUTAGE_DAYS': 'max'
                }).reset_index()
                site_totals_cottr = site_totals_cottr.sort_values('OUTAGE_MINUTES', ascending=False)
                total_all_sites_cottr = site_totals_cottr['OUTAGE_MINUTES'].sum()
                top_5_sites_cottr = site_totals_cottr.head(5)
                
                # Calculate combined percentage of top 5 sites
                top_5_total_cottr = top_5_sites_cottr['OUTAGE_MINUTES'].sum()
                top_5_pct_cottr = (top_5_total_cottr / total_all_sites_cottr * 100) if total_all_sites_cottr > 0 else 0
                
                st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
                st.markdown(f"**🔥 Top 5 Sites - Service Outage Mins ({top_5_pct_cottr:.1f}%)**")
                for _, site_row in top_5_sites_cottr.iterrows():
                    site_id = site_row['SITE_ID']
                    site_mins = float(site_row['OUTAGE_MINUTES']) if pd.notna(site_row['OUTAGE_MINUTES']) else 0.0
                    site_pct = (site_mins / total_all_sites_cottr * 100) if total_all_sites_cottr > 0 else 0
                    cottr_days = int(site_row['COTTR_OUTAGE_DAYS']) if pd.notna(site_row['COTTR_OUTAGE_DAYS']) else 0
                    avail_days = int(avail_days_dict.get(site_id, 0) or 0)
                    
                    # Get site availability (handle None values)
                    site_avail_val = cottr_site_avail_dict.get(site_id, 0)
                    site_avail = float(site_avail_val) if site_avail_val is not None else 0.0
                    avail_color = "#22c55e" if site_avail >= 99.85 else "#f59e0b"
                    
                    # Get summary category breakdown for this site
                    site_cats = top_sites_cottr_data[top_sites_cottr_data['SITE_ID'] == site_id]
                    site_total = site_cats['OUTAGE_MINUTES'].sum()
                    cat_pcts = {'Power': 0, 'RAN': 0, 'Transport': 0}
                    for _, cat_row in site_cats.iterrows():
                        summary_cat = cat_row['SITE_ID_SUMMARY_CATEGORY']
                        cat_mins = cat_row['OUTAGE_MINUTES']
                        if summary_cat in cat_pcts:
                            cat_pcts[summary_cat] = (cat_mins / site_total * 100) if site_total > 0 else 0
                    
                    # Get dominant focus category (highest outage minutes)
                    site_focus_totals = site_cats.groupby('SITE_ID_FOCUS_CATEGORY')['OUTAGE_MINUTES'].sum()
                    dominant_focus_cat = site_focus_totals.idxmax() if not site_focus_totals.empty else 'Unknown'
                    
                    # Get AAV vendor if focus category is Transport - AAV
                    aav_vendor = ''
                    if dominant_focus_cat == 'Transport - AAV':
                        raw_vendor = aav_vendor_dict.get(site_id, '')
                        if pd.isna(raw_vendor):
                            raw_vendor = ''
                        aav_vendor = shorten_aav_vendor(raw_vendor)
                    
                    # Build focus category display with AAV vendor if applicable
                    focus_display = dominant_focus_cat
                    if aav_vendor:
                        focus_display = f"{dominant_focus_cat} ({aav_vendor})"
                    
                    # Create mini bar
                    bar_html = '<div style="display:flex;width:100%;height:6px;border-radius:3px;overflow:hidden;margin-top:3px;">'
                    for cat in ['Power', 'RAN', 'Transport']:
                        pct_val = cat_pcts[cat]
                        color = SUMMARY_CATEGORY_COLORS[cat]
                        bar_html += f'<div style="width:{pct_val}%;background:{color};" title="{cat}: {pct_val:.0f}%"></div>'
                    bar_html += '</div>'
                    
                    # Find dominant summary category (highest percentage)
                    dominant_summary_cat = max(cat_pcts, key=cat_pcts.get) if any(cat_pcts.values()) else None
                    
                    # Legend line with colored squares - highlight dominant category
                    legend_items = []
                    for cat in ['Power', 'RAN', 'Transport']:
                        pct_val = cat_pcts[cat]
                        color = SUMMARY_CATEGORY_COLORS[cat]
                        if cat == dominant_summary_cat and pct_val > 0:
                            legend_items.append(f'<span style="display:inline-flex;align-items:center;margin-right:4px;background:#fff;padding:1px 4px;border-radius:3px;"><span style="display:inline-block;width:7px;height:7px;background:{color};border-radius:1px;margin-right:2px;"></span><span style="color:#f8f9fa;font-weight:600;">{cat}:{pct_val:.0f}%</span></span>')
                        else:
                            legend_items.append(f'<span style="display:inline-flex;align-items:center;margin-right:4px;"><span style="display:inline-block;width:7px;height:7px;background:{color};border-radius:1px;margin-right:2px;"></span>{cat}:{pct_val:.0f}%</span>')
                    
                    legend_html = f'<div style="display:flex;font-size:0.85rem;margin-top:2px;color:#f8f9fa;">{"".join(legend_items)}</div>'
                    focus_html = f'<div style="font-size:0.85rem;color:#f8f9fa;font-weight:500;margin-top:2px;">{focus_display}</div>'
                    
                    # Days info for top right corner
                    days_html = f'<div style="text-align:right;font-size:0.85rem;color:#f8f9fa;line-height:1.3;"><div>Avail: {avail_days}/{total_period_days_cottr} days</div><div>COTTR: {cottr_days}/{total_period_days_cottr} days</div></div>'
                    
                    # Service Outage Mins KPI box
                    mins_color = "#f59e0b"
                    mins_box_html = f'<div style="text-align:center;padding:8px 12px;background:#fff;border-radius:6px;border:1px solid #ddd;"><div style="font-size:1.3rem;font-weight:bold;color:{mins_color};">{format_number(site_mins)}</div><div style="font-size:0.75rem;color:#555;">Service Outage Mins</div></div>'
                    
                    # Create sparklines for COTTR daily outage minutes - show for short date ranges
                    sparklines_html = ''
                    if total_period_days_cottr <= 14:
                        site_daily_cottr = cottr_site_daily_data[cottr_site_daily_data['SITE_ID'] == site_id].sort_values('DATE_VALUE') if not cottr_site_daily_data.empty else pd.DataFrame()
                        if not site_daily_cottr.empty and len(site_daily_cottr) > 0:
                            daily_outage = site_daily_cottr['DAILY_OUTAGE_MINS'].tolist()
                            max_outage = max(daily_outage) if daily_outage else 1
                            
                            # Outage minutes bar chart
                            bars_html = '<div style="display:flex;align-items:flex-end;gap:1px;height:20px;justify-content:flex-end;">'
                            for i, omins in enumerate(daily_outage):
                                height_pct = (omins / max_outage * 100) if max_outage > 0 else 0
                                height_pct = max(8, min(100, height_pct))
                                bars_html += f'<div style="width:6px;height:{height_pct}%;background:{mins_color};border-radius:1px;" title="Day {i+1}: {format_number(omins)} mins"></div>'
                            bars_html += '</div>'
                            
                            sparklines_html = f'<div style="display:flex;flex-direction:column;align-items:flex-end;min-width:60px;padding:3px;background:#fff;border:1px solid #ddd;border-radius:4px;">{bars_html}</div>'
                    
                    # Focus display with colored background tag
                    focus_bg_color = FOCUS_CATEGORY_COLORS.get(dominant_focus_cat, DEFAULT_FOCUS_COLOR)
                    focus_html_display = f'<div style="margin-top:3px;"><span style="display:inline-block;padding:2px 8px;background:{focus_bg_color};color:#fff;font-size:0.7rem;font-weight:bold;border-radius:4px;">{focus_display}</span></div>'
                    
                    # Mins box
                    mins_box_display = f'<div style="text-align:center;padding:6px 10px;background:#fff;border-radius:5px;border:1px solid #ddd;min-width:70px;"><div style="font-size:1.1rem;font-weight:bold;color:{mins_color};">{format_number(site_mins)}</div><div style="font-size:0.6rem;color:#555;">Outage Mins</div></div>'
                    
                    # Outage mins value and days info combined (outage mins on top)
                    outage_days_display = f'<div style="text-align:right;min-width:90px;"><div style="font-size:0.9rem;font-weight:bold;color:#f59e0b;margin-bottom:2px;">{format_number(site_mins)} mins</div><div style="font-size:0.7rem;color:#555;line-height:1.3;"><div>Avail: {avail_days}/{total_period_days_cottr} days</div><div>COTTR: {cottr_days}/{total_period_days_cottr} days</div></div></div>'
                    
                    # Build complete HTML as single string
                    cottr_site_html = '<div class="market-box" style="height:auto;min-height:55px;padding:8px 10px;">'
                    cottr_site_html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">'
                    cottr_site_html += '<div style="flex:1;min-width:0;">'
                    cottr_site_html += f'<div style="font-size:0.9rem;font-weight:500;"><b>{site_id}</b>: ({site_pct:.1f}%)</div>'
                    cottr_site_html += focus_html_display
                    cottr_site_html += '</div>'
                    cottr_site_html += mins_box_display
                    cottr_site_html += outage_days_display
                    cottr_site_html += '</div></div>'
                    
                    st.markdown(cottr_site_html, unsafe_allow_html=True)
        
        # Add COTTR - Degraded Markets below Focus Categories (unfiltered only)
        if not market:
            # Add legend at top
            cottr_legend_html = '<div style="display:flex;gap:12px;margin-bottom:6px;font-size:0.75rem;">'
            cottr_legend_html += f'<span style="display:flex;align-items:center;"><span style="width:12px;height:12px;background:{SUMMARY_CATEGORY_COLORS["Power"]};border-radius:2px;margin-right:4px;"></span>Power</span>'
            cottr_legend_html += f'<span style="display:flex;align-items:center;"><span style="width:12px;height:12px;background:{SUMMARY_CATEGORY_COLORS["RAN"]};border-radius:2px;margin-right:4px;"></span>RAN</span>'
            cottr_legend_html += f'<span style="display:flex;align-items:center;"><span style="width:12px;height:12px;background:{SUMMARY_CATEGORY_COLORS["Transport"]};border-radius:2px;margin-right:4px;"></span>Transport</span>'
            cottr_legend_html += '</div>'
            st.markdown(f"**📍 COTTR - Degraded Markets** {cottr_legend_html}", unsafe_allow_html=True)
            if not cottr_market_by_cat.empty:
                # Aggregate by market
                cottr_market_totals = cottr_market_by_cat.groupby('MARKET_ID')['TOTAL_OUTAGE_MINUTES'].sum().reset_index()
                cottr_market_totals = cottr_market_totals.sort_values('TOTAL_OUTAGE_MINUTES', ascending=False)
                total_cottr_mins = cottr_market_totals['TOTAL_OUTAGE_MINUTES'].sum()
                top_cottr_mkts = cottr_market_totals.head(20)
                display_categories = ['Power', 'RAN', 'Transport']
                
                # Collect all COTTR market HTML for scrollable container
                all_cottr_markets_html = '<div style="max-height:460px;overflow-y:auto;padding-right:5px;padding-bottom:15px;">'
                
                for _, row in top_cottr_mkts.iterrows():
                    mkt = row['MARKET_ID']  # Already normalized to Global Market ID format
                    mins = float(row['TOTAL_OUTAGE_MINUTES']) if row['TOTAL_OUTAGE_MINUTES'] else 0
                    pct = (mins / total_cottr_mins * 100) if total_cottr_mins > 0 else 0
                    
                    # Get impacted subs for this market if available
                    mkt_subs = 0
                    if not impacted_subs_by_market.empty:
                        # Try multiple matching strategies
                        # 1. Check if impacted subs market contains COTTR market name (or vice versa)
                        mkt_base = mkt.split()[0] if ' ' in mkt else mkt  # Get first word (e.g., "PITTSBURGH" from "PITTSBURGH PA")
                        mkt_subs_row = impacted_subs_by_market[
                            impacted_subs_by_market['MARKET'].str.upper().str.contains(mkt_base.upper(), na=False) |
                            impacted_subs_by_market['MARKET'].str.upper().apply(lambda x: mkt_base.upper() in x if pd.notna(x) else False)
                        ]
                        if not mkt_subs_row.empty:
                            mkt_subs = mkt_subs_row['TOTAL_IMPACTED_SUBS'].sum()
                    
                    # Get summary category breakdown for this market (use UNFILTERED data for bar chart)
                    # Use unfiltered data if available, otherwise fall back to filtered data
                    cottr_data_for_bars = cottr_market_by_cat_unfiltered if cottr_market_by_cat_unfiltered is not None else cottr_market_by_cat
                    mkt_cats = cottr_data_for_bars[cottr_data_for_bars['MARKET_ID'] == mkt]
                    mkt_total = mkt_cats['TOTAL_OUTAGE_MINUTES'].sum()
                    
                    # Map focus categories to summary categories
                    cat_pcts = {'Power': 0, 'RAN': 0, 'Transport': 0}
                    for _, cat_row in mkt_cats.iterrows():
                        focus_cat = str(cat_row['SITE_ID_FOCUS_CATEGORY']) if cat_row['SITE_ID_FOCUS_CATEGORY'] else ''
                        cat_mins = cat_row['TOTAL_OUTAGE_MINUTES']
                        if 'Power' in focus_cat:
                            cat_pcts['Power'] += (cat_mins / mkt_total * 100) if mkt_total > 0 else 0
                        elif 'Transport' in focus_cat or 'AAV' in focus_cat or 'Backhaul' in focus_cat or 'Interconnection' in focus_cat or 'RingFed' in focus_cat:
                            cat_pcts['Transport'] += (cat_mins / mkt_total * 100) if mkt_total > 0 else 0
                        else:
                            # Everything else (RAN, Hardware, Software, Router, Headend, Site Mod, Microwave, etc.) goes to RAN
                            cat_pcts['RAN'] += (cat_mins / mkt_total * 100) if mkt_total > 0 else 0
                    
                    # Bar chart with % only (legend is at top of section)
                    bar_html = '<div style="display:flex;width:100%;height:22px;border-radius:4px;overflow:hidden;margin-top:4px;">'
                    for display_cat in display_categories:
                        pct_val = cat_pcts[display_cat]
                        color = SUMMARY_CATEGORY_COLORS[display_cat]
                        inner_html = f'<span style="font-size:0.7rem;font-weight:600;">{pct_val:.0f}%</span>' if pct_val >= 10 else ''
                        bar_html += f'<div style="width:{pct_val}%;background:{color};display:flex;align-items:center;justify-content:center;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,0.5);" title="{display_cat}: {pct_val:.0f}%">{inner_html}</div>'
                    bar_html += '</div>'
                    
                    # Outage mins display on right side
                    mins_color = "#f59e0b"
                    mins_box_html = f'<div style="text-align:center;padding:6px 10px;background:#fff;border-radius:6px;border:1px solid #ddd;"><div style="font-size:1rem;font-weight:bold;color:{mins_color};">{format_number(mins)}</div><div style="font-size:0.65rem;color:#555;">Service Outage Mins</div></div>'
                    
                    # Build complete HTML as single string
                    cottr_market_html = '<div class="market-box">'
                    cottr_market_html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">'
                    cottr_market_html += '<div style="flex:1;">'
                    cottr_market_html += f'<div style="font-size:0.8rem;">🚨 <b>{mkt}</b>: ({pct:.1f}%) <span style="color:#666;font-size:0.7rem;">{format_number(mins)} mins</span></div>'
                    cottr_market_html += bar_html
                    cottr_market_html += '</div>'
                    cottr_market_html += mins_box_html
                    cottr_market_html += '</div></div>'
                    
                    all_cottr_markets_html += cottr_market_html
                
                all_cottr_markets_html += '</div>'
                st.markdown(all_cottr_markets_html, unsafe_allow_html=True)
            else:
                st.info("No COTTR market data available.")
    
    # Customer Minutes column - Top Sites when market selected, Degraded Markets when unfiltered
    with insight_col_cm:
        if market:
            # MARKET SELECTED: Show Top Sites by Customer Minutes
            if not top_sites_cm.empty:
                total_cm = top_sites_cm['TOTAL_CUSTOMER_MINUTES'].sum()
                top_5_cm = top_sites_cm.head(5)['TOTAL_CUSTOMER_MINUTES'].sum()
                top_5_pct = (top_5_cm / total_cm * 100) if total_cm > 0 else 0
                st.markdown(f"**⏱️ Top 5 Sites - Customer Mins ({top_5_pct:.1f}%)**")
            else:
                st.markdown("**⏱️ Top 5 Sites - Customer Mins**")
            
            if not top_sites_cm.empty:
                display_categories = ['Power', 'RAN', 'Transport']
                
                for _, row in top_sites_cm.head(5).iterrows():
                    site_id = row['SITE_ID']
                    cm_val = row['TOTAL_CUSTOMER_MINUTES']
                    subs = row['TOTAL_IMPACTED_SUBS']
                    pct = (cm_val / total_cm * 100) if total_cm > 0 else 0
                    
                    # Get COTTR summary category breakdown for this site (map focus to summary)
                    cat_pcts = {'Power': 0, 'RAN': 0, 'Transport': 0}
                    if not top_sites_cm_cottr_cat.empty:
                        site_cottr = top_sites_cm_cottr_cat[top_sites_cm_cottr_cat['SITE_ID'] == site_id]
                        if not site_cottr.empty:
                            site_total_mins = site_cottr['TOTAL_OUTAGE_MINS'].sum()
                            for _, cat_row in site_cottr.iterrows():
                                focus_cat = cat_row['SITE_ID_FOCUS_CATEGORY']
                                cat_mins = cat_row['TOTAL_OUTAGE_MINS']
                                focus_cat_str = str(focus_cat) if pd.notna(focus_cat) and focus_cat else ''
                                if 'Power' in focus_cat_str:
                                    cat_pcts['Power'] += (cat_mins / site_total_mins * 100) if site_total_mins > 0 else 0
                                elif any(x in focus_cat_str for x in ['Transport', 'AAV', 'Backhaul', 'Interconnection', 'RingFed', 'Microwave']):
                                    cat_pcts['Transport'] += (cat_mins / site_total_mins * 100) if site_total_mins > 0 else 0
                                else:
                                    cat_pcts['RAN'] += (cat_mins / site_total_mins * 100) if site_total_mins > 0 else 0
                    
                    # Bar chart with % and category name inside each segment
                    # If no COTTR category data, show a placeholder bar
                    has_cat_data = sum(cat_pcts.values()) > 0
                    if has_cat_data:
                        bar_html = '<div style="display:flex;width:100%;height:36px;border-radius:4px;overflow:hidden;margin-top:4px;">'
                        for display_cat in display_categories:
                            pct_val = cat_pcts[display_cat]
                            color = SUMMARY_CATEGORY_COLORS[display_cat]
                            if pct_val >= 20:
                                inner_html = f'<div style="text-align:center;"><div style="font-size:0.75rem;font-weight:700;">{pct_val:.0f}%</div><div style="font-size:0.55rem;font-weight:500;opacity:0.9;">{display_cat}</div></div>'
                            elif pct_val >= 10:
                                inner_html = f'<span style="font-size:0.65rem;font-weight:600;">{pct_val:.0f}%</span>'
                            else:
                                inner_html = ''
                            bar_html += f'<div style="width:{pct_val}%;background:{color};display:flex;align-items:center;justify-content:center;flex-direction:column;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,0.5);" title="{display_cat}: {pct_val:.0f}%">{inner_html}</div>'
                        bar_html += '</div>'
                    else:
                        # No category data available - show gray placeholder with message
                        bar_html = '<div style="display:flex;width:100%;height:20px;border-radius:4px;overflow:hidden;margin-top:4px;background:#ddd;align-items:center;justify-content:center;"><span style="font-size:0.6rem;color:#888;">No COTTR category data</span></div>'
                    
                    # Customer Mins display box on right side
                    mins_box_html = f'<div style="text-align:center;padding:6px 10px;background:#fff;border-radius:6px;border:1px solid #ddd;"><div style="font-size:1rem;font-weight:bold;color:#e20074;">{format_number(cm_val)}</div><div style="font-size:0.65rem;color:#555;">Mins</div></div>'
                    
                    # Build HTML (same format as COTTR)
                    cm_site_html = '<div class="market-box">'
                    cm_site_html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">'
                    cm_site_html += '<div style="flex:1;">'
                    cm_site_html += f'<div style="font-size:0.8rem;">⏱️ <b>{site_id}</b>: ({pct:.1f}%) <span style="color:#666;font-size:0.7rem;">{format_number(cm_val)} mins</span></div>'
                    cm_site_html += bar_html
                    cm_site_html += '</div>'
                    cm_site_html += mins_box_html
                    cm_site_html += '</div></div>'
                    
                    st.markdown(cm_site_html, unsafe_allow_html=True)
            else:
                st.info("No customer minutes site data available.")
        else:
            # NO MARKET SELECTED: Show Degraded Markets by Customer Minutes
            # Add legend at top (same format as Availability and COTTR)
            cm_legend_html = '<div style="display:flex;gap:12px;margin-bottom:6px;font-size:0.75rem;">'
            cm_legend_html += f'<span style="display:flex;align-items:center;"><span style="width:12px;height:12px;background:{SUMMARY_CATEGORY_COLORS["Power"]};border-radius:2px;margin-right:4px;"></span>Power</span>'
            cm_legend_html += f'<span style="display:flex;align-items:center;"><span style="width:12px;height:12px;background:{SUMMARY_CATEGORY_COLORS["RAN"]};border-radius:2px;margin-right:4px;"></span>RAN</span>'
            cm_legend_html += f'<span style="display:flex;align-items:center;"><span style="width:12px;height:12px;background:{SUMMARY_CATEGORY_COLORS["Transport"]};border-radius:2px;margin-right:4px;"></span>Transport</span>'
            cm_legend_html += '</div>'
            st.markdown(f"**⏱️ Customer Minutes - Degraded Markets** {cm_legend_html}", unsafe_allow_html=True)
            
            if not impacted_subs_by_market.empty and 'TOTAL_CUSTOMER_MINUTES' in impacted_subs_by_market.columns:
                # Sort by customer minutes
                cm_by_market = impacted_subs_by_market.sort_values('TOTAL_CUSTOMER_MINUTES', ascending=False)
                total_cm = cm_by_market['TOTAL_CUSTOMER_MINUTES'].sum()
                top_cm_mkts = cm_by_market.head(20)
                display_categories = ['Power', 'RAN', 'Transport']
                
                # Collect all HTML for scrollable container
                all_cm_html = '<div style="max-height:460px;overflow-y:auto;padding-right:5px;padding-bottom:15px;">'
                
                for _, row in top_cm_mkts.iterrows():
                    mkt = row['MARKET']
                    cm_val = row['TOTAL_CUSTOMER_MINUTES']
                    subs = row['TOTAL_IMPACTED_SUBS']
                    pct = (cm_val / total_cm * 100) if total_cm > 0 else 0
                    mkt_base = mkt.split()[0] if ' ' in mkt else mkt
                    
                    # Get COTTR summary category breakdown for this market (using UNFILTERED COTTR data)
                    cat_pcts = {'Power': 0, 'RAN': 0, 'Transport': 0}
                    cottr_data_for_bars = cottr_market_by_cat_unfiltered if cottr_market_by_cat_unfiltered is not None else cottr_market_by_cat
                    if not cottr_data_for_bars.empty:
                        mkt_cottr = cottr_data_for_bars[
                            cottr_data_for_bars['MARKET_ID'].str.upper().str.contains(mkt_base.upper(), na=False)
                        ]
                        if not mkt_cottr.empty:
                            mkt_total_mins = mkt_cottr['TOTAL_OUTAGE_MINUTES'].sum()
                            for _, cat_row in mkt_cottr.iterrows():
                                focus_cat = str(cat_row['SITE_ID_FOCUS_CATEGORY']) if cat_row['SITE_ID_FOCUS_CATEGORY'] else ''
                                cat_mins = cat_row['TOTAL_OUTAGE_MINUTES']
                                if 'Power' in focus_cat:
                                    cat_pcts['Power'] += (cat_mins / mkt_total_mins * 100) if mkt_total_mins > 0 else 0
                                elif 'Transport' in focus_cat or 'AAV' in focus_cat or 'Backhaul' in focus_cat or 'Interconnection' in focus_cat or 'RingFed' in focus_cat:
                                    cat_pcts['Transport'] += (cat_mins / mkt_total_mins * 100) if mkt_total_mins > 0 else 0
                                else:
                                    cat_pcts['RAN'] += (cat_mins / mkt_total_mins * 100) if mkt_total_mins > 0 else 0
                    
                    # Bar chart with % only (legend is at top of section)
                    bar_html = '<div style="display:flex;width:100%;height:22px;border-radius:4px;overflow:hidden;margin-top:4px;">'
                    for display_cat in display_categories:
                        pct_val = cat_pcts[display_cat]
                        color = SUMMARY_CATEGORY_COLORS[display_cat]
                        inner_html = f'<span style="font-size:0.7rem;font-weight:600;">{pct_val:.0f}%</span>' if pct_val >= 10 else ''
                        bar_html += f'<div style="width:{pct_val}%;background:{color};display:flex;align-items:center;justify-content:center;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,0.5);" title="{display_cat}: {pct_val:.0f}%">{inner_html}</div>'
                    bar_html += '</div>'
                    
                    # Mins display box on right side (same format as COTTR)
                    mins_box_html = f'<div style="text-align:center;padding:6px 10px;background:#fff;border-radius:6px;border:1px solid #ddd;"><div style="font-size:1rem;font-weight:bold;color:#e20074;">{format_number(cm_val)}</div><div style="font-size:0.65rem;color:#555;">Mins</div></div>'
                    
                    # Build complete HTML (same format as COTTR)
                    cm_market_html = '<div class="market-box">'
                    cm_market_html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">'
                    cm_market_html += '<div style="flex:1;">'
                    cm_market_html += f'<div style="font-size:0.8rem;">⏱️ <b>{mkt}</b>: ({pct:.1f}%) <span style="color:#666;font-size:0.7rem;">{format_number(cm_val)} mins</span></div>'
                    cm_market_html += bar_html
                    cm_market_html += '</div>'
                    cm_market_html += mins_box_html
                    cm_market_html += '</div></div>'
                    
                    all_cm_html += cm_market_html
                
                all_cm_html += '</div>'
                st.markdown(all_cm_html, unsafe_allow_html=True)
            else:
                st.info("No customer minutes data available.")
    
    with insight_col4:
        # When market is selected, show Top 5 Sites by Impacted Subs
        # When no market selected, show top markets
        if market:
            # MARKET SELECTED: Show Top 5 Sites by Impacted Subs
            if not top_sites_impacted.empty:
                total_subs = top_sites_impacted['TOTAL_IMPACTED_SUBS'].sum()
                top_5_subs = top_sites_impacted.head(5)['TOTAL_IMPACTED_SUBS'].sum()
                top_5_pct = (top_5_subs / total_subs * 100) if total_subs > 0 else 0
                st.markdown(f"**📱 Top 5 Sites - Impacted Subs ({top_5_pct:.1f}%)**")
            else:
                st.markdown("**📱 Top 5 Sites - Impacted Subs**")
            
            if not top_sites_impacted.empty:
                display_categories = ['Power', 'RAN', 'Transport']
                
                for _, row in top_sites_impacted.head(5).iterrows():
                    site_id = row['SITE_ID']
                    subs = row['TOTAL_IMPACTED_SUBS']
                    pct = (subs / total_subs * 100) if total_subs > 0 else 0
                    
                    # Get COTTR summary category breakdown for this site (map focus to summary)
                    cat_pcts = {'Power': 0, 'RAN': 0, 'Transport': 0}
                    if not top_sites_impacted_cottr_cat.empty:
                        site_cottr = top_sites_impacted_cottr_cat[top_sites_impacted_cottr_cat['SITE_ID'] == site_id]
                        if not site_cottr.empty:
                            site_total_mins = site_cottr['TOTAL_OUTAGE_MINS'].sum()
                            for _, cat_row in site_cottr.iterrows():
                                focus_cat = cat_row['SITE_ID_FOCUS_CATEGORY']
                                cat_mins = cat_row['TOTAL_OUTAGE_MINS']
                                focus_cat_str = str(focus_cat) if pd.notna(focus_cat) and focus_cat else ''
                                if 'Power' in focus_cat_str:
                                    cat_pcts['Power'] += (cat_mins / site_total_mins * 100) if site_total_mins > 0 else 0
                                elif any(x in focus_cat_str for x in ['Transport', 'AAV', 'Backhaul', 'Interconnection', 'RingFed', 'Microwave']):
                                    cat_pcts['Transport'] += (cat_mins / site_total_mins * 100) if site_total_mins > 0 else 0
                                else:
                                    cat_pcts['RAN'] += (cat_mins / site_total_mins * 100) if site_total_mins > 0 else 0
                    
                    # Bar chart with % and category name inside each segment
                    has_cat_data = sum(cat_pcts.values()) > 0
                    if has_cat_data:
                        bar_html = '<div style="display:flex;width:100%;height:36px;border-radius:4px;overflow:hidden;margin-top:4px;">'
                        for display_cat in display_categories:
                            pct_val = cat_pcts[display_cat]
                            color = SUMMARY_CATEGORY_COLORS[display_cat]
                            if pct_val >= 20:
                                inner_html = f'<div style="text-align:center;"><div style="font-size:0.75rem;font-weight:700;">{pct_val:.0f}%</div><div style="font-size:0.55rem;font-weight:500;opacity:0.9;">{display_cat}</div></div>'
                            elif pct_val >= 10:
                                inner_html = f'<span style="font-size:0.65rem;font-weight:600;">{pct_val:.0f}%</span>'
                            else:
                                inner_html = ''
                            bar_html += f'<div style="width:{pct_val}%;background:{color};display:flex;align-items:center;justify-content:center;flex-direction:column;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,0.5);" title="{display_cat}: {pct_val:.0f}%">{inner_html}</div>'
                        bar_html += '</div>'
                    else:
                        bar_html = '<div style="display:flex;width:100%;height:20px;border-radius:4px;overflow:hidden;margin-top:4px;background:#ddd;align-items:center;justify-content:center;"><span style="font-size:0.6rem;color:#888;">No COTTR category data</span></div>'
                    
                    # Subs display box on right side
                    subs_box_html = f'<div style="text-align:center;padding:6px 10px;background:#fff;border-radius:6px;border:1px solid #ddd;"><div style="font-size:1rem;font-weight:bold;color:#22c55e;">{format_number(subs)}</div><div style="font-size:0.65rem;color:#555;">Subs</div></div>'
                    
                    # Build HTML (same format as COTTR)
                    subs_site_html = '<div class="market-box">'
                    subs_site_html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">'
                    subs_site_html += '<div style="flex:1;">'
                    subs_site_html += f'<div style="font-size:0.8rem;">📱 <b>{site_id}</b>: ({pct:.1f}%) <span style="color:#666;font-size:0.7rem;">{format_number(subs)} subs</span></div>'
                    subs_site_html += bar_html
                    subs_site_html += '</div>'
                    subs_site_html += subs_box_html
                    subs_site_html += '</div></div>'
                    
                    st.markdown(subs_site_html, unsafe_allow_html=True)
            else:
                st.info("No impacted subs site data available.")
        else:
            # Add legend at top (same format as Availability and COTTR)
            subs_legend_html = '<div style="display:flex;gap:12px;margin-bottom:6px;font-size:0.75rem;">'
            subs_legend_html += f'<span style="display:flex;align-items:center;"><span style="width:12px;height:12px;background:{SUMMARY_CATEGORY_COLORS["Power"]};border-radius:2px;margin-right:4px;"></span>Power</span>'
            subs_legend_html += f'<span style="display:flex;align-items:center;"><span style="width:12px;height:12px;background:{SUMMARY_CATEGORY_COLORS["RAN"]};border-radius:2px;margin-right:4px;"></span>RAN</span>'
            subs_legend_html += f'<span style="display:flex;align-items:center;"><span style="width:12px;height:12px;background:{SUMMARY_CATEGORY_COLORS["Transport"]};border-radius:2px;margin-right:4px;"></span>Transport</span>'
            subs_legend_html += '</div>'
            st.markdown(f"**📱 Impacted Subs - Degraded Markets** {subs_legend_html}", unsafe_allow_html=True)
            
            # Degraded Markets by Impacted Subscribers with summary category breakdown
            if not impacted_subs_by_market.empty:
                total_subs = impacted_subs_by_market['TOTAL_IMPACTED_SUBS'].sum()
                top_subs_mkts = impacted_subs_by_market.head(20)
                display_categories = ['Power', 'RAN', 'Transport']
                
                # Collect all HTML for scrollable container
                all_subs_html = '<div style="max-height:460px;overflow-y:auto;padding-right:5px;padding-bottom:15px;">'
                
                for _, row in top_subs_mkts.iterrows():
                    mkt = row['MARKET']
                    subs = row['TOTAL_IMPACTED_SUBS']
                    pct = (subs / total_subs * 100) if total_subs > 0 else 0
                    mkt_base = mkt.split()[0] if ' ' in mkt else mkt
                    
                    # Get COTTR summary category breakdown for this market (using UNFILTERED COTTR data)
                    cat_pcts = {'Power': 0, 'RAN': 0, 'Transport': 0}
                    cottr_data_for_bars = cottr_market_by_cat_unfiltered if cottr_market_by_cat_unfiltered is not None else cottr_market_by_cat
                    if not cottr_data_for_bars.empty:
                        mkt_cottr = cottr_data_for_bars[
                            cottr_data_for_bars['MARKET_ID'].str.upper().str.contains(mkt_base.upper(), na=False)
                        ]
                        if not mkt_cottr.empty:
                            mkt_total_mins = mkt_cottr['TOTAL_OUTAGE_MINUTES'].sum()
                            for _, cat_row in mkt_cottr.iterrows():
                                focus_cat = str(cat_row['SITE_ID_FOCUS_CATEGORY']) if cat_row['SITE_ID_FOCUS_CATEGORY'] else ''
                                cat_mins = cat_row['TOTAL_OUTAGE_MINUTES']
                                if 'Power' in focus_cat:
                                    cat_pcts['Power'] += (cat_mins / mkt_total_mins * 100) if mkt_total_mins > 0 else 0
                                elif 'Transport' in focus_cat or 'AAV' in focus_cat or 'Backhaul' in focus_cat or 'Interconnection' in focus_cat or 'RingFed' in focus_cat:
                                    cat_pcts['Transport'] += (cat_mins / mkt_total_mins * 100) if mkt_total_mins > 0 else 0
                                else:
                                    cat_pcts['RAN'] += (cat_mins / mkt_total_mins * 100) if mkt_total_mins > 0 else 0
                    
                    # Bar chart with % only (legend is at top of section)
                    bar_html = '<div style="display:flex;width:100%;height:22px;border-radius:4px;overflow:hidden;margin-top:4px;">'
                    for display_cat in display_categories:
                        pct_val = cat_pcts[display_cat]
                        color = SUMMARY_CATEGORY_COLORS[display_cat]
                        inner_html = f'<span style="font-size:0.7rem;font-weight:600;">{pct_val:.0f}%</span>' if pct_val >= 10 else ''
                        bar_html += f'<div style="width:{pct_val}%;background:{color};display:flex;align-items:center;justify-content:center;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,0.5);" title="{display_cat}: {pct_val:.0f}%">{inner_html}</div>'
                    bar_html += '</div>'
                    
                    # Subs display box on right side (same format as COTTR)
                    subs_box_html = f'<div style="text-align:center;padding:6px 10px;background:#fff;border-radius:6px;border:1px solid #ddd;"><div style="font-size:1rem;font-weight:bold;color:#22c55e;">{format_number(subs)}</div><div style="font-size:0.65rem;color:#555;">Subs</div></div>'
                    
                    # Build complete HTML (same format as COTTR)
                    subs_market_html = '<div class="market-box">'
                    subs_market_html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">'
                    subs_market_html += '<div style="flex:1;">'
                    subs_market_html += f'<div style="font-size:0.8rem;">📱 <b>{mkt}</b>: ({pct:.1f}%) <span style="color:#666;font-size:0.7rem;">{format_number(subs)} subs</span></div>'
                    subs_market_html += bar_html
                    subs_market_html += '</div>'
                    subs_market_html += subs_box_html
                    subs_market_html += '</div></div>'
                    
                    all_subs_html += subs_market_html
                
                all_subs_html += '</div>'
                st.markdown(all_subs_html, unsafe_allow_html=True)
            else:
                st.info("No impacted subs data available.")
    
    st.divider()
    
    # ===== SUMMARY CATEGORY CHARTS (SITE_ID_SUMMARY_CATEGORY) =====
    st.markdown("### 📊 Summary Category View")
    
    sum_col1, sum_col2 = st.columns(2)
    
    # Chart 1 (Summary): Availability & Downtime (LEFT)
    with sum_col1:
        st.markdown("#### 📈 Availability % & Downtime by Summary Category")
        st.markdown(
            "<span style='font-size:0.8rem;color:#bbbbbb;'>Site Type filter applied</span>",
            unsafe_allow_html=True,
        )
        
        if not avail_summary_df.empty:
            avail_summary_df['DATE'] = pd.to_datetime(avail_summary_df['DATE_VALUE']).dt.date
            avail_summary_df = avail_summary_df.sort_values('DATE')
            
            fig_s1 = make_subplots(specs=[[{"secondary_y": True}]])
            
            if not downtime_by_summary_df.empty:
                downtime_by_summary_df['DATE'] = pd.to_datetime(downtime_by_summary_df['DATE_VALUE']).dt.date
                
                sum_cat_totals = downtime_by_summary_df.groupby('SITE_ID_SUMMARY_CATEGORY')['TOTAL_DOWNTIME'].sum().sort_values(ascending=False)
                sum_categories = sum_cat_totals.head(10).index.tolist()
                
                for i, cat in enumerate(sum_categories):
                    cat_data = downtime_by_summary_df[downtime_by_summary_df['SITE_ID_SUMMARY_CATEGORY'] == cat]
                    cat_color = SUMMARY_CATEGORY_COLORS.get(cat, DEFAULT_SUMMARY_COLOR)
                    fig_s1.add_trace(
                        go.Bar(x=cat_data['DATE'], y=cat_data['TOTAL_DOWNTIME'], name=cat, marker_color=cat_color),
                        secondary_y=False
                    )
            
            fig_s1.add_trace(
                go.Scatter(x=avail_summary_df['DATE'], y=avail_summary_df['AVG_AVAILABILITY_PCT'], name='Availability %',
                           line=dict(color='#4a0e4e', width=4), mode='lines+markers', marker=dict(size=8)),
                secondary_y=True
            )
            
            # Goal line at 99.85% on secondary (right) axis
            fig_s1.add_shape(
                type="line",
                x0=0, x1=1, xref="paper",
                y0=99.85, y1=99.85, yref="y2",
                line=dict(color="#f59e0b", width=2, dash="dot"),
            )
            fig_s1.add_annotation(
                x=1, xref="paper",
                y=99.85, yref="y2",
                xanchor="right",
                yanchor="bottom",
                text="Goal: 99.85%",
                showarrow=False,
                font=dict(color="#f59e0b")
            )
            
            fig_s1.update_layout(template='plotly_white', height=400,
                              font=dict(size=14),
                              legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=12)),
                              hovermode='x unified', barmode='stack', margin=dict(t=80),
                              xaxis=dict(tickfont=dict(size=12)), yaxis=dict(tickfont=dict(size=12)))
            fig_s1.update_xaxes(tickformat="%b %d", tickangle=-45)
            fig_s1.update_yaxes(title_text="Downtime (sec)", secondary_y=False)
            fig_s1.update_yaxes(title_text="Availability %", secondary_y=True, range=[99, 100])
            
            st.plotly_chart(fig_s1, use_container_width=True, config=CHART_CONFIG, key="exec_sparkline_1")
        else:
            st.info("No availability data available.")
    
    # Chart 2 (Summary): COTTR & Impacted Subscribers (RIGHT)
    with sum_col2:
        st.markdown("#### 📈 COTTR Service Outage Minutes & Impacted Subs (Summary Category)")
        st.markdown(
            "<span style='font-size:0.8rem;color:#bbbbbb;'>Filtered: SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' | Site Type filter applied</span>",
            unsafe_allow_html=True,
        )
        
        if not cottr_by_summary.empty:
            cottr_by_summary['DATE'] = pd.to_datetime(cottr_by_summary['DATE_VALUE']).dt.date
            
            fig_s2 = make_subplots(specs=[[{"secondary_y": True}]])
            
            sum_cat_totals = cottr_by_summary.groupby('SITE_ID_SUMMARY_CATEGORY')['OUTAGE_MINUTES'].sum().sort_values(ascending=False)
            sum_categories = sum_cat_totals.head(10).index.tolist()
            
            for i, cat in enumerate(sum_categories):
                cat_data = cottr_by_summary[cottr_by_summary['SITE_ID_SUMMARY_CATEGORY'] == cat]
                cat_color = SUMMARY_CATEGORY_COLORS.get(cat, DEFAULT_SUMMARY_COLOR)
                fig_s2.add_trace(
                    go.Bar(x=cat_data['DATE'], y=cat_data['OUTAGE_MINUTES'], name=cat, marker_color=cat_color),
                    secondary_y=False
                )
            
            if not cm_daily.empty:
                cm_daily_sum = cm_daily.copy()
                cm_daily_sum['DATE'] = pd.to_datetime(cm_daily_sum['DATE_VALUE']).dt.date
                cm_daily_sum = cm_daily_sum.sort_values('DATE')
                fig_s2.add_trace(
                    go.Scatter(x=cm_daily_sum['DATE'], y=cm_daily_sum['IMPACTED_SUBS'], name='Impacted Subscribers',
                               line=dict(color='#4a0e4e', width=4), mode='lines+markers', marker=dict(size=8)),
                    secondary_y=True
                )
            
            fig_s2.update_layout(template='plotly_white', height=400, 
                              font=dict(size=14),
                              legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=12)),
                              hovermode='x unified', barmode='stack', margin=dict(t=80),
                              xaxis=dict(tickfont=dict(size=12)), yaxis=dict(tickfont=dict(size=12)))
            fig_s2.update_xaxes(tickformat="%b %d", tickangle=-45)
            fig_s2.update_yaxes(title_text="Service Outage Minutes", secondary_y=False)
            fig_s2.update_yaxes(title_text="Impacted Subs", secondary_y=True)
            
            st.plotly_chart(fig_s2, use_container_width=True, config=CHART_CONFIG, key="exec_sparkline_2")
        else:
            st.info("No COTTR data available.")

    st.divider()
    
    # ===== FOCUS CATEGORY CHARTS (existing) =====
    st.markdown("### 📊 Focus Category View")
    
    # Get data for charts
    cottr_by_cat = get_cottr_by_focus_category(conn, days, filters)
    cm_subs_daily = get_customer_minutes_daily(conn, days, filters)
    avail_pct_df, downtime_by_cat_df = get_availability_with_downtime_by_category(conn, days, filters)
    
    chart_col1, chart_col2 = st.columns(2)
    
    # Chart 1: Availability & Downtime (LEFT)
    with chart_col1:
        st.markdown("#### 📈 Availability % & Downtime by Focus Category")
        st.markdown(
            "<span style='font-size:0.8rem;color:#bbbbbb;'>Site Type filter applied</span>",
            unsafe_allow_html=True,
        )
        
        if not avail_pct_df.empty:
            avail_pct_df['DATE'] = pd.to_datetime(avail_pct_df['DATE_VALUE']).dt.date
            avail_pct_df = avail_pct_df.sort_values('DATE')
            
            fig1 = make_subplots(specs=[[{"secondary_y": True}]])
            
            if not downtime_by_cat_df.empty:
                downtime_by_cat_df['DATE'] = pd.to_datetime(downtime_by_cat_df['DATE_VALUE']).dt.date
                
                cat_totals = downtime_by_cat_df.groupby('SITE_ID_FOCUS_CATEGORY')['TOTAL_DOWNTIME'].sum().sort_values(ascending=False)
                categories = cat_totals.index.tolist()
                
                for cat in categories:
                    cat_data = downtime_by_cat_df[downtime_by_cat_df['SITE_ID_FOCUS_CATEGORY'] == cat]
                    color = FOCUS_CATEGORY_COLORS.get(cat, DEFAULT_FOCUS_COLOR)
                    fig1.add_trace(
                        go.Bar(x=cat_data['DATE'], y=cat_data['TOTAL_DOWNTIME'], name=cat, marker_color=color),
                        secondary_y=False
                    )
            
            fig1.add_trace(
                go.Scatter(x=avail_pct_df['DATE'], y=avail_pct_df['AVG_AVAILABILITY_PCT'], name='Availability %',
                           line=dict(color='#4a0e4e', width=4), mode='lines+markers', marker=dict(size=8)),
                secondary_y=True
            )
            
            # Goal line at 99.85% on secondary (right) axis
            fig1.add_shape(
                type="line",
                x0=0, x1=1, xref="paper",
                y0=99.85, y1=99.85, yref="y2",
                line=dict(color="#f59e0b", width=2, dash="dot"),
            )
            fig1.add_annotation(
                x=1, xref="paper",
                y=99.85, yref="y2",
                xanchor="right",
                yanchor="bottom",
                text="Goal: 99.85%",
                showarrow=False,
                font=dict(color="#f59e0b")
            )
            
            fig1.update_layout(template='plotly_white', height=450,
                              font=dict(size=14),
                              legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, font=dict(size=11)),
                              hovermode='x unified', barmode='stack', margin=dict(t=30, b=100),
                              xaxis=dict(tickfont=dict(size=12)), yaxis=dict(tickfont=dict(size=12)))
            fig1.update_xaxes(tickformat="%b %d", tickangle=-45)
            fig1.update_yaxes(title_text="Downtime (sec)", secondary_y=False)
            fig1.update_yaxes(title_text="Availability %", secondary_y=True, range=[99, 100])
            
            st.plotly_chart(fig1, use_container_width=True, config=CHART_CONFIG, key="exec_trend_1")
        else:
            st.info("No availability data available.")
    
    # Chart 2: COTTR & Impacted Subscribers (RIGHT)
    with chart_col2:
        st.markdown("#### 📈 COTTR Service Outage Minutes & Impacted Subs (Focus Category)")
        st.markdown(
            "<span style='font-size:0.8rem;color:#bbbbbb;'>Filtered: SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' | Site Type filter applied</span>",
            unsafe_allow_html=True,
        )
        
        if not cottr_by_cat.empty:
            cottr_by_cat['DATE'] = pd.to_datetime(cottr_by_cat['DATE_VALUE']).dt.date
            
            fig2 = make_subplots(specs=[[{"secondary_y": True}]])
            
            cat_totals = cottr_by_cat.groupby('SITE_ID_FOCUS_CATEGORY')['OUTAGE_MINUTES'].sum().sort_values(ascending=False)
            categories = cat_totals.index.tolist()
            
            for cat in categories:
                cat_data = cottr_by_cat[cottr_by_cat['SITE_ID_FOCUS_CATEGORY'] == cat]
                color = FOCUS_CATEGORY_COLORS.get(cat, DEFAULT_FOCUS_COLOR)
                fig2.add_trace(
                    go.Bar(x=cat_data['DATE'], y=cat_data['OUTAGE_MINUTES'], name=cat, marker_color=color),
                    secondary_y=False
                )
            
            if not cm_subs_daily.empty:
                cm_subs_daily['DATE'] = pd.to_datetime(cm_subs_daily['DATE_VALUE']).dt.date
                cm_subs_daily = cm_subs_daily.sort_values('DATE')
                fig2.add_trace(
                    go.Scatter(x=cm_subs_daily['DATE'], y=cm_subs_daily['IMPACTED_SUBS'], name='Impacted Subscribers',
                               line=dict(color='#4a0e4e', width=4), mode='lines+markers', marker=dict(size=8)),
                    secondary_y=True
                )
            
            fig2.update_layout(template='plotly_white', height=450, 
                              font=dict(size=14),
                              legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, font=dict(size=11)),
                              hovermode='x unified', barmode='stack', margin=dict(t=30, b=100),
                              xaxis=dict(tickfont=dict(size=12)), yaxis=dict(tickfont=dict(size=12)))
            fig2.update_xaxes(tickformat="%b %d", tickangle=-45)
            fig2.update_yaxes(title_text="Service Outage Minutes", secondary_y=False)
            fig2.update_yaxes(title_text="Impacted Subs", secondary_y=True)
            
            st.plotly_chart(fig2, use_container_width=True, config=CHART_CONFIG, key="exec_trend_2")
        else:
            st.info("No COTTR data available.")
    
    st.divider()
    
    # ===== AVAILABILITY SCATTER CHART =====
    st.markdown("### 📊 Availability Analysis - Downtime vs Availability %")
    st.markdown(
        "<span style='font-size:0.8rem;color:#bbbbbb;'>Site Type filter applied</span>",
        unsafe_allow_html=True,
    )
    
    # Determine if showing markets or sites based on filter
    show_sites = market is not None
    entity_label = "Sites" if show_sites else "Markets"
    
    avail_scatter_data = get_availability_scatter_data(conn, days, filters, by_site=show_sites)
    
    scatter_col1, scatter_col2 = st.columns(2)
    
    with scatter_col1:
        if not avail_scatter_data.empty:
            # Convert Decimal columns to float
            avail_scatter_data['TOTAL_DOWNTIME'] = avail_scatter_data['TOTAL_DOWNTIME'].astype(float)
            avail_scatter_data['AVG_AVAILABILITY'] = avail_scatter_data['AVG_AVAILABILITY'].astype(float)
            
            # Get top 5 by highest downtime
            top_5_df = avail_scatter_data.nlargest(5, 'TOTAL_DOWNTIME')
            top_5_ids = top_5_df['ENTITY_ID'].tolist()
            
            # Create scatter plot - use focus category colors when showing sites, region colors for markets
            if show_sites and 'FOCUS_CATEGORY' in avail_scatter_data.columns:
                avail_scatter_data['FOCUS_CATEGORY'] = avail_scatter_data['FOCUS_CATEGORY'].fillna('Uncategorized')
                fig = px.scatter(
                    avail_scatter_data,
                    x='TOTAL_DOWNTIME',
                    y='AVG_AVAILABILITY',
                    hover_name='ENTITY_NAME',
                    size='TOTAL_DOWNTIME',
                    size_max=25,
                    color='FOCUS_CATEGORY',
                    color_discrete_map=FOCUS_CATEGORY_COLORS,
                    title=f'Downtime vs Availability % by {entity_label}',
                    labels={
                        'TOTAL_DOWNTIME': 'Total Downtime (sec)',
                        'AVG_AVAILABILITY': 'Availability %',
                        'FOCUS_CATEGORY': 'Focus Category'
                    },
                )
            elif 'REGION_ID' in avail_scatter_data.columns:
                # Use region colors when showing markets
                avail_scatter_data['REGION_ID'] = avail_scatter_data['REGION_ID'].fillna('Unknown')
                fig = px.scatter(
                    avail_scatter_data,
                    x='TOTAL_DOWNTIME',
                    y='AVG_AVAILABILITY',
                    hover_name='ENTITY_NAME',
                    size='TOTAL_DOWNTIME',
                    size_max=25,
                    color='REGION_ID',
                    color_discrete_map=REGION_COLORS,
                    title=f'Downtime vs Availability % by {entity_label}',
                    labels={
                        'TOTAL_DOWNTIME': 'Total Downtime (sec)',
                        'AVG_AVAILABILITY': 'Availability %',
                        'REGION_ID': 'Region'
                    },
                )
            else:
                fig = px.scatter(
                    avail_scatter_data,
                    x='TOTAL_DOWNTIME',
                    y='AVG_AVAILABILITY',
                    hover_name='ENTITY_NAME',
                    size='TOTAL_DOWNTIME',
                    size_max=25,
                    title=f'Downtime vs Availability % by {entity_label}',
                    labels={
                        'TOTAL_DOWNTIME': 'Total Downtime (sec)',
                        'AVG_AVAILABILITY': 'Availability %'
                    },
                    color_discrete_sequence=['#e20074'],
                )
            
            # Add annotations for top 5 with alternating positions to avoid overlap
            positions = ['top center', 'bottom center', 'top right', 'bottom left', 'top left']
            for i, (_, row) in enumerate(top_5_df.iterrows()):
                fig.add_annotation(
                    x=row['TOTAL_DOWNTIME'],
                    y=row['AVG_AVAILABILITY'],
                    text=row['ENTITY_NAME'],
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=1,
                    arrowcolor='#666666',
                    ax=20 if i % 2 == 0 else -20,
                    ay=-25 if i % 2 == 0 else 25,
                    font=dict(size=9, color='#333333', family='Arial'),
                    bgcolor='rgba(255,255,255,0.8)',
                    bordercolor='#666666',
                    borderwidth=1,
                    borderpad=3,
                )
            
            # Add goal line at 99.85%
            fig.add_hline(y=99.85, line_dash="dot", line_color="#f59e0b", 
                         annotation_text="Goal: 99.85%", annotation_position="top right")
            
            # Custom hovertemplate: compact format, show downtime in K/M
            def format_k_avail(val):
                if val >= 1000000:
                    return f"{val/1000000:.2f}M"
                elif val >= 1000:
                    return f"{val/1000:.1f}k"
                return f"{val:.0f}"
            
            for trace in fig.data:
                trace.hovertemplate = '<b>%{hovertext}</b><br>Total Downtime (sec)=%{customdata[0]}<br>Availability %=%{customdata[1]}<extra></extra>'
                if hasattr(trace, 'x') and trace.x is not None and hasattr(trace, 'y') and trace.y is not None:
                    trace.customdata = [[format_k_avail(x), f"{y:.2f}"] for x, y in zip(trace.x, trace.y)]
            
            fig.update_traces(marker=dict(opacity=0.7, sizemin=5))
            min_avail = float(avail_scatter_data['AVG_AVAILABILITY'].min())
            fig.update_layout(
                template='plotly_white', 
                height=400,
                xaxis_title='Total Downtime (sec)',
                yaxis_title='Availability %',
                yaxis=dict(range=[min(99, min_avail - 0.1), 100]),
                margin=dict(t=60),
                hovermode='x unified',
                hoverlabel=HOVER_LABEL_STYLE,
            )
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="exec_scatter_avail")
        else:
            st.info("No availability data available for scatter chart.")
    
    with scatter_col2:
        if not focus_cat_totals.empty:
            top_focus = focus_cat_totals[~focus_cat_totals['SITE_ID_FOCUS_CATEGORY'].str.lower().str.contains('no outage', na=False)].sort_values('TOTAL_DOWNTIME', ascending=False)
            if 'SITE_COUNT' not in top_focus.columns:
                top_focus['SITE_COUNT'] = 0
            bar_colors = [FOCUS_CATEGORY_COLORS.get(cat, '#888888') for cat in top_focus['SITE_ID_FOCUS_CATEGORY']]
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(
                go.Bar(
                    x=top_focus['SITE_ID_FOCUS_CATEGORY'],
                    y=top_focus['TOTAL_DOWNTIME'],
                    marker_color=bar_colors,
                    name='Total Downtime',
                    hovertemplate='<b>%{x}</b><br>Downtime: %{y:,.0f} sec<extra></extra>',
                ),
                secondary_y=False,
            )
            fig.add_trace(
                go.Scatter(
                    x=top_focus['SITE_ID_FOCUS_CATEGORY'],
                    y=top_focus['SITE_COUNT'],
                    mode='markers+text',
                    name='Site Count',
                    marker=dict(size=8, color='#e20074'),
                    text=[f"{int(v):,}" for v in top_focus['SITE_COUNT']],
                    textposition='top center',
                    textfont=dict(size=9, color='#e20074', family='Arial Black'),
                    hovertemplate='<b>%{x}</b><br>Sites: %{y:,}<extra></extra>',
                ),
                secondary_y=True,
            )
            fig.update_layout(
                template='plotly_white',
                title='Total Downtime by Focus Category (Availability - Macro)',
                height=400,
                xaxis_tickangle=-45,
                showlegend=True,
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                hovermode=False,
                margin=dict(t=60),
            )
            fig.update_traces(hoverinfo='skip')
            fig.update_yaxes(title_text='Total Downtime (sec)', secondary_y=False)
            fig.update_yaxes(title_text='Distinct Sites', secondary_y=True, showgrid=False)
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="exec_focus_cat_bar")
    
    st.divider()

    # ===== COTTR SCATTER CHART =====
    st.markdown("### 📊 COTTR Analysis - Service Outage Minutes")
    st.markdown(
        "<span style='font-size:0.8rem;color:#bbbbbb;'>Using PER_DAY_OUTAGE_MINUTES | Filtered: SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' | Site Type filter applied</span>",
        unsafe_allow_html=True,
    )
    
    cottr_scatter_data = get_cottr_scatter_data(conn, days, filters, by_site=show_sites)
    
    cottr_col1, cottr_col2 = st.columns(2)
    
    with cottr_col1:
        if not cottr_scatter_data.empty:
            # Convert Decimal columns to float
            cottr_scatter_data['TOTAL_OUTAGE_MINUTES'] = cottr_scatter_data['TOTAL_OUTAGE_MINUTES'].astype(float)
            cottr_scatter_data['IMPACTED_SUBS'] = cottr_scatter_data['IMPACTED_SUBS'].astype(float)
            
            # Get top 5 by highest outage minutes
            top_5_df = cottr_scatter_data.nlargest(5, 'TOTAL_OUTAGE_MINUTES')
            
            # Create scatter plot - use focus category colors when showing sites, region colors for markets
            if show_sites and 'FOCUS_CATEGORY' in cottr_scatter_data.columns:
                cottr_scatter_data['FOCUS_CATEGORY'] = cottr_scatter_data['FOCUS_CATEGORY'].fillna('Uncategorized')
                fig = px.scatter(
                    cottr_scatter_data,
                    x='TOTAL_OUTAGE_MINUTES',
                    y='IMPACTED_SUBS',
                    hover_name='ENTITY_NAME',
                    size='TOTAL_OUTAGE_MINUTES',
                    color='FOCUS_CATEGORY',
                    color_discrete_map=FOCUS_CATEGORY_COLORS,
                    title=f'Service Outage Minutes vs Impacted Subscribers by {entity_label}',
                    labels={
                        'TOTAL_OUTAGE_MINUTES': 'Total Service Outage Minutes',
                        'IMPACTED_SUBS': 'Impacted Subscribers',
                        'FOCUS_CATEGORY': 'Focus Category'
                    },
                )
            elif 'REGION_ID' in cottr_scatter_data.columns:
                # Use region colors when showing markets
                cottr_scatter_data['REGION_ID'] = cottr_scatter_data['REGION_ID'].fillna('Unknown')
                fig = px.scatter(
                    cottr_scatter_data,
                    x='TOTAL_OUTAGE_MINUTES',
                    y='IMPACTED_SUBS',
                    hover_name='ENTITY_NAME',
                    size='TOTAL_OUTAGE_MINUTES',
                    color='REGION_ID',
                    color_discrete_map=REGION_COLORS,
                    title=f'Service Outage Minutes vs Impacted Subscribers by {entity_label}',
                    labels={
                        'TOTAL_OUTAGE_MINUTES': 'Total Service Outage Minutes',
                        'IMPACTED_SUBS': 'Impacted Subscribers',
                        'REGION_ID': 'Region'
                    },
                )
            else:
                fig = px.scatter(
                    cottr_scatter_data,
                    x='TOTAL_OUTAGE_MINUTES',
                    y='IMPACTED_SUBS',
                    hover_name='ENTITY_NAME',
                    size='TOTAL_OUTAGE_MINUTES',
                    title=f'Service Outage Minutes vs Impacted Subscribers by {entity_label}',
                    labels={
                        'TOTAL_OUTAGE_MINUTES': 'Total Service Outage Minutes',
                        'IMPACTED_SUBS': 'Impacted Subscribers'
                    },
                    color_discrete_sequence=['#f59e0b'],
                )
            
            # Add annotations for top 5 with alternating positions to avoid overlap
            for i, (_, row) in enumerate(top_5_df.iterrows()):
                fig.add_annotation(
                    x=row['TOTAL_OUTAGE_MINUTES'],
                    y=row['IMPACTED_SUBS'],
                    text=row['ENTITY_NAME'],
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=1,
                    arrowcolor='#666666',
                    ax=25 if i % 2 == 0 else -25,
                    ay=-30 if i % 2 == 0 else 30,
                    font=dict(size=9, color='#333333', family='Arial'),
                    bgcolor='rgba(255,255,255,0.8)',
                    bordercolor='#666666',
                    borderwidth=1,
                    borderpad=3,
                )
            
            # Custom hovertemplate: compact format, show minutes in K
            def format_k(val):
                if val >= 1000:
                    return f"{val/1000:.1f}k"
                return f"{val:.0f}"
            
            for trace in fig.data:
                trace.hovertemplate = '<b>%{hovertext}</b><br>Service Outage Mins=%{customdata[0]}<br>Impacted Subs=%{customdata[1]}<extra></extra>'
                if hasattr(trace, 'x') and trace.x is not None and hasattr(trace, 'y') and trace.y is not None:
                    trace.customdata = [[format_k(x), format_k(y)] for x, y in zip(trace.x, trace.y)]
            
            fig.update_traces(marker=dict(opacity=0.7, sizemin=5))
            fig.update_layout(
                template='plotly_white', 
                height=400,
                xaxis_title='Total Service Outage Minutes (K)',
                yaxis_title='Impacted Subscribers (K)',
                margin=dict(t=60),
                hovermode='x unified',
                hoverlabel=HOVER_LABEL_STYLE,
            )
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="exec_scatter_cottr")
        else:
            st.info("No COTTR data available for scatter chart.")
    
    with cottr_col2:
        if not focus_cottr_totals.empty:
            top_focus_cottr = focus_cottr_totals[~focus_cottr_totals['SITE_ID_FOCUS_CATEGORY'].str.lower().str.contains('no outage', na=False)].sort_values('TOTAL_OUTAGE_MINUTES', ascending=False)
            if 'SITE_COUNT' not in top_focus_cottr.columns:
                top_focus_cottr['SITE_COUNT'] = 0
            cottr_bar_colors = [FOCUS_CATEGORY_COLORS.get(cat, '#888888') for cat in top_focus_cottr['SITE_ID_FOCUS_CATEGORY']]
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(
                go.Bar(
                    x=top_focus_cottr['SITE_ID_FOCUS_CATEGORY'],
                    y=top_focus_cottr['TOTAL_OUTAGE_MINUTES'],
                    marker_color=cottr_bar_colors,
                    name='Outage Minutes',
                    hovertemplate='<b>%{x}</b><br>Outage Mins: %{y:,.0f}<extra></extra>',
                ),
                secondary_y=False,
            )
            fig.add_trace(
                go.Scatter(
                    x=top_focus_cottr['SITE_ID_FOCUS_CATEGORY'],
                    y=top_focus_cottr['SITE_COUNT'],
                    mode='markers+text',
                    name='Site Count',
                    marker=dict(size=8, color='#e20074'),
                    text=[f"{int(v):,}" for v in top_focus_cottr['SITE_COUNT']],
                    textposition='top center',
                    textfont=dict(size=9, color='#e20074', family='Arial Black'),
                    hovertemplate='<b>%{x}</b><br>Sites: %{y:,}<extra></extra>',
                ),
                secondary_y=True,
            )
            fig.update_layout(
                template='plotly_white',
                title='Total Service Outage Minutes by Focus Category (COTTR - Macro)',
                height=400,
                xaxis_tickangle=-45,
                showlegend=True,
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                hovermode=False,
                margin=dict(t=60),
            )
            fig.update_traces(hoverinfo='skip')
            fig.update_yaxes(title_text='Total Outage Minutes', secondary_y=False)
            fig.update_yaxes(title_text='Distinct Sites', secondary_y=True, showgrid=False)
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="exec_cottr_focus_bar")
    
    st.divider()
    
    # ===== MARKET COMPARISON (only show when no market is selected) =====
    if not market:
        st.markdown("### 🗺️ Market Comparison")
        st.markdown(
            "<span style='font-size:0.8rem;color:#bbbbbb;'>All charts filtered by Site Type</span>",
            unsafe_allow_html=True,
        )
        
        mkt_col1, mkt_col2 = st.columns(2)
        
        # Left: Availability downtime by market and focus category (markets below goal)
        with mkt_col1:
            if not market_by_cat.empty and not market_totals.empty:
                below_goal_mkts = market_totals[market_totals['AVG_AVAILABILITY'] < 99.85].sort_values('TOTAL_DOWNTIME', ascending=False)['MARKET_ID'].tolist()
                if below_goal_mkts:
                    # Show Top 15 in chart, with scrollbar for more
                    top_15_mkts = below_goal_mkts[:15]
                    total_below_goal = len(below_goal_mkts)
                    
                    # Aggregate by market and category first to avoid duplicates
                    market_cat_agg = market_by_cat.groupby(['MARKET_ID', 'SITE_ID_FOCUS_CATEGORY'], as_index=False)['TOTAL_DOWNTIME'].sum()
                    filtered_below = market_cat_agg[market_cat_agg['MARKET_ID'].isin(top_15_mkts)].copy()
                    
                    # Calculate % of impact for each category within each market
                    market_totals_dict = filtered_below.groupby('MARKET_ID')['TOTAL_DOWNTIME'].sum().to_dict()
                    filtered_below['PCT_IMPACT'] = filtered_below.apply(
                        lambda row: (row['TOTAL_DOWNTIME'] / market_totals_dict.get(row['MARKET_ID'], 1) * 100) if market_totals_dict.get(row['MARKET_ID'], 0) > 0 else 0,
                        axis=1
                    )
                    
                    # Determine top 3 categories per market for text display
                    filtered_below['RANK_IN_MARKET'] = filtered_below.groupby('MARKET_ID')['PCT_IMPACT'].rank(method='first', ascending=False)
                    
                    # Only show % text for top 3 categories (if segment is large enough - at least 10%)
                    filtered_below['TEXT_LABEL'] = filtered_below.apply(
                        lambda row: f"{row['PCT_IMPACT']:.0f}%" if row['RANK_IN_MARKET'] <= 3 and row['PCT_IMPACT'] >= 10 else '',
                        axis=1
                    )
                    
                    # Category order based on total impact (highest first)
                    cat_order = filtered_below.groupby('SITE_ID_FOCUS_CATEGORY')['TOTAL_DOWNTIME'].sum().sort_values(ascending=False).index.tolist()
                    
                    chart_title = f'Top 15 of {total_below_goal} Markets Below 99.85% Goal – Availability Downtime (by Focus Category)'
                    
                    fig = px.bar(
                        filtered_below,
                        x='TOTAL_DOWNTIME',
                        y='MARKET_ID',
                        color='SITE_ID_FOCUS_CATEGORY',
                        orientation='h',
                        title=chart_title,
                        color_discrete_map=FOCUS_CATEGORY_COLORS,
                        category_orders={'SITE_ID_FOCUS_CATEGORY': cat_order},
                        text='TEXT_LABEL',
                        custom_data=['SITE_ID_FOCUS_CATEGORY', 'PCT_IMPACT'],
                    )
                    
                    # Show text inside bars, enable hover for bars without text
                    fig.update_traces(
                        textposition='inside',
                        textfont=dict(size=14, color='white', family='Arial Black'),
                        insidetextanchor='middle',
                        hoverinfo='skip',
                    )
                    
                    fig.update_layout(
                        template='plotly_white',
                        height=500,
                        font=dict(size=14),
                        uniformtext=dict(minsize=12, mode='show'),
                        yaxis={'categoryorder': 'total ascending', 'dtick': 1, 'tickfont': dict(size=12)},
                        yaxis_title='Market',
                        xaxis_title='Downtime (sec)',
                        xaxis=dict(tickfont=dict(size=12)),
                        hovermode=False,
                        legend=dict(
                            orientation="h",
                            yanchor="top",
                            y=-0.15,
                            xanchor="right",
                            x=1,
                            font=dict(size=12),
                        ),
                        margin=dict(t=80, b=80),
                        title=dict(y=0.98),
                    )
                    st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="mkt_avail_bar")
                    
                    # Show expandable table with all markets below goal
                    if total_below_goal > 15:
                        with st.expander(f"📋 View All {total_below_goal} Markets Below Goal"):
                            all_below_df = market_totals[market_totals['AVG_AVAILABILITY'] < 99.85].sort_values('TOTAL_DOWNTIME', ascending=False)
                            display_cols = ['MARKET_ID', 'TOTAL_DOWNTIME', 'AVG_AVAILABILITY']
                            if 'SECONDS_BUDGET' in all_below_df.columns:
                                display_cols.append('SECONDS_BUDGET')
                            if 'OVER_UNDER' in all_below_df.columns:
                                display_cols.append('OVER_UNDER')
                            display_df = all_below_df[display_cols].copy()
                            # Format: Availability to 2 decimals, Budget and Over/Under to whole numbers
                            display_df['AVG_AVAILABILITY'] = pd.to_numeric(display_df['AVG_AVAILABILITY'], errors='coerce').round(2)
                            display_df['TOTAL_DOWNTIME'] = pd.to_numeric(display_df['TOTAL_DOWNTIME'], errors='coerce').fillna(0).astype(int)
                            if 'SECONDS_BUDGET' in display_df.columns:
                                display_df['SECONDS_BUDGET'] = pd.to_numeric(display_df['SECONDS_BUDGET'], errors='coerce').fillna(0).astype(int)
                            if 'OVER_UNDER' in display_df.columns:
                                display_df['OVER_UNDER'] = pd.to_numeric(display_df['OVER_UNDER'], errors='coerce').fillna(0).astype(int)
                            display_df.columns = ['Market', 'Total Downtime (sec)', 'Avg Availability %'] + (['Budget (sec)', 'Over/Under'] if len(display_cols) > 3 else [])
                            st.dataframe(display_df, use_container_width=True, height=300)
                else:
                    st.success("✅ All markets are above the 99.85% availability goal!")
        
        # Right: COTTR outage minutes by market and focus category
        with mkt_col2:
            if not cottr_market_by_cat.empty:
                # Aggregate by market and category first to avoid duplicates
                cottr_agg = cottr_market_by_cat.groupby(['MARKET_ID', 'SITE_ID_FOCUS_CATEGORY'], as_index=False)['TOTAL_OUTAGE_MINUTES'].sum()
                
                # Get markets with highest COTTR outage minutes
                cottr_market_totals = cottr_agg.groupby('MARKET_ID')['TOTAL_OUTAGE_MINUTES'].sum().sort_values(ascending=False)
                top_market_ids = cottr_market_totals.head(15).index.tolist()
                filtered_data = cottr_agg[cottr_agg['MARKET_ID'].isin(top_market_ids)].copy()
                
                # Calculate % of impact for each category within each market
                market_totals_cottr = filtered_data.groupby('MARKET_ID')['TOTAL_OUTAGE_MINUTES'].sum().to_dict()
                filtered_data['PCT_IMPACT'] = filtered_data.apply(
                    lambda row: (row['TOTAL_OUTAGE_MINUTES'] / market_totals_cottr.get(row['MARKET_ID'], 1) * 100) if market_totals_cottr.get(row['MARKET_ID'], 0) > 0 else 0,
                    axis=1
                )
                
                # Determine top 3 categories per market for text display
                filtered_data['RANK_IN_MARKET'] = filtered_data.groupby('MARKET_ID')['PCT_IMPACT'].rank(method='first', ascending=False)
                
                # Only show % text for top 3 categories (if segment is large enough - at least 10%)
                filtered_data['TEXT_LABEL'] = filtered_data.apply(
                    lambda row: f"{row['PCT_IMPACT']:.0f}%" if row['RANK_IN_MARKET'] <= 3 and row['PCT_IMPACT'] >= 10 else '',
                    axis=1
                )
                
                # Category order based on total impact (highest first)
                cat_order = filtered_data.groupby('SITE_ID_FOCUS_CATEGORY')['TOTAL_OUTAGE_MINUTES'].sum().sort_values(ascending=False).index.tolist()
                
                fig = px.bar(
                    filtered_data,
                    x='TOTAL_OUTAGE_MINUTES',
                    y='MARKET_ID',
                    color='SITE_ID_FOCUS_CATEGORY',
                    orientation='h',
                    title='Top 15 Markets by Service Outage Minutes - Macro (by Focus Category)',
                    color_discrete_map=FOCUS_CATEGORY_COLORS,
                    category_orders={'SITE_ID_FOCUS_CATEGORY': cat_order},
                    text='TEXT_LABEL',
                    custom_data=['SITE_ID_FOCUS_CATEGORY', 'PCT_IMPACT'],
                )
                
                # Show text inside bars, enable hover for bars without text
                fig.update_traces(
                    textposition='inside',
                    textfont=dict(size=14, color='white', family='Arial Black'),
                    insidetextanchor='middle',
                    hoverinfo='skip',
                )
                
                fig.update_layout(
                    template='plotly_white',
                    height=500,
                    font=dict(size=14),
                    uniformtext=dict(minsize=12, mode='show'),
                    yaxis={'categoryorder': 'total ascending', 'dtick': 1, 'tickfont': dict(size=12)},
                    yaxis_title='Market',
                    xaxis_title='Service Outage Minutes',
                    xaxis=dict(tickfont=dict(size=12)),
                    hovermode=False,
                    legend=dict(
                        orientation="h",
                        yanchor="top",
                        y=-0.15,
                        xanchor="right",
                        x=1,
                        font=dict(size=12),
                    ),
                    margin=dict(t=80, b=80),
                    title=dict(y=0.98),
                )
                st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="mkt_cottr_bar")
        
        st.divider()
    
    # ===== DAILY TREND SUMMARY =====
    trend_header_col1, trend_header_col2 = st.columns([3, 1])
    with trend_header_col1:
        st.markdown("### 📅 Daily Trend Summary")
    with trend_header_col2:
        show_prior_year = st.checkbox("📊 Show 2025 Comparison", value=False, key="prior_year_toggle")
    
    # Fetch prior year data if toggle is enabled
    cm_daily_prior, avail_daily_prior, cottr_daily_prior = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    cm_ytd_change, avail_ytd_change, cottr_ytd_change = None, None, None
    if show_prior_year:
        with st.spinner("Loading 2025 data..."):
            cm_daily_prior, avail_daily_prior, cottr_daily_prior = get_combined_daily_data_prior_year(conn, days, filters)
            
            # Calculate YTD comparison values
            if not cm_daily.empty and not cm_daily_prior.empty:
                cm_2026_ytd = cm_daily['CUSTOMER_MINUTES'].sum()
                cm_2025_ytd = cm_daily_prior['CUSTOMER_MINUTES'].sum()
                if cm_2025_ytd > 0:
                    cm_ytd_pct = ((cm_2026_ytd - cm_2025_ytd) / cm_2025_ytd) * 100
                    cm_ytd_change = {'pct': cm_ytd_pct, 'current': cm_2026_ytd, 'prior': cm_2025_ytd}
            
            if not avail_daily.empty and not avail_daily_prior.empty:
                # Use aggregated formula: SUM(N) / SUM(D) * 100 instead of averaging daily percentages
                if 'TOTAL_AVAILABILITY_N' in avail_daily.columns and 'TOTAL_AVAILABILITY_D' in avail_daily.columns:
                    total_n_2026 = avail_daily['TOTAL_AVAILABILITY_N'].sum()
                    total_d_2026 = avail_daily['TOTAL_AVAILABILITY_D'].sum()
                    avail_2026_ytd = (total_n_2026 / total_d_2026 * 100) if total_d_2026 > 0 else 0
                    
                    total_n_2025 = avail_daily_prior['TOTAL_AVAILABILITY_N'].sum()
                    total_d_2025 = avail_daily_prior['TOTAL_AVAILABILITY_D'].sum()
                    avail_2025_ytd = (total_n_2025 / total_d_2025 * 100) if total_d_2025 > 0 else 0
                else:
                    # Fallback to mean if columns not available
                    avail_2026_ytd = avail_daily['AVG_AVAILABILITY_PCT'].mean()
                    avail_2025_ytd = avail_daily_prior['AVG_AVAILABILITY_PCT'].mean()
                avail_ytd_diff = avail_2026_ytd - avail_2025_ytd
                avail_ytd_change = {'diff': avail_ytd_diff, 'current': avail_2026_ytd, 'prior': avail_2025_ytd}
            
            if not cottr_daily.empty and not cottr_daily_prior.empty:
                cottr_2026_ytd = cottr_daily['OUTAGE_MINUTES'].sum()
                cottr_2025_ytd = cottr_daily_prior['OUTAGE_MINUTES'].sum()
                if cottr_2025_ytd > 0:
                    cottr_ytd_pct = ((cottr_2026_ytd - cottr_2025_ytd) / cottr_2025_ytd) * 100
                    cottr_ytd_change = {'pct': cottr_ytd_pct, 'current': cottr_2026_ytd, 'prior': cottr_2025_ytd}
    
    trend_col1, trend_col2, trend_col3 = st.columns(3)
    
    with trend_col1:
        # Display YTD comparison badge if 2025 comparison is enabled
        cm_title = "Customer Minutes Trend"
        if show_prior_year and cm_ytd_change:
            pct = cm_ytd_change['pct']
            is_improved = pct < 0  # Lower is better for customer minutes
            color = "#22c55e" if is_improved else "#ef4444"
            arrow = "↓" if pct < 0 else "↑"
            status = "Improved" if is_improved else "Degraded"
            st.markdown(f"""
            <div style='display:flex;align-items:center;gap:10px;margin-bottom:5px;'>
                <span style='font-weight:bold;font-size:1rem;'>Customer Minutes Trend</span>
                <span style='background:{color};color:white;padding:2px 8px;border-radius:12px;font-size:0.75rem;font-weight:bold;'>
                    YTD: {arrow} {abs(pct):.1f}% {status}
                </span>
            </div>
            <div style='font-size:0.7rem;color:#888;margin-bottom:5px;'>
                2026: {cm_ytd_change['current']/1000:,.0f}K vs 2025: {cm_ytd_change['prior']/1000:,.0f}K
            </div>
            """, unsafe_allow_html=True)
            cm_title = None  # Don't show title in chart since we displayed it above
        
        if not cm_daily.empty:
            cm_daily_sorted = cm_daily.copy()
            cm_daily_sorted['DATE'] = pd.to_datetime(cm_daily_sorted['DATE_VALUE']).dt.date
            cm_daily_sorted = cm_daily_sorted.sort_values('DATE')
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=cm_daily_sorted['DATE'], y=cm_daily_sorted['CUSTOMER_MINUTES'],
                name='2026', mode='lines+markers', line=dict(color='#e20074', width=2),
                marker=dict(size=6),
                hovertemplate='%{x}<br>%{y:,.0f} mins<extra>2026</extra>'
            ))
            
            if show_prior_year and not cm_daily_prior.empty:
                cm_prior_sorted = cm_daily_prior.copy()
                cm_prior_sorted['DATE'] = pd.to_datetime(cm_prior_sorted['DATE_VALUE']).dt.date
                cm_prior_sorted = cm_prior_sorted.sort_values('DATE')
                # Shift prior year dates to align with current year for comparison
                cm_prior_sorted['DATE_ALIGNED'] = cm_prior_sorted['DATE'].apply(lambda d: d.replace(year=d.year + 1) if hasattr(d, 'replace') else d)
                fig.add_trace(go.Scatter(
                    x=cm_prior_sorted['DATE_ALIGNED'], y=cm_prior_sorted['CUSTOMER_MINUTES'],
                    name='2025', mode='lines+markers', line=dict(color='#888888', width=2, dash='dot'),
                    marker=dict(size=5), customdata=cm_prior_sorted['DATE'],
                    hovertemplate='%{customdata}<br>%{y:,.0f} mins<extra>2025</extra>'
                ))
            
            fig.update_layout(
                template='plotly_white', height=300, title=cm_title,
                xaxis_title='Date', yaxis_title='Customer Minutes',
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1)
            )
            fig.update_xaxes(tickformat='%m/%d', tickangle=-45)
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="daily_cm_trend")
    
    with trend_col2:
        # Display YTD comparison badge if 2025 comparison is enabled
        avail_title = 'Daily Availability % Trend (Macro)'
        if show_prior_year and avail_ytd_change:
            diff = avail_ytd_change['diff']
            is_improved = diff > 0  # Higher is better for availability
            color = "#22c55e" if is_improved else "#ef4444"
            arrow = "↑" if diff > 0 else "↓"
            status = "Improved" if is_improved else "Degraded"
            st.markdown(f"""
            <div style='display:flex;align-items:center;gap:10px;margin-bottom:5px;'>
                <span style='font-weight:bold;font-size:1rem;'>Daily Availability % Trend (Macro)</span>
                <span style='background:{color};color:white;padding:2px 8px;border-radius:12px;font-size:0.75rem;font-weight:bold;'>
                    YTD: {arrow} {abs(diff):.2f}% {status}
                </span>
            </div>
            <div style='font-size:0.7rem;color:#888;margin-bottom:5px;'>
                2026: {avail_ytd_change['current']:.2f}% vs 2025: {avail_ytd_change['prior']:.2f}%
            </div>
            """, unsafe_allow_html=True)
            avail_title = None  # Don't show title in chart since we displayed it above
        
        if not avail_daily.empty:
            avail_sorted = avail_daily.copy()
            avail_sorted['DATE'] = pd.to_datetime(avail_sorted['DATE_VALUE']).dt.date
            avail_sorted = avail_sorted.sort_values('DATE')
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=avail_sorted['DATE'], y=avail_sorted['AVG_AVAILABILITY_PCT'],
                name='2026', mode='lines+markers', line=dict(color='#a33c6e', width=2),
                marker=dict(size=6),
                hovertemplate='%{x}<br>%{y:.2f}%<extra>2026</extra>'
            ))
            
            if show_prior_year and not avail_daily_prior.empty:
                avail_prior_sorted = avail_daily_prior.copy()
                avail_prior_sorted['DATE'] = pd.to_datetime(avail_prior_sorted['DATE_VALUE']).dt.date
                avail_prior_sorted = avail_prior_sorted.sort_values('DATE')
                # Shift prior year dates to align with current year for comparison
                avail_prior_sorted['DATE_ALIGNED'] = avail_prior_sorted['DATE'].apply(lambda d: d.replace(year=d.year + 1) if hasattr(d, 'replace') else d)
                fig.add_trace(go.Scatter(
                    x=avail_prior_sorted['DATE_ALIGNED'], y=avail_prior_sorted['AVG_AVAILABILITY_PCT'],
                    name='2025', mode='lines+markers', line=dict(color='#888888', width=2, dash='dot'),
                    marker=dict(size=5), customdata=avail_prior_sorted['DATE'],
                    hovertemplate='%{customdata}<br>%{y:.2f}%<extra>2025</extra>'
                ))
            
            # Add 99.85% goal line
            fig.add_hline(y=99.85, line_dash="dot", line_color="#e20074", 
                         annotation_text="Goal: 99.85%", annotation_position="top right")
            
            # Set y-axis range
            min_val = float(avail_sorted['AVG_AVAILABILITY_PCT'].min()) if not avail_sorted.empty else 99
            max_val = float(avail_sorted['AVG_AVAILABILITY_PCT'].max()) if not avail_sorted.empty else 100
            if show_prior_year and not avail_daily_prior.empty:
                min_val = min(min_val, float(avail_prior_sorted['AVG_AVAILABILITY_PCT'].min()))
                max_val = max(max_val, float(avail_prior_sorted['AVG_AVAILABILITY_PCT'].max()))
            y_min = min(min_val - 0.5, 99.3)
            y_max = max(max_val + 0.2, 100.05)
            
            fig.update_layout(
                template='plotly_white', height=300, title=avail_title,
                xaxis_title='Date', yaxis_title='Daily Availability %',
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1)
            )
            fig.update_xaxes(tickformat='%m/%d', tickangle=-45)
            fig.update_yaxes(range=[y_min, y_max], tickformat=".2f")
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="daily_avail_trend")
    
    with trend_col3:
        # Display YTD comparison badge if 2025 comparison is enabled
        cottr_title = 'COTTR Service Outage Minutes Trend'
        if show_prior_year and cottr_ytd_change:
            pct = cottr_ytd_change['pct']
            is_improved = pct < 0  # Lower is better for outage minutes
            color = "#22c55e" if is_improved else "#ef4444"
            arrow = "↓" if pct < 0 else "↑"
            status = "Improved" if is_improved else "Degraded"
            st.markdown(f"""
            <div style='display:flex;align-items:center;gap:10px;margin-bottom:5px;'>
                <span style='font-weight:bold;font-size:1rem;'>COTTR Service Outage Minutes Trend</span>
                <span style='background:{color};color:white;padding:2px 8px;border-radius:12px;font-size:0.75rem;font-weight:bold;'>
                    YTD: {arrow} {abs(pct):.1f}% {status}
                </span>
            </div>
            <div style='font-size:0.7rem;color:#888;margin-bottom:5px;'>
                2026: {cottr_ytd_change['current']/1000:,.0f}K mins vs 2025: {cottr_ytd_change['prior']/1000:,.0f}K mins
            </div>
            """, unsafe_allow_html=True)
            cottr_title = None  # Don't show title in chart since we displayed it above
        
        if not cottr_daily.empty:
            cottr_sorted = cottr_daily.copy()
            cottr_sorted['DATE'] = pd.to_datetime(cottr_sorted['DATE_VALUE']).dt.date
            cottr_sorted = cottr_sorted.sort_values('DATE')
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=cottr_sorted['DATE'], y=cottr_sorted['OUTAGE_MINUTES'],
                name='2026', mode='lines+markers', line=dict(color='#8b4a72', width=2),
                marker=dict(size=6),
                hovertemplate='%{x}<br>%{y:,.0f} mins<extra>2026</extra>'
            ))
            
            if show_prior_year and not cottr_daily_prior.empty:
                cottr_prior_sorted = cottr_daily_prior.copy()
                cottr_prior_sorted['DATE'] = pd.to_datetime(cottr_prior_sorted['DATE_VALUE']).dt.date
                cottr_prior_sorted = cottr_prior_sorted.sort_values('DATE')
                # Shift prior year dates to align with current year for comparison
                cottr_prior_sorted['DATE_ALIGNED'] = cottr_prior_sorted['DATE'].apply(lambda d: d.replace(year=d.year + 1) if hasattr(d, 'replace') else d)
                fig.add_trace(go.Scatter(
                    x=cottr_prior_sorted['DATE_ALIGNED'], y=cottr_prior_sorted['OUTAGE_MINUTES'],
                    name='2025', mode='lines+markers', line=dict(color='#888888', width=2, dash='dot'),
                    marker=dict(size=5), customdata=cottr_prior_sorted['DATE'],
                    hovertemplate='%{customdata}<br>%{y:,.0f} mins<extra>2025</extra>'
                ))
            
            fig.update_layout(
                template='plotly_white', height=300, title=cottr_title,
                xaxis_title='Date', yaxis_title='Outage Minutes',
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1)
            )
            fig.update_xaxes(tickformat='%m/%d', tickangle=-45)
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="daily_cottr_trend")
    
    st.divider()
    
    # ===== MARKET AVAILABILITY GOAL TRACKING =====
    st.markdown("### 🎯 Market Availability Goal Tracking (Macro Only)")
    
    # Get market daily availability data
    market_daily = get_market_daily_availability(conn, days, filters)
    
    # Normalize market names to Global Market ID format
    if not market_daily.empty and 'MARKET_ID' in market_daily.columns:
        market_daily = normalize_market_column(market_daily, 'MARKET_ID', 'availability')
    
    if not market_daily.empty:
        # Calculate metrics per market
        market_daily['DAILY_AVAILABILITY'] = market_daily['DAILY_AVAILABILITY'].astype(float)
        market_daily['MEETS_GOAL'] = market_daily['DAILY_AVAILABILITY'] >= 99.85
        
        # Aggregate by market
        market_summary = market_daily.groupby(['MARKET_ID', 'REGION_ID']).agg({
            'DAILY_AVAILABILITY': 'mean',
            'MEETS_GOAL': ['sum', 'count']
        }).reset_index()
        market_summary.columns = ['MARKET_ID', 'REGION_ID', 'MEAN_AVAILABILITY', 'DAYS_MEETING_GOAL', 'TOTAL_DAYS']
        market_summary['PCT_DAYS_MEETING_GOAL'] = (market_summary['DAYS_MEETING_GOAL'] / market_summary['TOTAL_DAYS'] * 100).round(1)
        market_summary['MEAN_AVAILABILITY'] = market_summary['MEAN_AVAILABILITY'].round(3)
        
        # Get date range for subtitle
        start_dt = filters.get('start_date') if filters else None
        end_dt = filters.get('end_date') if filters else None
        date_range_str = f"{start_dt} to {end_dt}" if start_dt and end_dt else f"Last {days} days"
        total_days_in_range = int(market_summary['TOTAL_DAYS'].max()) if not market_summary.empty else 0
        
        # ===== NATIONAL & REGION SUMMARY TABLES =====
        summary_col1, summary_col2 = st.columns(2)
        
        with summary_col1:
            # National Summary
            st.markdown("##### National (Macro Only, Daily Availability ≥ 99.85%)")
            st.markdown(f"<span style='font-size:0.75rem;color:#888;'>Data window: {date_range_str} ({total_days_in_range} days)</span>", unsafe_allow_html=True)
            
            # Calculate national totals - aggregate by DATE first, then count calendar days
            national_daily = market_daily.groupby('DATE_VALUE').agg({
                'DAILY_AVAILABILITY': 'mean'
            }).reset_index()
            national_daily['MEETS_GOAL'] = national_daily['DAILY_AVAILABILITY'] >= 99.85
            national_days_meeting = int(national_daily['MEETS_GOAL'].sum())
            national_total_days = len(national_daily)
            national_pct = (national_days_meeting / national_total_days * 100) if national_total_days > 0 else 0
            
            national_df = pd.DataFrame({
                'Level': ['National'],
                'Macro Only — Days ≥ 99.85%': [f"{national_days_meeting} / {national_total_days}"],
                'Macro Only — % of Days': [f"{national_pct:.1f}%"]
            })
            st.dataframe(national_df, use_container_width=True, hide_index=True, height=70)
            
            # By Region Summary
            st.markdown("##### By Region (Macro Only)")
            
            # Aggregate by region AND date first to get daily regional averages, then count days
            region_daily = market_daily.groupby(['REGION_ID', 'DATE_VALUE']).agg({
                'DAILY_AVAILABILITY': 'mean'
            }).reset_index()
            region_daily['MEETS_GOAL'] = region_daily['DAILY_AVAILABILITY'] >= 99.85
            
            region_summary = region_daily.groupby('REGION_ID').agg({
                'MEETS_GOAL': ['sum', 'count']
            }).reset_index()
            region_summary.columns = ['Region', 'Days Meeting Goal', 'Total Days']
            region_summary['Macro Only (Days ≥ / Total)'] = region_summary['Days Meeting Goal'].astype(int).astype(str) + ' / ' + region_summary['Total Days'].astype(int).astype(str)
            region_summary['Macro Only % ≥ 99.85%'] = (region_summary['Days Meeting Goal'] / region_summary['Total Days'] * 100).round(1).astype(str) + '%'
            region_summary = region_summary[['Region', 'Macro Only (Days ≥ / Total)', 'Macro Only % ≥ 99.85%']]
            
            st.dataframe(region_summary, use_container_width=True, hide_index=True, height=180)
        
        with summary_col2:
            # Performance Band Distribution
            st.markdown("##### Performance Band (% of Days ≥ 99.85%)")
            st.markdown("<span style='font-size:0.75rem;color:#888;'>Band definition: % of days ≥ 99.85%</span>", unsafe_allow_html=True)
            
            def get_band(pct):
                if pct >= 60:
                    return '≥ 60% of Days'
                elif pct >= 40:
                    return '40% - 59.9%'
                elif pct >= 20:
                    return '20% - 39.9%'
                else:
                    return '< 20%'
            
            market_summary['Performance Band'] = market_summary['PCT_DAYS_MEETING_GOAL'].apply(get_band)
            
            band_order = ['≥ 60% of Days', '40% - 59.9%', '20% - 39.9%', '< 20%']
            band_dist = market_summary['Performance Band'].value_counts().reindex(band_order, fill_value=0).reset_index()
            band_dist.columns = ['Performance Band (% of Days ≥ 99.85%)', 'Market Count']
            band_dist['% of Total Markets'] = (band_dist['Market Count'] / len(market_summary) * 100).round(1).astype(str) + '%'
            
            st.dataframe(band_dist, use_container_width=True, hide_index=True, height=150)
            
            # Quartile Band Distribution
            st.markdown("##### Quartile Band (% of Days ≥ 99.85%)")
            
            # Calculate quartiles
            quartiles = market_summary['PCT_DAYS_MEETING_GOAL'].quantile([0, 0.25, 0.5, 0.75, 1.0]).values
            
            def get_quartile_band(pct):
                if pct <= quartiles[1]:
                    return f"{quartiles[0]:.1f}% – {quartiles[1]:.1f}%"
                elif pct <= quartiles[2]:
                    return f"{quartiles[1]:.1f}% – {quartiles[2]:.1f}%"
                elif pct <= quartiles[3]:
                    return f"{quartiles[2]:.1f}% – {quartiles[3]:.1f}%"
                else:
                    return f"{quartiles[3]:.1f}% – {quartiles[4]:.1f}%"
            
            market_summary['Quartile Band'] = market_summary['PCT_DAYS_MEETING_GOAL'].apply(get_quartile_band)
            
            quartile_order = [
                f"{quartiles[3]:.1f}% – {quartiles[4]:.1f}%",
                f"{quartiles[2]:.1f}% – {quartiles[3]:.1f}%",
                f"{quartiles[1]:.1f}% – {quartiles[2]:.1f}%",
                f"{quartiles[0]:.1f}% – {quartiles[1]:.1f}%"
            ]
            quartile_dist = market_summary['Quartile Band'].value_counts().reindex(quartile_order, fill_value=0).reset_index()
            quartile_dist.columns = ['Quartile Band (% of Days ≥ 99.85%)', 'Market Count']
            quartile_dist['% of Total Markets'] = (quartile_dist['Market Count'] / len(market_summary) * 100).round(1).astype(str) + '%'
            
            st.dataframe(quartile_dist, use_container_width=True, hide_index=True, height=150)
        
        st.markdown("---")
        
        # ===== ROLLING 30-DAY CHARTS =====
        rolling_data = get_rolling_availability_data(conn, filters)
        
        if not rolling_data.empty:
            rolling_data['DATE_VALUE'] = pd.to_datetime(rolling_data['DATE_VALUE'])
            rolling_data['DAILY_AVAILABILITY'] = rolling_data['DAILY_AVAILABILITY'].astype(float)
            rolling_data['MEETS_GOAL'] = (rolling_data['DAILY_AVAILABILITY'] >= 99.85).astype(int)
            
            # Calculate rolling 30-day count for each region
            rolling_results = []
            for region in rolling_data['REGION_ID'].unique():
                region_data = rolling_data[rolling_data['REGION_ID'] == region].sort_values('DATE_VALUE')
                # Rolling sum of previous 30 days (shift by 1 to exclude current day)
                region_data['ROLLING_30_DAYS_MET'] = region_data['MEETS_GOAL'].shift(1).rolling(window=30, min_periods=1).sum()
                rolling_results.append(region_data)
            
            rolling_df = pd.concat(rolling_results, ignore_index=True)
            
            # Filter to only the requested date range (remove the extra 30 days used for calculation)
            start_dt = filters.get('start_date') if filters else None
            if start_dt:
                rolling_df = rolling_df[rolling_df['DATE_VALUE'] >= pd.to_datetime(start_dt)]
            
            # Calculate national rolling 30-day 
            # First, calculate the national daily availability (average across all regions)
            national_daily = rolling_data.groupby('DATE_VALUE').agg({
                'DAILY_AVAILABILITY': 'mean'  # Average availability across all regions for each day
            }).reset_index()
            national_daily = national_daily.sort_values('DATE_VALUE')
            # Check if national average meets goal each day
            national_daily['MEETS_GOAL'] = (national_daily['DAILY_AVAILABILITY'] >= 99.85).astype(int)
            # Rolling 30-day count (excluding current day)
            national_daily['ROLLING_30_DAYS_MET'] = national_daily['MEETS_GOAL'].shift(1).rolling(window=30, min_periods=1).sum()
            
            if start_dt:
                national_daily = national_daily[national_daily['DATE_VALUE'] >= pd.to_datetime(start_dt)]
            
            rolling_col1, rolling_col2 = st.columns(2)
            
            with rolling_col1:
                st.markdown("##### National Rolling 30-Day Days Met ≥ 99.85%")
                
                fig_national = px.line(
                    national_daily,
                    x='DATE_VALUE',
                    y='ROLLING_30_DAYS_MET',
                    labels={'DATE_VALUE': 'Score Date', 'ROLLING_30_DAYS_MET': 'Days Met (0-30)'},
                    color_discrete_sequence=['#e20074'],
                )
                fig_national.update_traces(name='Rolling30_DaysMet', showlegend=True)
                fig_national.update_layout(
                    template='plotly_white',
                    height=450,
                    xaxis_title='',
                    yaxis_title='Days Met (0-30)',
                    yaxis=dict(range=[0, 30], tickfont=dict(size=12)),
                    xaxis=dict(tickfont=dict(size=12)),
                    font=dict(size=14),
                    legend=dict(orientation='h', yanchor='top', y=-0.25, xanchor='center', x=0.5, font=dict(size=12)),
                    margin=dict(b=120)
                )
                fig_national.update_xaxes(tickformat="%Y-%m-%d", tickangle=-45)
                st.plotly_chart(fig_national, use_container_width=True, config=CHART_CONFIG, key="rolling_national")
            
            with rolling_col2:
                st.markdown("##### Regions Rolling 30-Day Days Met ≥ 99.85%")
                
                # Region colors matching the scatter chart
                region_colors = {
                    'Central': '#000000',  # Black
                    'Northeast': '#e20074',  # Magenta
                    'South': '#4a0e4e',  # Dark purple
                    'West': '#888888',  # Gray
                }
                
                fig_regions = px.line(
                    rolling_df,
                    x='DATE_VALUE',
                    y='ROLLING_30_DAYS_MET',
                    color='REGION_ID',
                    color_discrete_map=region_colors,
                    labels={'DATE_VALUE': 'Score Date', 'ROLLING_30_DAYS_MET': 'Days Met (0-30)', 'REGION_ID': 'Region'},
                )
                fig_regions.update_layout(
                    template='plotly_white',
                    height=450,
                    xaxis_title='',
                    yaxis_title='Days Met (0-30)',
                    yaxis=dict(range=[0, 30], tickfont=dict(size=12)),
                    xaxis=dict(tickfont=dict(size=12)),
                    font=dict(size=14),
                    legend=dict(orientation='h', yanchor='top', y=-0.25, xanchor='center', x=0.5, font=dict(size=12), title_text='Region'),
                    margin=dict(b=120)
                )
                fig_regions.update_xaxes(tickformat="%Y-%m-%d", tickangle=-45)
                st.plotly_chart(fig_regions, use_container_width=True, config=CHART_CONFIG, key="rolling_regions")
        
        st.markdown("---")
        
        # Layout: Scatter chart on left, top/bottom tables on right
        scatter_col, tables_col = st.columns([1.2, 1])
        
        with scatter_col:
            st.markdown(f"##### Macro Only Markets — Mean Availability vs % of Days ≥ 99.85%")
            st.markdown(f"<span style='font-size:0.75rem;color:#888;'>(Daily Availability | {date_range_str})</span>", unsafe_allow_html=True)
            
            # Use EXACT same pattern as working COTTR chart
            fig = px.scatter(
                market_summary,
                x='MEAN_AVAILABILITY',
                y='PCT_DAYS_MEETING_GOAL',
                color='REGION_ID',
                color_discrete_map=REGION_COLORS,
                hover_name='MARKET_ID',
            )
            
            # Custom hover - EXACT same pattern as COTTR chart that works
            for trace in fig.data:
                trace.hovertemplate = '<b>%{hovertext}</b><br>Mean Availability=%{customdata[0]}<br>Days Meeting Goal=%{customdata[1]}<br>Total Days=%{customdata[2]}<br>% of Days=%{customdata[3]}<extra></extra>'
                if hasattr(trace, 'hovertext') and trace.hovertext is not None:
                    # Build customdata by matching hovertext (market names) to dataframe
                    customdata_list = []
                    for market_name in trace.hovertext:
                        match = market_summary[market_summary['MARKET_ID'] == market_name]
                        if not match.empty:
                            row = match.iloc[0]
                            customdata_list.append([
                                f"{row['MEAN_AVAILABILITY']:.2f}%",
                                f"{int(row['DAYS_MEETING_GOAL'])}",
                                f"{int(row['TOTAL_DAYS'])}",
                                f"{row['PCT_DAYS_MEETING_GOAL']:.1f}%"
                            ])
                        else:
                            customdata_list.append(["N/A", "0", "0", "N/A"])
                    trace.customdata = customdata_list
            
            fig.update_traces(marker=dict(size=10, opacity=0.8))
            
            # Add labels for outlier markets (top right and bottom left corners)
            high_performers = market_summary[market_summary['PCT_DAYS_MEETING_GOAL'] >= 90].nlargest(5, 'MEAN_AVAILABILITY')
            low_performers = market_summary[market_summary['PCT_DAYS_MEETING_GOAL'] < 50].nsmallest(5, 'MEAN_AVAILABILITY')
            markets_to_label = pd.concat([high_performers, low_performers])
            
            for _, row in markets_to_label.iterrows():
                fig.add_annotation(
                    x=row['MEAN_AVAILABILITY'],
                    y=row['PCT_DAYS_MEETING_GOAL'],
                    text=row['MARKET_ID'],
                    showarrow=False,
                    font=dict(size=12, color='#333'),
                    bgcolor='rgba(255,255,255,0.8)',
                    xshift=10,
                )
            
            # Add vertical goal line at 99.85%
            fig.add_vline(x=99.85, line_dash="dot", line_color="#ef4444", 
                         annotation_text="99.85% Goal", annotation_position="top")
            
            fig.update_layout(
                template='plotly_white',
                height=500,
                xaxis_title='Mean Availability (%)',
                yaxis_title='% of Days ≥ 99.85%',
                xaxis=dict(
                    range=[market_summary['MEAN_AVAILABILITY'].min() - 0.05, 100],
                    hoverformat='.2f',
                ),
                yaxis=dict(range=[0, 105]),
                hovermode='x unified',
                hoverlabel=HOVER_LABEL_STYLE,
                legend=dict(
                    title='Region',
                    orientation='v',
                    yanchor='top',
                    y=0.99,
                    xanchor='left',
                    x=0.01,
                ),
            )
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="mkt_goal_tracking")
        
        with tables_col:
            # Top 10 Markets (scrollable to see all)
            st.markdown("##### 99.85% — Top 10 Markets (Macro Only, Daily Availability)")
            # Sort all markets by PCT_DAYS_MEETING_GOAL descending (best first)
            all_markets_top = market_summary.sort_values('PCT_DAYS_MEETING_GOAL', ascending=False)[['MARKET_ID', 'REGION_ID', 'MEAN_AVAILABILITY', 'DAYS_MEETING_GOAL', 'TOTAL_DAYS', 'PCT_DAYS_MEETING_GOAL']]
            all_markets_top['Rank'] = range(1, len(all_markets_top) + 1)
            all_markets_top['Days ≥ 99.85%'] = all_markets_top['DAYS_MEETING_GOAL'].astype(int).astype(str) + ' / ' + all_markets_top['TOTAL_DAYS'].astype(int).astype(str)
            all_markets_top['Mean Avail'] = all_markets_top['MEAN_AVAILABILITY'].apply(lambda x: f"{x:.3f}%")
            all_markets_top['% of Days'] = all_markets_top['PCT_DAYS_MEETING_GOAL'].apply(lambda x: f"{x:.1f}%")
            all_markets_top = all_markets_top[['Rank', 'MARKET_ID', 'REGION_ID', 'Mean Avail', 'Days ≥ 99.85%', '% of Days']]
            all_markets_top.columns = ['Rank', 'Market', 'Region', 'Mean Avail', 'Days ≥ 99.85%', '% of Days']
            st.dataframe(all_markets_top, use_container_width=True, hide_index=True, height=300)
            
            # Bottom 10 Markets (scrollable to see all, ranked from total count down)
            st.markdown("##### 99.85% — Bottom 10 Markets (Macro Only, Daily Availability)")
            total_markets = len(market_summary)
            # Sort all markets by PCT_DAYS_MEETING_GOAL ascending (worst first)
            all_markets_bottom = market_summary.sort_values('PCT_DAYS_MEETING_GOAL', ascending=True)[['MARKET_ID', 'REGION_ID', 'MEAN_AVAILABILITY', 'DAYS_MEETING_GOAL', 'TOTAL_DAYS', 'PCT_DAYS_MEETING_GOAL']]
            # Rank from total count down (e.g., 59, 58, 57...)
            all_markets_bottom['Rank'] = range(total_markets, 0, -1)
            all_markets_bottom['Days ≥ 99.85%'] = all_markets_bottom['DAYS_MEETING_GOAL'].astype(int).astype(str) + ' / ' + all_markets_bottom['TOTAL_DAYS'].astype(int).astype(str)
            all_markets_bottom['Mean Avail'] = all_markets_bottom['MEAN_AVAILABILITY'].apply(lambda x: f"{x:.3f}%")
            all_markets_bottom['% of Days'] = all_markets_bottom['PCT_DAYS_MEETING_GOAL'].apply(lambda x: f"{x:.1f}%")
            all_markets_bottom = all_markets_bottom[['Rank', 'MARKET_ID', 'REGION_ID', 'Mean Avail', 'Days ≥ 99.85%', '% of Days']]
            all_markets_bottom.columns = ['Rank', 'Market', 'Region', 'Mean Avail', 'Days ≥ 99.85%', '% of Days']
            st.dataframe(all_markets_bottom, use_container_width=True, hide_index=True, height=300)
    else:
        st.info("No market availability data available.")

def site_analysis_dashboard(conn, days, filters=None):
    """Site-level analysis"""
    market = get_market_display_name(filters.get('market') if filters else None)
    st.markdown(f'<div class="section-header">🏗️ Site-Level Analysis</div>', unsafe_allow_html=True)
    
    # ===== KPI CARDS =====
    st.markdown("### 🎯 Key Performance Indicators")
    
    # OPTIMIZATION: Use cached version for faster repeated access
    filters_hash = filters_to_hashable(filters)
    cm_daily, avail_daily, cottr_daily = get_combined_daily_data_cached(conn, days, filters_hash)
    
    # Calculate KPI values
    total_cm = float(cm_daily['CUSTOMER_MINUTES'].sum()) if not cm_daily.empty else 0
    total_subs = float(cm_daily['IMPACTED_SUBS'].sum()) if not cm_daily.empty else 0
    
    if not avail_daily.empty and 'TOTAL_AVAILABILITY_N' in avail_daily.columns and 'TOTAL_AVAILABILITY_D' in avail_daily.columns:
        total_n = float(avail_daily['TOTAL_AVAILABILITY_N'].sum())
        total_d = float(avail_daily['TOTAL_AVAILABILITY_D'].sum())
        avg_avail = (total_n / total_d * 100) if total_d > 0 else 0
    else:
        avg_avail = float(avail_daily['AVG_AVAILABILITY_PCT'].mean()) if not avail_daily.empty else 0
    
    total_downtime = float(avail_daily['TOTAL_DOWNTIME'].sum()) if not avail_daily.empty else 0
    total_outages = float(cottr_daily['OUTAGE_COUNT'].sum()) if not cottr_daily.empty else 0
    total_outage_mins = float(cottr_daily['OUTAGE_MINUTES'].sum()) if not cottr_daily.empty else 0
    
    # Get unique site counts for COTTR and Customer Minutes
    cottr_filter = build_filter_clause(filters, 'cottr')
    cm_filter = build_filter_clause(filters, 'customer_minutes')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    
    date_filter_cottr = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_cm = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZATION: Run site count queries in parallel for faster loading
    def get_cottr_site_count():
        cottr_sites_query = f"""
        SELECT COUNT(DISTINCT SITE_CD) as UNIQUE_SITES
        FROM {TABLES['cottr']}
        WHERE {date_filter_cottr} AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'  {cottr_filter}
        """
        return run_query(conn, cottr_sites_query, use_cache=True)
    
    def get_cm_site_count():
        if site_type:
            cm_filter_aliased = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
            cm_sites_query = f"""
            SELECT COUNT(DISTINCT cm.SITE_ID) as UNIQUE_SITES
            FROM {TABLES['customer_minutes']} cm
            INNER JOIN (
                SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
                WHERE {date_filter_avail} AND {get_site_type_sql_filter(site_type)}
            ) st ON cm.SITE_ID = st.SITE_ID
            WHERE {date_filter_cm.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')} {cm_filter_aliased}
            """
        else:
            cm_sites_query = f"""
            SELECT COUNT(DISTINCT SITE_ID) as UNIQUE_SITES
            FROM {TABLES['customer_minutes']}
            WHERE {date_filter_cm} {cm_filter}
            """
        return run_query(conn, cm_sites_query, use_cache=True)
    
    # Execute both queries in parallel
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_cottr = executor.submit(get_cottr_site_count)
        future_cm = executor.submit(get_cm_site_count)
        cottr_sites_count = future_cottr.result()
        cm_sites_count = future_cm.result()
    
    unique_cottr_sites = int(cottr_sites_count['UNIQUE_SITES'].iloc[0]) if not cottr_sites_count.empty else 0
    unique_cm_sites = int(cm_sites_count['UNIQUE_SITES'].iloc[0]) if not cm_sites_count.empty else 0
    
    # Calculate total seconds budget for 99.85% availability and over/under
    if not avail_daily.empty and 'TOTAL_AVAILABILITY_D' in avail_daily.columns:
        total_d = float(avail_daily['TOTAL_AVAILABILITY_D'].sum())
        total_seconds_allowed = 0.0015 * total_d if total_d > 0 else 0
        avg_daily_d = float(avail_daily['TOTAL_AVAILABILITY_D'].mean())
        daily_downtime_threshold = 0.0015 * avg_daily_d if avg_daily_d > 0 else None
        over_under = total_downtime - total_seconds_allowed
    else:
        total_seconds_allowed = 0
        daily_downtime_threshold = None
        over_under = 0
    downtime_threshold_label = f"Goal: {format_number(daily_downtime_threshold)}" if daily_downtime_threshold else None
    
    # Calculate days meeting goal for availability stats
    days_meeting_goal = 0
    total_days_count = 0
    if not avail_daily.empty and 'AVG_AVAILABILITY_PCT' in avail_daily.columns:
        total_days_count = len(avail_daily)
        days_meeting_goal = (avail_daily['AVG_AVAILABILITY_PCT'] >= 99.85).sum()
    goal_pct = (days_meeting_goal / total_days_count * 100) if total_days_count > 0 else 0
    
    # Build top-right stats for availability
    goal_color = "#22c55e" if goal_pct >= 80 else "#f59e0b" if goal_pct >= 50 else "#ef4444"
    avail_stats = {
        'line1': f"<b>{days_meeting_goal}/{total_days_count}</b> = {goal_pct:.0f}%",
        'line2': "Days ≥ 99.85%",
        'color1': goal_color
    }
    
    # Build downtime stats with unavailability info
    is_over = over_under > 0
    indicator_color = "#ef4444" if is_over else "#22c55e"
    over_under_label = f"+{format_number(over_under)}" if is_over else f"{format_number(over_under)}"
    
    # Calculate unavailability %
    unavail_pct = 100 - avg_avail
    unavail_goal = 0.15  # 100 - 99.85
    unavail_over = unavail_pct > unavail_goal
    unavail_color = "#ef4444" if unavail_over else "#22c55e"
    unavail_indicator = "Over" if unavail_over else "Under"
    
    downtime_stats = {
        'line1': f"Downtime: <b>{format_number(total_downtime)}</b> sec",
        'line2': f"<span style='color:#888888;'>Goal: 0.15%</span> <span style='color:{unavail_color}'>{unavail_indicator}</span>",
        'line3': f"Budget: <b>{format_number(total_seconds_allowed)}</b>",
        'line4': f"<b>{over_under_label}</b> {'🔴 Over' if is_over else '🟢 Under'}",
        'color1': '#22c55e',
        'color2': '#888888',
        'color4': indicator_color
    }
    
    # COTTR sites stat
    cottr_sites_stats = {
        'line1': f"<b>{unique_cottr_sites}</b> sites",
        'line2': "with outages",
        'color1': "#f59e0b"
    }
    
    # Customer minutes sites stat
    cm_sites_stats = {
        'line1': f"<b>{unique_cm_sites}</b> sites",
        'line2': "impacted",
        'color1': "#e20074"
    }
    
    kpi_col1, kpi_col2, kpi_col3, kpi_col4, kpi_col5, kpi_col6 = st.columns(6)
    
    # Order: Availability (left), COTTR (middle), Customer Mins (right) - using same format as Executive Summary
    with kpi_col1:
        render_kpi_card_with_sparkline("Daily Availability %", f"{avg_avail:.2f}%", avail_daily, 'DATE_VALUE', 'AVG_AVAILABILITY_PCT', "All In Availability", "green", format_large=False, goal_value=99.85, show_sparkline=True, top_right_stats=avail_stats, key_prefix="site_kpi")
    
    with kpi_col2:
        render_kpi_card_with_sparkline("Unavailability", f"{unavail_pct:.2f}%", avail_daily, 'DATE_VALUE', 'TOTAL_DOWNTIME', "All In Availability", "green", format_large=False, goal_value=daily_downtime_threshold, goal_label=downtime_threshold_label, show_sparkline=True, top_right_stats=downtime_stats, key_prefix="site_kpi")
    
    with kpi_col3:
        render_kpi_card_with_sparkline("Service Outage Events", total_outages, cottr_daily, 'DATE_VALUE', 'OUTAGE_COUNT', "COTTR", "orange", show_sparkline=True, top_right_stats=cottr_sites_stats, key_prefix="site_kpi")
    
    with kpi_col4:
        render_kpi_card_with_sparkline("Service Outage Minutes", total_outage_mins, cottr_daily, 'DATE_VALUE', 'OUTAGE_MINUTES', "COTTR", "orange", show_sparkline=True, key_prefix="site_kpi")
    
    with kpi_col5:
        render_kpi_card_with_sparkline("Customer Minutes", total_cm, cm_daily, 'DATE_VALUE', 'CUSTOMER_MINUTES', "Customer Minutes V2", "magenta", show_sparkline=True, top_right_stats=cm_sites_stats, key_prefix="site_kpi")
    
    with kpi_col6:
        render_kpi_card_with_sparkline("Impacted Subscribers", total_subs, cm_daily, 'DATE_VALUE', 'IMPACTED_SUBS', "Customer Minutes V2", "magenta", show_sparkline=True, key_prefix="site_kpi")
    
    st.divider()
    
    # ===== SUMMARY & FOCUS CATEGORY BREAKDOWNS =====
    st.markdown("### 📊 Category Breakdowns")
    
    # OPTIMIZATION: Run all category queries in parallel with cached versions
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_avail_summary = executor.submit(get_availability_with_downtime_by_summary, conn, days, filters)
        future_cottr_summary = executor.submit(get_cottr_by_summary_category, conn, days, filters)
        future_focus_avail = executor.submit(get_focus_category_totals_cached, conn, days, filters_hash)
        future_focus_cottr = executor.submit(get_focus_category_totals_cottr_cached, conn, days, filters_hash)
        
        _, avail_by_summary = future_avail_summary.result()
        cottr_by_summary_site = future_cottr_summary.result()
        focus_cat_avail = future_focus_avail.result()
        focus_cat_cottr = future_focus_cottr.result()
    
    # Focus Category treemaps (Availability & COTTR) - matching Executive Summary style
    focus_col1, focus_col2 = st.columns(2)
    
    with focus_col1:
        # Calculate summary category percentages for Availability
        avail_summary_text = ""
        if not focus_cat_avail.empty:
            focus_cat_avail_filtered = focus_cat_avail[~focus_cat_avail['SITE_ID_FOCUS_CATEGORY'].str.lower().str.contains('no outage', na=False)]
            focus_total = focus_cat_avail_filtered['TOTAL_DOWNTIME'].sum()
            
            # Calculate Power/RAN/Transport summary percentages
            if 'SITE_ID_SUMMARY_CATEGORY' in focus_cat_avail_filtered.columns:
                summary_totals = focus_cat_avail_filtered.groupby('SITE_ID_SUMMARY_CATEGORY')['TOTAL_DOWNTIME'].sum()
            else:
                # Map focus categories to summary categories
                def map_to_summary(cat):
                    cat_lower = str(cat).lower() if cat else ''
                    if 'power' in cat_lower:
                        return 'Power'
                    elif 'transport' in cat_lower or 'aav' in cat_lower or 'microwave' in cat_lower or 'fiber' in cat_lower:
                        return 'Transport'
                    else:
                        return 'RAN'
                focus_cat_avail_filtered['SUMMARY_CAT'] = focus_cat_avail_filtered['SITE_ID_FOCUS_CATEGORY'].apply(map_to_summary)
                summary_totals = focus_cat_avail_filtered.groupby('SUMMARY_CAT')['TOTAL_DOWNTIME'].sum()
            
            summary_total = summary_totals.sum()
            if summary_total > 0:
                pwr_pct = (summary_totals.get('Power', 0) / summary_total * 100)
                ran_pct = (summary_totals.get('RAN', 0) / summary_total * 100)
                trn_pct = (summary_totals.get('Transport', 0) / summary_total * 100)
                avail_summary_text = f"<div style='font-size:1rem;color:#000000;font-weight:600;margin-top:2px;'>Summary Categories: Power: {pwr_pct:.0f}% | RAN: {ran_pct:.0f}% | Transport: {trn_pct:.0f}%</div>"
        
        st.markdown(f"<div style='margin-bottom:5px;'><b>📉 Availability - Categories</b>{avail_summary_text}</div>", unsafe_allow_html=True)
        
        if not focus_cat_avail.empty:
            focus_cat_avail_filtered = focus_cat_avail[~focus_cat_avail['SITE_ID_FOCUS_CATEGORY'].str.lower().str.contains('no outage', na=False)]
            focus_total = focus_cat_avail_filtered['TOTAL_DOWNTIME'].sum()
            
            if not focus_cat_avail_filtered.empty and focus_total > 0:
                treemap_data = []
                for _, row in focus_cat_avail_filtered.iterrows():
                    cat = row['SITE_ID_FOCUS_CATEGORY']
                    dt = float(row['TOTAL_DOWNTIME'])
                    cat_pct = (dt / focus_total * 100)
                    color = FOCUS_CATEGORY_COLORS.get(cat, DEFAULT_FOCUS_COLOR)
                    treemap_data.append({
                        'category': cat,
                        'value': dt,
                        'pct': cat_pct,
                        'color': color
                    })
                
                fig_treemap_avail = go.Figure(go.Treemap(
                    labels=[f"{r['category']}<br>{r['pct']:.0f}%" for r in treemap_data],
                    parents=[''] * len(treemap_data),
                    values=[r['value'] for r in treemap_data],
                    marker=dict(colors=[r['color'] for r in treemap_data]),
                    textinfo='label',
                    textfont=dict(size=14, color='white'),
                    hovertemplate='<b>%{label}</b><br>Downtime: %{value:,.0f}<extra></extra>'
                ))
                fig_treemap_avail.update_layout(
                    margin=dict(t=5, l=5, r=5, b=5),
                    height=250,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)'
                )
                st.markdown("<div style='font-size:1rem;color:#000000;font-weight:600;margin-top:2px;margin-bottom:-15px;'>Focus Categories</div>", unsafe_allow_html=True)
                st.plotly_chart(fig_treemap_avail, use_container_width=True, config=CHART_CONFIG, key="site_avail_treemap")
            else:
                st.info("No category data available.")
        else:
            st.info("No availability focus category data available.")
    
    with focus_col2:
        # Calculate summary category percentages for COTTR
        cottr_summary_text = ""
        if not focus_cat_cottr.empty:
            focus_cat_cottr_filtered = focus_cat_cottr[~focus_cat_cottr['SITE_ID_FOCUS_CATEGORY'].str.lower().str.contains('no outage', na=False)]
            focus_cottr_total = focus_cat_cottr_filtered['TOTAL_OUTAGE_MINUTES'].sum()
            
            # Calculate Power/RAN/Transport summary percentages
            if 'SITE_ID_SUMMARY_CATEGORY' in focus_cat_cottr_filtered.columns:
                cottr_summary_totals = focus_cat_cottr_filtered.groupby('SITE_ID_SUMMARY_CATEGORY')['TOTAL_OUTAGE_MINUTES'].sum()
            else:
                # Map focus categories to summary categories
                def map_to_summary_cottr(cat):
                    cat_lower = str(cat).lower() if cat else ''
                    if 'power' in cat_lower:
                        return 'Power'
                    elif 'transport' in cat_lower or 'aav' in cat_lower or 'microwave' in cat_lower or 'fiber' in cat_lower:
                        return 'Transport'
                    else:
                        return 'RAN'
                focus_cat_cottr_filtered['SUMMARY_CAT'] = focus_cat_cottr_filtered['SITE_ID_FOCUS_CATEGORY'].apply(map_to_summary_cottr)
                cottr_summary_totals = focus_cat_cottr_filtered.groupby('SUMMARY_CAT')['TOTAL_OUTAGE_MINUTES'].sum()
            
            cottr_summary_total = cottr_summary_totals.sum()
            if cottr_summary_total > 0:
                pwr_pct = (cottr_summary_totals.get('Power', 0) / cottr_summary_total * 100)
                ran_pct = (cottr_summary_totals.get('RAN', 0) / cottr_summary_total * 100)
                trn_pct = (cottr_summary_totals.get('Transport', 0) / cottr_summary_total * 100)
                cottr_summary_text = f"<div style='font-size:1rem;color:#000000;font-weight:600;margin-top:2px;'>Summary Categories: Power: {pwr_pct:.0f}% | RAN: {ran_pct:.0f}% | Transport: {trn_pct:.0f}%</div>"
        
        st.markdown(f"<div style='margin-bottom:5px;'><b>🚨 COTTR - Categories</b>{cottr_summary_text}</div>", unsafe_allow_html=True)
        
        if not focus_cat_cottr.empty:
            focus_cat_cottr_filtered = focus_cat_cottr[~focus_cat_cottr['SITE_ID_FOCUS_CATEGORY'].str.lower().str.contains('no outage', na=False)]
            focus_cottr_total = focus_cat_cottr_filtered['TOTAL_OUTAGE_MINUTES'].sum()
            
            if not focus_cat_cottr_filtered.empty and focus_cottr_total > 0:
                treemap_data_cottr = []
                for _, row in focus_cat_cottr_filtered.iterrows():
                    cat = row['SITE_ID_FOCUS_CATEGORY']
                    mins = float(row['TOTAL_OUTAGE_MINUTES'])
                    cat_pct = (mins / focus_cottr_total * 100)
                    color = FOCUS_CATEGORY_COLORS.get(cat, DEFAULT_FOCUS_COLOR)
                    treemap_data_cottr.append({
                        'category': cat,
                        'value': mins,
                        'pct': cat_pct,
                        'color': color
                    })
                
                fig_treemap_cottr = go.Figure(go.Treemap(
                    labels=[f"{r['category']}<br>{r['pct']:.0f}%" for r in treemap_data_cottr],
                    parents=[''] * len(treemap_data_cottr),
                    values=[r['value'] for r in treemap_data_cottr],
                    marker=dict(colors=[r['color'] for r in treemap_data_cottr]),
                    textinfo='label',
                    textfont=dict(size=14, color='white'),
                    hovertemplate='<b>%{label}</b><br>Outage Minutes: %{value:,.0f}<extra></extra>'
                ))
                fig_treemap_cottr.update_layout(
                    margin=dict(t=5, l=5, r=5, b=5),
                    height=250,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)'
                )
                st.markdown("<div style='font-size:1rem;color:#000000;font-weight:600;margin-top:2px;margin-bottom:-15px;'>Focus Categories</div>", unsafe_allow_html=True)
                st.plotly_chart(fig_treemap_cottr, use_container_width=True, config=CHART_CONFIG, key="site_cottr_treemap")
            else:
                st.info("No category data available.")
        else:
            st.info("No COTTR focus category data available.")
    
    # ===== FIELD OPS BREAKDOWNS (only when market is selected) =====
    selected_market = filters.get('market') if filters else None
    market_display = get_market_display_name(selected_market)
    
    if selected_market:
        st.markdown("<div style='margin-top:1.5rem;'></div>", unsafe_allow_html=True)
        st.markdown(f"### 👷 Field Ops Availability — {market_display}")
        
        # OPTIMIZATION: Get field ops data in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_group = executor.submit(get_availability_by_field_ops_group, conn, days, filters)
            future_mgr = executor.submit(get_availability_by_field_ops_mgr, conn, days, filters)
            field_ops_group_data = future_group.result()
            field_ops_mgr_data = future_mgr.result()
        
        # Helper function to render compact table row
        def render_table_row(name, downtime, avail_pct, seconds_allowed, over_under, site_count, days_meeting=0, total_days=0, cust_mins=0):
            is_over = over_under > 0
            status_color = "#ef4444" if is_over else "#22c55e"
            over_under_text = f"+{format_number(abs(over_under))}" if is_over else f"-{format_number(abs(over_under))}"
            usage_pct = min((downtime / seconds_allowed * 100), 150) if seconds_allowed > 0 else 0
            bar_color = "#ef4444" if usage_pct > 100 else "#f59e0b" if usage_pct > 75 else "#22c55e"
            display_name = str(name)[:30] + ('...' if len(str(name)) > 30 else '')
            days_pct = (days_meeting / total_days * 100) if total_days > 0 else 0
            days_color = "#22c55e" if days_pct >= 80 else "#f59e0b" if days_pct >= 50 else "#ef4444"
            
            avail_color = "#ef4444" if avail_pct < 99.85 else "#22c55e"
            return (
                f'<tr style="border-bottom:1px solid #dee2e6;">'
                f'<td style="padding:6px 8px;font-size:0.75rem;color:#1a1a2e;font-weight:600;" title="{name}">{display_name}</td>'
                f'<td style="padding:6px 8px;text-align:right;font-size:0.75rem;color:#e20074;font-weight:600;">{format_number(downtime)}s</td>'
                f'<td style="padding:6px 8px;text-align:right;font-size:0.75rem;color:{avail_color};font-weight:600;">{avail_pct:.2f}%</td>'
                f'<td style="padding:6px 8px;width:80px;">'
                f'<div style="display:flex;align-items:center;gap:4px;">'
                f'<div style="flex:1;background:#dee2e6;border-radius:3px;height:6px;overflow:hidden;">'
                f'<div style="background:{bar_color};height:100%;width:{min(usage_pct, 100)}%;"></div>'
                f'</div>'
                f'<span style="font-size:0.65rem;color:#666;white-space:nowrap;">{usage_pct:.0f}%</span>'
                f'</div>'
                f'</td>'
                f'<td style="padding:6px 8px;text-align:right;font-size:0.75rem;color:{status_color};font-weight:600;">{over_under_text}</td>'
                f'<td style="padding:6px 8px;text-align:center;font-size:0.75rem;color:{days_color};font-weight:600;">{int(days_meeting)}/{int(total_days)}</td>'
                f'<td style="padding:6px 8px;text-align:right;font-size:0.75rem;color:#e20074;">{format_number(cust_mins)}</td>'
                f'<td style="padding:6px 8px;text-align:center;font-size:0.75rem;color:#666;">{site_count}</td>'
                f'</tr>'
            )
        
        # Get Customer Minutes by Field Ops Group and Manager
        cm_filter = build_filter_clause(filters, 'customer_minutes')
        avail_filter_for_cm = build_filter_clause(filters, 'availability')
        start_date = filters.get('start_date') if filters else None
        end_date = filters.get('end_date') if filters else None
        site_type = filters.get('site_type') if filters else None
        site_type_filter_cm = get_site_type_sql_filter(site_type)
        date_filter_cm = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
        date_filter_avail_cm = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
        
        # OPTIMIZATION: Build queries first, then run in parallel
        site_group_query = f"""
        SELECT SITE_ID, MAX(FIELD_OPS_ASSIGNMENT_GROUP) as FIELD_OPS_ASSIGNMENT_GROUP, MAX(FIELD_OPS_MGR) as FIELD_OPS_MGR
        FROM {TABLES['availability']}
        WHERE {date_filter_avail_cm} AND {site_type_filter_cm} {avail_filter_for_cm}
        GROUP BY SITE_ID
        """
        
        # Get CM by site - with site_type filtering
        if site_type:
            cm_filter_aliased = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
            cm_site_query = f"""
            SELECT cm.SITE_ID, SUM(cm.IMPACT_DURATION_IN_MINS) as CUSTOMER_MINUTES
            FROM {TABLES['customer_minutes']} cm
            INNER JOIN (
                SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
            WHERE {date_filter_avail_cm} AND {get_site_type_sql_filter(site_type)}
        ) st ON cm.SITE_ID = st.SITE_ID
            WHERE {date_filter_cm.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')} {cm_filter_aliased}
            GROUP BY cm.SITE_ID
            """
        else:
            cm_site_query = f"""
            SELECT SITE_ID, SUM(IMPACT_DURATION_IN_MINS) as CUSTOMER_MINUTES
            FROM {TABLES['customer_minutes']}
            WHERE {date_filter_cm} {cm_filter}
            GROUP BY SITE_ID
            """
        
        # Run both queries in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_group = executor.submit(run_query, conn, site_group_query, use_cache=True)
            future_cm = executor.submit(run_query, conn, cm_site_query, use_cache=True)
            site_group_map = future_group.result()
            cm_site_data = future_cm.result()
        
        # Merge to get CM by group and manager
        cm_by_group = pd.DataFrame(columns=['FIELD_OPS_ASSIGNMENT_GROUP', 'CUSTOMER_MINUTES'])
        cm_by_mgr = pd.DataFrame(columns=['FIELD_OPS_MGR', 'CUSTOMER_MINUTES'])
        if not site_group_map.empty and not cm_site_data.empty:
            cm_merged = pd.merge(cm_site_data, site_group_map, on='SITE_ID', how='left')
            cm_merged['FIELD_OPS_ASSIGNMENT_GROUP'] = cm_merged['FIELD_OPS_ASSIGNMENT_GROUP'].fillna('Unassigned')
            cm_merged['FIELD_OPS_MGR'] = cm_merged['FIELD_OPS_MGR'].fillna('Unassigned')
            cm_by_group = cm_merged.groupby('FIELD_OPS_ASSIGNMENT_GROUP')['CUSTOMER_MINUTES'].sum().reset_index()
            cm_by_mgr = cm_merged.groupby('FIELD_OPS_MGR')['CUSTOMER_MINUTES'].sum().reset_index()
        
        # Two-column layout for both tables
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**📋 Assignment Groups**")
            if not field_ops_group_data.empty:
                field_ops_group_data['TOTAL_D'] = field_ops_group_data['TOTAL_D'].astype(float)
                field_ops_group_data['TOTAL_DOWNTIME'] = field_ops_group_data['TOTAL_DOWNTIME'].astype(float)
                field_ops_group_data['SECONDS_ALLOWED'] = field_ops_group_data['TOTAL_D'] * 0.0015
                field_ops_group_data['OVER_UNDER'] = field_ops_group_data['TOTAL_DOWNTIME'] - field_ops_group_data['SECONDS_ALLOWED']
                
                # Merge CM data
                if not cm_by_group.empty:
                    field_ops_group_data = pd.merge(field_ops_group_data, cm_by_group, on='FIELD_OPS_ASSIGNMENT_GROUP', how='left')
                    field_ops_group_data['CUSTOMER_MINUTES'] = field_ops_group_data['CUSTOMER_MINUTES'].fillna(0)
                else:
                    field_ops_group_data['CUSTOMER_MINUTES'] = 0
                
                top_groups = field_ops_group_data.head(8)
                
                table_html = (
                    '<table style="width:100%;border-collapse:collapse;background:#f8f9fa;border-radius:8px;overflow:hidden;font-size:0.75rem;">'
                    '<thead><tr style="background:#e9ecef;border-bottom:2px solid #dee2e6;">'
                    '<th style="padding:8px 6px;text-align:left;color:#555;font-weight:600;">Group</th>'
                    '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">Down</th>'
                    '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">Avail%</th>'
                    '<th style="padding:8px 6px;text-align:center;color:#555;font-weight:600;">Budget</th>'
                    '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">+/-</th>'
                    '<th style="padding:8px 6px;text-align:center;color:#555;font-weight:600;">Days</th>'
                    '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">CM</th>'
                    '<th style="padding:8px 6px;text-align:center;color:#555;font-weight:600;">Sites</th>'
                    '</tr></thead><tbody>'
                )
                
                for _, row in top_groups.iterrows():
                    avail_pct = float(row['AVG_AVAILABILITY']) if pd.notna(row['AVG_AVAILABILITY']) else 0
                    days_meeting = int(row['DAYS_MEETING_GOAL']) if 'DAYS_MEETING_GOAL' in row and pd.notna(row['DAYS_MEETING_GOAL']) else 0
                    total_days = int(row['TOTAL_DAYS']) if 'TOTAL_DAYS' in row and pd.notna(row['TOTAL_DAYS']) else 0
                    cust_mins = float(row['CUSTOMER_MINUTES']) if 'CUSTOMER_MINUTES' in row and pd.notna(row['CUSTOMER_MINUTES']) else 0
                    table_html += render_table_row(
                        row['FIELD_OPS_ASSIGNMENT_GROUP'],
                        row['TOTAL_DOWNTIME'],
                        avail_pct,
                        row['SECONDS_ALLOWED'],
                        row['OVER_UNDER'],
                        row['SITE_COUNT'],
                        days_meeting,
                        total_days,
                        cust_mins
                    )
                
                table_html += '</tbody></table>'
                st.markdown(table_html, unsafe_allow_html=True)
            else:
                st.info("No Assignment Group data available.")
        
        with col2:
            st.markdown("**👤 Field Ops Managers**")
            if not field_ops_mgr_data.empty:
                field_ops_mgr_data['TOTAL_D'] = field_ops_mgr_data['TOTAL_D'].astype(float)
                field_ops_mgr_data['TOTAL_DOWNTIME'] = field_ops_mgr_data['TOTAL_DOWNTIME'].astype(float)
                field_ops_mgr_data['SECONDS_ALLOWED'] = field_ops_mgr_data['TOTAL_D'] * 0.0015
                field_ops_mgr_data['OVER_UNDER'] = field_ops_mgr_data['TOTAL_DOWNTIME'] - field_ops_mgr_data['SECONDS_ALLOWED']
                
                # Merge CM data
                if not cm_by_mgr.empty:
                    field_ops_mgr_data = pd.merge(field_ops_mgr_data, cm_by_mgr, on='FIELD_OPS_MGR', how='left')
                    field_ops_mgr_data['CUSTOMER_MINUTES'] = field_ops_mgr_data['CUSTOMER_MINUTES'].fillna(0)
                else:
                    field_ops_mgr_data['CUSTOMER_MINUTES'] = 0
                
                top_mgrs = field_ops_mgr_data.head(8)
                
                table_html = (
                    '<table style="width:100%;border-collapse:collapse;background:#f8f9fa;border-radius:8px;overflow:hidden;font-size:0.75rem;">'
                    '<thead><tr style="background:#e9ecef;border-bottom:2px solid #dee2e6;">'
                    '<th style="padding:8px 6px;text-align:left;color:#555;font-weight:600;">Manager</th>'
                    '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">Down</th>'
                    '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">Avail%</th>'
                    '<th style="padding:8px 6px;text-align:center;color:#555;font-weight:600;">Budget</th>'
                    '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">+/-</th>'
                    '<th style="padding:8px 6px;text-align:center;color:#555;font-weight:600;">Days</th>'
                    '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">CM</th>'
                    '<th style="padding:8px 6px;text-align:center;color:#555;font-weight:600;">Sites</th>'
                    '</tr></thead><tbody>'
                )
                
                for _, row in top_mgrs.iterrows():
                    avail_pct = float(row['AVG_AVAILABILITY']) if pd.notna(row['AVG_AVAILABILITY']) else 0
                    days_meeting = int(row['DAYS_MEETING_GOAL']) if 'DAYS_MEETING_GOAL' in row and pd.notna(row['DAYS_MEETING_GOAL']) else 0
                    total_days = int(row['TOTAL_DAYS']) if 'TOTAL_DAYS' in row and pd.notna(row['TOTAL_DAYS']) else 0
                    cust_mins = float(row['CUSTOMER_MINUTES']) if 'CUSTOMER_MINUTES' in row and pd.notna(row['CUSTOMER_MINUTES']) else 0
                    table_html += render_table_row(
                        row['FIELD_OPS_MGR'],
                        row['TOTAL_DOWNTIME'],
                        avail_pct,
                        row['SECONDS_ALLOWED'],
                        row['OVER_UNDER'],
                        row['SITE_COUNT'],
                        days_meeting,
                        total_days,
                        cust_mins
                    )
                
                table_html += '</tbody></table>'
                st.markdown(table_html, unsafe_allow_html=True)
            else:
                st.info("No Field Ops Manager data available.")
        
        # Add Field Ops Assignee section
        st.markdown("<div style='margin-top:1rem;'></div>", unsafe_allow_html=True)
        st.markdown("**🧑‍🔧 Field Ops Assignees**")
        
        field_ops_assignee_data = get_availability_by_field_ops_assignee(conn, days, filters)
        
        # Get COTTR data by Field Ops Assignee (join with availability to get assignee)
        cottr_filter = build_filter_clause(filters, 'cottr')
        avail_filter = build_filter_clause(filters, 'availability')
        start_date = filters.get('start_date') if filters else None
        end_date = filters.get('end_date') if filters else None
        date_filter_cottr = f"c.LOCAL_START_TIMESTAMP >= '{start_date}' AND c.LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"c.LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
        date_filter_avail = f"a.DATE_VALUE >= '{start_date}' AND a.DATE_VALUE <= '{end_date}'" if start_date and end_date else f"a.DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
        
        # Get site-to-assignee mapping from availability
        site_type = filters.get('site_type') if filters else None
        site_type_filter = get_site_type_sql_filter(site_type)
        site_assignee_query = f"""
        SELECT SITE_ID, MAX(FIELD_OPS_ASSIGNEE) as FIELD_OPS_ASSIGNEE
        FROM {TABLES['availability']}
        WHERE {date_filter_avail.replace('a.', '')} AND {site_type_filter} {avail_filter}
        GROUP BY SITE_ID
        """
        site_assignee_map = run_query(conn, site_assignee_query)
        
        # Get COTTR by site
        cottr_site_query = f"""
        SELECT SITE_CD as SITE_ID, SUM(PER_DAY_OUTAGE_MINUTES) as COTTR_MINUTES
        FROM {TABLES['cottr']}
        WHERE {date_filter_cottr.replace('c.', '')} AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'  {cottr_filter}
        GROUP BY SITE_CD
        """
        cottr_site_data = run_query(conn, cottr_site_query)
        
        # Get Impacted Subs by site
        cm_filter = build_filter_clause(filters, 'customer_minutes')
        site_type = filters.get('site_type') if filters else None
        date_filter_cm = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
        date_filter_avail_for_st = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
        
        if site_type:
            cm_filter_aliased = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
            subs_site_query = f"""
            SELECT cm.SITE_ID, SUM(cm.TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
            FROM {TABLES['customer_minutes']} cm
            INNER JOIN (
                SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
            WHERE {date_filter_avail_for_st} AND {get_site_type_sql_filter(site_type)}
        ) st ON cm.SITE_ID = st.SITE_ID
            WHERE {date_filter_cm.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')} {cm_filter_aliased}
            GROUP BY cm.SITE_ID
            """
        else:
            subs_site_query = f"""
            SELECT SITE_ID, SUM(TOTAL_IMPACTED_SUB_CNT) as IMPACTED_SUBS
            FROM {TABLES['customer_minutes']}
            WHERE {date_filter_cm} {cm_filter}
            GROUP BY SITE_ID
            """
        subs_site_data = run_query(conn, subs_site_query)
        
        # Merge to get COTTR and Subs by assignee
        cottr_assignee_data = pd.DataFrame(columns=['FIELD_OPS_ASSIGNEE', 'COTTR_MINUTES'])
        subs_assignee_data = pd.DataFrame(columns=['FIELD_OPS_ASSIGNEE', 'IMPACTED_SUBS'])
        
        if not site_assignee_map.empty:
            if not cottr_site_data.empty:
                cottr_merged = pd.merge(cottr_site_data, site_assignee_map, on='SITE_ID', how='left')
                cottr_merged['FIELD_OPS_ASSIGNEE'] = cottr_merged['FIELD_OPS_ASSIGNEE'].fillna('Unassigned')
                cottr_assignee_data = cottr_merged.groupby('FIELD_OPS_ASSIGNEE')['COTTR_MINUTES'].sum().reset_index()
            
            if not subs_site_data.empty:
                subs_merged = pd.merge(subs_site_data, site_assignee_map, on='SITE_ID', how='left')
                subs_merged['FIELD_OPS_ASSIGNEE'] = subs_merged['FIELD_OPS_ASSIGNEE'].fillna('Unassigned')
                subs_assignee_data = subs_merged.groupby('FIELD_OPS_ASSIGNEE')['IMPACTED_SUBS'].sum().reset_index()
        
        if not field_ops_assignee_data.empty:
            field_ops_assignee_data['TOTAL_D'] = field_ops_assignee_data['TOTAL_D'].astype(float)
            field_ops_assignee_data['TOTAL_DOWNTIME'] = field_ops_assignee_data['TOTAL_DOWNTIME'].astype(float)
            field_ops_assignee_data['SECONDS_ALLOWED'] = field_ops_assignee_data['TOTAL_D'] * 0.0015
            field_ops_assignee_data['OVER_UNDER'] = field_ops_assignee_data['TOTAL_DOWNTIME'] - field_ops_assignee_data['SECONDS_ALLOWED']
            
            # Merge COTTR and Impacted Subs data
            if not cottr_assignee_data.empty:
                field_ops_assignee_data = pd.merge(field_ops_assignee_data, cottr_assignee_data, on='FIELD_OPS_ASSIGNEE', how='left')
            else:
                field_ops_assignee_data['COTTR_MINUTES'] = 0
            
            if not subs_assignee_data.empty:
                field_ops_assignee_data = pd.merge(field_ops_assignee_data, subs_assignee_data, on='FIELD_OPS_ASSIGNEE', how='left')
            else:
                field_ops_assignee_data['IMPACTED_SUBS'] = 0
            
            field_ops_assignee_data['COTTR_MINUTES'] = field_ops_assignee_data['COTTR_MINUTES'].fillna(0).astype(float)
            field_ops_assignee_data['IMPACTED_SUBS'] = field_ops_assignee_data['IMPACTED_SUBS'].fillna(0).astype(float)
            
            top_assignees = field_ops_assignee_data.head(10)
            
            # Get CM data by assignee
            cm_assignee_data = pd.DataFrame(columns=['FIELD_OPS_ASSIGNEE', 'CUSTOMER_MINUTES'])
            if not site_assignee_map.empty and not cm_site_data.empty:
                cm_merged_assignee = pd.merge(cm_site_data, site_assignee_map, on='SITE_ID', how='left')
                cm_merged_assignee['FIELD_OPS_ASSIGNEE'] = cm_merged_assignee['FIELD_OPS_ASSIGNEE'].fillna('Unassigned') if 'FIELD_OPS_ASSIGNEE' in cm_merged_assignee.columns else 'Unassigned'
                if 'FIELD_OPS_ASSIGNEE' in cm_merged_assignee.columns:
                    cm_assignee_data = cm_merged_assignee.groupby('FIELD_OPS_ASSIGNEE')['CUSTOMER_MINUTES'].sum().reset_index()
            
            # Merge CM data
            if not cm_assignee_data.empty:
                field_ops_assignee_data = pd.merge(field_ops_assignee_data, cm_assignee_data, on='FIELD_OPS_ASSIGNEE', how='left')
                field_ops_assignee_data['CUSTOMER_MINUTES'] = field_ops_assignee_data['CUSTOMER_MINUTES'].fillna(0)
            else:
                field_ops_assignee_data['CUSTOMER_MINUTES'] = 0
            
            top_assignees = field_ops_assignee_data.head(10)
            
            table_html = (
                '<table style="width:100%;border-collapse:collapse;background:#f8f9fa;border-radius:8px;overflow:hidden;font-size:0.75rem;">'
                '<thead><tr style="background:#e9ecef;border-bottom:2px solid #dee2e6;">'
                '<th style="padding:8px 6px;text-align:left;color:#555;font-weight:600;">Assignee</th>'
                '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">Down</th>'
                '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">Avail%</th>'
                '<th style="padding:8px 6px;text-align:center;color:#555;font-weight:600;">Budget</th>'
                '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">+/-</th>'
                '<th style="padding:8px 6px;text-align:center;color:#555;font-weight:600;">Days</th>'
                '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">COTTR</th>'
                '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">CM</th>'
                '<th style="padding:8px 6px;text-align:right;color:#555;font-weight:600;">Subs</th>'
                '<th style="padding:8px 6px;text-align:center;color:#555;font-weight:600;">Sites</th>'
                '</tr></thead><tbody>'
            )
            
            for _, row in top_assignees.iterrows():
                avail_pct = float(row['AVG_AVAILABILITY']) if pd.notna(row['AVG_AVAILABILITY']) else 0
                is_over = row['OVER_UNDER'] > 0
                status_color = "#ef4444" if is_over else "#22c55e"
                over_under_text = f"+{format_number(abs(row['OVER_UNDER']))}" if is_over else f"-{format_number(abs(row['OVER_UNDER']))}"
                usage_pct = min((row['TOTAL_DOWNTIME'] / row['SECONDS_ALLOWED'] * 100), 150) if row['SECONDS_ALLOWED'] > 0 else 0
                bar_color = "#ef4444" if usage_pct > 100 else "#f59e0b" if usage_pct > 75 else "#22c55e"
                display_name = str(row['FIELD_OPS_ASSIGNEE'])[:25] + ('...' if len(str(row['FIELD_OPS_ASSIGNEE'])) > 25 else '')
                days_meeting = int(row['DAYS_MEETING_GOAL']) if 'DAYS_MEETING_GOAL' in row and pd.notna(row['DAYS_MEETING_GOAL']) else 0
                total_days = int(row['TOTAL_DAYS']) if 'TOTAL_DAYS' in row and pd.notna(row['TOTAL_DAYS']) else 0
                days_pct = (days_meeting / total_days * 100) if total_days > 0 else 0
                days_color = "#22c55e" if days_pct >= 80 else "#f59e0b" if days_pct >= 50 else "#ef4444"
                cust_mins = float(row['CUSTOMER_MINUTES']) if 'CUSTOMER_MINUTES' in row and pd.notna(row['CUSTOMER_MINUTES']) else 0
                
                table_html += (
                    f'<tr style="border-bottom:1px solid #dee2e6;">'
                    f'<td style="padding:6px 8px;font-size:0.75rem;color:#1a1a2e;font-weight:600;" title="{row["FIELD_OPS_ASSIGNEE"]}">{display_name}</td>'
                    f'<td style="padding:6px 8px;text-align:right;font-size:0.75rem;color:#e20074;font-weight:600;">{format_number(row["TOTAL_DOWNTIME"])}s</td>'
                    f'<td style="padding:6px 8px;text-align:right;font-size:0.75rem;color:{"#ef4444" if avail_pct < 99.85 else "#22c55e"};font-weight:600;">{avail_pct:.2f}%</td>'
                    f'<td style="padding:6px 8px;width:70px;">'
                    f'<div style="display:flex;align-items:center;gap:4px;">'
                    f'<div style="flex:1;background:#dee2e6;border-radius:3px;height:6px;overflow:hidden;">'
                    f'<div style="background:{bar_color};height:100%;width:{min(usage_pct, 100)}%;"></div>'
                    f'</div>'
                    f'<span style="font-size:0.65rem;color:#666;white-space:nowrap;">{usage_pct:.0f}%</span>'
                    f'</div>'
                    f'</td>'
                    f'<td style="padding:6px 8px;text-align:right;font-size:0.75rem;color:{status_color};font-weight:600;">{over_under_text}</td>'
                    f'<td style="padding:6px 8px;text-align:center;font-size:0.75rem;color:{days_color};font-weight:600;">{days_meeting}/{total_days}</td>'
                    f'<td style="padding:6px 8px;text-align:right;font-size:0.75rem;color:#f59e0b;font-weight:600;">{format_number(row["COTTR_MINUTES"])}</td>'
                    f'<td style="padding:6px 8px;text-align:right;font-size:0.75rem;color:#e20074;">{format_number(cust_mins)}</td>'
                    f'<td style="padding:6px 8px;text-align:right;font-size:0.75rem;color:#e20074;font-weight:600;">{format_number(row["IMPACTED_SUBS"])}</td>'
                    f'<td style="padding:6px 8px;text-align:center;font-size:0.75rem;color:#666;">{row["SITE_COUNT"]}</td>'
                    f'</tr>'
                )
            
            table_html += '</tbody></table>'
            st.markdown(table_html, unsafe_allow_html=True)
        else:
            st.info("No Field Ops Assignee data available.")
    
    st.divider()
    
    # Get combined site data (parallelized internally for speed)
    cm_sites, avail_sites, cottr_sites = get_combined_site_data(conn, days, 100, filters)
    
    # Pre-compute zero-avail-but-COTTR stats from raw site data (single source of truth)
    _avail_site_ids = set(avail_sites[avail_sites['TOTAL_DOWNTIME'] > 0]['SITE_ID'].unique()) if not avail_sites.empty else set()
    if not cottr_sites.empty:
        _cottr_by_site = cottr_sites.groupby('SITE_ID')['OUTAGE_MINUTES'].sum().reset_index()
        _cottr_only = _cottr_by_site[~_cottr_by_site['SITE_ID'].isin(_avail_site_ids)]
        zero_avail_cottr_site_count = len(_cottr_only)
        zero_avail_cottr_mins_total = float(_cottr_only['OUTAGE_MINUTES'].sum())
    else:
        zero_avail_cottr_site_count = 0
        zero_avail_cottr_mins_total = 0.0
    
    # ===== DATA VALIDATION =====
    validate_site_scatter_data(avail_sites, cottr_sites)
    if data_validator.has_issues():
        data_validator.display_messages()
    
    # No site selector - show all sites
    selected_site_id = None
    
    # Row 1: Top Sites by Downtime and Site Outage Summary
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("##### Top Sites by Downtime")
        if not avail_sites.empty:
            # Filter out rows with NULL focus category
            avail_with_cat = avail_sites[avail_sites['SITE_ID_FOCUS_CATEGORY'].notna()].copy()
            
            if not avail_with_cat.empty:
                # Determine top N based on whether market is selected
                market_selected = filters.get('market') if filters else None
                top_n = 20 if market_selected else 50
                
                # Get top N sites by total downtime
                site_totals = avail_with_cat.groupby('SITE_ID')['TOTAL_DOWNTIME'].sum().nlargest(top_n)
                top_sites = site_totals.index.tolist()
                avail_filtered = avail_with_cat[avail_with_cat['SITE_ID'].isin(top_sites)].copy()
                
                # Calculate total downtime for percentage calculation
                total_all_downtime = avail_filtered['TOTAL_DOWNTIME'].sum()
                
                # Calculate what % of total these top sites represent
                all_sites_total = avail_with_cat['TOTAL_DOWNTIME'].sum()
                top_sites_pct = (total_all_downtime / all_sites_total * 100) if all_sites_total > 0 else 0
                num_all_sites = avail_with_cat['SITE_ID'].nunique()
                actual_top_n = min(top_n, num_all_sites)
                
                site_type_display = filters.get('site_type', 'All') if filters else 'All'
                st.markdown(f"<span style='font-size:0.75rem;color:#888;'>Availability | {site_type_display} | Downtime > 0 | By Focus Category</span> <span style='font-size:0.75rem;color:#22c55e;font-weight:bold;'>| Top {actual_top_n} of {num_all_sites:,} sites = {top_sites_pct:.2f}% of total downtime</span>", unsafe_allow_html=True)
                
                # Calculate percentage for each row
                avail_filtered['PCT'] = (avail_filtered['TOTAL_DOWNTIME'] / total_all_downtime * 100).round(1)
                # Create text with focus category short name + percentage
                def get_short_category(cat):
                    if pd.isna(cat):
                        return ''
                    cat_str = str(cat)
                    # Shorten common category names
                    if 'Vandalized' in cat_str:
                        return 'V/D'
                    elif 'Hardware' in cat_str and 'Antenna' in cat_str:
                        return 'HW-Ant'
                    elif 'Hardware' in cat_str:
                        return 'HW'
                    elif 'Unaccounted' in cat_str:
                        return 'Unacc'
                    elif 'Transport' in cat_str and 'AAV' in cat_str:
                        return 'T-AAV'
                    elif 'Transport' in cat_str:
                        return 'Trans'
                    elif 'Power' in cat_str:
                        return 'Pwr'
                    elif 'RAN' in cat_str:
                        return 'RAN'
                    elif 'Internal' in cat_str:
                        return 'Int'
                    else:
                        return cat_str[:8]  # Truncate to 8 chars
                
                avail_filtered['CAT_SHORT'] = avail_filtered['SITE_ID_FOCUS_CATEGORY'].apply(get_short_category)
                avail_filtered['PCT_TEXT'] = avail_filtered.apply(lambda x: f"{x['PCT']:.1f}% {x['CAT_SHORT']}", axis=1)
                
                # Calculate chart height: full height for all bars (22px per bar + padding)
                chart_height = max(400, actual_top_n * 22 + 80)
                
                # Build complete color map ensuring all categories have colors (prevents Plotly auto-assign)
                unique_cats = avail_filtered['SITE_ID_FOCUS_CATEGORY'].unique()
                complete_color_map = {cat: FOCUS_CATEGORY_COLORS.get(cat, DEFAULT_FOCUS_COLOR) for cat in unique_cats}
                
                fig = px.bar(
                    avail_filtered, 
                    x='TOTAL_DOWNTIME', 
                    y='SITE_ID', 
                    orientation='h',
                    color='SITE_ID_FOCUS_CATEGORY',
                    color_discrete_map=complete_color_map,
                    text='PCT_TEXT',
                )
                fig.update_traces(
                    textposition='inside',
                    textfont=dict(color='white', size=10, family='Arial Black'),
                    insidetextanchor='middle',
                    hoverinfo='none',
                    hovertemplate=None
                )
                fig.update_layout(
                    template='plotly_white', 
                    height=chart_height, 
                    font=dict(size=14),
                    showlegend=False,
                    hovermode=False,
                    yaxis={'categoryorder': 'total ascending', 'tickfont': dict(size=11)},
                    xaxis={'title': 'Total Downtime (sec)', 'tickfont': dict(size=12)},
                    uniformtext_minsize=8,
                    uniformtext_mode='hide',
                    margin=dict(l=10, r=10, t=10, b=40)
                )
                # Display only 15 bars visible with scrollbar to view rest
                if actual_top_n > 15:
                    with st.container(height=420):
                        st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="site_focus_cat_bar")
                else:
                    st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="site_focus_cat_bar")
            else:
                st.markdown("<span style='font-size:0.75rem;color:#888;'>Availability | Macro | Downtime > 0 | By Focus Category</span>", unsafe_allow_html=True)
                st.info("No availability data with focus categories available.")
        else:
            site_type_display = filters.get('site_type', 'All') if filters else 'All'
            st.markdown(f"<span style='font-size:0.75rem;color:#888;'>Availability | {site_type_display} | Downtime > 0 | By Focus Category</span>", unsafe_allow_html=True)
            st.info("No availability downtime data available.")
    
    with col2:
        site_type_display = filters.get('site_type', 'All') if filters else 'All'
        st.markdown("##### Site Outage Summary")
        st.markdown(f"<span style='font-size:0.75rem;color:#888;'>Count of Days: Avail DT>0 ({site_type_display}) | COTTR Outages ({site_type_display}) | CM Subs>0</span>", unsafe_allow_html=True)
        
        # Get ALL sites with any KPI > 0 (no limit)
        site_summary_raw = get_site_summary_data(conn, days, 100000, filters)
        
        # Show site count message
        site_count = len(site_summary_raw) if not site_summary_raw.empty else 0
        st.markdown(f"<span style='font-size:0.75rem;color:#10b981;'>Showing all <b>{site_count:,}</b> sites with any KPI > 0, sorted by total days</span>", unsafe_allow_html=True)
        
        # Show Coverage Class breakdown
        if not site_summary_raw.empty and 'COVERAGE_CLASSIFICATION' in site_summary_raw.columns:
            coverage_counts = site_summary_raw['COVERAGE_CLASSIFICATION'].fillna('Unknown').value_counts().reset_index()
            coverage_counts.columns = ['Coverage Class', 'Site Count']
            
            # Create inline display of coverage class counts
            coverage_items = []
            for _, row in coverage_counts.iterrows():
                coverage_items.append(f"<span style='background:#2a2a4a;padding:3px 8px;border-radius:4px;margin-right:8px;font-size:0.8rem;color:#ffffff;'><b>{row['Coverage Class']}</b>: {row['Site Count']}</span>")
            
            st.markdown(f"<div style='margin-bottom:10px;'>{''.join(coverage_items)}</div>", unsafe_allow_html=True)
        
        # Build site summary table from combined query results
        site_summary = pd.DataFrame()
        
        if not site_summary_raw.empty:
            # Include columns with both Avail and COTTR last outage info
            cols_to_use = ['SITE_ID', 'MARKET_ID', 'AVAIL_DOWNTIME_DAYS', 'TOTAL_DOWNTIME_SEC', 'AVAIL_RECORD_COUNT', 'COTTR_OUTAGE_DAYS', 'TOTAL_OUTAGE_MINS', 'COTTR_RECORD_COUNT', 'CM_DAYS', 
                          'IMPACT_DURATION_MINS', 'CM_DAY_COUNT',
                          'FIELD_OPS_ASSIGNEE', 'FIELD_OPS_ASSIGNMENT_GROUP', 'FIELD_OPS_MGR', 'MB_MKT_AREA', 
                          'LAST_AVAIL_OUTAGE_DATE', 'LAST_AVAIL_FOCUS_CATEGORY', 'LAST_AVAIL_OUTAGE_DESCRIPTION',
                          'LAST_COTTR_OUTAGE_DATE', 'LAST_COTTR_FOCUS_CATEGORY',
                          'COVERAGE_CLASSIFICATION']
            available_cols = [c for c in cols_to_use if c in site_summary_raw.columns]
            site_summary = site_summary_raw[available_cols].copy()
            
            # Rename columns
            col_rename = {
                'MARKET_ID': 'Market',
                'AVAIL_DOWNTIME_DAYS': 'Avail Days (DT>0)',
                'TOTAL_DOWNTIME_SEC': 'Total Downtime (sec)',
                'AVAIL_RECORD_COUNT': 'Avail Records',
                'COTTR_OUTAGE_DAYS': 'COTTR Outage Days',
                'TOTAL_OUTAGE_MINS': 'Service Outage Mins',
                'COTTR_RECORD_COUNT': 'COTTR Records',
                'CM_DAYS': 'CM Days (Subs>0)',
                'IMPACT_DURATION_MINS': 'Impact Dur (mins)',
                'CM_DAY_COUNT': 'CM Day Count',
                'FIELD_OPS_ASSIGNEE': 'Field Ops Assignee',
                'FIELD_OPS_ASSIGNMENT_GROUP': 'Assignment Group',
                'FIELD_OPS_MGR': 'Field Ops Mgr',
                'MB_MKT_AREA': 'Market Area',
                'LAST_AVAIL_OUTAGE_DATE': 'Last Avail Outage',
                'LAST_AVAIL_FOCUS_CATEGORY': 'Last Avail Category',
                'LAST_AVAIL_OUTAGE_DESCRIPTION': 'Last Avail Desc',
                'LAST_COTTR_OUTAGE_DATE': 'Last COTTR Outage',
                'LAST_COTTR_FOCUS_CATEGORY': 'Last COTTR Category',
                'COVERAGE_CLASSIFICATION': 'Coverage Class'
            }
            site_summary = site_summary.rename(columns=col_rename)
        
        if not site_summary.empty:
            # Fill NaN for numeric columns
            numeric_cols = ['Avail Days (DT>0)', 'Avail Records', 'COTTR Outage Days', 'COTTR Records', 'CM Days (Subs>0)']
            for col in numeric_cols:
                if col in site_summary.columns:
                    site_summary[col] = site_summary[col].fillna(0).astype(int)
            
            # Calculate total for sorting - show ALL sites with any KPI > 0 (no head limit)
            sort_cols = [c for c in numeric_cols if c in site_summary.columns]
            if sort_cols:
                site_summary['Total'] = site_summary[sort_cols].sum(axis=1)
                site_summary = site_summary.sort_values('Total', ascending=False)
                site_summary = site_summary.drop(columns=['Total'])
            
            # Format Last Outage Dates (both Avail and COTTR)
            if 'Last Avail Outage' in site_summary.columns:
                site_summary['Last Avail Outage'] = pd.to_datetime(site_summary['Last Avail Outage'], errors='coerce').dt.strftime('%Y-%m-%d')
                site_summary['Last Avail Outage'] = site_summary['Last Avail Outage'].fillna('-')
            if 'Last COTTR Outage' in site_summary.columns:
                site_summary['Last COTTR Outage'] = pd.to_datetime(site_summary['Last COTTR Outage'], errors='coerce').dt.strftime('%Y-%m-%d')
                site_summary['Last COTTR Outage'] = site_summary['Last COTTR Outage'].fillna('-')
            
            # Fill empty string columns
            if 'Market' in site_summary.columns:
                site_summary['Market'] = site_summary['Market'].fillna('Unknown')
            if 'Field Ops Assignee' in site_summary.columns:
                site_summary['Field Ops Assignee'] = site_summary['Field Ops Assignee'].fillna('-')
            if 'Last Avail Category' in site_summary.columns:
                site_summary['Last Avail Category'] = site_summary['Last Avail Category'].fillna('-')
            if 'Last COTTR Category' in site_summary.columns:
                site_summary['Last COTTR Category'] = site_summary['Last COTTR Category'].fillna('-')
            if 'Last Avail Desc' in site_summary.columns:
                site_summary['Last Avail Desc'] = site_summary['Last Avail Desc'].fillna('-')
            
            # Filter mask: sites with 0 Avail Downtime but COTTR > 0
            zero_avail_mask = (
                (site_summary.get('Total Downtime (sec)', pd.Series(dtype=float)).fillna(0) == 0) &
                (site_summary.get('Service Outage Mins', pd.Series(dtype=float)).fillna(0) > 0)
            )
            
            csv_data = site_summary.to_csv(index=False).encode('utf-8')
            download_col, filter_col, spacer_col = st.columns([1, 2, 3])
            with download_col:
                st.download_button(
                    label="📥 Download CSV",
                    data=csv_data,
                    file_name="site_outage_summary.csv",
                    mime="text/csv",
                    key="download_site_outage_csv"
                )
            with filter_col:
                if zero_avail_cottr_site_count > 0:
                    filter_zero_avail = st.checkbox(
                        f"⚠️ {zero_avail_cottr_site_count} sites: 0 Avail DT but {zero_avail_cottr_mins_total:,.0f} COTTR mins",
                        key="filter_zero_avail_cottr"
                    )
                else:
                    filter_zero_avail = False
            
            display_df = site_summary[zero_avail_mask] if filter_zero_avail else site_summary
            
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No site data available.")
    
    # Row 2: Scatter Chart - Availability vs COTTR by Site (Full Width)
    st.markdown("##### Availability vs COTTR by Site")
    
    # Combine availability and COTTR data for scatter chart
    if not avail_sites.empty or not cottr_sites.empty:
        # Aggregate availability by site - get dominant focus category (one with most downtime)
        if not avail_sites.empty:
            avail_by_site = avail_sites.groupby('SITE_ID').agg({
                'TOTAL_DOWNTIME': 'sum'
            }).reset_index()
            avail_by_site.columns = ['SITE_ID', 'AVAIL_DOWNTIME_SEC']
            
            # Get dominant focus category per site (category with highest downtime)
            site_focus = avail_sites.groupby(['SITE_ID', 'SITE_ID_FOCUS_CATEGORY'])['TOTAL_DOWNTIME'].sum().reset_index()
            site_focus = site_focus.loc[site_focus.groupby('SITE_ID')['TOTAL_DOWNTIME'].idxmax()][['SITE_ID', 'SITE_ID_FOCUS_CATEGORY']]
            site_focus.columns = ['SITE_ID', 'FOCUS_CATEGORY']
            
            # Get Field Ops Assignee per site (take max/first non-null value)
            if 'FIELD_OPS_ASSIGNEE' in avail_sites.columns:
                site_assignee = avail_sites.groupby('SITE_ID')['FIELD_OPS_ASSIGNEE'].first().reset_index()
                site_assignee.columns = ['SITE_ID', 'FIELD_OPS_ASSIGNEE']
            else:
                site_assignee = pd.DataFrame({'SITE_ID': avail_by_site['SITE_ID'], 'FIELD_OPS_ASSIGNEE': 'N/A'})
            
            # Merge focus category and assignee into avail_by_site
            avail_by_site = pd.merge(avail_by_site, site_focus, on='SITE_ID', how='left')
            avail_by_site = pd.merge(avail_by_site, site_assignee, on='SITE_ID', how='left')
        else:
            avail_by_site = pd.DataFrame(columns=['SITE_ID', 'AVAIL_DOWNTIME_SEC', 'FOCUS_CATEGORY', 'FIELD_OPS_ASSIGNEE'])
        
        # Aggregate COTTR by site - also get dominant focus category
        if not cottr_sites.empty:
            cottr_by_site = cottr_sites.groupby('SITE_ID').agg({
                'OUTAGE_MINUTES': 'sum'
            }).reset_index()
            cottr_by_site.columns = ['SITE_ID', 'COTTR_OUTAGE_MIN']
            
            # Get dominant COTTR focus category per site
            cottr_focus = cottr_sites.groupby(['SITE_ID', 'SITE_ID_FOCUS_CATEGORY'])['OUTAGE_MINUTES'].sum().reset_index()
            cottr_focus = cottr_focus.loc[cottr_focus.groupby('SITE_ID')['OUTAGE_MINUTES'].idxmax()][['SITE_ID', 'SITE_ID_FOCUS_CATEGORY']]
            cottr_focus.columns = ['SITE_ID', 'COTTR_FOCUS_CATEGORY']
            
            cottr_by_site = pd.merge(cottr_by_site, cottr_focus, on='SITE_ID', how='left')
        else:
            cottr_by_site = pd.DataFrame(columns=['SITE_ID', 'COTTR_OUTAGE_MIN', 'COTTR_FOCUS_CATEGORY'])
        
        # Merge the data - use outer join to include all sites
        combined = pd.merge(avail_by_site, cottr_by_site, on='SITE_ID', how='outer')
        
        # Fill only numeric columns with 0 (not the category columns!)
        combined['AVAIL_DOWNTIME_SEC'] = combined['AVAIL_DOWNTIME_SEC'].fillna(0).astype(float)
        combined['COTTR_OUTAGE_MIN'] = combined['COTTR_OUTAGE_MIN'].fillna(0).astype(float)
        
        # Use avail focus category if available, otherwise COTTR focus category
        if 'FOCUS_CATEGORY' in combined.columns and 'COTTR_FOCUS_CATEGORY' in combined.columns:
            combined['FOCUS_CATEGORY'] = combined['FOCUS_CATEGORY'].fillna(combined['COTTR_FOCUS_CATEGORY'])
        elif 'COTTR_FOCUS_CATEGORY' in combined.columns:
            combined['FOCUS_CATEGORY'] = combined['COTTR_FOCUS_CATEGORY']
        
        # Fill any remaining NaN with 'Other'
        if 'FOCUS_CATEGORY' in combined.columns:
            combined['FOCUS_CATEGORY'] = combined['FOCUS_CATEGORY'].fillna('Other').replace({'': 'Other'})
        else:
            combined['FOCUS_CATEGORY'] = 'Other'
        
        # Fill null FIELD_OPS_ASSIGNEE
        if 'FIELD_OPS_ASSIGNEE' in combined.columns:
            combined['FIELD_OPS_ASSIGNEE'] = combined['FIELD_OPS_ASSIGNEE'].fillna('Unassigned').replace({0: 'Unassigned', '': 'Unassigned'})
        else:
            combined['FIELD_OPS_ASSIGNEE'] = 'Unassigned'
        
        # Filter to sites with at least some downtime
        combined = combined[(combined['AVAIL_DOWNTIME_SEC'] > 0) | (combined['COTTR_OUTAGE_MIN'] > 0)]
        
        st.markdown(f"<span style='font-size:0.75rem;color:#888;'>X: Avail Downtime (sec) - Macro | Y: COTTR Outage (min) - Service Outage, Macro | Color: Focus Category</span> &nbsp;&nbsp; <span style='font-size:0.8rem;color:#ef4444;font-weight:bold;'>⚠️ {zero_avail_cottr_site_count:,} sites with 0 Avail Downtime but {zero_avail_cottr_mins_total:,.0f} COTTR mins</span>", unsafe_allow_html=True)
        
        if not combined.empty:
            # Label top 5 by total impact
            combined['TOTAL_IMPACT'] = combined['AVAIL_DOWNTIME_SEC'] + (combined['COTTR_OUTAGE_MIN'] * 60)
            top_5 = combined.nlargest(5, 'TOTAL_IMPACT')['SITE_ID'].tolist()
            
            # Create scatter plot - tooltip will appear at top of chart
            fig_scatter = go.Figure()
            
            for category in combined['FOCUS_CATEGORY'].unique():
                cat_data = combined[combined['FOCUS_CATEGORY'] == category].copy()
                color = FOCUS_CATEGORY_COLORS.get(category, DEFAULT_FOCUS_COLOR)
                
                fig_scatter.add_trace(go.Scatter(
                    x=cat_data['AVAIL_DOWNTIME_SEC'].tolist(),
                    y=cat_data['COTTR_OUTAGE_MIN'].tolist(),
                    mode='markers',
                    name=category,
                    marker=dict(size=10, color=color, opacity=0.8),
                    customdata=list(zip(
                        cat_data['SITE_ID'].tolist(),
                        cat_data['FOCUS_CATEGORY'].tolist(),
                        cat_data['AVAIL_DOWNTIME_SEC'].tolist(),
                        cat_data['COTTR_OUTAGE_MIN'].tolist(),
                        cat_data['FIELD_OPS_ASSIGNEE'].fillna('N/A').tolist()
                    )),
                    hovertemplate=(
                        "<b>%{customdata[0]}</b> | " +
                        "%{customdata[1]} | " +
                        "Avail: %{customdata[2]:,.0f} sec | " +
                        "COTTR: %{customdata[3]:,.0f} min | " +
                        "Assignee: %{customdata[4]}<extra></extra>"
                    ),
                ))
            
            # Highlight selected site with larger marker
            if selected_site_id and selected_site_id in combined['SITE_ID'].values:
                selected_row = combined[combined['SITE_ID'] == selected_site_id].iloc[0]
                fig_scatter.add_trace(go.Scatter(
                    x=[selected_row['AVAIL_DOWNTIME_SEC']],
                    y=[selected_row['COTTR_OUTAGE_MIN']],
                    mode='markers',
                    marker=dict(size=20, color='#22c55e', line=dict(width=3, color='white')),
                    name='Selected',
                    hoverinfo='skip',
                    showlegend=False,
                ))
            
            # Add annotations for top 5 or selected site
            sites_to_label = [selected_site_id] if selected_site_id and selected_site_id in combined['SITE_ID'].values else top_5
            for i, (_, row) in enumerate(combined[combined['SITE_ID'].isin(sites_to_label)].iterrows()):
                fig_scatter.add_annotation(
                    x=row['AVAIL_DOWNTIME_SEC'],
                    y=row['COTTR_OUTAGE_MIN'],
                    text=row['SITE_ID'],
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=1,
                    arrowcolor='#22c55e' if row['SITE_ID'] == selected_site_id else '#666666',
                    ax=20 if i % 2 == 0 else -20,
                    ay=-20 if i % 2 == 0 else 20,
                    font=dict(size=9, color='#22c55e' if row['SITE_ID'] == selected_site_id else '#333333', family='Arial'),
                    bgcolor='rgba(255,255,255,0.9)',
                    bordercolor='#22c55e' if row['SITE_ID'] == selected_site_id else '#666666',
                    borderwidth=2 if row['SITE_ID'] == selected_site_id else 1,
                    borderpad=3,
                )
            
            fig_scatter.update_layout(
                template='plotly_white', 
                height=450, 
                font=dict(size=14),
                xaxis_title='Availability Downtime (sec)',
                yaxis_title='COTTR Outage (min)',
                legend=dict(
                    orientation="h",
                    yanchor="top",
                    y=-0.12,
                    xanchor="center",
                    x=0.5,
                    font=dict(size=12),
                ),
                margin=dict(t=60, b=100),
                hovermode='x unified',
                hoverlabel=HOVER_LABEL_STYLE,
            )
            
            st.plotly_chart(fig_scatter, use_container_width=True, config=CHART_CONFIG, key="site_scatter_downtime")
        else:
            st.info("No sites with downtime data.")
    else:
        st.info("No data available.")
    
    st.divider()
    
    # ===== THIRD ROW OF CHARTS =====
    st.markdown("### 📊 Additional Analysis")
    
    # Chart #6: COTTR Duration Analysis by Focus Category
    chart_col3, _ = st.columns([2, 1])
    with chart_col3:
        st.markdown("##### Outage Duration Distribution")
        st.markdown("<span style='font-size:0.75rem;color:#888;'>COTTR outage minutes | Service Outage, Macro | By Focus Category</span>", unsafe_allow_html=True)
        
        if not cottr_sites.empty and 'OUTAGE_MINUTES' in cottr_sites.columns and 'SITE_ID_FOCUS_CATEGORY' in cottr_sites.columns:
            # Create duration bins (in minutes)
            bins = [0, 30, 60, 120, 240, 480, float('inf')]
            labels = ['0-30 min', '30-60 min', '1-2 hrs', '2-4 hrs', '4-8 hrs', '8+ hrs']
            
            cottr_duration = cottr_sites.copy()
            cottr_duration['Duration Range'] = pd.cut(cottr_duration['OUTAGE_MINUTES'].astype(float), bins=bins, labels=labels, include_lowest=True)
            cottr_duration['SITE_ID_FOCUS_CATEGORY'] = cottr_duration['SITE_ID_FOCUS_CATEGORY'].fillna('Other')
            
            # Group by duration range and focus category
            duration_dist = cottr_duration.groupby(['Duration Range', 'SITE_ID_FOCUS_CATEGORY']).size().reset_index(name='Count')
            
            fig = px.bar(
                duration_dist,
                x='Duration Range',
                y='Count',
                color='SITE_ID_FOCUS_CATEGORY',
                color_discrete_map=FOCUS_CATEGORY_COLORS,
                barmode='stack',
            )
            fig.update_layout(
                template='plotly_white',
                height=400,
                font=dict(size=14),
                xaxis_title='Outage Duration',
                yaxis_title='Number of Events',
                xaxis_tickangle=-45,
                xaxis=dict(tickfont=dict(size=12)),
                yaxis=dict(tickfont=dict(size=12)),
                legend=dict(orientation='h', yanchor='top', y=-0.2, xanchor='center', x=0.5, font=dict(size=12)),
                legend_title_text='',
                margin=dict(b=100),
            )
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="site_cottr_duration")
        else:
            st.info("No COTTR duration data available.")
    
    st.divider()
    
    
    # Data tables - filter by selected site if one is selected
    if selected_site_id:
        st.markdown(f"### 📋 Raw Data - Filtered to Site: **{selected_site_id}**")
    else:
        st.markdown("### 📋 Raw Data")
    
    tab1, tab2, tab3 = st.tabs(["Customer Minutes", "Availability", "COTTR"])
    with tab1:
        if not cm_sites.empty:
            display_cm = cm_sites[cm_sites['SITE_ID'] == selected_site_id] if selected_site_id else cm_sites
            if not display_cm.empty:
                display_cm = display_cm.reset_index(drop=True)
                display_cm.index = display_cm.index + 1
                st.dataframe(display_cm, use_container_width=True, height=300)
            else:
                st.info(f"No Customer Minutes data for site {selected_site_id}")
        else:
            st.info("No Customer Minutes data available.")
    with tab2:
        if not avail_sites.empty:
            display_avail = avail_sites[avail_sites['SITE_ID'] == selected_site_id] if selected_site_id else avail_sites
            if not display_avail.empty:
                display_avail = display_avail.reset_index(drop=True)
                display_avail.index = display_avail.index + 1
                st.dataframe(display_avail, use_container_width=True, height=300)
            else:
                st.info(f"No Availability data for site {selected_site_id}")
        else:
            st.info("No Availability data available.")
    with tab3:
        if not cottr_sites.empty:
            display_cottr = cottr_sites[cottr_sites['SITE_ID'] == selected_site_id] if selected_site_id else cottr_sites
            if not display_cottr.empty:
                display_cottr = display_cottr.reset_index(drop=True)
                display_cottr.index = display_cottr.index + 1
                st.dataframe(display_cottr, use_container_width=True, height=300)
            else:
                st.info(f"No COTTR data for site {selected_site_id}")
        else:
            st.info("No COTTR data available.")

def region_availability_summary(conn, days, filters=None):
    """Region Availability Summary - Threshold analysis and insights"""
    
    AVAILABILITY_GOAL = 99.85
    
    st.markdown('<div class="section-header">🌎 Region Availability Summary</div>', unsafe_allow_html=True)
    st.markdown(f"<span style='font-size:0.85rem;color:#888;'>*Market Availability to meet ≥ {AVAILABILITY_GOAL}% | Site Type filter applied</span>", unsafe_allow_html=True)
    
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    oem_filter = filters.get('oem') if filters else None
    site_type = filters.get('site_type') if filters else None
    site_type_filter = get_site_type_sql_filter(site_type)
    site_type_filter_a = get_site_type_sql_filter(site_type, 'a.')
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Build OEM join clause if needed
    if oem_filter:
        avail_filter_aliased = avail_filter.replace('MARKET_ID', 'a.MARKET_ID') if avail_filter else ''
        oem_join = f"JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)"
        oem_where = f"AND mt.M_OEM = '{oem_filter}'"
        tbl_prefix = "a."
    else:
        avail_filter_aliased = avail_filter
        oem_join = ""
        oem_where = ""
        tbl_prefix = ""
    
    # Get market-level availability details with threshold calculations
    if oem_filter:
        market_query = f"""
        SELECT 
            a.MARKET_ID,
            a.REGION_ID,
            SUM(a.TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_N) as AVAILABILITY_NUMERATOR,
            SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
            SUM(a.TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100) as SECONDS_ALLOWED,
            GREATEST(SUM(a.TOTAL_DOWNTIME) - (SUM(a.TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100)), 0) as OVER_THRESHOLD
        FROM {TABLES['availability']} a
        {oem_join}
        WHERE {date_filter} AND {site_type_filter_a} {oem_where} {avail_filter_aliased}
        GROUP BY a.MARKET_ID, a.REGION_ID
        ORDER BY DOWNTIME_SECONDS DESC
        """
    else:
        market_query = f"""
        SELECT 
            MARKET_ID,
            REGION_ID,
            SUM(TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(TOTAL_AVAILABILITY_D) as TOTAL_SECONDS,
            SUM(TOTAL_AVAILABILITY_N) as AVAILABILITY_NUMERATOR,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
            SUM(TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100) as SECONDS_ALLOWED,
            GREATEST(SUM(TOTAL_DOWNTIME) - (SUM(TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100)), 0) as OVER_THRESHOLD
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY MARKET_ID, REGION_ID
        ORDER BY DOWNTIME_SECONDS DESC
        """
    market_data = run_query(conn, market_query)
    
    # Normalize market names to Global Market ID format
    if not market_data.empty and 'MARKET_ID' in market_data.columns:
        market_data = normalize_market_column(market_data, 'MARKET_ID', 'availability')
    
    # Get region-level summary
    if oem_filter:
        region_query = f"""
        SELECT 
            a.REGION_ID,
            SUM(a.TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
            SUM(a.TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100) as SECONDS_ALLOWED,
            GREATEST(SUM(a.TOTAL_DOWNTIME) - (SUM(a.TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100)), 0) as OVER_THRESHOLD
        FROM {TABLES['availability']} a
        {oem_join}
        WHERE {date_filter} AND {site_type_filter_a} {oem_where} {avail_filter_aliased}
        GROUP BY a.REGION_ID
        ORDER BY DOWNTIME_SECONDS DESC
        """
    else:
        region_query = f"""
        SELECT 
            REGION_ID,
            SUM(TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(TOTAL_AVAILABILITY_D) as TOTAL_SECONDS,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
            SUM(TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100) as SECONDS_ALLOWED,
            GREATEST(SUM(TOTAL_DOWNTIME) - (SUM(TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100)), 0) as OVER_THRESHOLD
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY REGION_ID
        ORDER BY DOWNTIME_SECONDS DESC
        """
    region_data = run_query(conn, region_query)
    
    # Get national summary
    if oem_filter:
        national_query = f"""
        SELECT 
            'National' as ENTITY,
            SUM(a.TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
            SUM(a.TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100) as SECONDS_ALLOWED,
            GREATEST(SUM(a.TOTAL_DOWNTIME) - (SUM(a.TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100)), 0) as OVER_THRESHOLD
        FROM {TABLES['availability']} a
        {oem_join}
        WHERE {date_filter} AND {site_type_filter_a} {oem_where} {avail_filter_aliased}
        """
    else:
        national_query = f"""
        SELECT 
            'National' as ENTITY,
            SUM(TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(TOTAL_AVAILABILITY_D) as TOTAL_SECONDS,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
            SUM(TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100) as SECONDS_ALLOWED,
            GREATEST(SUM(TOTAL_DOWNTIME) - (SUM(TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100)), 0) as OVER_THRESHOLD
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        """
    national_data = run_query(conn, national_query)
    
    # Get downtime by focus category
    if oem_filter:
        category_query = f"""
        SELECT 
            COALESCE(a.SITE_ID_FOCUS_CATEGORY, 'Uncategorized') as FOCUS_CATEGORY,
            SUM(a.TOTAL_DOWNTIME) as DOWNTIME_SECONDS
        FROM {TABLES['availability']} a
        {oem_join}
        WHERE {date_filter} AND {site_type_filter_a} {oem_where} {avail_filter_aliased}
        GROUP BY a.SITE_ID_FOCUS_CATEGORY
        ORDER BY DOWNTIME_SECONDS DESC
        """
    else:
        category_query = f"""
        SELECT 
            COALESCE(SITE_ID_FOCUS_CATEGORY, 'Uncategorized') as FOCUS_CATEGORY,
            SUM(TOTAL_DOWNTIME) as DOWNTIME_SECONDS
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY SITE_ID_FOCUS_CATEGORY
        ORDER BY DOWNTIME_SECONDS DESC
        """
    category_data = run_query(conn, category_query)
    
    # Get daily availability trend by region
    if oem_filter:
        daily_region_query = f"""
        SELECT 
            a.DATE_VALUE,
            a.REGION_ID,
            SUM(a.TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT
        FROM {TABLES['availability']} a
        {oem_join}
        WHERE {date_filter} AND {site_type_filter_a} {oem_where} {avail_filter_aliased}
        GROUP BY a.DATE_VALUE, a.REGION_ID
        ORDER BY a.DATE_VALUE
        """
    else:
        daily_region_query = f"""
        SELECT 
            DATE_VALUE,
            REGION_ID,
            SUM(TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY DATE_VALUE, REGION_ID
        ORDER BY DATE_VALUE, REGION_ID
        """
    daily_region_data = run_query(conn, daily_region_query)
    
    if market_data.empty:
        st.info("No availability data available for the selected filters.")
        return
    
    # Convert to float
    for col in ['DOWNTIME_SECONDS', 'TOTAL_SECONDS', 'AVAILABILITY_PCT', 'SECONDS_ALLOWED', 'OVER_THRESHOLD']:
        if col in market_data.columns:
            market_data[col] = market_data[col].astype(float)
        if col in region_data.columns:
            region_data[col] = region_data[col].astype(float)
        if col in national_data.columns:
            national_data[col] = national_data[col].astype(float)
    
    # ===== ROW 1: National & Regional KPIs =====
    st.markdown("### 📊 National & Regional Summary")
    
    if not national_data.empty:
        nat = national_data.iloc[0]
        nat_avail = nat['AVAILABILITY_PCT']
        nat_status = "✅" if nat_avail >= AVAILABILITY_GOAL else "❌"
        
        kpi_cols = st.columns(5)
        with kpi_cols[0]:
            st.metric("National Availability", f"{nat_avail:.2f}%", 
                     delta=f"{nat_avail - AVAILABILITY_GOAL:.2f}%" if nat_avail >= AVAILABILITY_GOAL else f"{nat_avail - AVAILABILITY_GOAL:.2f}%")
        with kpi_cols[1]:
            st.metric("Total Downtime", format_number(nat['DOWNTIME_SECONDS']) + " sec")
        with kpi_cols[2]:
            st.metric("Seconds Budget", format_number(nat['SECONDS_ALLOWED']) + " sec")
        with kpi_cols[3]:
            st.metric("Over Threshold", format_number(nat['OVER_THRESHOLD']) + " sec",
                     delta=None if nat['OVER_THRESHOLD'] == 0 else "Over limit")
        with kpi_cols[4]:
            markets_below = len(market_data[market_data['AVAILABILITY_PCT'] < AVAILABILITY_GOAL])
            st.metric("Markets Below Goal", f"{markets_below} / {len(market_data)}")
    
    st.divider()
    
    # ===== ROW 2: Region Cards =====
    if not region_data.empty:
        st.markdown("### 🗺️ Regional Breakdown")
        region_cols = st.columns(len(region_data))
        for i, (_, row) in enumerate(region_data.iterrows()):
            with region_cols[i]:
                avail_pct = row['AVAILABILITY_PCT']
                status_color = "#22c55e" if avail_pct >= AVAILABILITY_GOAL else "#ef4444"
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, #1e1e2e 0%, #2d2d44 100%); padding: 15px; border-radius: 10px; border-left: 4px solid {status_color};">
                    <h4 style="margin:0; color:white;">{row['REGION_ID']}</h4>
                    <p style="margin:5px 0; font-size:1.5rem; color:{status_color}; font-weight:bold;">{avail_pct:.2f}%</p>
                    <p style="margin:2px 0; font-size:0.8rem; color:#aaa;">Downtime: {format_number(row['DOWNTIME_SECONDS'])} sec</p>
                    <p style="margin:2px 0; font-size:0.8rem; color:#aaa;">Budget: {format_number(row['SECONDS_ALLOWED'])} sec</p>
                    <p style="margin:2px 0; font-size:0.8rem; color:{'#ef4444' if row['OVER_THRESHOLD'] > 0 else '#22c55e'};">
                        Over: {format_number(row['OVER_THRESHOLD'])} sec
                    </p>
                </div>
                """, unsafe_allow_html=True)
    
    st.divider()
    
    # ===== ROW 3: Market Details Table & Downtime Bar Chart =====
    st.markdown("### 📋 Market Availability Details")
    
    table_col, chart_col = st.columns([1, 1.5])
    
    with table_col:
        # Prepare display table with rank column
        display_df = market_data[['MARKET_ID', 'REGION_ID', 'DOWNTIME_SECONDS', 'SECONDS_ALLOWED', 'OVER_THRESHOLD', 'AVAILABILITY_PCT']]
        display_df.insert(0, 'Rank', range(1, len(display_df) + 1))
        display_df['Downtime (sec)'] = display_df['DOWNTIME_SECONDS'].apply(lambda x: f"{x:,.0f}")
        display_df['Budget (sec)'] = display_df['SECONDS_ALLOWED'].apply(lambda x: f"{x:,.0f}")
        display_df['Over Threshold'] = display_df['OVER_THRESHOLD'].apply(lambda x: f"{x:,.0f}")
        display_df['Avail %'] = display_df['AVAILABILITY_PCT'].apply(lambda x: f"{x:.2f}")
        
        # Create styled dataframe - show all markets with scrolling, hide index
        st.dataframe(
            display_df[['Rank', 'MARKET_ID', 'REGION_ID', 'Downtime (sec)', 'Budget (sec)', 'Over Threshold', 'Avail %']].rename(
                columns={'MARKET_ID': 'Market', 'REGION_ID': 'Region'}
            ),
            use_container_width=True,
            height=500,
            hide_index=True
        )
    
    with chart_col:
        # Bar chart: Top markets by downtime
        st.markdown("##### Region Availability History (Top 15 Markets by Downtime)")
        top_markets = market_data.head(15).copy()
        
        # Color by region
        fig = px.bar(
            top_markets,
            x='MARKET_ID',
            y='DOWNTIME_SECONDS',
            color='REGION_ID',
            color_discrete_map=REGION_COLORS,
            text='DOWNTIME_SECONDS',
            labels={'MARKET_ID': 'Market', 'DOWNTIME_SECONDS': 'Downtime (sec)', 'REGION_ID': 'Region'}
        )
        fig.update_traces(texttemplate='%{text:,.0f}', textposition='outside', textfont_size=9)
        fig.update_layout(
            template='plotly_white',
            height=450,
            xaxis_tickangle=-45,
            showlegend=True,
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5),
            margin=dict(t=50, b=100)
        )
        st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="unavail_daily_trend")
    
    st.divider()
    
    # ===== ROW 4: Availability Reason & Daily Trend =====
    st.markdown("### 📊 Availability Analysis")
    
    reason_col, trend_col = st.columns(2)
    
    with reason_col:
        st.markdown("##### Region Availability Reason (Downtime by Focus Category)")
        if not category_data.empty:
            category_data['DOWNTIME_SECONDS'] = category_data['DOWNTIME_SECONDS'].astype(float)
            
            fig_cat = px.bar(
                category_data.head(15),
                x='FOCUS_CATEGORY',
                y='DOWNTIME_SECONDS',
                color='FOCUS_CATEGORY',
                color_discrete_map=FOCUS_CATEGORY_COLORS,
                text='DOWNTIME_SECONDS',
                labels={'FOCUS_CATEGORY': 'Impacted Category', 'DOWNTIME_SECONDS': 'Downtime (sec)'}
            )
            fig_cat.update_traces(texttemplate='%{text:,.0f}', textposition='outside', textfont_size=9)
            fig_cat.update_layout(
                template='plotly_white',
                height=400,
                xaxis_tickangle=-45,
                showlegend=False,
                margin=dict(b=120)
            )
            st.plotly_chart(fig_cat, use_container_width=True, config=CHART_CONFIG, key="unavail_cat_bar")
    
    with trend_col:
        st.markdown("##### Daily Availability Trend by Region")
        if not daily_region_data.empty:
            daily_region_data['DATE'] = pd.to_datetime(daily_region_data['DATE_VALUE']).dt.date
            daily_region_data['AVAILABILITY_PCT'] = daily_region_data['AVAILABILITY_PCT'].astype(float)
            
            fig_trend = px.line(
                daily_region_data,
                x='DATE',
                y='AVAILABILITY_PCT',
                color='REGION_ID',
                color_discrete_map=REGION_COLORS,
                markers=True,
                labels={'DATE': 'Date', 'AVAILABILITY_PCT': 'Availability %', 'REGION_ID': 'Region'}
            )
            fig_trend.add_hline(y=AVAILABILITY_GOAL, line_dash="dot", line_color="#f59e0b",
                              annotation_text=f"Goal: {AVAILABILITY_GOAL}%", annotation_position="top right")
            fig_trend.update_layout(
                template='plotly_white',
                height=500,
                font=dict(size=14),  # Base font size for fullscreen readability
                yaxis=dict(range=[min(99, daily_region_data['AVAILABILITY_PCT'].min() - 0.1), 100], tickfont=dict(size=12)),
                xaxis=dict(tickfont=dict(size=12)),
                legend=dict(orientation='h', yanchor='top', y=-0.15, xanchor='center', x=0.5, font=dict(size=12)),
                margin=dict(b=150)
            )
            fig_trend.update_xaxes(tickformat="%b %d")
            st.plotly_chart(fig_trend, use_container_width=True, config=CHART_CONFIG, key="region_daily_trend")
    
    st.divider()
    
    # ===== ROW 5: Over/Under Threshold Analysis =====
    st.markdown("### ⚠️ Threshold Analysis")
    
    thresh_col1, thresh_col2 = st.columns(2)
    
    with thresh_col1:
        st.markdown("##### Markets Over Threshold (Exceeding Budget)")
        over_threshold = market_data[market_data['OVER_THRESHOLD'] > 0]
        if not over_threshold.empty:
            over_threshold = over_threshold.sort_values('OVER_THRESHOLD', ascending=False).head(15)
            
            fig_over = px.bar(
                over_threshold,
                x='MARKET_ID',
                y='OVER_THRESHOLD',
                color='REGION_ID',
                color_discrete_map=REGION_COLORS,
                text='OVER_THRESHOLD',
                labels={'MARKET_ID': 'Market', 'OVER_THRESHOLD': 'Seconds Over Threshold', 'REGION_ID': 'Region'}
            )
            fig_over.update_traces(texttemplate='%{text:,.0f}', textposition='outside', textfont_size=9)
            fig_over.update_layout(
                template='plotly_white',
                height=350,
                xaxis_tickangle=-45,
                showlegend=True,
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5),
                margin=dict(t=50, b=80)
            )
            st.plotly_chart(fig_over, use_container_width=True, config=CHART_CONFIG, key="mkt_over_threshold")
        else:
            st.success("✅ All markets are within their downtime budget!")
    
    with thresh_col2:
        st.markdown("##### Markets Under Threshold (Buffer Remaining)")
        under_threshold = market_data[market_data['OVER_THRESHOLD'] == 0]
        if not under_threshold.empty:
            under_threshold['BUFFER'] = under_threshold['SECONDS_ALLOWED'] - under_threshold['DOWNTIME_SECONDS']
            under_threshold = under_threshold.sort_values('BUFFER', ascending=True).head(15)
            
            fig_under = px.bar(
                under_threshold,
                x='MARKET_ID',
                y='BUFFER',
                color='REGION_ID',
                color_discrete_map=REGION_COLORS,
                text='BUFFER',
                labels={'MARKET_ID': 'Market', 'BUFFER': 'Buffer Remaining (sec)', 'REGION_ID': 'Region'}
            )
            fig_under.update_traces(texttemplate='%{text:,.0f}', textposition='outside', textfont_size=9)
            fig_under.update_layout(
                template='plotly_white',
                height=350,
                xaxis_tickangle=-45,
                showlegend=True,
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5),
                margin=dict(t=50, b=80)
            )
            st.plotly_chart(fig_under, use_container_width=True, config=CHART_CONFIG, key="mkt_under_threshold")
        else:
            st.warning("All markets are over their threshold.")
    
    st.divider()
    
    # ===== ROW 6: Availability vs Downtime Scatter =====
    st.markdown("### 📈 Market Performance Overview")
    
    scatter_col1, scatter_col2 = st.columns(2)
    
    with scatter_col1:
        st.markdown("##### Downtime vs Availability % (by Market)")
        fig_scatter = px.scatter(
            market_data,
            x='DOWNTIME_SECONDS',
            y='AVAILABILITY_PCT',
            color='REGION_ID',
            color_discrete_map=REGION_COLORS,
            hover_name='MARKET_ID',
            size='OVER_THRESHOLD',
            size_max=20,
            labels={'DOWNTIME_SECONDS': 'Downtime (sec)', 'AVAILABILITY_PCT': 'Availability %', 'REGION_ID': 'Region'}
        )
        fig_scatter.add_hline(y=AVAILABILITY_GOAL, line_dash="dot", line_color="#f59e0b",
                            annotation_text=f"Goal: {AVAILABILITY_GOAL}%")
        
        # Add labels for top 5 markets by downtime
        top5_downtime = market_data.nlargest(5, 'DOWNTIME_SECONDS')
        for _, row in top5_downtime.iterrows():
            fig_scatter.add_annotation(
                x=row['DOWNTIME_SECONDS'],
                y=row['AVAILABILITY_PCT'],
                text=row['MARKET_ID'],
                showarrow=True,
                arrowhead=2,
                arrowsize=1,
                arrowwidth=1,
                ax=20,
                ay=-20,
                font=dict(size=9, color='white'),
                bgcolor='rgba(0,0,0,0.6)',
                borderpad=2
            )
        
        fig_scatter.update_layout(
            template='plotly_white',
            height=500,
            font=dict(size=14),
            xaxis=dict(tickfont=dict(size=12)),
            yaxis=dict(range=[min(98.5, market_data['AVAILABILITY_PCT'].min() - 0.2), 100], tickfont=dict(size=12)),
            legend=dict(orientation='h', yanchor='top', y=-0.15, xanchor='center', x=0.5, font=dict(size=12)),
            margin=dict(b=150)
        )
        st.plotly_chart(fig_scatter, use_container_width=True, config=CHART_CONFIG, key="region_scatter_downtime")
    
    with scatter_col2:
        st.markdown("##### Over Threshold vs Availability % (by Market)")
        # Only show markets that are over threshold
        over_data = market_data[market_data['OVER_THRESHOLD'] > 0]
        if not over_data.empty:
            fig_scatter2 = px.scatter(
                over_data,
                x='OVER_THRESHOLD',
                y='AVAILABILITY_PCT',
                color='REGION_ID',
                color_discrete_map=REGION_COLORS,
                hover_name='MARKET_ID',
                size='DOWNTIME_SECONDS',
                size_max=25,
                labels={'OVER_THRESHOLD': 'Seconds Over Threshold', 'AVAILABILITY_PCT': 'Availability %', 'REGION_ID': 'Region'}
            )
            fig_scatter2.add_hline(y=AVAILABILITY_GOAL, line_dash="dot", line_color="#f59e0b")
            
            # Add labels for top 5 markets by over threshold
            top5_over = over_data.nlargest(5, 'OVER_THRESHOLD')
            for _, row in top5_over.iterrows():
                fig_scatter2.add_annotation(
                    x=row['OVER_THRESHOLD'],
                    y=row['AVAILABILITY_PCT'],
                    text=row['MARKET_ID'],
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=1,
                    ax=20,
                    ay=-20,
                    font=dict(size=9, color='white'),
                    bgcolor='rgba(0,0,0,0.6)',
                    borderpad=2
                )
            
            fig_scatter2.update_layout(
                template='plotly_white',
                height=500,
                font=dict(size=14),
                xaxis=dict(tickfont=dict(size=12)),
                yaxis=dict(range=[min(98.5, over_data['AVAILABILITY_PCT'].min() - 0.2), AVAILABILITY_GOAL + 0.1], tickfont=dict(size=12)),
                legend=dict(orientation='h', yanchor='top', y=-0.15, xanchor='center', x=0.5, font=dict(size=12)),
                margin=dict(b=150)
            )
            st.plotly_chart(fig_scatter2, use_container_width=True, config=CHART_CONFIG, key="region_scatter_over")
        else:
            st.success("✅ No markets are over threshold!")
    
    st.divider()
    
    # ===== ROW 7: Region Comparison Heatmap =====
    st.markdown("### 🔥 Regional Performance Heatmap")
    
    # Get daily data by region
    if not daily_region_data.empty:
        pivot_data = daily_region_data.pivot(index='DATE', columns='REGION_ID', values='AVAILABILITY_PCT')
        
        fig_heatmap = go.Figure(data=go.Heatmap(
            z=pivot_data.values,
            x=pivot_data.columns,
            y=[str(d) for d in pivot_data.index],
            colorscale=[
                [0, '#ef4444'],      # Red for low
                [0.5, '#f59e0b'],    # Yellow for middle
                [1, '#22c55e']       # Green for high
            ],
            zmin=98.5,
            zmax=100,
            text=[[f"{v:.2f}%" for v in row] for row in pivot_data.values],
            texttemplate="%{text}",
            textfont={"size": 10},
            hovertemplate="Region: %{x}<br>Date: %{y}<br>Availability: %{z:.2f}%<extra></extra>"
        ))
        
        fig_heatmap.update_layout(
            template='plotly_white',
            height=300,
            xaxis_title='Region',
            yaxis_title='Date',
            margin=dict(l=80)
        )
        st.plotly_chart(fig_heatmap, use_container_width=True, config=CHART_CONFIG, key="region_heatmap")

def area_availability_summary(conn, days, filters=None):
    """Area Availability Summary - Threshold analysis and insights by MB_MKT_AREA"""
    
    AVAILABILITY_GOAL = 99.85
    
    st.markdown('<div class="section-header">🗺️ Area Availability Summary</div>', unsafe_allow_html=True)
    st.markdown(f"<span style='font-size:0.85rem;color:#888;'>*Market Availability to meet ≥ {AVAILABILITY_GOAL}% | Site Type filter applied | Grouped by MB_MKT_AREA</span>", unsafe_allow_html=True)
    
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    oem_filter = filters.get('oem') if filters else None
    site_type = filters.get('site_type') if filters else None
    site_type_filter = get_site_type_sql_filter(site_type)
    site_type_filter_a = get_site_type_sql_filter(site_type, 'a.')
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Build OEM join clause if needed
    if oem_filter:
        avail_filter_aliased = avail_filter.replace('MARKET_ID', 'a.MARKET_ID') if avail_filter else ''
        oem_join = f"JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)"
        oem_where = f"AND mt.M_OEM = '{oem_filter}'"
    else:
        avail_filter_aliased = avail_filter
        oem_join = ""
        oem_where = ""
    
    # Get market-level availability details with threshold calculations (including Area)
    if oem_filter:
        market_query = f"""
        SELECT 
            a.MARKET_ID,
            a.MB_MKT_AREA,
            a.REGION_ID,
            SUM(a.TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_N) as AVAILABILITY_NUMERATOR,
            SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
            SUM(a.TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100) as SECONDS_ALLOWED,
            GREATEST(SUM(a.TOTAL_DOWNTIME) - (SUM(a.TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100)), 0) as OVER_THRESHOLD
        FROM {TABLES['availability']} a
        {oem_join}
        WHERE {date_filter} AND {site_type_filter_a} {oem_where} {avail_filter_aliased}
        GROUP BY a.MARKET_ID, a.MB_MKT_AREA, a.REGION_ID
        ORDER BY DOWNTIME_SECONDS DESC
        """
    else:
        market_query = f"""
        SELECT 
            MARKET_ID,
            MB_MKT_AREA,
            REGION_ID,
            SUM(TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(TOTAL_AVAILABILITY_D) as TOTAL_SECONDS,
            SUM(TOTAL_AVAILABILITY_N) as AVAILABILITY_NUMERATOR,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
            SUM(TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100) as SECONDS_ALLOWED,
            GREATEST(SUM(TOTAL_DOWNTIME) - (SUM(TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100)), 0) as OVER_THRESHOLD
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY MARKET_ID, MB_MKT_AREA, REGION_ID
        ORDER BY DOWNTIME_SECONDS DESC
        """
    market_data = run_query(conn, market_query)
    
    # Normalize market names to Global Market ID format
    if not market_data.empty and 'MARKET_ID' in market_data.columns:
        market_data = normalize_market_column(market_data, 'MARKET_ID', 'availability')
    
    # Get area-level summary
    if oem_filter:
        area_query = f"""
        SELECT 
            a.MB_MKT_AREA,
            SUM(a.TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
            SUM(a.TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100) as SECONDS_ALLOWED,
            GREATEST(SUM(a.TOTAL_DOWNTIME) - (SUM(a.TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100)), 0) as OVER_THRESHOLD
        FROM {TABLES['availability']} a
        {oem_join}
        WHERE {date_filter} AND {site_type_filter_a} AND a.MB_MKT_AREA IS NOT NULL {oem_where} {avail_filter_aliased}
        GROUP BY a.MB_MKT_AREA
        ORDER BY DOWNTIME_SECONDS DESC
        """
    else:
        area_query = f"""
        SELECT 
            MB_MKT_AREA,
            SUM(TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(TOTAL_AVAILABILITY_D) as TOTAL_SECONDS,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
            SUM(TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100) as SECONDS_ALLOWED,
            GREATEST(SUM(TOTAL_DOWNTIME) - (SUM(TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100)), 0) as OVER_THRESHOLD
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} AND MB_MKT_AREA IS NOT NULL {avail_filter}
        GROUP BY MB_MKT_AREA
        ORDER BY DOWNTIME_SECONDS DESC
        """
    area_data = run_query(conn, area_query)
    
    # Get national summary
    if oem_filter:
        national_query = f"""
        SELECT 
            'National' as ENTITY,
            SUM(a.TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
            SUM(a.TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100) as SECONDS_ALLOWED,
            GREATEST(SUM(a.TOTAL_DOWNTIME) - (SUM(a.TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100)), 0) as OVER_THRESHOLD
        FROM {TABLES['availability']} a
        {oem_join}
        WHERE {date_filter} AND {site_type_filter_a} {oem_where} {avail_filter_aliased}
        """
    else:
        national_query = f"""
        SELECT 
            'National' as ENTITY,
            SUM(TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(TOTAL_AVAILABILITY_D) as TOTAL_SECONDS,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
            SUM(TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100) as SECONDS_ALLOWED,
            GREATEST(SUM(TOTAL_DOWNTIME) - (SUM(TOTAL_AVAILABILITY_D) * (1 - {AVAILABILITY_GOAL}/100)), 0) as OVER_THRESHOLD
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        """
    national_data = run_query(conn, national_query)
    
    # Get downtime by focus category
    if oem_filter:
        category_query = f"""
        SELECT 
            COALESCE(a.SITE_ID_FOCUS_CATEGORY, 'Uncategorized') as FOCUS_CATEGORY,
            SUM(a.TOTAL_DOWNTIME) as DOWNTIME_SECONDS
        FROM {TABLES['availability']} a
        {oem_join}
        WHERE {date_filter} AND {site_type_filter_a} {oem_where} {avail_filter_aliased}
        GROUP BY a.SITE_ID_FOCUS_CATEGORY
        ORDER BY DOWNTIME_SECONDS DESC
        """
    else:
        category_query = f"""
        SELECT 
            COALESCE(SITE_ID_FOCUS_CATEGORY, 'Uncategorized') as FOCUS_CATEGORY,
            SUM(TOTAL_DOWNTIME) as DOWNTIME_SECONDS
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY SITE_ID_FOCUS_CATEGORY
        ORDER BY DOWNTIME_SECONDS DESC
        """
    category_data = run_query(conn, category_query)
    
    # Get daily availability trend by area
    if oem_filter:
        daily_area_query = f"""
        SELECT 
            a.DATE_VALUE,
            a.MB_MKT_AREA,
            SUM(a.TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT
        FROM {TABLES['availability']} a
        {oem_join}
        WHERE {date_filter} AND {site_type_filter_a} AND a.MB_MKT_AREA IS NOT NULL {oem_where} {avail_filter_aliased}
        GROUP BY a.DATE_VALUE, a.MB_MKT_AREA
        ORDER BY a.DATE_VALUE, a.MB_MKT_AREA
        """
    else:
        daily_area_query = f"""
        SELECT 
            DATE_VALUE,
            MB_MKT_AREA,
            SUM(TOTAL_DOWNTIME) as DOWNTIME_SECONDS,
            SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} AND MB_MKT_AREA IS NOT NULL {avail_filter}
        GROUP BY DATE_VALUE, MB_MKT_AREA
        ORDER BY DATE_VALUE, MB_MKT_AREA
        """
    daily_area_data = run_query(conn, daily_area_query)
    
    if market_data.empty:
        st.info("No availability data available for the selected filters.")
        return
    
    # Convert to float
    for col in ['DOWNTIME_SECONDS', 'TOTAL_SECONDS', 'AVAILABILITY_PCT', 'SECONDS_ALLOWED', 'OVER_THRESHOLD']:
        if col in market_data.columns:
            market_data[col] = market_data[col].astype(float)
        if col in area_data.columns:
            area_data[col] = area_data[col].astype(float)
        if col in national_data.columns:
            national_data[col] = national_data[col].astype(float)
    
    # Area colors
    AREA_COLORS = {
        'AREA 1': '#e20074',
        'AREA 2': '#b30059',
        'AREA 3': '#ff4d94',
        'AREA 4': '#4a0e4e',
        'AREA 5': '#8b4a72',
        'AREA 6': '#666666',
        'AREA 7': '#888888',
        'AREA 8': '#333333',
    }
    DEFAULT_AREA_COLOR = "#6b7280"
    
    # ===== ROW 1: National & Area KPIs =====
    st.markdown("### 📊 National & Area Summary")
    
    if not national_data.empty:
        nat = national_data.iloc[0]
        nat_avail = nat['AVAILABILITY_PCT']
        
        kpi_cols = st.columns(5)
        with kpi_cols[0]:
            st.metric("National Availability", f"{nat_avail:.2f}%", 
                     delta=f"{nat_avail - AVAILABILITY_GOAL:.2f}%" if nat_avail >= AVAILABILITY_GOAL else f"{nat_avail - AVAILABILITY_GOAL:.2f}%")
        with kpi_cols[1]:
            st.metric("Total Downtime", format_number(nat['DOWNTIME_SECONDS']) + " sec")
        with kpi_cols[2]:
            st.metric("Seconds Budget", format_number(nat['SECONDS_ALLOWED']) + " sec")
        with kpi_cols[3]:
            st.metric("Over Threshold", format_number(nat['OVER_THRESHOLD']) + " sec",
                     delta=None if nat['OVER_THRESHOLD'] == 0 else "Over limit")
        with kpi_cols[4]:
            markets_below = len(market_data[market_data['AVAILABILITY_PCT'] < AVAILABILITY_GOAL])
            st.metric("Markets Below Goal", f"{markets_below} / {len(market_data)}")
    
    st.divider()
    
    # ===== ROW 2: Area Cards =====
    if not area_data.empty:
        st.markdown("### 🗺️ Area Breakdown")
        
        # Display areas in rows of 4
        num_areas = len(area_data)
        for row_start in range(0, num_areas, 4):
            row_areas = area_data.iloc[row_start:row_start+4]
            area_cols = st.columns(len(row_areas))
            for i, (_, row) in enumerate(row_areas.iterrows()):
                with area_cols[i]:
                    avail_pct = row['AVAILABILITY_PCT']
                    area_name = row['MB_MKT_AREA'] if pd.notna(row['MB_MKT_AREA']) else 'Unknown'
                    status_color = "#22c55e" if avail_pct >= AVAILABILITY_GOAL else "#ef4444"
                    st.markdown(f"""
                    <div style="background: linear-gradient(135deg, #1e1e2e 0%, #2d2d44 100%); padding: 15px; border-radius: 10px; border-left: 4px solid {status_color};">
                        <h4 style="margin:0; color:white; font-size:0.95rem;">{area_name}</h4>
                        <p style="margin:5px 0; font-size:1.3rem; color:{status_color}; font-weight:bold;">{avail_pct:.2f}%</p>
                        <p style="margin:2px 0; font-size:0.75rem; color:#aaa;">Downtime: {format_number(row['DOWNTIME_SECONDS'])} sec</p>
                        <p style="margin:2px 0; font-size:0.75rem; color:#aaa;">Budget: {format_number(row['SECONDS_ALLOWED'])} sec</p>
                        <p style="margin:2px 0; font-size:0.75rem; color:{'#ef4444' if row['OVER_THRESHOLD'] > 0 else '#22c55e'};">
                            Over: {format_number(row['OVER_THRESHOLD'])} sec
                        </p>
                    </div>
                    """, unsafe_allow_html=True)
    
    st.divider()
    
    # ===== ROW 3: Market Details Table & Downtime Bar Chart =====
    st.markdown("### 📋 Market Availability by Area")
    
    table_col, chart_col = st.columns([1, 1.5])
    
    with table_col:
        # Prepare display table with rank column
        display_df = market_data[['MARKET_ID', 'MB_MKT_AREA', 'REGION_ID', 'DOWNTIME_SECONDS', 'SECONDS_ALLOWED', 'OVER_THRESHOLD', 'AVAILABILITY_PCT']]
        display_df.insert(0, 'Rank', range(1, len(display_df) + 1))
        display_df['Downtime (sec)'] = display_df['DOWNTIME_SECONDS'].apply(lambda x: f"{x:,.0f}")
        display_df['Budget (sec)'] = display_df['SECONDS_ALLOWED'].apply(lambda x: f"{x:,.0f}")
        display_df['Over Threshold'] = display_df['OVER_THRESHOLD'].apply(lambda x: f"{x:,.0f}")
        display_df['Avail %'] = display_df['AVAILABILITY_PCT'].apply(lambda x: f"{x:.2f}")
        
        st.dataframe(
            display_df[['Rank', 'MARKET_ID', 'MB_MKT_AREA', 'Downtime (sec)', 'Budget (sec)', 'Over Threshold', 'Avail %']].rename(
                columns={'MARKET_ID': 'Market', 'MB_MKT_AREA': 'Area'}
            ),
            use_container_width=True,
            height=500
        )
    
    with chart_col:
        st.markdown("##### Top 15 Markets by Downtime (by Area)")
        top_markets = market_data.head(15).copy()
        
        fig = px.bar(
            top_markets,
            x='MARKET_ID',
            y='DOWNTIME_SECONDS',
            color='MB_MKT_AREA',
            text='DOWNTIME_SECONDS',
            labels={'MARKET_ID': 'Market', 'DOWNTIME_SECONDS': 'Downtime (sec)', 'MB_MKT_AREA': 'Area'}
        )
        fig.update_traces(texttemplate='%{text:,.0f}', textposition='outside', textfont_size=9)
        fig.update_layout(
            template='plotly_white',
            height=450,
            xaxis_tickangle=-45,
            showlegend=True,
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5),
            margin=dict(t=50, b=100)
        )
        st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="area_top_markets_bar")
    
    st.divider()
    
    # ===== ROW 4: Availability Reason & Daily Trend =====
    st.markdown("### 📊 Area Availability Analysis")
    
    reason_col, trend_col = st.columns(2)
    
    with reason_col:
        st.markdown("##### Downtime by Focus Category")
        if not category_data.empty:
            category_data['DOWNTIME_SECONDS'] = category_data['DOWNTIME_SECONDS'].astype(float)
            
            fig_cat = px.bar(
                category_data.head(15),
                x='FOCUS_CATEGORY',
                y='DOWNTIME_SECONDS',
                color='FOCUS_CATEGORY',
                color_discrete_map=FOCUS_CATEGORY_COLORS,
                text='DOWNTIME_SECONDS',
                labels={'FOCUS_CATEGORY': 'Impacted Category', 'DOWNTIME_SECONDS': 'Downtime (sec)'}
            )
            fig_cat.update_traces(texttemplate='%{text:,.0f}', textposition='outside', textfont_size=9)
            fig_cat.update_layout(
                template='plotly_white',
                height=400,
                xaxis_tickangle=-45,
                showlegend=False,
                margin=dict(b=120)
            )
            st.plotly_chart(fig_cat, use_container_width=True, config=CHART_CONFIG, key="area_category_bar")
    
    with trend_col:
        st.markdown("##### Daily Availability Trend by Area")
        if not daily_area_data.empty:
            daily_area_data['DATE'] = pd.to_datetime(daily_area_data['DATE_VALUE']).dt.date
            daily_area_data['AVAILABILITY_PCT'] = daily_area_data['AVAILABILITY_PCT'].astype(float)
            
            fig_trend = px.line(
                daily_area_data,
                x='DATE',
                y='AVAILABILITY_PCT',
                color='MB_MKT_AREA',
                markers=True,
                labels={'DATE': 'Date', 'AVAILABILITY_PCT': 'Availability %', 'MB_MKT_AREA': 'Area'}
            )
            fig_trend.add_hline(y=AVAILABILITY_GOAL, line_dash="dot", line_color="#f59e0b",
                              annotation_text=f"Goal: {AVAILABILITY_GOAL}%", annotation_position="top right")
            fig_trend.update_layout(
                template='plotly_white',
                height=500,
                font=dict(size=14),  # Base font size for fullscreen readability
                yaxis=dict(range=[min(99, daily_area_data['AVAILABILITY_PCT'].min() - 0.1), 100], tickfont=dict(size=12)),
                xaxis=dict(tickfont=dict(size=12)),
                legend=dict(orientation='h', yanchor='top', y=-0.15, xanchor='center', x=0.5, font=dict(size=12)),
                margin=dict(b=150)
            )
            fig_trend.update_xaxes(tickformat="%b %d")
            st.plotly_chart(fig_trend, use_container_width=True, config=CHART_CONFIG, key="area_daily_trend")
    
    st.divider()
    
    # ===== ROW 5: Over/Under Threshold Analysis =====
    st.markdown("### ⚠️ Threshold Analysis by Area")
    
    thresh_col1, thresh_col2 = st.columns(2)
    
    with thresh_col1:
        st.markdown("##### Markets Over Threshold (by Area)")
        over_threshold = market_data[market_data['OVER_THRESHOLD'] > 0]
        if not over_threshold.empty:
            over_threshold = over_threshold.sort_values('OVER_THRESHOLD', ascending=False).head(15)
            
            fig_over = px.bar(
                over_threshold,
                x='MARKET_ID',
                y='OVER_THRESHOLD',
                color='MB_MKT_AREA',
                text='OVER_THRESHOLD',
                labels={'MARKET_ID': 'Market', 'OVER_THRESHOLD': 'Seconds Over Threshold', 'MB_MKT_AREA': 'Area'}
            )
            fig_over.update_traces(texttemplate='%{text:,.0f}', textposition='outside', textfont_size=9)
            fig_over.update_layout(
                template='plotly_white',
                height=350,
                xaxis_tickangle=-45,
                showlegend=True,
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5),
                margin=dict(t=50, b=80)
            )
            st.plotly_chart(fig_over, use_container_width=True, config=CHART_CONFIG, key="area_over_threshold")
        else:
            st.success("✅ All markets are within their downtime budget!")
    
    with thresh_col2:
        st.markdown("##### Markets Under Threshold (Buffer by Area)")
        under_threshold = market_data[market_data['OVER_THRESHOLD'] == 0]
        if not under_threshold.empty:
            under_threshold['BUFFER'] = under_threshold['SECONDS_ALLOWED'] - under_threshold['DOWNTIME_SECONDS']
            under_threshold = under_threshold.sort_values('BUFFER', ascending=True).head(15)
            
            fig_under = px.bar(
                under_threshold,
                x='MARKET_ID',
                y='BUFFER',
                color='MB_MKT_AREA',
                text='BUFFER',
                labels={'MARKET_ID': 'Market', 'BUFFER': 'Buffer Remaining (sec)', 'MB_MKT_AREA': 'Area'}
            )
            fig_under.update_traces(texttemplate='%{text:,.0f}', textposition='outside', textfont_size=9)
            fig_under.update_layout(
                template='plotly_white',
                height=350,
                xaxis_tickangle=-45,
                showlegend=True,
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5),
                margin=dict(t=50, b=80)
            )
            st.plotly_chart(fig_under, use_container_width=True, config=CHART_CONFIG, key="area_under_threshold")
        else:
            st.warning("All markets are over their threshold.")
    
    st.divider()
    
    # ===== ROW 6: Scatter Plots =====
    st.markdown("### 📈 Market Performance by Area")
    
    scatter_col1, scatter_col2 = st.columns(2)
    
    with scatter_col1:
        st.markdown("##### Downtime vs Availability % (by Area)")
        # Fill NaN values in size column to avoid Plotly errors
        scatter_data = market_data.copy()
        if 'OVER_THRESHOLD' in scatter_data.columns:
            scatter_data['OVER_THRESHOLD'] = scatter_data['OVER_THRESHOLD'].fillna(0)
        fig_scatter = px.scatter(
            scatter_data,
            x='DOWNTIME_SECONDS',
            y='AVAILABILITY_PCT',
            color='MB_MKT_AREA',
            hover_name='MARKET_ID',
            size='OVER_THRESHOLD',
            size_max=20,
            labels={'DOWNTIME_SECONDS': 'Downtime (sec)', 'AVAILABILITY_PCT': 'Availability %', 'MB_MKT_AREA': 'Area'}
        )
        fig_scatter.add_hline(y=AVAILABILITY_GOAL, line_dash="dot", line_color="#f59e0b",
                            annotation_text=f"Goal: {AVAILABILITY_GOAL}%")
        fig_scatter.update_layout(
            template='plotly_white',
            height=400,
            font=dict(size=14),
            xaxis=dict(tickfont=dict(size=12)),
            yaxis=dict(range=[min(98.5, scatter_data['AVAILABILITY_PCT'].min() - 0.2), 100], tickfont=dict(size=12)),
            legend=dict(orientation='h', yanchor='top', y=-0.15, xanchor='center', x=0.5, font=dict(size=12)),
            margin=dict(b=150)
        )
        st.plotly_chart(fig_scatter, use_container_width=True, config=CHART_CONFIG, key="area_scatter_downtime")
    
    with scatter_col2:
        st.markdown("##### Over Threshold vs Availability % (by Area)")
        over_data = market_data[market_data['OVER_THRESHOLD'] > 0]
        if not over_data.empty:
            fig_scatter2 = px.scatter(
                over_data,
                x='OVER_THRESHOLD',
                y='AVAILABILITY_PCT',
                color='MB_MKT_AREA',
                hover_name='MARKET_ID',
                size='DOWNTIME_SECONDS',
                size_max=25,
                labels={'OVER_THRESHOLD': 'Seconds Over Threshold', 'AVAILABILITY_PCT': 'Availability %', 'MB_MKT_AREA': 'Area'}
            )
            fig_scatter2.add_hline(y=AVAILABILITY_GOAL, line_dash="dot", line_color="#f59e0b")
            fig_scatter2.update_layout(
                template='plotly_white',
                height=400,
                font=dict(size=14),
                xaxis=dict(tickfont=dict(size=12)),
                yaxis=dict(range=[min(98.5, over_data['AVAILABILITY_PCT'].min() - 0.2), AVAILABILITY_GOAL + 0.1], tickfont=dict(size=12)),
                legend=dict(orientation='h', yanchor='top', y=-0.15, xanchor='center', x=0.5, font=dict(size=12)),
                margin=dict(b=150)
            )
            st.plotly_chart(fig_scatter2, use_container_width=True, config=CHART_CONFIG, key="area_scatter_over")
        else:
            st.success("✅ No markets are over threshold!")
    
    st.divider()
    
    # ===== ROW 7: Area Performance Heatmap =====
    st.markdown("### 🔥 Area Performance Heatmap")
    
    if not daily_area_data.empty:
        pivot_data = daily_area_data.pivot(index='DATE', columns='MB_MKT_AREA', values='AVAILABILITY_PCT')
        
        fig_heatmap = go.Figure(data=go.Heatmap(
            z=pivot_data.values,
            x=pivot_data.columns,
            y=[str(d) for d in pivot_data.index],
            colorscale=[
                [0, '#ef4444'],
                [0.5, '#f59e0b'],
                [1, '#22c55e']
            ],
            zmin=98.5,
            zmax=100,
            text=[[f"{v:.2f}%" if pd.notna(v) else "" for v in row] for row in pivot_data.values],
            texttemplate="%{text}",
            textfont={"size": 9},
            hovertemplate="Area: %{x}<br>Date: %{y}<br>Availability: %{z:.2f}%<extra></extra>"
        ))
        
        fig_heatmap.update_layout(
            template='plotly_white',
            height=350,
            xaxis_title='Area',
            yaxis_title='Date',
            margin=dict(l=80),
            xaxis_tickangle=-45
        )
        st.plotly_chart(fig_heatmap, use_container_width=True, config=CHART_CONFIG, key="area_heatmap")
    
    st.divider()
    
    # ===== ROW 8: Area Summary Table =====
    st.markdown("### 📊 Area Summary Statistics")
    
    if not area_data.empty:
        area_summary = area_data.copy()
        area_summary['Status'] = area_summary['AVAILABILITY_PCT'].apply(lambda x: '✅ Meeting Goal' if x >= AVAILABILITY_GOAL else '❌ Below Goal')
        area_summary['Avail %'] = area_summary['AVAILABILITY_PCT'].apply(lambda x: f"{x:.3f}%")
        area_summary['Downtime'] = area_summary['DOWNTIME_SECONDS'].apply(lambda x: format_number(x) + " sec")
        area_summary['Budget'] = area_summary['SECONDS_ALLOWED'].apply(lambda x: format_number(x) + " sec")
        area_summary['Over/Under'] = area_summary['OVER_THRESHOLD'].apply(lambda x: f"+{format_number(x)} sec" if x > 0 else "Within limit")
        
        # Count markets per area
        markets_per_area = market_data.groupby('MB_MKT_AREA').size().reset_index(name='Market Count')
        markets_below_per_area = market_data[market_data['AVAILABILITY_PCT'] < AVAILABILITY_GOAL].groupby('MB_MKT_AREA').size().reset_index(name='Below Goal')
        
        area_summary = area_summary.merge(markets_per_area, on='MB_MKT_AREA', how='left')
        area_summary = area_summary.merge(markets_below_per_area, on='MB_MKT_AREA', how='left')
        area_summary['Below Goal'] = area_summary['Below Goal'].fillna(0).astype(int)
        
        display_cols = ['MB_MKT_AREA', 'Avail %', 'Downtime', 'Budget', 'Over/Under', 'Market Count', 'Below Goal', 'Status']
        st.dataframe(
            area_summary[display_cols].rename(columns={'MB_MKT_AREA': 'Area'}),
            use_container_width=True,
            hide_index=True
        )

def detailed_availability_dashboard(conn, days, filters=None):
    """Detailed availability analysis"""
    st.markdown(f'<div class="section-header">📈 Detailed Availability Analysis</div>', unsafe_allow_html=True)
    
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    site_type_filter = get_site_type_sql_filter(site_type)
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    query = f"""
    SELECT DATE_VALUE, MARKET_ID, REGION_ID, VENDOR, SITE_ID, SITE_ID_FOCUS_CATEGORY, OUTAGE_TYPE,
           TOTAL_DOWNTIME, CASE WHEN TOTAL_AVAILABILITY_D > 0 THEN (TOTAL_AVAILABILITY_N / TOTAL_AVAILABILITY_D) * 100 ELSE 100 END as AVAILABILITY_PCT
    FROM {TABLES['availability']}
    WHERE {date_filter} AND {site_type_filter} {avail_filter}
    ORDER BY DATE_VALUE DESC LIMIT 1000
    """
    
    with st.spinner("Loading availability data..."):
        df = run_query(conn, query)
    
    if df.empty:
        st.warning("No data available.")
        return
    
    # Normalize market names to Global Market ID format
    if 'MARKET_ID' in df.columns:
        df = normalize_market_column(df, 'MARKET_ID', 'availability')
    
    col1, col2 = st.columns(2)
    with col1:
        vendor_data = df.groupby('VENDOR')['TOTAL_DOWNTIME'].sum().reset_index()
        fig = px.pie(vendor_data, values='TOTAL_DOWNTIME', names='VENDOR', title='Downtime by Vendor',
                    color_discrete_sequence=px.colors.sequential.Magenta)
        fig.update_layout(template='plotly_white', height=350)
        st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="detail_vendor_pie")
    
    with col2:
        region_data = df.groupby('REGION_ID')['TOTAL_DOWNTIME'].sum().reset_index().nlargest(10, 'TOTAL_DOWNTIME')
        fig = px.bar(region_data, x='REGION_ID', y='TOTAL_DOWNTIME', title='Downtime by Region',
                    color_discrete_sequence=['#a33c6e'])
        fig.update_layout(template='plotly_white', height=350)
        st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="detail_region_bar")
    
    with st.expander("📋 View Raw Data"):
        st.dataframe(df, use_container_width=True, height=400)

def detailed_cottr_dashboard(conn, days, filters=None):
    """Detailed COTTR analysis"""
    st.markdown(f'<div class="section-header">🚨 Detailed COTTR Analysis</div>', unsafe_allow_html=True)
    
    cottr_filter = build_filter_clause(filters, 'cottr')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    date_filter = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    query = f"""
    SELECT PER_DAY_LOCAL_DATE, MKT_NAME, SITE_CD, SECTOR_TYPE_CATEGORY, OUTAGE_TYPE, SITE_ID_FOCUS_CATEGORY,
           SUM(PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINUTES, COUNT(*) as OUTAGE_COUNT
    FROM {TABLES['cottr']}
    WHERE {date_filter} AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'  {cottr_filter}
    GROUP BY PER_DAY_LOCAL_DATE, MKT_NAME, SITE_CD, SECTOR_TYPE_CATEGORY, OUTAGE_TYPE, SITE_ID_FOCUS_CATEGORY
    ORDER BY PER_DAY_LOCAL_DATE DESC LIMIT 1000
    """
    
    with st.spinner("Loading COTTR data..."):
        df = run_query(conn, query)
    
    if df.empty:
        st.warning("No data available.")
        return
    
    # Normalize market names to Global Market ID format
    if 'MKT_NAME' in df.columns:
        df = normalize_market_column(df, 'MKT_NAME', 'cottr')
    
    col1, col2 = st.columns(2)
    with col1:
        cat_data = df.groupby('SITE_ID_FOCUS_CATEGORY')['TOTAL_OUTAGE_MINUTES'].sum().reset_index()
        fig = px.pie(cat_data, values='TOTAL_OUTAGE_MINUTES', names='SITE_ID_FOCUS_CATEGORY', title='Service Outage Minutes by Category',
                    color_discrete_sequence=px.colors.sequential.Magenta)
        fig.update_layout(template='plotly_white', height=350)
        st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="cottr_cat_pie")
    
    with col2:
        mkt_data = df.groupby('MKT_NAME')['OUTAGE_COUNT'].sum().reset_index().nlargest(10, 'OUTAGE_COUNT')
        fig = px.bar(mkt_data, x='MKT_NAME', y='OUTAGE_COUNT', title='Outages by Market',
                    color_discrete_sequence=['#8b4a72'])
        fig.update_layout(template='plotly_white', height=350, xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="cottr_mkt_bar")
    
    with st.expander("📋 View Raw Data"):
        st.dataframe(df, use_container_width=True, height=400)

def detailed_customer_minutes_dashboard(conn, days, filters=None):
    """Detailed customer minutes analysis"""
    st.markdown(f'<div class="section-header">📱 Detailed Customer Minutes Analysis</div>', unsafe_allow_html=True)
    
    cm_filter = build_filter_clause(filters, 'customer_minutes')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    site_type = filters.get('site_type') if filters else None
    date_filter = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    if site_type:
        cm_filter_aliased = cm_filter.replace('SITE_ID', 'cm.SITE_ID').replace('MARKET', 'cm.MARKET')
        query = f"""
        SELECT cm.LOCAL_DATE_PART, cm.MARKET, cm.SITE_ID, cm.OEM, cm.TECHNOLOGY,
               SUM(cm.IMPACT_DURATION_IN_MINS) as TOTAL_CUSTOMER_MINUTES, SUM(cm.TOTAL_IMPACTED_SUB_CNT) as TOTAL_IMPACTED_SUBS
        FROM {TABLES['customer_minutes']} cm
        INNER JOIN (
            SELECT DISTINCT SITE_ID FROM {TABLES['availability']} 
            WHERE {date_filter_avail} AND {get_site_type_sql_filter(site_type)}
        ) st ON cm.SITE_ID = st.SITE_ID
        WHERE {date_filter.replace('LOCAL_START_TIMESTAMP', 'cm.LOCAL_START_TIMESTAMP')} {cm_filter_aliased}
        GROUP BY cm.LOCAL_DATE_PART, cm.MARKET, cm.SITE_ID, cm.OEM, cm.TECHNOLOGY
        ORDER BY cm.LOCAL_DATE_PART DESC LIMIT 1000
        """
    else:
        query = f"""
        SELECT LOCAL_DATE_PART, MARKET, SITE_ID, OEM, TECHNOLOGY,
               SUM(IMPACT_DURATION_IN_MINS) as TOTAL_CUSTOMER_MINUTES, SUM(TOTAL_IMPACTED_SUB_CNT) as TOTAL_IMPACTED_SUBS
        FROM {TABLES['customer_minutes']}
        WHERE {date_filter} {cm_filter}
        GROUP BY LOCAL_DATE_PART, MARKET, SITE_ID, OEM, TECHNOLOGY
        ORDER BY LOCAL_DATE_PART DESC LIMIT 1000
        """
    
    with st.spinner("Loading customer minutes data..."):
        df = run_query(conn, query)
    
    if df.empty:
        st.warning("No data available.")
        return
    
    # Normalize market names to Global Market ID format
    if 'MARKET' in df.columns:
        df = normalize_market_column(df, 'MARKET', 'customer_minutes')
    
    col1, col2 = st.columns(2)
    with col1:
        oem_data = df.groupby('OEM')['TOTAL_CUSTOMER_MINUTES'].sum().reset_index()
        fig = px.pie(oem_data, values='TOTAL_CUSTOMER_MINUTES', names='OEM', title='Customer Minutes by OEM',
                    color_discrete_sequence=px.colors.sequential.Magenta)
        fig.update_layout(template='plotly_white', height=350)
        st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="cm_oem_pie")
    
    with col2:
        tech_data = df.groupby('TECHNOLOGY')['TOTAL_CUSTOMER_MINUTES'].sum().reset_index()
        fig = px.bar(tech_data, x='TECHNOLOGY', y='TOTAL_CUSTOMER_MINUTES', title='Customer Minutes by Technology',
                    color_discrete_sequence=['#a33c6e'])
        fig.update_layout(template='plotly_white', height=350)
        st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="cm_tech_bar")
    
    with st.expander("📋 View Raw Data"):
        st.dataframe(df, use_container_width=True, height=400)

def dashboard_views_dashboard(conn, days, filters=None):
    """Dashboard Views - 4 alternative views of Executive Summary data"""
    
    market = get_market_display_name(filters.get('market') if filters else None)
    header_text = f"📊 Dashboard Views - {market}" if market else "📊 Dashboard Views - All Markets"
    st.markdown(f'<div class="section-header">{header_text}</div>', unsafe_allow_html=True)
    
    # Fetch all data (same as executive summary)
    with st.spinner("Loading data..."):
        cm_daily, avail_daily, cottr_daily = get_combined_daily_data(conn, days, filters)
        market_totals = get_market_totals(conn, days, filters)
        focus_cat_totals = get_focus_category_totals(conn, days, filters)
        focus_cottr_totals = get_focus_category_totals_cottr(conn, days, filters)
        market_by_summary_cat = get_market_by_summary_category(conn, days, filters)
        cottr_by_summary = get_cottr_by_summary_category(conn, days, filters)
    
    # Normalize market names to Global Market ID format for display
    if not market_totals.empty and 'MARKET_ID' in market_totals.columns:
        market_totals = normalize_market_column(market_totals, 'MARKET_ID', 'availability')
    if not market_by_summary_cat.empty and 'MARKET_ID' in market_by_summary_cat.columns:
        market_by_summary_cat = normalize_market_column(market_by_summary_cat, 'MARKET_ID', 'availability')
    
    # Calculate KPI values
    total_cm = float(cm_daily['CUSTOMER_MINUTES'].sum()) if not cm_daily.empty else 0
    total_subs = float(cm_daily['IMPACTED_SUBS'].sum()) if not cm_daily.empty else 0
    
    if not avail_daily.empty and 'TOTAL_AVAILABILITY_N' in avail_daily.columns and 'TOTAL_AVAILABILITY_D' in avail_daily.columns:
        total_n = float(avail_daily['TOTAL_AVAILABILITY_N'].sum())
        total_d = float(avail_daily['TOTAL_AVAILABILITY_D'].sum())
        avg_avail = (total_n / total_d * 100) if total_d > 0 else 0
    else:
        avg_avail = float(avail_daily['AVG_AVAILABILITY_PCT'].mean()) if not avail_daily.empty else 0
    
    total_downtime = float(avail_daily['TOTAL_DOWNTIME'].sum()) if not avail_daily.empty else 0
    total_outages = float(cottr_daily['OUTAGE_COUNT'].sum()) if not cottr_daily.empty else 0
    total_outage_mins = float(cottr_daily['OUTAGE_MINUTES'].sum()) if not cottr_daily.empty else 0
    
    # Calculate days meeting goal
    days_meeting_goal = 0
    total_days = 0
    if not avail_daily.empty:
        total_days = len(avail_daily)
        days_meeting_goal = (avail_daily['AVG_AVAILABILITY_PCT'] >= 99.85).sum()
    
    # ========================================
    # VIEW 1: SCORECARD VIEW
    # ========================================
    st.markdown("### 🎯 View 1: Scorecard View")
    st.markdown("<span style='font-size:0.85rem;color:#888;'>At-a-glance health indicators with goal comparisons</span>", unsafe_allow_html=True)
    
    # Large scorecard tiles in a 3-column layout
    score_col1, score_col2, score_col3 = st.columns(3)
    
    with score_col1:
        # Availability Scorecard
        avail_status = "🟢" if avg_avail >= 99.85 else "🟡" if avg_avail >= 99.5 else "🔴"
        avail_color = "#22c55e" if avg_avail >= 99.85 else "#f59e0b" if avg_avail >= 99.5 else "#ef4444"
        goal_diff = avg_avail - 99.85
        goal_text = f"+{goal_diff:.3f}%" if goal_diff >= 0 else f"{goal_diff:.3f}%"
        
        st.markdown(f"""
        <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:12px;padding:20px;border-left:5px solid {avail_color};">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-size:1.2rem;color:#888;">Availability</span>
                <span style="font-size:2rem;">{avail_status}</span>
            </div>
            <div style="font-size:2.5rem;font-weight:bold;color:{avail_color};margin:10px 0;">{avg_avail:.3f}%</div>
            <div style="display:flex;justify-content:space-between;font-size:0.9rem;">
                <span style="color:#888;">Goal: 99.85%</span>
                <span style="color:{avail_color};font-weight:600;">{goal_text}</span>
            </div>
            <div style="margin-top:10px;font-size:0.85rem;color:#888;">
                Days ≥ Goal: <b style="color:{avail_color};">{days_meeting_goal}/{total_days}</b>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with score_col2:
        # COTTR Scorecard
        cottr_status = "🟢" if total_outage_mins < 100000 else "🟡" if total_outage_mins < 500000 else "🔴"
        cottr_color = "#22c55e" if total_outage_mins < 100000 else "#f59e0b" if total_outage_mins < 500000 else "#ef4444"
        
        st.markdown(f"""
        <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:12px;padding:20px;border-left:5px solid {cottr_color};">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-size:1.2rem;color:#888;">COTTR Outages</span>
                <span style="font-size:2rem;">{cottr_status}</span>
            </div>
            <div style="font-size:2.5rem;font-weight:bold;color:#f59e0b;margin:10px 0;">{format_number(total_outages)}</div>
            <div style="display:flex;justify-content:space-between;font-size:0.9rem;">
                <span style="color:#888;">Service Outage Events</span>
                <span style="color:#f59e0b;font-weight:600;">{format_number(total_outage_mins)} mins</span>
            </div>
            <div style="margin-top:10px;font-size:0.85rem;color:#888;">
                Downtime: <b style="color:#22c55e;">{format_number(total_downtime)} sec</b>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with score_col3:
        # Customer Impact Scorecard
        impact_status = "🟢" if total_subs < 1000000 else "🟡" if total_subs < 5000000 else "🔴"
        impact_color = "#22c55e" if total_subs < 1000000 else "#f59e0b" if total_subs < 5000000 else "#ef4444"
        
        st.markdown(f"""
        <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:12px;padding:20px;border-left:5px solid #e20074;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-size:1.2rem;color:#888;">Customer Impact</span>
                <span style="font-size:2rem;">{impact_status}</span>
            </div>
            <div style="font-size:2.5rem;font-weight:bold;color:#e20074;margin:10px 0;">{format_number(total_subs)}</div>
            <div style="display:flex;justify-content:space-between;font-size:0.9rem;">
                <span style="color:#888;">Impacted Subscribers</span>
                <span style="color:#e20074;font-weight:600;">{format_number(total_cm)} mins</span>
            </div>
            <div style="margin-top:10px;font-size:0.85rem;color:#888;">
                Customer Minutes
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # ========================================
    # VIEW 2: COMPARISON VIEW
    # ========================================
    st.markdown("### ⚖️ View 2: Availability vs COTTR Comparison")
    st.markdown("<span style='font-size:0.85rem;color:#888;'>Side-by-side analysis of Availability and COTTR metrics</span>", unsafe_allow_html=True)
    
    comp_col1, comp_col2 = st.columns(2)
    
    with comp_col1:
        st.markdown("#### 📉 Availability Breakdown")
        
        # Summary category breakdown for Availability
        if not market_by_summary_cat.empty:
            summary_totals = market_by_summary_cat.groupby('SITE_ID_SUMMARY_CATEGORY')['TOTAL_DOWNTIME'].sum().reset_index()
            summary_totals = summary_totals.sort_values('TOTAL_DOWNTIME', ascending=True)
            
            fig = go.Figure()
            for _, row in summary_totals.iterrows():
                cat = row['SITE_ID_SUMMARY_CATEGORY']
                color = SUMMARY_CATEGORY_COLORS.get(cat, '#888888')
                fig.add_trace(go.Bar(
                    y=[cat],
                    x=[row['TOTAL_DOWNTIME']],
                    orientation='h',
                    name=cat,
                    marker_color=color,
                    text=[format_number(row['TOTAL_DOWNTIME']) + 's'],
                    textposition='auto',
                ))
            
            fig.update_layout(
                template='plotly_white',
                height=200,
                showlegend=False,
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis_title="Downtime (seconds)",
                barmode='stack'
            )
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="comp_avail_bar")
        
        # Metrics
        st.markdown(f"""
        <div style="background:#f8f9fa;border-radius:8px;padding:15px;margin-top:10px;">
            <div style="display:flex;justify-content:space-between;margin-bottom:10px;">
                <span style="color:#888;">Total Downtime</span>
                <span style="color:#22c55e;font-weight:600;">{format_number(total_downtime)} sec</span>
            </div>
            <div style="display:flex;justify-content:space-between;">
                <span style="color:#888;">Availability %</span>
                <span style="color:#22c55e;font-weight:600;">{avg_avail:.3f}%</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with comp_col2:
        st.markdown("#### 🚨 COTTR Breakdown")
        
        # Summary category breakdown for COTTR
        if not cottr_by_summary.empty:
            cottr_summary = cottr_by_summary.groupby('SITE_ID_SUMMARY_CATEGORY')['OUTAGE_MINUTES'].sum().reset_index()
            cottr_summary = cottr_summary.sort_values('OUTAGE_MINUTES', ascending=True)
            
            fig = go.Figure()
            for _, row in cottr_summary.iterrows():
                cat = row['SITE_ID_SUMMARY_CATEGORY']
                color = SUMMARY_CATEGORY_COLORS.get(cat, '#888888')
                fig.add_trace(go.Bar(
                    y=[cat],
                    x=[row['OUTAGE_MINUTES']],
                    orientation='h',
                    name=cat,
                    marker_color=color,
                    text=[format_number(row['OUTAGE_MINUTES']) + ' mins'],
                    textposition='auto',
                ))
            
            fig.update_layout(
                template='plotly_white',
                height=200,
                showlegend=False,
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis_title="Service Outage Minutes",
                barmode='stack'
            )
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="comp_cottr_bar")
        
        # Metrics
        st.markdown(f"""
        <div style="background:#f8f9fa;border-radius:8px;padding:15px;margin-top:10px;">
            <div style="display:flex;justify-content:space-between;margin-bottom:10px;">
                <span style="color:#888;">Service Outage Mins</span>
                <span style="color:#f59e0b;font-weight:600;">{format_number(total_outage_mins)} mins</span>
            </div>
            <div style="display:flex;justify-content:space-between;">
                <span style="color:#888;">Service Outage Events</span>
                <span style="color:#f59e0b;font-weight:600;">{format_number(total_outages)}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # ========================================
    # VIEW 3: LEADERBOARD VIEW
    # ========================================
    st.markdown("### 🏆 View 3: Leaderboard View")
    st.markdown("<span style='font-size:0.85rem;color:#888;'>Market rankings by performance</span>", unsafe_allow_html=True)
    
    if not market_totals.empty:
        # Sort markets by availability
        market_totals_sorted = market_totals.sort_values('AVG_AVAILABILITY', ascending=False).reset_index(drop=True)
        market_totals_sorted['RANK'] = range(1, len(market_totals_sorted) + 1)
        
        leader_col1, leader_col2 = st.columns(2)
        
        with leader_col1:
            st.markdown("#### 🥇 Top 10 Markets (Best Availability)")
            top_10 = market_totals_sorted.head(10)
            
            table_html = '<table style="width:100%;border-collapse:collapse;background:#f8f9fa;border-radius:8px;overflow:hidden;">'
            table_html += '<thead><tr style="background:#e9ecef;"><th style="padding:10px;text-align:left;color:#888;">Rank</th><th style="padding:10px;text-align:left;color:#888;">Market</th><th style="padding:10px;text-align:right;color:#888;">Avail %</th><th style="padding:10px;text-align:right;color:#888;">Downtime</th></tr></thead><tbody>'
            
            for _, row in top_10.iterrows():
                avail = float(row['AVG_AVAILABILITY']) if pd.notna(row['AVG_AVAILABILITY']) else 0
                color = "#22c55e" if avail >= 99.85 else "#f59e0b" if avail >= 99.5 else "#ef4444"
                medal = "🥇" if row['RANK'] == 1 else "🥈" if row['RANK'] == 2 else "🥉" if row['RANK'] == 3 else str(row['RANK'])
                table_html += f'<tr style="border-bottom:1px solid #2a2a4a;"><td style="padding:8px;color:#fff;">{medal}</td><td style="padding:8px;color:#fff;">{row["MARKET_ID"]}</td><td style="padding:8px;text-align:right;color:{color};font-weight:600;">{avail:.3f}%</td><td style="padding:8px;text-align:right;color:#888;">{format_number(row["TOTAL_DOWNTIME"])}s</td></tr>'
            
            table_html += '</tbody></table>'
            st.markdown(table_html, unsafe_allow_html=True)
        
        with leader_col2:
            st.markdown("#### ⚠️ Bottom 10 Markets (Need Attention)")
            bottom_10 = market_totals_sorted.tail(10).sort_values('AVG_AVAILABILITY', ascending=True)
            
            table_html = '<table style="width:100%;border-collapse:collapse;background:#f8f9fa;border-radius:8px;overflow:hidden;">'
            table_html += '<thead><tr style="background:#e9ecef;"><th style="padding:10px;text-align:left;color:#888;">Rank</th><th style="padding:10px;text-align:left;color:#888;">Market</th><th style="padding:10px;text-align:right;color:#888;">Avail %</th><th style="padding:10px;text-align:right;color:#888;">Downtime</th></tr></thead><tbody>'
            
            rank = len(market_totals_sorted)
            for _, row in bottom_10.iterrows():
                avail = float(row['AVG_AVAILABILITY']) if pd.notna(row['AVG_AVAILABILITY']) else 0
                color = "#22c55e" if avail >= 99.85 else "#f59e0b" if avail >= 99.5 else "#ef4444"
                table_html += f'<tr style="border-bottom:1px solid #2a2a4a;"><td style="padding:8px;color:#ef4444;">{rank}</td><td style="padding:8px;color:#fff;">{row["MARKET_ID"]}</td><td style="padding:8px;text-align:right;color:{color};font-weight:600;">{avail:.3f}%</td><td style="padding:8px;text-align:right;color:#e20074;">{format_number(row["TOTAL_DOWNTIME"])}s</td></tr>'
                rank -= 1
            
            table_html += '</tbody></table>'
            st.markdown(table_html, unsafe_allow_html=True)
    else:
        st.info("No market data available for leaderboard.")
    
    st.divider()
    
    # ========================================
    # VIEW 4: TREND ANALYSIS VIEW
    # ========================================
    st.markdown("### 📈 View 4: Trend Analysis")
    st.markdown("<span style='font-size:0.85rem;color:#888;'>Daily trends with direction indicators</span>", unsafe_allow_html=True)
    
    trend_col1, trend_col2 = st.columns(2)
    
    with trend_col1:
        st.markdown("#### Availability Trend")
        if not avail_daily.empty:
            avail_trend = avail_daily.copy()
            avail_trend['DATE'] = pd.to_datetime(avail_trend['DATE_VALUE']).dt.date
            avail_trend = avail_trend.sort_values('DATE')
            
            # Calculate trend direction
            if len(avail_trend) >= 2:
                first_half_avg = avail_trend.head(len(avail_trend)//2)['AVG_AVAILABILITY_PCT'].mean()
                second_half_avg = avail_trend.tail(len(avail_trend)//2)['AVG_AVAILABILITY_PCT'].mean()
                trend_dir = "↑ Improving" if second_half_avg > first_half_avg else "↓ Declining" if second_half_avg < first_half_avg else "→ Stable"
                trend_color = "#22c55e" if second_half_avg > first_half_avg else "#ef4444" if second_half_avg < first_half_avg else "#888888"
            else:
                trend_dir = "→ Stable"
                trend_color = "#888888"
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=avail_trend['DATE'],
                y=avail_trend['AVG_AVAILABILITY_PCT'],
                mode='lines+markers',
                name='Availability %',
                line=dict(color='#22c55e', width=3),
                marker=dict(size=8),
                fill='tozeroy',
                fillcolor='rgba(34, 197, 94, 0.1)'
            ))
            
            # Add goal line
            fig.add_hline(y=99.85, line_dash="dot", line_color="#f59e0b", annotation_text="Goal: 99.85%")
            
            fig.update_layout(
                template='plotly_white',
                height=300,
                margin=dict(l=10, r=10, t=30, b=10),
                yaxis=dict(range=[min(99, avail_trend['AVG_AVAILABILITY_PCT'].min() - 0.1), 100]),
                xaxis_title="",
                yaxis_title="Availability %"
            )
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="trend_avail")
            st.markdown(f"<div style='text-align:center;font-size:1.2rem;color:{trend_color};font-weight:600;'>{trend_dir}</div>", unsafe_allow_html=True)
        else:
            st.info("No availability trend data.")
    
    with trend_col2:
        st.markdown("#### COTTR Outage Trend")
        if not cottr_daily.empty:
            cottr_trend = cottr_daily.copy()
            cottr_trend['DATE'] = pd.to_datetime(cottr_trend['DATE_VALUE']).dt.date
            cottr_trend = cottr_trend.sort_values('DATE')
            
            # Calculate trend direction (lower is better for outages)
            if len(cottr_trend) >= 2:
                first_half_avg = cottr_trend.head(len(cottr_trend)//2)['OUTAGE_MINUTES'].mean()
                second_half_avg = cottr_trend.tail(len(cottr_trend)//2)['OUTAGE_MINUTES'].mean()
                trend_dir = "↑ Improving" if second_half_avg < first_half_avg else "↓ Declining" if second_half_avg > first_half_avg else "→ Stable"
                trend_color = "#22c55e" if second_half_avg < first_half_avg else "#ef4444" if second_half_avg > first_half_avg else "#888888"
            else:
                trend_dir = "→ Stable"
                trend_color = "#888888"
            
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=cottr_trend['DATE'],
                y=cottr_trend['OUTAGE_MINUTES'],
                name='Service Outage Minutes',
                marker_color='#f59e0b',
            ))
            
            fig.update_layout(
                template='plotly_white',
                height=300,
                margin=dict(l=10, r=10, t=30, b=10),
                xaxis_title="",
                yaxis_title="Service Outage Minutes"
            )
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="trend_cottr")
            st.markdown(f"<div style='text-align:center;font-size:1.2rem;color:{trend_color};font-weight:600;'>{trend_dir}</div>", unsafe_allow_html=True)
        else:
            st.info("No COTTR trend data.")

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_unavailability_data(_conn, start_date, end_date, days, site_types, avail_filter, oem_filter=None):
    """Cached single query for unavailability data - aggregated at site/date/market/category level"""
    
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Handle Non-Macro specially - it means SITE_TYPE != 'Macro' (various types like DAS, Micro, Pico, etc.)
    if len(site_types) == 1:
        if site_types[0] == 'Non-Macro':
            site_type_filter = "(SITE_TYPE != 'Macro' OR SITE_TYPE IS NULL)"
        else:
            site_type_filter = f"SITE_TYPE = '{site_types[0]}'"
    else:
        # Multiple types or (All) - include everything
        site_type_filter = "1=1"
    
    # Add OEM filter via join to MARKET_TRACKER if OEM is selected
    if oem_filter:
        # Replace MARKET_ID with a.MARKET_ID in filter clause to avoid ambiguity
        avail_filter_aliased = avail_filter.replace('MARKET_ID', 'a.MARKET_ID') if avail_filter else ''
        site_type_filter_a = site_type_filter.replace('SITE_TYPE', 'a.SITE_TYPE')
        query = f"""
        SELECT 
            a.DATE_VALUE,
            a.MARKET_ID,
            a.SITE_ID_FOCUS_CATEGORY,
            SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
            SUM(a.TOTAL_AVAILABILITY_N) as TOTAL_N,
            SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_D
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE {date_filter} AND {site_type_filter_a} AND mt.M_OEM = '{oem_filter}' {avail_filter_aliased}
        GROUP BY a.DATE_VALUE, a.MARKET_ID, a.SITE_ID_FOCUS_CATEGORY
        """
    else:
        query = f"""
        SELECT 
            DATE_VALUE,
            MARKET_ID,
            SITE_ID_FOCUS_CATEGORY,
            SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
            SUM(TOTAL_AVAILABILITY_N) as TOTAL_N,
            SUM(TOTAL_AVAILABILITY_D) as TOTAL_D
        FROM {TABLES['availability']}
        WHERE {date_filter} AND {site_type_filter} {avail_filter}
        GROUP BY DATE_VALUE, MARKET_ID, SITE_ID_FOCUS_CATEGORY
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_unavailability_site_data(_conn, start_date, end_date, days, site_types, market, avail_filter):
    """Get site-level unavailability data for a specific market"""
    
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Handle Non-Macro specially - it means SITE_TYPE != 'Macro' (various types like DAS, Micro, Pico, etc.)
    if len(site_types) == 1:
        if site_types[0] == 'Non-Macro':
            site_type_filter = "(SITE_TYPE != 'Macro' OR SITE_TYPE IS NULL)"
        else:
            site_type_filter = f"SITE_TYPE = '{site_types[0]}'"
    else:
        # Multiple types or (All) - include everything
        site_type_filter = "1=1"
    
    query = f"""
    SELECT 
        SITE_ID,
        SITE_ID_FOCUS_CATEGORY,
        SITE_ID_SUMMARY_CATEGORY,
        SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
        SUM(TOTAL_AVAILABILITY_N) as TOTAL_N,
        SUM(TOTAL_AVAILABILITY_D) as TOTAL_D,
        (SUM(TOTAL_DOWNTIME) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0)) * 100 as UNAVAILABILITY_PCT
    FROM {TABLES['availability']}
    WHERE {date_filter} AND {site_type_filter} AND MARKET_ID = '{market}' {avail_filter}
    GROUP BY SITE_ID, SITE_ID_FOCUS_CATEGORY, SITE_ID_SUMMARY_CATEGORY
    ORDER BY TOTAL_DOWNTIME DESC
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_unavailability_all_sites_data(_conn, start_date, end_date, days, site_types, avail_filter, oem_filter=None):
    """Get site-level unavailability data for all sites (no market filter) - for site-level breakdown"""
    
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Handle Non-Macro specially - it means SITE_TYPE != 'Macro' (various types like DAS, Micro, Pico, etc.)
    if len(site_types) == 1:
        if site_types[0] == 'Non-Macro':
            site_type_filter = "(SITE_TYPE != 'Macro' OR SITE_TYPE IS NULL)"
        else:
            site_type_filter = f"SITE_TYPE = '{site_types[0]}'"
    else:
        # Multiple types or (All) - include everything
        site_type_filter = "1=1"
    
    # Build date filters for COTTR and Customer Minutes
    cottr_date_filter = f"PER_DAY_LOCAL_DATE >= '{start_date}' AND PER_DAY_LOCAL_DATE <= '{end_date}'" if start_date and end_date else f"PER_DAY_LOCAL_DATE >= DATEADD(day, -{days}, CURRENT_DATE())"
    cm_date_filter = f"LOCAL_DATE_PART >= '{start_date}' AND LOCAL_DATE_PART <= '{end_date}'" if start_date and end_date else f"LOCAL_DATE_PART >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    if oem_filter:
        avail_filter_aliased = avail_filter.replace('MARKET_ID', 'a.MARKET_ID') if avail_filter else ''
        site_type_filter_a = site_type_filter.replace('SITE_TYPE', 'a.SITE_TYPE')
        query = f"""
        WITH avail_data AS (
            SELECT 
                a.SITE_ID,
                a.MARKET_ID,
                mt.M_OEM as OEM,
                a.SITE_ID_FOCUS_CATEGORY,
                SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
                SUM(a.TOTAL_AVAILABILITY_N) as TOTAL_N,
                SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_D,
                SUM(a.TOTAL_AVAILABILITY_D) - SUM(a.TOTAL_AVAILABILITY_N) as SITE_UNAVAIL_SECONDS,
                MIN(CASE WHEN a.TOTAL_DOWNTIME > 0 THEN a.DATE_VALUE END) as FIRST_OUTAGE_DATE,
                MAX(CASE WHEN a.TOTAL_DOWNTIME > 0 THEN a.DATE_VALUE END) as LAST_OUTAGE_DATE,
                COUNT(DISTINCT CASE WHEN a.TOTAL_DOWNTIME > 0 THEN a.DATE_VALUE END) as DAYS_WITH_DOWNTIME,
                COUNT(DISTINCT a.TOP_RECORDID) as COUNT_OF_TKTS
            FROM {TABLES['availability']} a
            JOIN {TABLES['market_tracker']} mt ON UPPER({get_market_case_sql()}) = UPPER(mt.M_CAPITAL_MARKET)
            WHERE {date_filter} AND {site_type_filter_a} AND mt.M_OEM = '{oem_filter}' {avail_filter_aliased}
            GROUP BY a.SITE_ID, a.MARKET_ID, mt.M_OEM, a.SITE_ID_FOCUS_CATEGORY
            HAVING SUM(a.TOTAL_AVAILABILITY_D) - SUM(a.TOTAL_AVAILABILITY_N) > 0
            ORDER BY SITE_UNAVAIL_SECONDS DESC
            LIMIT 1000
        ),
        top_sites AS (
            SELECT DISTINCT SITE_ID FROM avail_data
        ),
        detail_cat AS (
            SELECT a.SITE_ID, a.SITE_ID_FOCUS_CATEGORY,
                   LISTAGG(DISTINCT a.SITE_ID_DETAIL_CATEGORY, '/') WITHIN GROUP (ORDER BY a.SITE_ID_DETAIL_CATEGORY) as SITE_ID_DETAIL_CATEGORY
            FROM {TABLES['availability']} a
            JOIN {TABLES['market_tracker']} mt ON UPPER({get_market_case_sql()}) = UPPER(mt.M_CAPITAL_MARKET)
            WHERE a.SITE_ID IN (SELECT SITE_ID FROM top_sites)
              AND {date_filter} AND {site_type_filter_a} AND mt.M_OEM = '{oem_filter}' {avail_filter_aliased}
            GROUP BY a.SITE_ID, a.SITE_ID_FOCUS_CATEGORY
        ),
        desc_data AS (
            SELECT SITE_ID, SITE_ID_FOCUS_CATEGORY, TOP_RECORDID as DESC_TOP_RECORDID, DESCRIPTION_1, DESCRIPTION_2, DESCRIPTION_3
            FROM (
                SELECT a.SITE_ID, a.SITE_ID_FOCUS_CATEGORY, a.TOP_RECORDID, a.DESCRIPTION_1, a.DESCRIPTION_2, a.DESCRIPTION_3,
                       ROW_NUMBER() OVER (PARTITION BY a.SITE_ID, a.SITE_ID_FOCUS_CATEGORY ORDER BY a.DATE_VALUE DESC, a.TOTAL_DOWNTIME DESC) as rn
                FROM {TABLES['availability']} a
                WHERE a.SITE_ID IN (SELECT SITE_ID FROM top_sites)
                  AND a.SITE_ID_FOCUS_CATEGORY IN (SELECT SITE_ID_FOCUS_CATEGORY FROM avail_data WHERE avail_data.SITE_ID = a.SITE_ID)
                  AND a.TOTAL_DOWNTIME > 0 AND {date_filter}
            ) WHERE rn = 1
        ),
        cottr_data AS (
            SELECT SITE_CD as SITE_ID, 
                   SUM(PER_DAY_OUTAGE_MINUTES) as COTTR_MINUTES,
                   COUNT(DISTINCT PER_DAY_LOCAL_DATE) as COTTR_DAYS
            FROM {TABLES['cottr']}
            WHERE {cottr_date_filter} AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' AND SITE_CD NOT LIKE 'USC%'
              AND SITE_CD IN (SELECT SITE_ID FROM top_sites)
            GROUP BY SITE_CD
        ),
        cm_data AS (
            SELECT SITE_ID, SUM(IMPACT_DURATION_IN_MINS) as CUSTOMER_MINUTES
            FROM {TABLES['customer_minutes']}
            WHERE {cm_date_filter} AND SITE_ID NOT LIKE 'USC%'
              AND SITE_ID IN (SELECT SITE_ID FROM top_sites)
            GROUP BY SITE_ID
        )
        SELECT 
            av.*,
            COALESCE(dc.SITE_ID_DETAIL_CATEGORY, '') as SITE_ID_DETAIL_CATEGORY,
            COALESCE(d.DESC_TOP_RECORDID, '') as DESC_TOP_RECORDID,
            COALESCE(d.DESCRIPTION_1, '') as DESCRIPTION_1,
            COALESCE(d.DESCRIPTION_2, '') as DESCRIPTION_2,
            COALESCE(d.DESCRIPTION_3, '') as DESCRIPTION_3,
            COALESCE(c.COTTR_MINUTES, 0) as COTTR_MINUTES,
            COALESCE(c.COTTR_DAYS, 0) as COTTR_DAYS,
            COALESCE(cm.CUSTOMER_MINUTES, 0) as CUSTOMER_MINUTES
        FROM avail_data av
        LEFT JOIN detail_cat dc ON av.SITE_ID = dc.SITE_ID AND av.SITE_ID_FOCUS_CATEGORY = dc.SITE_ID_FOCUS_CATEGORY
        LEFT JOIN desc_data d ON av.SITE_ID = d.SITE_ID AND av.SITE_ID_FOCUS_CATEGORY = d.SITE_ID_FOCUS_CATEGORY
        LEFT JOIN cottr_data c ON av.SITE_ID = c.SITE_ID
        LEFT JOIN cm_data cm ON av.SITE_ID = cm.SITE_ID
        ORDER BY av.SITE_UNAVAIL_SECONDS DESC
        """
    else:
        date_filter_a = date_filter.replace('DATE_VALUE', 'a.DATE_VALUE').replace('SITE_TYPE', 'a.SITE_TYPE')
        site_type_filter_a = site_type_filter.replace('SITE_TYPE', 'a.SITE_TYPE')
        avail_filter_a = avail_filter.replace('MARKET_ID', 'a.MARKET_ID') if avail_filter else ''
        query = f"""
        WITH avail_data AS (
            SELECT 
                a.SITE_ID,
                a.MARKET_ID,
                COALESCE(mt.M_OEM, 'Unknown') as OEM,
                a.SITE_ID_FOCUS_CATEGORY,
                SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
                SUM(a.TOTAL_AVAILABILITY_N) as TOTAL_N,
                SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_D,
                SUM(a.TOTAL_AVAILABILITY_D) - SUM(a.TOTAL_AVAILABILITY_N) as SITE_UNAVAIL_SECONDS,
                MIN(CASE WHEN a.TOTAL_DOWNTIME > 0 THEN a.DATE_VALUE END) as FIRST_OUTAGE_DATE,
                MAX(CASE WHEN a.TOTAL_DOWNTIME > 0 THEN a.DATE_VALUE END) as LAST_OUTAGE_DATE,
                COUNT(DISTINCT CASE WHEN a.TOTAL_DOWNTIME > 0 THEN a.DATE_VALUE END) as DAYS_WITH_DOWNTIME,
                COUNT(DISTINCT a.TOP_RECORDID) as COUNT_OF_TKTS
            FROM {TABLES['availability']} a
            LEFT JOIN {TABLES['market_tracker']} mt ON UPPER({get_market_case_sql()}) = UPPER(mt.M_CAPITAL_MARKET)
            WHERE {date_filter_a} AND {site_type_filter_a} {avail_filter_a}
            GROUP BY a.SITE_ID, a.MARKET_ID, mt.M_OEM, a.SITE_ID_FOCUS_CATEGORY
            HAVING SUM(a.TOTAL_AVAILABILITY_D) - SUM(a.TOTAL_AVAILABILITY_N) > 0
            ORDER BY SITE_UNAVAIL_SECONDS DESC
            LIMIT 1000
        ),
        top_sites AS (
            SELECT DISTINCT SITE_ID FROM avail_data
        ),
        detail_cat AS (
            SELECT a.SITE_ID, a.SITE_ID_FOCUS_CATEGORY,
                   LISTAGG(DISTINCT a.SITE_ID_DETAIL_CATEGORY, '/') WITHIN GROUP (ORDER BY a.SITE_ID_DETAIL_CATEGORY) as SITE_ID_DETAIL_CATEGORY
            FROM {TABLES['availability']} a
            LEFT JOIN {TABLES['market_tracker']} mt ON UPPER({get_market_case_sql()}) = UPPER(mt.M_CAPITAL_MARKET)
            WHERE a.SITE_ID IN (SELECT SITE_ID FROM top_sites)
              AND {date_filter_a} AND {site_type_filter_a} {avail_filter_a}
            GROUP BY a.SITE_ID, a.SITE_ID_FOCUS_CATEGORY
        ),
        desc_data AS (
            SELECT SITE_ID, SITE_ID_FOCUS_CATEGORY, TOP_RECORDID as DESC_TOP_RECORDID, DESCRIPTION_1, DESCRIPTION_2, DESCRIPTION_3
            FROM (
                SELECT a.SITE_ID, a.SITE_ID_FOCUS_CATEGORY, a.TOP_RECORDID, a.DESCRIPTION_1, a.DESCRIPTION_2, a.DESCRIPTION_3,
                       ROW_NUMBER() OVER (PARTITION BY a.SITE_ID, a.SITE_ID_FOCUS_CATEGORY ORDER BY a.DATE_VALUE DESC, a.TOTAL_DOWNTIME DESC) as rn
                FROM {TABLES['availability']} a
                WHERE a.SITE_ID IN (SELECT SITE_ID FROM top_sites)
                  AND a.SITE_ID_FOCUS_CATEGORY IN (SELECT SITE_ID_FOCUS_CATEGORY FROM avail_data WHERE avail_data.SITE_ID = a.SITE_ID)
                  AND a.TOTAL_DOWNTIME > 0 AND {date_filter}
            ) WHERE rn = 1
        ),
        cottr_data AS (
            SELECT SITE_CD as SITE_ID, 
                   SUM(PER_DAY_OUTAGE_MINUTES) as COTTR_MINUTES,
                   COUNT(DISTINCT PER_DAY_LOCAL_DATE) as COTTR_DAYS
            FROM {TABLES['cottr']}
            WHERE {cottr_date_filter} AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' AND SITE_CD NOT LIKE 'USC%'
              AND SITE_CD IN (SELECT SITE_ID FROM top_sites)
            GROUP BY SITE_CD
        ),
        cm_data AS (
            SELECT SITE_ID, SUM(IMPACT_DURATION_IN_MINS) as CUSTOMER_MINUTES
            FROM {TABLES['customer_minutes']}
            WHERE {cm_date_filter} AND SITE_ID NOT LIKE 'USC%'
              AND SITE_ID IN (SELECT SITE_ID FROM top_sites)
            GROUP BY SITE_ID
        )
        SELECT 
            av.*,
            COALESCE(dc.SITE_ID_DETAIL_CATEGORY, '') as SITE_ID_DETAIL_CATEGORY,
            COALESCE(d.DESC_TOP_RECORDID, '') as DESC_TOP_RECORDID,
            COALESCE(d.DESCRIPTION_1, '') as DESCRIPTION_1,
            COALESCE(d.DESCRIPTION_2, '') as DESCRIPTION_2,
            COALESCE(d.DESCRIPTION_3, '') as DESCRIPTION_3,
            COALESCE(c.COTTR_MINUTES, 0) as COTTR_MINUTES,
            COALESCE(c.COTTR_DAYS, 0) as COTTR_DAYS,
            COALESCE(cm.CUSTOMER_MINUTES, 0) as CUSTOMER_MINUTES
        FROM avail_data av
        LEFT JOIN detail_cat dc ON av.SITE_ID = dc.SITE_ID AND av.SITE_ID_FOCUS_CATEGORY = dc.SITE_ID_FOCUS_CATEGORY
        LEFT JOIN desc_data d ON av.SITE_ID = d.SITE_ID AND av.SITE_ID_FOCUS_CATEGORY = d.SITE_ID_FOCUS_CATEGORY
        LEFT JOIN cottr_data c ON av.SITE_ID = c.SITE_ID
        LEFT JOIN cm_data cm ON av.SITE_ID = cm.SITE_ID
        ORDER BY av.SITE_UNAVAIL_SECONDS DESC
        """
    return run_query(_conn, query)

def unavailability_dashboard(conn, days, filters=None):
    """Unavailability Dashboard - Shows downtime % (100% - availability%)"""
    
    market = get_market_display_name(filters.get('market') if filters else None)
    st.markdown('<div class="section-header">📉 Unavailability Analysis</div>', unsafe_allow_html=True)
    st.markdown("<span style='font-size:0.9rem;color:#888;'>Downtime % = 100% - Availability % | Site Type filter applied</span>", unsafe_allow_html=True)
    
    # Use global Site Type filter
    site_type = filters.get('site_type') if filters else 'Macro'
    selected_site_types = (site_type,) if site_type else ('Macro', 'Non-Macro')
    
    avail_filter = build_filter_clause(filters, 'availability')
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    oem_filter = filters.get('oem') if filters else None
    
    # Fire the heavy site-level query in background while aggregate query + KPIs render
    site_data_future = ThreadPoolExecutor(max_workers=1).submit(
        get_unavailability_all_sites_data, conn, start_date, end_date, days, selected_site_types, avail_filter, oem_filter
    )
    
    # Get all data in one cached query (no spinner since cache is fast)
    raw_data = get_unavailability_data(conn, start_date, end_date, days, selected_site_types, avail_filter, oem_filter)
    
    if raw_data.empty:
        st.info("No unavailability data found for the selected filters.")
        return
    
    # Bulk convert all Decimal columns to float once (avoids repeated conversions later)
    for col in ['TOTAL_DOWNTIME', 'TOTAL_N', 'TOTAL_D', 'UNAVAILABILITY_PCT']:
        if col in raw_data.columns:
            raw_data[col] = pd.to_numeric(raw_data[col], errors='coerce').fillna(0).astype(float)
    
    # Aggregate using pandas (much faster than multiple SQL queries)
    # Focus category aggregation
    focus_cat_data = raw_data.groupby('SITE_ID_FOCUS_CATEGORY').agg({
        'TOTAL_DOWNTIME': 'sum',
        'TOTAL_N': 'sum',
        'TOTAL_D': 'sum'
    }).reset_index()
    focus_cat_data['UNAVAILABILITY_PCT'] = 100 - (focus_cat_data['TOTAL_N'] / focus_cat_data['TOTAL_D'].replace(0, float('nan')) * 100)
    focus_cat_data = focus_cat_data.sort_values('TOTAL_DOWNTIME', ascending=False)
    
    # Market aggregation - normalize to Global Market ID format for display
    raw_data['MARKET_ID'] = raw_data['MARKET_ID'].apply(lambda x: get_canonical_market_name(x, 'availability') if pd.notna(x) else x)
    market_data = raw_data.groupby('MARKET_ID').agg({
        'TOTAL_DOWNTIME': 'sum',
        'TOTAL_N': 'sum',
        'TOTAL_D': 'sum'
    }).reset_index()
    market_data['UNAVAILABILITY_PCT'] = 100 - (market_data['TOTAL_N'] / market_data['TOTAL_D'].replace(0, float('nan')) * 100)
    market_data = market_data.sort_values('UNAVAILABILITY_PCT', ascending=False)
    
    # Daily trend aggregation
    daily_data = raw_data.groupby('DATE_VALUE').agg({
        'TOTAL_DOWNTIME': 'sum',
        'TOTAL_N': 'sum',
        'TOTAL_D': 'sum'
    }).reset_index()
    daily_data['UNAVAILABILITY_PCT'] = 100 - (daily_data['TOTAL_N'] / daily_data['TOTAL_D'].replace(0, float('nan')) * 100)
    daily_data = daily_data.sort_values('DATE_VALUE')
    
    # Market/focus aggregation for breakdown chart
    market_focus_data = raw_data.groupby(['MARKET_ID', 'SITE_ID_FOCUS_CATEGORY']).agg({
        'TOTAL_DOWNTIME': 'sum',
        'TOTAL_D': 'sum'
    }).reset_index()
    
    # Add market totals FIRST, then calculate unavailability using market total
    market_totals = raw_data.groupby('MARKET_ID')['TOTAL_D'].sum().reset_index()
    market_totals.columns = ['MARKET_ID', 'MARKET_TOTAL_D']
    market_focus_data = market_focus_data.merge(market_totals, on='MARKET_ID', how='left')
    
    # Calculate unavailability % using MARKET_TOTAL_D (total time for entire market, not just category)
    market_focus_data['UNAVAILABILITY_PCT'] = (market_focus_data['TOTAL_DOWNTIME'] / market_focus_data['MARKET_TOTAL_D'].replace(0, float('nan'))) * 100
    market_focus_data = market_focus_data.sort_values(['MARKET_ID', 'TOTAL_DOWNTIME'], ascending=[True, False])
    
    # Daily focus category aggregation
    daily_focus_data = raw_data.groupby(['DATE_VALUE', 'SITE_ID_FOCUS_CATEGORY']).agg({
        'TOTAL_DOWNTIME': 'sum'
    }).reset_index()
    daily_focus_data = daily_focus_data.sort_values(['DATE_VALUE', 'TOTAL_DOWNTIME'], ascending=[True, False])
    
    # Calculate overall unavailability
    if not focus_cat_data.empty:
        total_n = float(focus_cat_data['TOTAL_N'].sum())
        total_d = float(focus_cat_data['TOTAL_D'].sum())
        overall_avail = (total_n / total_d * 100) if total_d > 0 else 0
        overall_unavail = 100 - overall_avail
    else:
        overall_avail = 0
        overall_unavail = 0
    
    # ===== ROW 1: KPI Summary =====
    st.markdown("### 📊 Unavailability Summary")
    
    # Calculate markets meeting/not meeting target for later use
    markets_meeting = 0
    markets_not_meeting = 0
    if not market_data.empty:
        market_data['AVAILABILITY_PCT'] = 100 - market_data['UNAVAILABILITY_PCT']
        markets_meeting = len(market_data[market_data['AVAILABILITY_PCT'] >= 99.85])
        markets_not_meeting = len(market_data[market_data['AVAILABILITY_PCT'] < 99.85])
    
    # 4 columns: 3 KPIs + 1 markets meeting target
    kpi_col1, kpi_col2, kpi_col3, target_col = st.columns([1, 1, 1, 1.2])
    
    with kpi_col1:
        # Build sparkline from daily data with goal line at 0.15%
        sparkline_html = '<span></span>'
        unavail_goal = 0.15  # 100% - 99.85%
        dt_days_met_goal = 0
        dt_total_days = 0
        if not daily_data.empty:
            daily_data_sorted = daily_data.sort_values('DATE_VALUE')
            daily_unavail = daily_data_sorted['UNAVAILABILITY_PCT'].astype(float).tolist()
            dt_total_days = len(daily_unavail)
            dt_days_met_goal = sum(1 for val in daily_unavail if val <= unavail_goal)
            # Only show sparklines for 14 days or less to prevent overflow
            if daily_unavail and dt_total_days <= 14:
                max_val = max(max(daily_unavail), unavail_goal * 1.5) if daily_unavail else unavail_goal * 1.5
                min_val = 0
                goal_height_pct = (unavail_goal / max_val * 100) if max_val > 0 else 50
                sparkline_html = f'<div style="position:relative;display:flex;align-items:flex-end;gap:3px;height:45px;">'
                sparkline_html += f'<div style="position:absolute;bottom:{goal_height_pct}%;left:0;right:0;height:0;border-top:2px dashed #f59e0b;" title="Goal: {unavail_goal}%"></div>'
                sparkline_html += f'<div style="position:absolute;bottom:{goal_height_pct}%;left:0;font-size:0.7rem;color:#f59e0b;transform:translate(-100%, 50%);">Goal</div>'
                for i, val in enumerate(daily_unavail):
                    height_pct = (val / max_val * 100) if max_val > 0 else 50
                    bar_color = '#22c55e' if val <= unavail_goal else '#ef4444'
                    sparkline_html += f'<div style="width:6px;height:{height_pct}%;background:{bar_color};border-radius:2px;opacity:0.9;" title="Day {i+1}: {val:.3f}%"></div>'
                sparkline_html += '</div>'
        
        # Calculate days met percentage for downtime
        dt_days_met_pct = (dt_days_met_goal / dt_total_days * 100) if dt_total_days > 0 else 0
        dt_days_met_color = '#22c55e' if dt_days_met_pct == 100 else ('#f59e0b' if dt_days_met_pct >= 80 else '#ef4444')
        
        st.markdown(f"""
        <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:10px;padding:12px 15px;position:relative;">
            <div style="position:absolute;top:8px;right:12px;font-size:0.8rem;color:{dt_days_met_color};font-weight:bold;">{dt_days_met_goal} of {dt_total_days} days = {dt_days_met_pct:.0f}%</div>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;">
                <div style="text-align:left;">
                    <div style="font-size:0.85rem;color:#888;">Downtime %</div>
                    <div style="font-size:1.8rem;font-weight:bold;color:#ef4444;">{overall_unavail:.2f}%</div>
                    <div style="font-size:0.75rem;color:#888;">Goal: ≤0.15%</div>
                </div>
                {sparkline_html}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with kpi_col2:
        # Build sparkline from daily data for availability with goal line at 99.85%
        avail_sparkline_html = '<span></span>'
        avail_goal = 99.85
        days_met_goal = 0
        total_days = 0
        if not daily_data.empty:
            daily_data_sorted = daily_data.sort_values('DATE_VALUE')
            daily_avail = (100 - daily_data_sorted['UNAVAILABILITY_PCT'].astype(float)).tolist()
            total_days = len(daily_avail)
            days_met_goal = sum(1 for val in daily_avail if val >= avail_goal)
            # Only show sparklines for 14 days or less to prevent overflow
            if daily_avail and total_days <= 14:
                max_val = 100
                min_val = min(min(daily_avail), avail_goal - 0.5) if daily_avail else avail_goal - 0.5
                range_val = max_val - min_val
                goal_height_pct = ((avail_goal - min_val) / range_val * 100) if range_val > 0 else 50
                avail_sparkline_html = f'<div style="position:relative;display:flex;align-items:flex-end;gap:3px;height:45px;">'
                avail_sparkline_html += f'<div style="position:absolute;bottom:{goal_height_pct}%;left:0;right:0;height:0;border-top:2px dashed #f59e0b;" title="Goal: {avail_goal}%"></div>'
                avail_sparkline_html += f'<div style="position:absolute;bottom:{goal_height_pct}%;left:0;font-size:0.7rem;color:#f59e0b;transform:translate(-100%, 50%);">Goal</div>'
                for i, val in enumerate(daily_avail):
                    height_pct = ((val - min_val) / range_val * 100) if range_val > 0 else 50
                    bar_color = '#22c55e' if val >= avail_goal else '#ef4444'
                    avail_sparkline_html += f'<div style="width:6px;height:{height_pct}%;background:{bar_color};border-radius:2px;opacity:0.9;" title="Day {i+1}: {val:.2f}%"></div>'
                avail_sparkline_html += '</div>'
        
        # Calculate days met percentage
        days_met_pct = (days_met_goal / total_days * 100) if total_days > 0 else 0
        days_met_color = '#22c55e' if days_met_pct == 100 else ('#f59e0b' if days_met_pct >= 80 else '#ef4444')
        
        # Color availability based on goal
        avail_value_color = '#22c55e' if overall_avail >= 99.85 else '#ef4444'
        
        st.markdown(f"""
        <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:10px;padding:12px 15px;position:relative;">
            <div style="position:absolute;top:8px;right:12px;font-size:0.8rem;color:{days_met_color};font-weight:bold;">{days_met_goal} of {total_days} days = {days_met_pct:.0f}%</div>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;">
                <div style="text-align:left;">
                    <div style="font-size:0.85rem;color:#888;">Availability %</div>
                    <div style="font-size:1.8rem;font-weight:bold;color:{avail_value_color};">{overall_avail:.2f}%</div>
                    <div style="font-size:0.75rem;color:#888;">Goal: ≥99.85%</div>
                </div>
                {avail_sparkline_html}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with kpi_col3:
        total_downtime = float(focus_cat_data['TOTAL_DOWNTIME'].sum()) if not focus_cat_data.empty else 0
        
        # Build sparkline from daily downtime data with average as goal line
        downtime_sparkline_html = '<span></span>'
        daily_dt = []
        avg_dt = 0
        if not daily_data.empty:
            daily_data_sorted = daily_data.sort_values('DATE_VALUE')
            daily_dt = daily_data_sorted['TOTAL_DOWNTIME'].astype(float).tolist()
            dt_days_count = len(daily_dt)
            if daily_dt:
                avg_dt = sum(daily_dt) / len(daily_dt) if daily_dt else 0
                # Only show sparklines for 14 days or less to prevent overflow
                if dt_days_count <= 14:
                    max_val = max(daily_dt) if max(daily_dt) > 0 else 1
                    min_val = 0
                    goal_height_pct = (avg_dt / max_val * 100) if max_val > 0 else 50
                    downtime_sparkline_html = f'<div style="position:relative;display:flex;align-items:flex-end;gap:3px;height:45px;">'
                    downtime_sparkline_html += f'<div style="position:absolute;bottom:{goal_height_pct}%;left:0;right:0;height:0;border-top:2px dashed #f59e0b;" title="Avg: {format_number(avg_dt)} sec"></div>'
                    downtime_sparkline_html += f'<div style="position:absolute;bottom:{goal_height_pct}%;left:0;font-size:0.7rem;color:#f59e0b;transform:translate(-100%, 50%);">Avg</div>'
                    for i, val in enumerate(daily_dt):
                        height_pct = (val / max_val * 100) if max_val > 0 else 50
                        height_pct = max(5, height_pct)
                        bar_color = '#22c55e' if val <= avg_dt else '#f59e0b'
                        downtime_sparkline_html += f'<div style="width:6px;height:{height_pct}%;background:{bar_color};border-radius:2px;opacity:0.8;" title="Day {i+1}: {format_number(val)} sec"></div>'
                    downtime_sparkline_html += '</div>'
        
        # Calculate days below average for consistency with other cards
        dt_days_below_avg = sum(1 for val in daily_dt if val <= avg_dt) if daily_dt else 0
        dt_days_total = len(daily_dt) if daily_dt else 0
        dt_below_avg_pct = (dt_days_below_avg / dt_days_total * 100) if dt_days_total > 0 else 0
        dt_below_avg_color = '#22c55e' if dt_below_avg_pct >= 50 else '#f59e0b'
        
        st.markdown(f"""
        <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:10px;padding:12px 15px;position:relative;">
            <div style="position:absolute;top:8px;right:12px;font-size:0.8rem;color:{dt_below_avg_color};font-weight:bold;">{dt_days_below_avg} of {dt_days_total} days ≤ avg</div>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;">
                <div style="text-align:left;">
                    <div style="font-size:0.85rem;color:#888;">Total Downtime</div>
                    <div style="font-size:1.8rem;font-weight:bold;color:#f59e0b;">{format_number(total_downtime)}</div>
                    <div style="font-size:0.75rem;color:#888;">seconds</div>
                </div>
                {downtime_sparkline_html}
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # Markets Meeting Target column
    with target_col:
        total_markets = markets_meeting + markets_not_meeting
        meeting_pct = (markets_meeting / total_markets * 100) if total_markets > 0 else 0
        st.markdown(f"<div style='font-size:0.75rem;font-weight:bold;color:#888;margin-bottom:5px;'>Markets Meeting 99.85% <span style='color:#e20074;font-size:0.9rem;'>({meeting_pct:.1f}%)</span></div>", unsafe_allow_html=True)
        
        fig_target = go.Figure()
        fig_target.add_trace(go.Bar(
            y=[''],
            x=[markets_not_meeting],
            orientation='h',
            name='Not Meeting',
            marker_color='#000000',
            text=[f'{markets_not_meeting}'],
            textposition='auto',
            textfont=dict(size=14, color='white')
        ))
        fig_target.add_trace(go.Bar(
            y=[''],
            x=[markets_meeting],
            orientation='h',
            name='Meeting',
            marker_color='#e20074',
            text=[f'{markets_meeting}'],
            textposition='auto',
            textfont=dict(size=14, color='white')
        ))
        fig_target.update_layout(
            template='plotly_white',
            height=100,
            barmode='stack',
            showlegend=True,
            legend=dict(orientation='h', yanchor='bottom', y=-0.3, xanchor='center', x=0.5, font=dict(size=9)),
            margin=dict(l=5, r=5, t=5, b=30),
            xaxis=dict(showticklabels=False),
            yaxis=dict(showticklabels=False)
        )
        st.plotly_chart(fig_target, use_container_width=True, config=CHART_CONFIG, key="unavail_markets_meeting_target")
    
    st.divider()
    
    # ===== ROW 2: Three Column Layout - Focus Category, Market Downtime & Daily Trend =====
    row2_col1, row2_col2, row2_col3 = st.columns(3)
    
    with row2_col1:
        st.markdown(f"### 📊 Focus Category % <span style='font-size:1rem;color:#22c55e;font-weight:normal;'>({overall_avail:.2f}% Avail)</span>", unsafe_allow_html=True)
        st.markdown("<span style='font-size:0.75rem;color:#888;'>Sum of all categories = Total Downtime %</span>", unsafe_allow_html=True)
        
        if not focus_cat_data.empty:
            # Filter out categories with minimal impact and sort by downtime descending
            focus_filtered = focus_cat_data[focus_cat_data['TOTAL_DOWNTIME'] > 0]
            focus_filtered = focus_filtered.sort_values('TOTAL_DOWNTIME', ascending=False)
            
            # Use the SAME overall unavailability as calculated for the KPI cards
            total_downtime_all = focus_filtered['TOTAL_DOWNTIME'].sum()
            
            # Each category's contribution = (category downtime / total downtime) * overall unavailability
            focus_filtered['DOWNTIME_PCT'] = (focus_filtered['TOTAL_DOWNTIME'] / total_downtime_all * overall_unavail) if total_downtime_all > 0 else 0
            
            # Limit to top 10 categories for cleaner display
            focus_top = focus_filtered.head(10).copy()
            
            # Calculate cumulative availability (starting from 100% and subtracting)
            cumulative_avail = []
            running_avail = 100.0
            for _, row in focus_top.iterrows():
                running_avail = running_avail - row['DOWNTIME_PCT']
                cumulative_avail.append(running_avail)
            focus_top['CUMULATIVE_AVAIL'] = cumulative_avail
            
            # Get colors for each category
            colors = [FOCUS_CATEGORY_COLORS.get(cat, DEFAULT_FOCUS_COLOR) for cat in focus_top['SITE_ID_FOCUS_CATEGORY']]
            
            # Create horizontal bar chart
            fig_focus_bar = go.Figure()
            
            fig_focus_bar.add_trace(go.Bar(
                y=focus_top['SITE_ID_FOCUS_CATEGORY'],
                x=focus_top['DOWNTIME_PCT'],
                orientation='h',
                marker_color=colors,
                text=[f"{v:.2f}%" for v in focus_top['DOWNTIME_PCT']],
                textposition='inside',
                insidetextanchor='middle',
                textfont=dict(size=14, color='white'),
                hovertemplate='<b>%{y}</b><br>Unavailability: %{x:.2f}%<extra></extra>'
            ))
            
            # Add cumulative availability text on the right side (outside plot area)
            # Red if below 99.85%, green if at or above
            max_x = focus_top['DOWNTIME_PCT'].max()
            availability_goal = 99.85
            
            for i, (_, row) in enumerate(focus_top.iterrows()):
                avail_color = '#ef4444' if row['CUMULATIVE_AVAIL'] < availability_goal else '#22c55e'
                fig_focus_bar.add_annotation(
                    x=max_x * 1.08,
                    y=row['SITE_ID_FOCUS_CATEGORY'],
                    text=f"{row['CUMULATIVE_AVAIL']:.2f}%",
                    showarrow=False,
                    xanchor='left',
                    yanchor='middle',
                    font=dict(size=14, color=avail_color)
                )
            
            fig_focus_bar.update_layout(
                template='plotly_white',
                height=420,
                showlegend=False,
                font=dict(size=15),
                xaxis=dict(
                    title=dict(text="Unavailability %", font=dict(size=15)),
                    tickformat=".2f",
                    tickfont=dict(size=13),
                    range=[0, max_x * 1.1]
                ),
                yaxis=dict(autorange="reversed", tickfont=dict(size=14)),
                margin=dict(l=160, r=80, t=10, b=40)
            )
            st.plotly_chart(fig_focus_bar, use_container_width=True, config=CHART_CONFIG, key="unavail_focus_bar")
    
    with row2_col2:
        st.markdown(f"### 📊 All Categories - Downtime % <span style='font-size:1rem;color:#ef4444;font-weight:normal;'>({overall_unavail:.2f}%)</span>", unsafe_allow_html=True)
        st.markdown("<span style='font-size:0.75rem;color:#888;'>Select Market to Filter or Highlight on other charts</span>", unsafe_allow_html=True)
        
        if not market_data.empty and not market_focus_data.empty:
            # Get up to 50 markets for scrolling, display shows ~15 initially
            top_markets = market_data.head(50)
            top_market_ids = top_markets['MARKET_ID'].tolist()
            
            # Filter market_focus_data to only include top markets
            focus_data_filtered = market_focus_data[market_focus_data['MARKET_ID'].isin(top_market_ids)].copy()
            
            # Get unique focus categories sorted by total downtime contribution - limit to top 8 for cleaner legend
            focus_totals = focus_data_filtered.groupby('SITE_ID_FOCUS_CATEGORY')['UNAVAILABILITY_PCT'].sum().sort_values(ascending=False)
            top_focus_categories = focus_totals.head(8).index.tolist()
            
            # Group remaining categories as "Other"
            focus_data_filtered['DISPLAY_CATEGORY'] = focus_data_filtered['SITE_ID_FOCUS_CATEGORY'].apply(
                lambda x: x if x in top_focus_categories else 'Other'
            )
            
            # Reaggregate with display categories
            display_data = focus_data_filtered.groupby(['MARKET_ID', 'DISPLAY_CATEGORY'])['UNAVAILABILITY_PCT'].sum().reset_index()
            display_categories = top_focus_categories + ['Other']
            
            fig_markets = go.Figure()
            
            # Add stacked bars for each focus category
            for focus_cat in display_categories:
                cat_data = display_data[display_data['DISPLAY_CATEGORY'] == focus_cat]
                
                # Create a series with all top markets, filling missing with 0
                cat_values = []
                for mkt in top_market_ids:
                    mkt_cat_data = cat_data[cat_data['MARKET_ID'] == mkt]
                    if not mkt_cat_data.empty:
                        cat_values.append(float(mkt_cat_data['UNAVAILABILITY_PCT'].values[0]))
                    else:
                        cat_values.append(0)
                
                if focus_cat == 'Other':
                    color = '#4a4a4a'
                else:
                    color = FOCUS_CATEGORY_COLORS.get(focus_cat, DEFAULT_FOCUS_COLOR)
                
                fig_markets.add_trace(go.Bar(
                    y=top_market_ids,
                    x=cat_values,
                    orientation='h',
                    name=focus_cat,
                    marker_color=color,
                    hovertemplate=f'<b>%{{y}}</b><br>{focus_cat}: %{{x:.4f}}%<extra></extra>'
                ))
            
            # Calculate average unavailability for the displayed markets
            avg_unavail = top_markets['UNAVAILABILITY_PCT'].mean()
            
            # Add vertical dotted line for average (using dark gray for visibility on dark theme)
            fig_markets.add_vline(
                x=avg_unavail,
                line_dash="dot",
                line_color="#333333",
                line_width=2,
                annotation_text=f"Avg: {avg_unavail:.2f}%",
                annotation_position="top",
                annotation_font_size=11,
                annotation_font_color="#333333",
                annotation_bgcolor="rgba(255,255,255,0.85)",
                annotation_borderpad=3,
                annotation_yshift=10
            )
            
            # Dynamic height based on number of markets (28px per bar)
            chart_height = len(top_market_ids) * 28 + 60
            
            fig_markets.update_layout(
                template='plotly_white',
                height=chart_height,
                barmode='stack',
                font=dict(size=15),
                yaxis=dict(autorange="reversed", tickfont=dict(size=13)),
                xaxis_title="Downtime %",
                xaxis=dict(tickfont=dict(size=13), title=dict(font=dict(size=15))),
                margin=dict(l=10, r=10, t=30, b=40),
                showlegend=False
            )
            
            # Wrap in scrollable container (show ~15 markets initially = 420px)
            with st.container(height=420, border=False):
                st.plotly_chart(fig_markets, use_container_width=True, config=CHART_CONFIG, key="unavail_markets")
        elif not market_data.empty:
            # Fallback to single color if no focus data
            top_markets = market_data.head(50)
            
            fig_markets = go.Figure()
            fig_markets.add_trace(go.Bar(
                y=top_markets['MARKET_ID'],
                x=top_markets['UNAVAILABILITY_PCT'],
                orientation='h',
                marker_color='#e20074',
                text=[f"{v:.2f}%" for v in top_markets['UNAVAILABILITY_PCT']],
                textposition='outside',
                textfont=dict(size=18),
                hovertemplate='<b>%{y}</b><br>Downtime: %{x:.4f}%<extra></extra>'
            ))
            
            # Calculate average unavailability for the displayed markets
            avg_unavail = top_markets['UNAVAILABILITY_PCT'].mean()
            
            # Add vertical dotted line for average (using dark gray for visibility on dark theme)
            fig_markets.add_vline(
                x=avg_unavail,
                line_dash="dot",
                line_color="#333333",
                line_width=2,
                annotation_text=f"Avg: {avg_unavail:.2f}%",
                annotation_position="top",
                annotation_font_size=11,
                annotation_font_color="#333333",
                annotation_bgcolor="rgba(255,255,255,0.85)",
                annotation_borderpad=3,
                annotation_yshift=10
            )
            
            # Dynamic height based on number of markets (28px per bar)
            chart_height = len(top_markets) * 28 + 60
            
            fig_markets.update_layout(
                template='plotly_white',
                height=chart_height,
                font=dict(size=15),
                yaxis=dict(autorange="reversed", tickfont=dict(size=13)),
                xaxis_title="Downtime %",
                xaxis=dict(tickfont=dict(size=13), title=dict(font=dict(size=15))),
                margin=dict(l=10, r=80, t=30, b=40)
            )
            
            # Wrap in scrollable container (show ~15 markets initially = 420px)
            with st.container(height=420, border=False):
                st.plotly_chart(fig_markets, use_container_width=True, config=CHART_CONFIG, key="unavail_markets")
    
    with row2_col3:
        # Add time aggregation selector
        time_agg = st.radio("View:", ["Daily", "Weekly", "Monthly"], horizontal=True, key="time_agg_combo", label_visibility="collapsed")
        st.markdown(f"### 📊 {time_agg} Availability & Downtime")
        st.markdown(f"<span style='font-size:0.75rem;color:#888;'>{start_date} - {end_date}</span>", unsafe_allow_html=True)
        
        if not daily_focus_data.empty and not daily_data.empty:
            daily_focus_data['DATE'] = pd.to_datetime(daily_focus_data['DATE_VALUE'])
            daily_data['DATE'] = pd.to_datetime(daily_data['DATE_VALUE'])
            daily_data = daily_data.sort_values('DATE')
            
            # Aggregate based on selection
            if time_agg == "Weekly":
                # Weekly aggregation - use week start date as string label
                daily_focus_data['PERIOD'] = daily_focus_data['DATE'].dt.to_period('W').dt.start_time
                daily_focus_data['PERIOD_LABEL'] = daily_focus_data['PERIOD'].dt.strftime('%m/%d')
                daily_data['PERIOD'] = daily_data['DATE'].dt.to_period('W').dt.start_time
                daily_data['PERIOD_LABEL'] = daily_data['PERIOD'].dt.strftime('%m/%d')
                use_string_labels = True
            elif time_agg == "Monthly":
                # Monthly aggregation - use month name as string label to avoid duplicate ticks
                daily_focus_data['PERIOD'] = daily_focus_data['DATE'].dt.to_period('M').dt.start_time
                daily_focus_data['PERIOD_LABEL'] = daily_focus_data['PERIOD'].dt.strftime('%b %Y')
                daily_data['PERIOD'] = daily_data['DATE'].dt.to_period('M').dt.start_time
                daily_data['PERIOD_LABEL'] = daily_data['PERIOD'].dt.strftime('%b %Y')
                use_string_labels = True
            else:
                # Daily (default)
                daily_focus_data['PERIOD'] = daily_focus_data['DATE']
                daily_focus_data['PERIOD_LABEL'] = daily_focus_data['DATE'].dt.strftime('%m/%d')
                daily_data['PERIOD'] = daily_data['DATE']
                daily_data['PERIOD_LABEL'] = daily_data['DATE'].dt.strftime('%m/%d')
                use_string_labels = False
            
            # Aggregate focus data by period (include PERIOD_LABEL for charting)
            focus_agg = daily_focus_data.groupby(['PERIOD', 'PERIOD_LABEL', 'SITE_ID_FOCUS_CATEGORY'])['TOTAL_DOWNTIME'].sum().reset_index()
            
            # Aggregate availability data by period (use N/D for accurate aggregation)
            avail_agg = daily_data.groupby(['PERIOD', 'PERIOD_LABEL']).agg({
                'TOTAL_N': 'sum',
                'TOTAL_D': 'sum'
            }).reset_index()
            avail_agg['AVAILABILITY_PCT'] = (avail_agg['TOTAL_N'] / avail_agg['TOTAL_D']) * 100
            avail_agg = avail_agg.sort_values('PERIOD')
            
            # Get unique periods and labels
            periods = sorted(focus_agg['PERIOD'].unique())
            period_labels = focus_agg.drop_duplicates('PERIOD').sort_values('PERIOD')['PERIOD_LABEL'].tolist()
            
            # Get top categories by total downtime
            cat_totals = focus_agg.groupby('SITE_ID_FOCUS_CATEGORY')['TOTAL_DOWNTIME'].sum().reset_index()
            cat_totals = cat_totals.sort_values('TOTAL_DOWNTIME', ascending=False)
            top_cats = cat_totals['SITE_ID_FOCUS_CATEGORY'].tolist()
            
            # Pivot data for stacked bars - normalize to 100%
            # Use PERIOD_LABEL as index for clean x-axis labels
            pivot_data = focus_agg.pivot_table(
                index='PERIOD_LABEL', 
                columns='SITE_ID_FOCUS_CATEGORY', 
                values='TOTAL_DOWNTIME', 
                aggfunc='sum'
            ).fillna(0)
            
            # Reorder index to match chronological order
            pivot_data = pivot_data.reindex(period_labels)
            
            # Calculate percentage of period total for each category
            period_totals = pivot_data.sum(axis=1)
            pivot_pct = pivot_data.div(period_totals, axis=0) * 100
            
            # Create figure with secondary y-axis
            fig_combo = go.Figure()
            
            # Add stacked bars for each category (normalized to 100%)
            for cat in reversed(top_cats):  # Reverse so first category is at bottom
                if cat in pivot_pct.columns:
                    color = FOCUS_CATEGORY_COLORS.get(cat, DEFAULT_FOCUS_COLOR)
                    fig_combo.add_trace(go.Bar(
                        x=pivot_pct.index,
                        y=pivot_pct[cat],
                        name=cat,
                        marker_color=color,
                        hovertemplate=f'<b>{cat}</b><br>%{{y:.1f}}% of {time_agg.lower()} downtime<extra></extra>',
                        showlegend=False
                    ))
            
            # Add availability line (on secondary y-axis) - use PERIOD_LABEL for x
            fig_combo.add_trace(go.Scatter(
                x=avail_agg['PERIOD_LABEL'],
                y=avail_agg['AVAILABILITY_PCT'],
                mode='lines+markers',
                name=f'{time_agg} Avail %',
                line=dict(color='#22c55e', width=3),
                marker=dict(size=8, color='#22c55e'),
                yaxis='y2',
                hovertemplate='<b>%{x}</b><br>Availability: %{y:.2f}%<extra></extra>'
            ))
            
            # Add aggregated availability line (horizontal line on secondary y-axis)
            fig_combo.add_trace(go.Scatter(
                x=[period_labels[0], period_labels[-1]] if period_labels else [],
                y=[overall_avail, overall_avail],
                mode='lines',
                name=f'Agg ({overall_avail:.2f}%)',
                line=dict(color='#f59e0b', width=2, dash='dot'),
                yaxis='y2',
                hovertemplate=f'Aggregate: {overall_avail:.2f}%<extra></extra>'
            ))
            
            # Calculate dynamic y2 range based on data
            min_avail = avail_agg['AVAILABILITY_PCT'].min() if not avail_agg.empty else 99.5
            y2_min = max(99.0, min_avail - 0.2)
            
            # Configure x-axis - use category type for string labels
            xaxis_config = dict(
                title='',
                tickfont=dict(size=13),
                type='category'  # Force category axis for clean labels
            )
            
            fig_combo.update_layout(
                template='plotly_white',
                height=420,
                barmode='stack',
                font=dict(size=15),
                xaxis=xaxis_config,
                yaxis=dict(
                    title='',
                    range=[0, 100],
                    showticklabels=False
                ),
                yaxis2=dict(
                    title='',
                    overlaying='y',
                    side='right',
                    range=[y2_min, 100],
                    tickformat='.2f',
                    tickfont=dict(size=13),
                    showgrid=False
                ),
                legend=dict(
                    orientation='h',
                    yanchor='top',
                    y=-0.06,
                    xanchor='center',
                    x=0.5,
                    font=dict(size=13),
                    bgcolor='rgba(0,0,0,0)'
                ),
                margin=dict(l=5, r=50, t=10, b=60)
            )
            
            st.plotly_chart(fig_combo, use_container_width=True, config=CHART_CONFIG, key="avail_category_combo")
    
    # ===== ROW 3: Focus Category Breakdown by Market (Compact) =====
    selected_market = filters.get('market') if filters else None
    market_display = get_market_display_name(selected_market)
    is_single = is_single_market_selected(selected_market)
    
    if selected_market:
        # When a market is selected, fetch ALL market data (without market filter) for comparison
        # Build filter clause without market filter
        filters_no_market = {k: v for k, v in filters.items() if k != 'market'} if filters else {}
        avail_filter_no_market = build_filter_clause(filters_no_market, 'availability')
        
        # Fetch all market data for comparison view
        all_market_raw = get_unavailability_data(conn, start_date, end_date, days, selected_site_types, avail_filter_no_market, oem_filter)
        
        if not all_market_raw.empty:
            for col in ['TOTAL_DOWNTIME', 'TOTAL_N', 'TOTAL_D']:
                if col in all_market_raw.columns:
                    all_market_raw[col] = pd.to_numeric(all_market_raw[col], errors='coerce').fillna(0)
            
            # Aggregate market/focus data from all markets
            all_market_focus = all_market_raw.groupby(['MARKET_ID', 'SITE_ID_FOCUS_CATEGORY']).agg({
                'TOTAL_DOWNTIME': 'sum',
                'TOTAL_D': 'sum'
            }).reset_index()
            
            all_market_totals = all_market_raw.groupby('MARKET_ID')['TOTAL_D'].sum().reset_index()
            all_market_totals.columns = ['MARKET_ID', 'MARKET_TOTAL_D']
            all_market_focus = all_market_focus.merge(all_market_totals, on='MARKET_ID', how='left')
            all_market_focus['UNAVAILABILITY_PCT'] = (all_market_focus['TOTAL_DOWNTIME'] / all_market_focus['MARKET_TOTAL_D'].replace(0, float('nan'))) * 100
            
            # Filter to selected market(s) - handle both single and multi-select
            if is_single:
                first_market = get_first_market(selected_market)
                selected_market_upper = first_market.upper()
                market_mask = all_market_focus['MARKET_ID'].str.upper().str.contains(selected_market_upper, na=False)
            else:
                # Multiple markets - match any of them
                market_list_upper = [m.upper() for m in selected_market]
                market_mask = all_market_focus['MARKET_ID'].str.upper().isin(market_list_upper)
            selected_market_data = all_market_focus[market_mask]
            
            # Calculate market-level unavailability
            market_unavail = 0
            if not selected_market_data.empty:
                mkt_total_d = selected_market_data['MARKET_TOTAL_D'].sum() if not is_single else selected_market_data['MARKET_TOTAL_D'].iloc[0]
                mkt_downtime = selected_market_data['TOTAL_DOWNTIME'].sum()
                market_unavail = (mkt_downtime / mkt_total_d * 100) if mkt_total_d > 0 else 0
            
            st.markdown(f"<h3 style='margin-top:-40px;'>📊 Unavailability % by Focus Category & Market - {market_display} <span style='color:#e20074;'>({market_unavail:.4f}% Unavailability)</span></h3>", unsafe_allow_html=True)
            
            # Get top 6 categories for selected market by downtime
            cat_totals = selected_market_data.groupby('SITE_ID_FOCUS_CATEGORY')['TOTAL_DOWNTIME'].sum().reset_index()
            top_categories = cat_totals.nlargest(6, 'TOTAL_DOWNTIME')['SITE_ID_FOCUS_CATEGORY'].tolist()
            
            # Max unavailability for bar scaling
            max_unavail = selected_market_data['UNAVAILABILITY_PCT'].max() if not selected_market_data.empty else 1
            
            # Pre-compute category data dict for faster lookup
            cat_data_dict = {cat: selected_market_data[selected_market_data['SITE_ID_FOCUS_CATEGORY'] == cat].sort_values('UNAVAILABILITY_PCT', ascending=False) 
                           for cat in top_categories}
            
            # Create 3x2 grid for focus categories
            num_cols = 3
            rows = [top_categories[i:i+num_cols] for i in range(0, len(top_categories), num_cols)]
            
            for row_cats in rows:
                cols = st.columns(len(row_cats))
                for idx, cat in enumerate(row_cats):
                    with cols[idx]:
                        cat_data = cat_data_dict.get(cat, selected_market_data.iloc[0:0])
                        color = FOCUS_CATEGORY_COLORS.get(cat, DEFAULT_FOCUS_COLOR)
                        
                        # Build compact HTML
                        html = f'<div style="font-size:1rem;font-weight:bold;color:{color};margin-bottom:6px;">{cat}</div>'
                        html += '<div style="height:130px;overflow-y:auto;overflow-x:hidden;">'
                        
                        if not cat_data.empty:
                            for _, row in cat_data.iterrows():
                                pct = row['UNAVAILABILITY_PCT']
                                bar_width = min((pct / max_unavail) * 100, 100) if max_unavail > 0 else 0
                                html += f'''<div style="display:flex;align-items:center;margin-bottom:4px;">
                                    <span style="font-size:0.85rem;width:95px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:bold;color:#e20074;">{row['MARKET_ID']}</span>
                                    <div style="flex:1;height:16px;background:#ffffff;border-radius:2px;margin:0 4px;border:2px solid #e20074;">
                                        <div style="width:{bar_width}%;height:100%;background:{color};border-radius:2px;"></div>
                                    </div>
                                    <span style="font-size:0.85rem;width:50px;text-align:right;font-weight:bold;color:#e20074;">{pct:.2f}%</span>
                                </div>'''
                        else:
                            html += '<div style="font-size:0.85rem;color:#888;">No data for this category</div>'
                        
                        html += '</div>'
                        st.markdown(html, unsafe_allow_html=True)
        else:
            st.info(f"No market data available")
    else:
        # No market selected - show all markets grouped by category
        st.markdown("<h3 style='margin-top:-40px;'>📊 Unavailability % by Focus Category & Market</h3>", unsafe_allow_html=True)
        
        # Get unique focus categories
        if not market_focus_data.empty:
            # Filter to top 6 categories by total downtime
            cat_totals = market_focus_data.groupby('SITE_ID_FOCUS_CATEGORY')['TOTAL_DOWNTIME'].sum().reset_index()
            cat_totals = cat_totals.sort_values('TOTAL_DOWNTIME', ascending=False)
            top_categories = cat_totals.head(6)['SITE_ID_FOCUS_CATEGORY'].tolist()
            
            # Find max unavailability for consistent bar scaling
            max_unavail = market_focus_data['UNAVAILABILITY_PCT'].max()
            
            # Create 3x2 grid for focus categories using compact HTML
            num_cols = 3
            rows = [top_categories[i:i+num_cols] for i in range(0, len(top_categories), num_cols)]
            
            for row_cats in rows:
                cols = st.columns(len(row_cats))
                for idx, cat in enumerate(row_cats):
                    with cols[idx]:
                        cat_data = market_focus_data[market_focus_data['SITE_ID_FOCUS_CATEGORY'] == cat].copy()
                        cat_data = cat_data.sort_values('UNAVAILABILITY_PCT', ascending=False)
                        
                        color = FOCUS_CATEGORY_COLORS.get(cat, DEFAULT_FOCUS_COLOR)
                        
                        # Build compact HTML with mini bars in scrollable container
                        html = f'<div style="font-size:1rem;font-weight:bold;color:{color};margin-bottom:6px;">{cat}</div>'
                        html += '<div style="height:130px;overflow-y:auto;overflow-x:hidden;">'
                        
                        if not cat_data.empty:
                            for _, row in cat_data.iterrows():
                                mkt = row['MARKET_ID']
                                pct = row['UNAVAILABILITY_PCT']
                                bar_width = min((pct / max_unavail) * 100, 100) if max_unavail > 0 else 0
                                html += f'''<div style="display:flex;align-items:center;margin-bottom:4px;">
                                    <span style="font-size:0.85rem;width:95px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{mkt}</span>
                                    <div style="flex:1;height:16px;background:#ffffff;border-radius:2px;margin:0 4px;">
                                        <div style="width:{bar_width}%;height:100%;background:{color};border-radius:2px;"></div>
                                    </div>
                                    <span style="font-size:0.85rem;width:50px;text-align:right;">{pct:.2f}%</span>
                                </div>'''
                        
                        html += '</div>'
                        st.markdown(html, unsafe_allow_html=True)
    
    st.divider()
    
    # ===== ROW 4: Availability Trend =====
    st.markdown("### 📈 Availability % & Category Downtime %")
    st.markdown(f"<span style='font-size:0.75rem;color:#888;'>{start_date} - {end_date}</span>", unsafe_allow_html=True)
    
    if not daily_data.empty:
        daily_data['DATE'] = pd.to_datetime(daily_data['DATE_VALUE']).dt.date
        daily_data = daily_data.sort_values('DATE')
        
        fig_trend = go.Figure()
        
        # Add unavailability line
        fig_trend.add_trace(go.Scatter(
            x=daily_data['DATE'],
            y=daily_data['UNAVAILABILITY_PCT'],
            mode='lines+markers',
            name='Downtime %',
            line=dict(color='#ef4444', width=2),
            marker=dict(size=6),
            yaxis='y2'
        ))
        
        # Add availability line
        avail_pct = 100 - daily_data['UNAVAILABILITY_PCT']
        fig_trend.add_trace(go.Scatter(
            x=daily_data['DATE'],
            y=avail_pct,
            mode='lines+markers',
            name='Availability %',
            line=dict(color='#22c55e', width=2),
            marker=dict(size=6)
        ))
        
        avail_min = float(avail_pct.min()) if len(avail_pct) > 0 else 99
        avail_max = float(avail_pct.max()) if len(avail_pct) > 0 else 100
        avail_padding = max((avail_max - avail_min) * 0.1, 0.2)
        avail_range = [max(0, avail_min - avail_padding), min(100, avail_max + avail_padding)]

        dt_vals = daily_data['UNAVAILABILITY_PCT']
        dt_max = float(dt_vals.max()) if len(dt_vals) > 0 else 1
        dt_padding = max(dt_max * 0.1, 0.05)
        dt_range = [0, dt_max + dt_padding]

        fig_trend.update_layout(
            template='plotly_white',
            height=400,
            font=dict(size=14),
            legend=dict(orientation='h', yanchor='top', y=-0.15, xanchor='center', x=0.5, font=dict(size=12)),
            yaxis=dict(title='Availability %', range=avail_range, tickfont=dict(size=12), title_font=dict(size=14)),
            yaxis2=dict(title='Downtime %', overlaying='y', side='right', range=dt_range, tickfont=dict(size=12), title_font=dict(size=14)),
            xaxis=dict(tickfont=dict(size=12)),
            margin=dict(l=10, r=10, t=10, b=80)
        )
        st.plotly_chart(fig_trend, use_container_width=True, config=CHART_CONFIG, key="unavail_trend")
    
    # ===== SITE-LEVEL UNAVAILABILITY ANALYSIS =====
    st.divider()
    st.markdown("### 🔧 Site-Level Unavailability Analysis")
    st.markdown("<span style='font-size:0.9rem;color:#888;'>Identify which sites contribute most to unavailability and potential improvement from fixing them</span>", unsafe_allow_html=True)
    
    # Use the CORRECT overall values from the main calculation (not from site-level query)
    # These are already calculated above from focus_cat_data which has ALL data
    main_total_n = float(focus_cat_data['TOTAL_N'].sum()) if not focus_cat_data.empty else 0
    main_total_d = float(focus_cat_data['TOTAL_D'].sum()) if not focus_cat_data.empty else 0
    main_overall_unavail = overall_unavail  # Already calculated above as 0.13%
    main_overall_avail = overall_avail      # Already calculated above as 99.87%
    main_total_unavail_seconds = main_total_d - main_total_n  # Total unavailability in same units
    main_total_downtime = float(focus_cat_data['TOTAL_DOWNTIME'].sum()) if not focus_cat_data.empty and 'TOTAL_DOWNTIME' in focus_cat_data.columns else 0
    
    # Display overall Availability/Unavailability tiles (consistent with top of page)
    avail_tile_col1, avail_tile_col2, avail_tile_col3 = st.columns(3)
    
    with avail_tile_col1:
        st.markdown(f"""
        <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:12px;padding:clamp(14px, 2vw, 20px);text-align:left;border-left:4px solid #22c55e;height:130px;display:flex;flex-direction:column;justify-content:space-between;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div style="font-size:clamp(2rem, 3.5vw, 3rem);font-weight:bold;color:#22c55e;line-height:1;">{main_overall_avail:.2f}%</div>
                <div style="min-height:40px;text-align:right;"><div style="font-size:clamp(0.75rem, 1vw, 0.85rem);color:#666;">Goal: ≥99.85%</div></div>
            </div>
            <div style="font-size:clamp(0.85rem, 1.2vw, 1.1rem);color:#aaa;">Availability %</div>
        </div>
        """, unsafe_allow_html=True)
    
    with avail_tile_col2:
        st.markdown(f"""
        <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:12px;padding:clamp(14px, 2vw, 20px);text-align:left;border-left:4px solid #ef4444;height:130px;display:flex;flex-direction:column;justify-content:space-between;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div style="font-size:clamp(2rem, 3.5vw, 3rem);font-weight:bold;color:#ef4444;line-height:1;">{main_overall_unavail:.2f}%</div>
                <div style="min-height:40px;text-align:right;"><div style="font-size:clamp(0.75rem, 1vw, 0.85rem);color:#666;">Goal: ≤0.15%</div></div>
            </div>
            <div style="font-size:clamp(0.85rem, 1.2vw, 1.1rem);color:#aaa;">Unavailability %</div>
        </div>
        """, unsafe_allow_html=True)
    
    with avail_tile_col3:
        # Format downtime nicely
        if main_total_downtime >= 1e9:
            downtime_display = f"{main_total_downtime/1e9:.2f}B"
        elif main_total_downtime >= 1e6:
            downtime_display = f"{main_total_downtime/1e6:.1f}M"
        else:
            downtime_display = f"{main_total_downtime:,.0f}"
        
        # Calculate budget (0.15% of total seconds)
        downtime_budget = main_total_d * 0.0015 if main_total_d > 0 else 0
        downtime_over_under = main_total_downtime - downtime_budget
        is_over_budget = downtime_over_under > 0
        
        # Format budget display
        if downtime_budget >= 1e9:
            budget_display = f"{downtime_budget/1e9:.2f}B"
        elif downtime_budget >= 1e6:
            budget_display = f"{downtime_budget/1e6:.1f}M"
        else:
            budget_display = f"{downtime_budget:,.0f}"
        
        # Format over/under display
        if abs(downtime_over_under) >= 1e9:
            over_under_display = f"{abs(downtime_over_under)/1e9:.2f}B"
        elif abs(downtime_over_under) >= 1e6:
            over_under_display = f"{abs(downtime_over_under)/1e6:.1f}M"
        else:
            over_under_display = f"{abs(downtime_over_under):,.0f}"
        
        over_under_color = "#ef4444" if is_over_budget else "#22c55e"
        over_under_sign = "+" if is_over_budget else "-"
        over_under_icon = "🔴" if is_over_budget else "🟢"
        
        st.markdown(f"""
        <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:12px;padding:clamp(14px, 2vw, 20px);text-align:left;border-left:4px solid #e20074;height:130px;display:flex;flex-direction:column;justify-content:space-between;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div style="font-size:clamp(2rem, 3.5vw, 3rem);font-weight:bold;color:#e20074;line-height:1;">{downtime_display}</div>
                <div style="min-height:40px;text-align:right;">
                    <div style="font-size:clamp(0.7rem, 0.9vw, 0.8rem);color:#888;">Budget: {budget_display}</div>
                    <div style="font-size:clamp(0.75rem, 1vw, 0.85rem);color:{over_under_color};font-weight:bold;">{over_under_sign}{over_under_display} {over_under_icon}</div>
                </div>
            </div>
            <div style="font-size:clamp(0.85rem, 1.2vw, 1.1rem);color:#aaa;">Total Downtime</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<div style='margin-top:15px;'></div>", unsafe_allow_html=True)
    
    # Collect pre-fetched site-level data from background thread
    with st.spinner("Loading site-level data..."):
        site_data = site_data_future.result()
    
    if not site_data.empty:
        # Convert Decimal to float in bulk (optimized)
        numeric_cols = ['TOTAL_DOWNTIME', 'TOTAL_N', 'TOTAL_D', 'SITE_UNAVAIL_SECONDS']
        for col in numeric_cols:
            if col in site_data.columns:
                site_data[col] = pd.to_numeric(site_data[col], errors='coerce').fillna(0)
        
        # Calculate site-level downtime total (for % of downtime calculations)
        total_downtime = site_data['TOTAL_DOWNTIME'].sum()
        
        # SITE_UNAVAIL_SECONDS is now pre-computed in SQL, no need to recalculate
        # Data already sorted by SITE_UNAVAIL_SECONDS DESC from SQL
        
        # Use the larger of main_total_downtime (aggregate query) and total_downtime (site query)
        # to ensure PCT never exceeds 100%. Both should agree after the SQL fix, but max() is a safeguard.
        pct_denominator = max(main_total_downtime, total_downtime) if main_total_downtime > 0 or total_downtime > 0 else 0
        if pct_denominator > 0:
            site_data['PCT_OF_UNAVAIL'] = site_data['TOTAL_DOWNTIME'] / pct_denominator * 100
        else:
            site_data['PCT_OF_UNAVAIL'] = 0
        
        # SITE_UNAVAIL_CONTRIBUTION uses main_total_d from aggregate query for Pareto/projection
        if main_total_d > 0:
            site_data['SITE_UNAVAIL_CONTRIBUTION'] = site_data['SITE_UNAVAIL_SECONDS'] / main_total_d * 100
        else:
            site_data['SITE_UNAVAIL_CONTRIBUTION'] = 0
        
        # site_total_unavail for cumulative Pareto analysis
        site_total_unavail = site_data['SITE_UNAVAIL_SECONDS'].sum()
        site_data['CUMULATIVE_UNAVAIL_SECONDS'] = site_data['SITE_UNAVAIL_SECONDS'].cumsum()
        
        if site_total_unavail > 0:
            site_data['CUMULATIVE_PCT'] = site_data['CUMULATIVE_UNAVAIL_SECONDS'] / site_total_unavail * 100
        else:
            site_data['CUMULATIVE_PCT'] = 0
            
        if main_total_d > 0:
            site_data['CUMULATIVE_UNAVAIL_FIXED'] = site_data['CUMULATIVE_UNAVAIL_SECONDS'] / main_total_d * 100
        else:
            site_data['CUMULATIVE_UNAVAIL_FIXED'] = 0
            
        site_data['NEW_AVAIL_IF_FIXED'] = main_overall_avail + site_data['CUMULATIVE_UNAVAIL_FIXED']
        
        # ===== KPI Row =====
        kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
        
        # Data already filtered to SITE_UNAVAIL_SECONDS > 0 in SQL, just count unique sites
        total_sites_with_downtime = site_data['SITE_ID'].nunique()
        # Top 50/100 sites' share of the overall unavailability
        top_50_unavail = site_data.head(50)['SITE_UNAVAIL_CONTRIBUTION'].sum()
        top_50_pct_of_unavail = site_data.head(50)['PCT_OF_UNAVAIL'].sum()
        top_50_projected_avail = round(main_overall_avail, 2) + round(top_50_unavail, 2)
        top_100_unavail = site_data.head(100)['SITE_UNAVAIL_CONTRIBUTION'].sum()
        top_100_pct_of_unavail = site_data.head(100)['PCT_OF_UNAVAIL'].sum()
        top_100_projected_avail = round(main_overall_avail, 2) + round(top_100_unavail, 2)
        
        # How many sites needed to reach 80% of unavailability
        sites_for_80pct = min(len(site_data[site_data['CUMULATIVE_PCT'] <= 80]) + 1, len(site_data))
        
        with kpi_col1:
            st.markdown(f"""
            <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:12px;padding:clamp(14px, 2vw, 20px);text-align:left;border-left:4px solid #e20074;height:130px;display:flex;flex-direction:column;justify-content:space-between;">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div style="font-size:clamp(2rem, 3.5vw, 3rem);font-weight:bold;color:#e20074;line-height:1;">{total_sites_with_downtime:,}</div>
                    <div style="min-height:40px;text-align:right;"><div style="font-size:clamp(0.75rem, 1vw, 0.85rem);color:#666;">total sites</div></div>
                </div>
                <div style="font-size:clamp(0.85rem, 1.2vw, 1.1rem);color:#aaa;">Sites with Unavailability</div>
            </div>
            """, unsafe_allow_html=True)
        
        with kpi_col2:
            st.markdown(f"""
            <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:12px;padding:clamp(14px, 2vw, 20px);text-align:left;border-left:4px solid #ef4444;height:130px;display:flex;flex-direction:column;justify-content:space-between;position:relative;">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div style="font-size:clamp(2rem, 3.5vw, 3rem);font-weight:bold;color:#ef4444;line-height:1;">{top_50_unavail:.2f}%</div>
                    <div style="min-height:40px;text-align:right;"><div style="font-size:clamp(0.75rem, 1vw, 0.85rem);color:#666;">{top_50_pct_of_unavail:.0f}% of unavail</div></div>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:flex-end;">
                    <div style="font-size:clamp(0.85rem, 1.2vw, 1.1rem);color:#aaa;">Top 50 Sites</div>
                    <div style="font-size:0.8rem;color:#22c55e;font-weight:600;">Projected: {top_50_projected_avail:.2f}%</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        with kpi_col3:
            st.markdown(f"""
            <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:12px;padding:clamp(14px, 2vw, 20px);text-align:left;border-left:4px solid #f59e0b;height:130px;display:flex;flex-direction:column;justify-content:space-between;position:relative;">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div style="font-size:clamp(2rem, 3.5vw, 3rem);font-weight:bold;color:#f59e0b;line-height:1;">{top_100_unavail:.2f}%</div>
                    <div style="min-height:40px;text-align:right;"><div style="font-size:clamp(0.75rem, 1vw, 0.85rem);color:#666;">{top_100_pct_of_unavail:.0f}% of unavail</div></div>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:flex-end;">
                    <div style="font-size:clamp(0.85rem, 1.2vw, 1.1rem);color:#aaa;">Top 100 Sites</div>
                    <div style="font-size:0.8rem;color:#22c55e;font-weight:600;">Projected: {top_100_projected_avail:.2f}%</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        with kpi_col4:
            st.markdown(f"""
            <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:12px;padding:clamp(14px, 2vw, 20px);text-align:left;border-left:4px solid #22c55e;height:130px;display:flex;flex-direction:column;justify-content:space-between;">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div style="font-size:clamp(2rem, 3.5vw, 3rem);font-weight:bold;color:#22c55e;line-height:1;">{sites_for_80pct}</div>
                    <div style="min-height:40px;text-align:right;"><div style="font-size:clamp(0.75rem, 1vw, 0.85rem);color:#666;">80% of unavail</div></div>
                </div>
                <div style="font-size:clamp(0.85rem, 1.2vw, 1.1rem);color:#aaa;">Sites for 80% Impact</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("<div style='margin-top:1rem;'></div>", unsafe_allow_html=True)
        
        # ===== Charts Row =====
        chart_col1, chart_col2 = st.columns(2)
        
        with chart_col1:
            st.markdown("#### 📊 Top 100 Sites - Unavailability Contribution")
            st.markdown(f"<span style='font-size:0.8rem;color:#888;'>Each site's share of the {main_overall_unavail:.2f}% total unavailability (sum = {main_overall_unavail:.2f}%)</span>", unsafe_allow_html=True)
            
            top_100 = site_data.head(100).copy()
            
            # Color by focus category
            top_100['COLOR'] = top_100['SITE_ID_FOCUS_CATEGORY'].apply(
                lambda x: FOCUS_CATEGORY_COLORS.get(x, DEFAULT_FOCUS_COLOR)
            )
            
            fig_sites = go.Figure()
            
            # Create text with focus category and value
            bar_text = [f"{cat} | {v:.4f}%" for cat, v in zip(top_100['SITE_ID_FOCUS_CATEGORY'], top_100['SITE_UNAVAIL_CONTRIBUTION'])]
            
            fig_sites.add_trace(go.Bar(
                y=top_100['SITE_ID'],
                x=top_100['SITE_UNAVAIL_CONTRIBUTION'],
                orientation='h',
                marker_color=top_100['COLOR'],
                text=bar_text,
                textposition='inside',
                insidetextanchor='end',
                textfont=dict(size=16, color='white', family='Arial Black'),
                customdata=list(zip(
                    top_100['MARKET_ID'], 
                    top_100['SITE_ID_FOCUS_CATEGORY'],
                    top_100['SITE_UNAVAIL_CONTRIBUTION'],
                    top_100['PCT_OF_UNAVAIL']
                )),
                hovertemplate="<b>%{y}</b><br>" +
                              "Market: %{customdata[0]}<br>" +
                              "Category: %{customdata[1]}<br>" +
                              "Contribution: %{customdata[2]:.4f}%<br>" +
                              "% of Total: %{customdata[3]:.1f}%" +
                              "<extra></extra>"
            ))
            
            # Calculate height based on number of sites (30px per bar for larger text)
            chart_height = max(600, len(top_100) * 30)
            
            fig_sites.update_layout(
                template='plotly_white',
                height=chart_height,
                font=dict(size=14),
                yaxis=dict(autorange="reversed", tickfont=dict(size=13, family='Arial')),
                xaxis=dict(title="Unavailability Contribution %", tickformat=".4f", tickfont=dict(size=12)),
                margin=dict(l=130, r=20, t=10, b=40),
                showlegend=False,
                hovermode='y unified'
            )
            
            # Update hoverlabel for all traces
            fig_sites.update_traces(
                hoverlabel=HOVER_LABEL_STYLE,
            )
            
            # Use container with scrollbar for 100 sites
            with st.container(height=550):
                st.plotly_chart(fig_sites, use_container_width=True, config=CHART_CONFIG, key="site_unavail_bar")
        
        with chart_col2:
            st.markdown("#### 📈 Improvement Potential (Pareto Analysis)")
            
            # Show what availability would be if we fixed top N sites
            top_50 = site_data.head(50).copy()
            top_50['SITE_NUM'] = range(1, len(top_50) + 1)
            
            # Calculate before/after availability (use rounded values for visual consistency)
            before_avail = round(main_overall_avail, 2)
            top_50_contrib = round(site_data.head(50)['SITE_UNAVAIL_CONTRIBUTION'].sum(), 2)
            after_avail = before_avail + top_50_contrib
            improvement = top_50_contrib
            
            # Show before → after with improvement
            st.markdown(f"""
            <div style='display:flex; align-items:center; gap:15px; margin-bottom:10px;'>
                <div style='text-align:center;'>
                    <div style='font-size:0.7rem;color:#888;'>BEFORE</div>
                    <div style='font-size:1.3rem;font-weight:bold;color:#ef4444;'>{before_avail:.2f}%</div>
                </div>
                <div style='font-size:1.5rem;color:#22c55e;'>→</div>
                <div style='text-align:center;'>
                    <div style='font-size:0.7rem;color:#888;'>AFTER (Top 50 Fixed)</div>
                    <div style='font-size:1.3rem;font-weight:bold;color:#22c55e;'>{after_avail:.2f}%</div>
                </div>
                <div style='text-align:center;background:#f8f9fa;padding:5px 10px;border-radius:5px;'>
                    <div style='font-size:0.7rem;color:#888;'>IMPROVEMENT</div>
                    <div style='font-size:1.1rem;font-weight:bold;color:#22c55e;'>+{improvement:.3f}%</div>
                </div>
                <div style='text-align:center;margin-left:auto;'>
                    <div style='font-size:0.7rem;color:#888;'>GOAL</div>
                    <div style='font-size:1.1rem;font-weight:bold;color:#f59e0b;'>99.85%</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Create x and y values including starting point (0 sites fixed = current state)
            x_vals = [0] + top_50['SITE_NUM'].tolist()
            avail_vals = [main_overall_avail] + top_50['NEW_AVAIL_IF_FIXED'].tolist()
            cumulative_vals = [0] + top_50['CUMULATIVE_PCT'].tolist()
            
            fig_pareto = go.Figure()
            
            # Bar: Cumulative % of downtime fixed (starts at 0)
            fig_pareto.add_trace(go.Bar(
                x=x_vals,
                y=cumulative_vals,
                name='Cumulative % Fixed',
                marker_color='#e20074',
                opacity=0.7,
                customdata=list(zip(x_vals, cumulative_vals)),
                hovertemplate="<b>Sites Fixed: %{customdata[0]}</b><br>" +
                              "Cumulative: %{customdata[1]:.1f}% of unavailability" +
                              "<extra></extra>"
            ))
            
            # Line: Availability starting from current and improving
            fig_pareto.add_trace(go.Scatter(
                x=x_vals,
                y=avail_vals,
                mode='lines+markers',
                name='Availability %',
                line=dict(color='#22c55e', width=3),
                marker=dict(size=6),
                yaxis='y2',
                customdata=list(zip(x_vals, avail_vals)),
                hovertemplate="<b>Sites Fixed: %{customdata[0]}</b><br>" +
                              "Availability: %{customdata[1]:.2f}%" +
                              "<extra></extra>"
            ))
            
            # Add goal line at 99.85% with better positioned annotation
            fig_pareto.add_hline(
                y=99.85,
                line_dash="dash",
                line_color="#f59e0b",
                line_width=2,
                yref='y2'
            )
            # Add goal text annotation on the left side for better readability
            fig_pareto.add_annotation(
                x=0,
                y=99.85,
                xref="x",
                yref="y2",
                text="Goal: 99.85%",
                showarrow=False,
                font=dict(size=11, color="#f59e0b", weight="bold"),
                bgcolor="rgba(30, 30, 50, 0.8)",
                borderpad=3,
                xanchor="left",
                yanchor="bottom"
            )
            
            # Add annotation for the last data point on the availability line
            last_avail = avail_vals[-1] if avail_vals else main_overall_avail
            fig_pareto.add_annotation(
                x=x_vals[-1],
                y=last_avail,
                xref="x",
                yref="y2",
                text=f"{last_avail:.2f}%",
                showarrow=True,
                arrowhead=2,
                arrowsize=1,
                arrowwidth=1,
                arrowcolor="#22c55e",
                font=dict(size=11, color="#22c55e", weight="bold"),
                bgcolor="rgba(30, 30, 50, 0.8)",
                borderpad=3,
                ax=30,
                ay=-20
            )
            
            # Only show "sites needed" line if we're BELOW the goal
            sites_to_goal = pd.DataFrame()  # Initialize empty for later use
            if main_overall_avail < 99.85:
                sites_to_goal = top_50[top_50['NEW_AVAIL_IF_FIXED'] >= 99.85]
                if not sites_to_goal.empty:
                    sites_needed = int(sites_to_goal.iloc[0]['SITE_NUM'])
                    fig_pareto.add_vline(
                        x=sites_needed,
                        line_dash="dot",
                        line_color="#22c55e",
                        line_width=2,
                        annotation_text=f"{sites_needed} sites needed",
                        annotation_position="top",
                        annotation_font_size=11,
                        annotation_font_color="#22c55e"
                    )
            
            # Set y2 axis range based on current availability
            y2_min = min(main_overall_avail - 0.05, 99.80)
            
            # Set y1 (cumulative %) range based on actual data - start at 0 but cap at max + padding
            max_cumulative = max(cumulative_vals) if cumulative_vals else 100
            y1_max = min(max_cumulative * 1.2, 105)  # 20% padding, but cap at 105
            
            fig_pareto.update_layout(
                template='plotly_white',
                height=500,
                font=dict(size=12),
                legend=dict(orientation='h', yanchor='top', y=-0.12, xanchor='center', x=0.5, font=dict(size=11)),
                xaxis=dict(title="Number of Sites Fixed (ranked by impact)", tickfont=dict(size=11)),
                yaxis=dict(title="Cumulative % Fixed", range=[0, y1_max], tickfont=dict(size=11)),
                yaxis2=dict(title="Availability %", overlaying='y', side='right', range=[y2_min, 100], tickfont=dict(size=11)),
                margin=dict(l=60, r=60, t=10, b=80),
                hovermode='x unified'
            )
            
            # Update hoverlabel for all traces
            fig_pareto.update_traces(
                hoverlabel=HOVER_LABEL_STYLE,
            )
            st.plotly_chart(fig_pareto, use_container_width=True, config=CHART_CONFIG, key="site_pareto")
        
        # ===== Detailed Table =====
        total_sites_in_data = len(site_data)
        sites_displayed = min(100, total_sites_in_data)
        st.markdown(f"#### 📋 Site-Level Unavailability Details <span style='font-size:1rem;color:#e20074;font-weight:normal;'>({sites_displayed:,} of {total_sites_in_data:,} sites)</span>", unsafe_allow_html=True)
        
        # Show focus category breakdown for top 100 sites
        top_100_for_table = site_data.head(100)
        category_counts = top_100_for_table['SITE_ID_FOCUS_CATEGORY'].value_counts()
        category_breakdown = " | ".join([f"**{cat}**: {count}" for cat, count in category_counts.items()])
        st.markdown(f"**Focus Category Breakdown (Top 100):** {category_breakdown}")
        
        # Prepare display table
        display_cols = ['SITE_ID', 'MARKET_ID', 'OEM', 'SITE_ID_FOCUS_CATEGORY', 'SITE_ID_DETAIL_CATEGORY', 'PCT_OF_UNAVAIL', 'SITE_UNAVAIL_CONTRIBUTION', 'TOTAL_DOWNTIME', 'DAYS_WITH_DOWNTIME', 'COUNT_OF_TKTS', 'COTTR_MINUTES', 'COTTR_DAYS', 'CUSTOMER_MINUTES', 'FIRST_OUTAGE_DATE', 'LAST_OUTAGE_DATE', 'NEW_AVAIL_IF_FIXED', 'DESC_TOP_RECORDID', 'DESCRIPTION_1', 'DESCRIPTION_2', 'DESCRIPTION_3']
        # Ensure DAYS_WITH_DOWNTIME column exists (may not exist in cached data)
        if 'DAYS_WITH_DOWNTIME' not in site_data.columns:
            site_data['DAYS_WITH_DOWNTIME'] = 0
        # Ensure FIRST_OUTAGE_DATE column exists (may not exist in cached data)
        if 'FIRST_OUTAGE_DATE' not in site_data.columns:
            site_data['FIRST_OUTAGE_DATE'] = None
        # Ensure COUNT_OF_TKTS column exists (may not exist in cached data)
        if 'COUNT_OF_TKTS' not in site_data.columns:
            site_data['COUNT_OF_TKTS'] = 0
        # Ensure SITE_ID_DETAIL_CATEGORY column exists (may not exist in cached data)
        if 'SITE_ID_DETAIL_CATEGORY' not in site_data.columns:
            site_data['SITE_ID_DETAIL_CATEGORY'] = None
        # Ensure COTTR_MINUTES column exists (may not exist in cached data)
        if 'COTTR_MINUTES' not in site_data.columns:
            site_data['COTTR_MINUTES'] = 0
        # Ensure COTTR_DAYS column exists (may not exist in cached data)
        if 'COTTR_DAYS' not in site_data.columns:
            site_data['COTTR_DAYS'] = 0
        # Ensure CUSTOMER_MINUTES column exists (may not exist in cached data)
        if 'CUSTOMER_MINUTES' not in site_data.columns:
            site_data['CUSTOMER_MINUTES'] = 0
        if 'OEM' not in site_data.columns:
            site_data['OEM'] = 'Unknown'
        for desc_col in ['DESC_TOP_RECORDID', 'DESCRIPTION_1', 'DESCRIPTION_2', 'DESCRIPTION_3']:
            if desc_col not in site_data.columns:
                site_data[desc_col] = ''
        display_df = site_data.head(100)[display_cols].copy()
        
        # Add rank column as first column
        display_df.insert(0, 'Rank', range(1, len(display_df) + 1))
        display_df['Rank'] = display_df['Rank'].apply(lambda x: f"#{x}")
        
        display_df.columns = ['Rank', 'Site ID', 'Market', 'OEM', 'Focus Category', 'Detail Category', '% of Total Unavail', 'Unavail Contribution %', 'Downtime (sec)', 'Days w/ Downtime', 'Count of Tkts', 'COTTR Mins', 'Days w/ COTTR', 'Cust Mins', 'First Outage Date', 'Last Outage Date', 'Avail % if Fixed', 'Desc Top Record', 'Desc 1', 'Desc 2', 'Desc 3']
        
        # Format columns using vectorized string formatting
        display_df['% of Total Unavail'] = display_df['% of Total Unavail'].map('{:.2f}%'.format)
        display_df['Unavail Contribution %'] = display_df['Unavail Contribution %'].map('{:.4f}%'.format)
        display_df['Downtime (sec)'] = display_df['Downtime (sec)'].map('{:,.0f}'.format)
        display_df['Days w/ Downtime'] = display_df['Days w/ Downtime'].astype(int)
        display_df['Count of Tkts'] = display_df['Count of Tkts'].astype(int)
        display_df['COTTR Mins'] = display_df['COTTR Mins'].map('{:,.0f}'.format)
        display_df['Days w/ COTTR'] = display_df['Days w/ COTTR'].astype(int)
        display_df['Cust Mins'] = display_df['Cust Mins'].map('{:,.0f}'.format)
        display_df['First Outage Date'] = pd.to_datetime(display_df['First Outage Date']).dt.strftime('%Y-%m-%d').fillna('N/A')
        display_df['Last Outage Date'] = pd.to_datetime(display_df['Last Outage Date']).dt.strftime('%Y-%m-%d').fillna('N/A')
        display_df['Avail % if Fixed'] = display_df['Avail % if Fixed'].map('{:.2f}%'.format)
        
        # Column configuration with tooltips for each column
        column_config = {
            "Rank": st.column_config.TextColumn("Rank", help="Site ranking by unavailability impact"),
            "Site ID": st.column_config.TextColumn("Site ID", help="Unique site identifier"),
            "Market": st.column_config.TextColumn("Market", help="Market region"),
            "OEM": st.column_config.TextColumn("OEM", help="Original Equipment Manufacturer (Ericsson/Nokia)"),
            "Focus Category": st.column_config.TextColumn("Focus Category", help="Primary outage category"),
            "Detail Category": st.column_config.TextColumn("Detail Category", help="Combined detail subcategories (e.g. Site Mod/Integration)"),
            "% of Total Unavail": st.column_config.TextColumn("% of Total Unavail", help="Site's percentage of total unavailability"),
            "Unavail Contribution %": st.column_config.TextColumn("Unavail Contribution %", help="Site's contribution to overall unavailability"),
            "Downtime (sec)": st.column_config.TextColumn("Downtime (sec)", help="Total downtime in seconds"),
            "Days w/ Downtime": st.column_config.NumberColumn("Days w/ Downtime", help="Number of days with recorded downtime"),
            "Count of Tkts": st.column_config.NumberColumn("Count of Tkts", help="Number of trouble tickets"),
            "COTTR Mins": st.column_config.TextColumn("COTTR Mins", help="Customer Outage Time to Restore in minutes"),
            "Days w/ COTTR": st.column_config.NumberColumn("Days w/ COTTR", help="Number of days with COTTR events"),
            "Cust Mins": st.column_config.TextColumn("Cust Mins", help="Total customer minutes impacted"),
            "First Outage Date": st.column_config.TextColumn("First Outage Date", help="Date of first recorded outage"),
            "Last Outage Date": st.column_config.TextColumn("Last Outage Date", help="Date of most recent outage"),
            "Avail % if Fixed": st.column_config.TextColumn("Avail % if Fixed", help="Projected availability if this site is fixed"),
            "Desc Top Record": st.column_config.TextColumn("Desc Top Record", help="TOP_RECORDID of the most recent ticket used for descriptions"),
            "Desc 1": st.column_config.TextColumn("Desc 1", help="Description 1 from most recent ticket"),
            "Desc 2": st.column_config.TextColumn("Desc 2", help="Description 2 from most recent ticket"),
            "Desc 3": st.column_config.TextColumn("Desc 3", help="Description 3 from most recent ticket"),
        }
        
        # Download button for CSV export
        csv_data = display_df.to_csv(index=False).encode('utf-8')
        download_col, spacer_col = st.columns([1, 5])
        with download_col:
            st.download_button(
                label="📥 Download CSV",
                data=csv_data,
                file_name="site_unavailability_details.csv",
                mime="text/csv",
                key="download_site_unavail_csv"
            )
        
        # Dataframe without fixed height - uses page scroll only (no double scrollbar)
        st.dataframe(display_df, use_container_width=True, hide_index=True, column_config=column_config)
        
        # ===== FORECAST SIMULATOR =====
        st.divider()
        st.markdown("### 🔮 Availability Forecast Simulator")
        st.markdown("<span style='font-size:0.9rem;color:#888;'>Simulate fixing sites to forecast availability improvement by category</span>", unsafe_allow_html=True)
        
        # Get category breakdown using correct unavailability metric
        category_summary = site_data.groupby('SITE_ID_FOCUS_CATEGORY').agg({
            'SITE_UNAVAIL_SECONDS': 'sum',
            'TOTAL_DOWNTIME': 'sum',
            'SITE_ID': 'count'
        }).reset_index()
        category_summary.columns = ['Category', 'Total Unavail', 'Total Downtime', 'Site Count']
        category_summary['PCT_OF_UNAVAIL'] = (category_summary['Total Unavail'] / main_total_unavail_seconds * 100) if main_total_unavail_seconds > 0 else 0
        category_summary['UNAVAIL_CONTRIBUTION'] = (category_summary['Total Unavail'] / main_total_d * 100) if main_total_d > 0 else 0
        category_summary = category_summary.sort_values('Total Unavail', ascending=False)
        
        # Simulator controls
        sim_col1, sim_col2 = st.columns([1, 2])
        
        with sim_col1:
            st.markdown("#### ⚙️ Simulation Settings")
            
            # Option to simulate by number of sites or by category
            sim_mode = st.radio("Simulate by:", ["Top N Sites", "Category Fix"], horizontal=True, key="sim_mode")
            
            if sim_mode == "Top N Sites":
                max_sites = len(site_data)
                sites_to_fix = st.number_input("Number of sites to fix:", min_value=1, max_value=max_sites, value=min(100, max_sites), step=10, key="sites_input")
                
                # Calculate forecast using correct unavailability metric with MAIN totals
                sites_fixed = site_data.head(sites_to_fix)
                unavail_fixed = sites_fixed['SITE_UNAVAIL_SECONDS'].sum()  # Use correct metric
                new_unavail_seconds = main_total_unavail_seconds - unavail_fixed
                new_unavail = (new_unavail_seconds / main_total_d * 100) if main_total_d > 0 else 0
                new_avail = 100 - new_unavail
                improvement = new_avail - main_overall_avail
                
                # Category breakdown of what would be fixed
                fixed_by_category = sites_fixed.groupby('SITE_ID_FOCUS_CATEGORY')['SITE_UNAVAIL_SECONDS'].sum().reset_index()
                fixed_by_category.columns = ['Category', 'Unavail Fixed']
                
            else:
                # Select categories to fix
                available_cats = category_summary['Category'].tolist()
                selected_cats = st.multiselect("Categories to fix:", available_cats, default=[available_cats[0]] if available_cats else [], key="cat_select")
                
                # Option to fix all sites or top N per category
                fix_mode = st.radio("Fix:", ["All sites in category", "Top N sites per category"], key="fix_mode")
                
                if fix_mode == "Top N sites per category":
                    sites_per_cat = st.slider("Sites per category:", 1, 1000, 20, key="sites_per_cat")
                else:
                    sites_per_cat = None
                
                # Calculate forecast using correct unavailability metric
                if selected_cats:
                    if sites_per_cat:
                        # Top N per category - optimized with list comprehension
                        cat_dfs = [site_data[site_data['SITE_ID_FOCUS_CATEGORY'] == cat].head(sites_per_cat) for cat in selected_cats]
                        sites_fixed = pd.concat(cat_dfs, ignore_index=True) if cat_dfs else pd.DataFrame()
                    else:
                        # All sites in selected categories
                        sites_fixed = site_data[site_data['SITE_ID_FOCUS_CATEGORY'].isin(selected_cats)]
                    
                    sites_to_fix = len(sites_fixed)
                    unavail_fixed = sites_fixed['SITE_UNAVAIL_SECONDS'].sum()  # Use correct metric
                    new_unavail_seconds = main_total_unavail_seconds - unavail_fixed
                    new_unavail = (new_unavail_seconds / main_total_d * 100) if main_total_d > 0 else 0
                    new_avail = 100 - new_unavail
                    improvement = new_avail - main_overall_avail
                    
                    fixed_by_category = sites_fixed.groupby('SITE_ID_FOCUS_CATEGORY')['SITE_UNAVAIL_SECONDS'].sum().reset_index()
                    fixed_by_category.columns = ['Category', 'Unavail Fixed']
                else:
                    sites_to_fix = 0
                    unavail_fixed = 0
                    new_unavail = main_overall_unavail
                    new_avail = main_overall_avail
                    improvement = 0
                    fixed_by_category = pd.DataFrame(columns=['Category', 'Unavail Fixed'])
            
            # Display forecast results
            st.markdown("---")
            st.markdown("#### 📊 Forecast Results")
            
            # Round values consistently so they add up visually
            current_display = round(main_overall_avail, 2)
            improvement_display = round(improvement, 2)
            projected_display = round(current_display + improvement_display, 2)
            
            # Before/After comparison
            goal_met = new_avail >= 99.85
            goal_color = "#22c55e" if goal_met else "#ef4444"
            
            st.markdown(f"""
            <div style="background:linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);border-radius:10px;padding:15px;margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <div style="text-align:center;flex:1;">
                        <div style="font-size:0.75rem;color:#888;">CURRENT</div>
                        <div style="font-size:1.5rem;font-weight:bold;color:#ef4444;">{current_display:.2f}%</div>
                        <div style="font-size:0.7rem;color:#888;">Availability</div>
                    </div>
                    <div style="font-size:1.5rem;color:#e20074;">→</div>
                    <div style="text-align:center;flex:1;">
                        <div style="font-size:0.75rem;color:#888;">PROJECTED</div>
                        <div style="font-size:1.5rem;font-weight:bold;color:{goal_color};">{projected_display:.2f}%</div>
                        <div style="font-size:0.7rem;color:#888;">Availability</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Improvement metrics
            st.markdown(f"""
            <div style="display:flex;gap:10px;">
                <div style="flex:1;background:#f8f9fa;border-radius:8px;padding:10px;text-align:center;">
                    <div style="font-size:0.7rem;color:#888;">Sites to Fix</div>
                    <div style="font-size:1.2rem;font-weight:bold;color:#e20074;">{sites_to_fix}</div>
                </div>
                <div style="flex:1;background:#f8f9fa;border-radius:8px;padding:10px;text-align:center;">
                    <div style="font-size:0.7rem;color:#888;">Improvement</div>
                    <div style="font-size:1.2rem;font-weight:bold;color:#22c55e;">+{improvement_display:.2f}%</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown(f"""
            <div style="display:flex;gap:10px;margin-top:10px;">
                <div style="flex:1;background:#f8f9fa;border-radius:8px;padding:10px;text-align:center;">
                    <div style="font-size:0.7rem;color:#888;">Unavail Before</div>
                    <div style="font-size:1.2rem;font-weight:bold;color:#ef4444;">{main_overall_unavail:.2f}%</div>
                </div>
                <div style="flex:1;background:#f8f9fa;border-radius:8px;padding:10px;text-align:center;">
                    <div style="font-size:0.7rem;color:#888;">Unavail After</div>
                    <div style="font-size:1.2rem;font-weight:bold;color:#22c55e;">{new_unavail:.2f}%</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if goal_met:
                st.success("✅ This scenario meets the 99.85% availability goal!")
            else:
                gap = 99.85 - new_avail
                st.warning(f"⚠️ Still {gap:.3f}% below 99.85% goal")
        
        with sim_col2:
            st.markdown("#### 📊 Category Impact Breakdown")
            
            # Merge fixed data with original category summary
            if not fixed_by_category.empty:
                cat_impact = category_summary.merge(fixed_by_category, on='Category', how='left')
                cat_impact['Unavail Fixed'] = cat_impact['Unavail Fixed'].fillna(0)
                cat_impact['Remaining Unavail'] = cat_impact['Total Unavail'] - cat_impact['Unavail Fixed']
                cat_impact['PCT_Fixed'] = (cat_impact['Unavail Fixed'] / cat_impact['Total Unavail'] * 100).fillna(0)
                cat_impact['New Unavail Contribution'] = (cat_impact['Remaining Unavail'] / main_total_d * 100) if main_total_d > 0 else 0
                cat_impact['Reduction'] = cat_impact['UNAVAIL_CONTRIBUTION'] - cat_impact['New Unavail Contribution']
            else:
                cat_impact = category_summary.copy()
                cat_impact['Unavail Fixed'] = 0
                cat_impact['Remaining Unavail'] = cat_impact['Total Unavail']
                cat_impact['PCT_Fixed'] = 0
                cat_impact['New Unavail Contribution'] = cat_impact['UNAVAIL_CONTRIBUTION']
                cat_impact['Reduction'] = 0
            
            # Before/After stacked bar chart - exclude "No Outage" category
            cat_impact_chart = cat_impact[cat_impact['Category'] != 'No Outage'].copy()
            fig_forecast = go.Figure()
            
            # Sort by original unavailability contribution
            cat_impact_chart = cat_impact_chart.sort_values('UNAVAIL_CONTRIBUTION', ascending=True)
            
            # Add "After" bars (remaining)
            fig_forecast.add_trace(go.Bar(
                y=cat_impact_chart['Category'],
                x=cat_impact_chart['New Unavail Contribution'],
                orientation='h',
                name='After Fix',
                marker_color=[FOCUS_CATEGORY_COLORS.get(c, DEFAULT_FOCUS_COLOR) for c in cat_impact_chart['Category']],
                text=[f"{v:.3f}%" for v in cat_impact_chart['New Unavail Contribution']],
                textposition='inside',
                textfont=dict(size=11, color='white'),
                hovertemplate='<b>%{y}</b><br>After: %{x:.4f}% unavailability<extra></extra>'
            ))
            
            # Add "Fixed" portion (stacked)
            fig_forecast.add_trace(go.Bar(
                y=cat_impact_chart['Category'],
                x=cat_impact_chart['Reduction'],
                orientation='h',
                name='Reduction',
                marker_color='#22c55e',
                opacity=0.7,
                text=[f"-{v:.3f}%" if v > 0.001 else "" for v in cat_impact_chart['Reduction']],
                textposition='inside',
                textfont=dict(size=10, color='white'),
                hovertemplate='<b>%{y}</b><br>Reduction: %{x:.4f}%<extra></extra>'
            ))
            
            fig_forecast.update_layout(
                template='plotly_white',
                height=450,
                barmode='stack',
                font=dict(size=12),
                legend=dict(orientation='h', yanchor='top', y=-0.18, xanchor='center', x=0.5),
                xaxis=dict(title="Unavailability Contribution %", tickformat=".3f", tickfont=dict(size=11)),
                yaxis=dict(tickfont=dict(size=11)),
                margin=dict(l=150, r=20, t=10, b=90)
            )
            st.plotly_chart(fig_forecast, use_container_width=True, config=CHART_CONFIG, key="forecast_bar")
            
            # Summary table - exclude "No Outage" category
            st.markdown("##### Category Summary")
            cat_impact_filtered = cat_impact[cat_impact['Category'] != 'No Outage']
            
            # Calculate totals for summary
            total_sites = int(cat_impact_filtered['Site Count'].sum())
            total_before = float(cat_impact_filtered['UNAVAIL_CONTRIBUTION'].sum())
            total_reduction = float(cat_impact_filtered['Reduction'].sum())
            total_after = float(cat_impact_filtered['New Unavail Contribution'].sum())
            
            # Display totals above table
            st.markdown(f"""
            <div style="display:flex;gap:20px;margin-bottom:12px;flex-wrap:wrap;">
                <div style="background:#f8f9fa;padding:8px 15px;border-radius:8px;border-left:3px solid #e20074;">
                    <div style="font-size:0.75rem;color:#888;">Total Sites</div>
                    <div style="font-size:1.2rem;font-weight:bold;color:#e20074;">{total_sites:,}</div>
                </div>
                <div style="background:#f8f9fa;padding:8px 15px;border-radius:8px;border-left:3px solid #ef4444;">
                    <div style="font-size:0.75rem;color:#888;">Total Before</div>
                    <div style="font-size:1.2rem;font-weight:bold;color:#ef4444;">{total_before:.2f}%</div>
                </div>
                <div style="background:#f8f9fa;padding:8px 15px;border-radius:8px;border-left:3px solid #22c55e;">
                    <div style="font-size:0.75rem;color:#888;">Total Reduction</div>
                    <div style="font-size:1.2rem;font-weight:bold;color:#22c55e;">-{total_reduction:.2f}%</div>
                </div>
                <div style="background:#f8f9fa;padding:8px 15px;border-radius:8px;border-left:3px solid #3b82f6;">
                    <div style="font-size:0.75rem;color:#888;">Total After</div>
                    <div style="font-size:1.2rem;font-weight:bold;color:#3b82f6;">{total_after:.2f}%</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            summary_display = cat_impact_filtered[['Category', 'Site Count', 'UNAVAIL_CONTRIBUTION', 'Reduction', 'New Unavail Contribution']].copy()
            summary_display.columns = ['Category', 'Sites', 'Before %', 'Reduction %', 'After %']
            # Sort by After % (highest to lowest) BEFORE formatting
            summary_display = summary_display.sort_values('After %', ascending=False)
            # Now format the columns - 2 decimal places
            summary_display['Before %'] = summary_display['Before %'].apply(lambda x: f"{x:.2f}%")
            summary_display['Reduction %'] = summary_display['Reduction %'].apply(lambda x: f"-{x:.2f}%" if x > 0 else "0%")
            summary_display['After %'] = summary_display['After %'].apply(lambda x: f"{x:.2f}%")
            
            st.dataframe(summary_display, use_container_width=True, hide_index=True)
    else:
        st.info("No site-level data available for the selected filters.")

# ==================== NON-MACRO COMPARISON DASHBOARD ====================
# OPTIMIZED: Single master query fetches all data, pandas does aggregation

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def ask_cortex(_conn, question, context_summary):
    """
    Use Snowflake Cortex to answer natural language questions about the data.
    Note: _conn uses underscore prefix to prevent Streamlit from trying to hash it.
    Falls back to rule-based responses if Cortex is not available.
    """
    
    # Build the full prompt
    full_prompt = f"""You are a data analyst assistant. Answer based on this data:

{context_summary}

Question: {question}

Answer concisely (2-4 sentences):"""

    try:
        # Escape single quotes for SQL
        prompt_escaped = full_prompt.replace("'", "''")
        
        # Try simpler Cortex syntax
        query = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{prompt_escaped}') as response"
        cursor = _conn.cursor()
        cursor.execute(query)
        result = cursor.fetchone()
        if result and result[0]:
            return result[0]
        return "Unable to get response."
    except Exception as e:
        error_msg = str(e)
        
        # If Cortex not available, use rule-based fallback
        if "Unknown user-defined function" in error_msg or "CORTEX" in error_msg:
            return answer_with_rules(question, context_summary)
        
        return f"Error: {error_msg}"

def answer_with_rules(question, context_summary):
    """
    Fallback rule-based answering when Cortex is not available.
    Parses the context and answers common questions.
    """
    question_lower = question.lower()
    
    # Parse key metrics from context
    lines = context_summary.split('\n')
    metrics = {}
    
    for line in lines:
        if 'Total Non-Macro Sites:' in line:
            metrics['total_sites'] = line.split(':')[-1].strip()
        elif 'V1 Total Impact Minutes:' in line:
            metrics['v1_total'] = line.split(':')[-1].strip()
        elif 'V2 Total Impact Minutes:' in line:
            metrics['v2_total'] = line.split(':')[-1].strip()
        elif 'Delta (V1 - V2):' in line:
            metrics['delta'] = line.split(':')[-1].strip()
    
    # Parse site type data
    site_types = []
    in_site_type_section = False
    for line in lines:
        if 'BY SITE TYPE:' in line:
            in_site_type_section = True
            continue
        if 'TOP 10 MARKETS' in line:
            in_site_type_section = False
        if in_site_type_section and line.strip() and 'SITE_TYPE' not in line:
            parts = line.split()
            if len(parts) >= 5:
                site_types.append({
                    'type': parts[0],
                    'sites': parts[1],
                    'v1': parts[2],
                    'v2': parts[3],
                    'delta': parts[4]
                })
    
    # Answer based on question patterns
    if any(word in question_lower for word in ['highest', 'most', 'top', 'biggest', 'largest']):
        if 'site type' in question_lower or 'type' in question_lower:
            if site_types:
                top = max(site_types, key=lambda x: float(x['v1'].replace(',', '')) if x['v1'].replace(',', '').replace('.', '').isdigit() else 0)
                return f"**{top['type']}** has the highest impact with {top['v1']} V1 impact minutes across {top['sites']} sites."
        if 'impact' in question_lower:
            return f"The highest V1 impact is {metrics.get('v1_total', 'N/A')} minutes total. Check the 'By Site Type' section for breakdown."
    
    if 'total' in question_lower or 'how many' in question_lower:
        if 'site' in question_lower:
            return f"There are **{metrics.get('total_sites', 'N/A')}** total non-macro sites in this analysis."
        if 'minute' in question_lower or 'impact' in question_lower:
            return f"V1 Total: {metrics.get('v1_total', 'N/A')} minutes. V2 Total: {metrics.get('v2_total', 'N/A')} minutes. Delta: {metrics.get('delta', 'N/A')}."
    
    if 'compare' in question_lower or 'difference' in question_lower or 'vs' in question_lower or 'versus' in question_lower:
        return f"**V1 vs V2 Comparison:** V1 has {metrics.get('v1_total', 'N/A')} impact minutes while V2 has {metrics.get('v2_total', 'N/A')}. The delta is {metrics.get('delta', 'N/A')}."
    
    if 'das' in question_lower:
        das_data = next((s for s in site_types if s['type'].upper() == 'DAS'), None)
        if das_data:
            return f"**DAS sites:** {das_data['sites']} sites with V1={das_data['v1']} mins, V2={das_data['v2']} mins, Delta={das_data['delta']}."
    
    if 'micro' in question_lower:
        micro_data = next((s for s in site_types if s['type'].upper() == 'MICRO'), None)
        if micro_data:
            return f"**Micro sites:** {micro_data['sites']} sites with V1={micro_data['v1']} mins, V2={micro_data['v2']} mins, Delta={micro_data['delta']}."
    
    if 'pico' in question_lower:
        pico_data = next((s for s in site_types if s['type'].upper() == 'PICO'), None)
        if pico_data:
            return f"**Pico sites:** {pico_data['sites']} sites with V1={pico_data['v1']} mins, V2={pico_data['v2']} mins, Delta={pico_data['delta']}."
    
    # Default response with summary
    return f"""Based on the data: There are {metrics.get('total_sites', 'N/A')} non-macro sites. V1 impact: {metrics.get('v1_total', 'N/A')} mins, V2 impact: {metrics.get('v2_total', 'N/A')} mins, Delta: {metrics.get('delta', 'N/A')}. 

Try asking about specific site types (DAS, Micro, Pico) or ask "which site type has the highest impact?"."""

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_nonmacro_master_data(_conn, days, start_date=None, end_date=None):
    """
    OPTIMIZED: Single master query that fetches all non-macro comparison data.
    Returns base data that can be aggregated by pandas for different views.
    This replaces 6+ separate queries with 1 query. Cached for 5 minutes.
    Cache key only uses date params (not entire filters dict) for better hit rate.
    """
    # Use start_date/end_date if provided, otherwise fall back to days
    if start_date and end_date:
        date_filter = f"LOCAL_DATE_PART >= '{start_date}' AND LOCAL_DATE_PART <= '{end_date}'"
        date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'"
    else:
        date_filter = f"LOCAL_DATE_PART >= DATEADD(day, -{days}, CURRENT_DATE())"
        date_filter_avail = f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    query = f"""
    WITH non_macro_sites AS (
        SELECT 
            SITE_ID, 
            MAX(SITE_TYPE) as SITE_TYPE, 
            MAX(MARKET_ID) as MARKET_ID,
            MAX(REGION_ID) as REGION_ID,
            MAX(SITE_ID_FOCUS_CATEGORY) as FOCUS_CATEGORY
        FROM {TABLES['availability']}
        WHERE (SITE_TYPE != 'Macro' OR SITE_TYPE IS NULL)
          AND {date_filter_avail}
        GROUP BY SITE_ID
    ),
    v1_by_site_date AS (
        SELECT 
            v1.SITE_ID,
            v1.LOCAL_DATE_PART as DATE_VALUE,
            SUM(v1.IMPACT_DURATION_IN_MINS) as V1_IMPACT_MINS,
            SUM(v1.TOTAL_IMPACTED_SUB_CNT) as V1_TOTAL_SUBS
        FROM {TABLES['customer_minutes_v1']} v1
        WHERE {date_filter}
        GROUP BY v1.SITE_ID, v1.LOCAL_DATE_PART
    ),
    v2_by_site_date AS (
        SELECT 
            v2.SITE_ID,
            v2.LOCAL_DATE_PART as DATE_VALUE,
            SUM(v2.IMPACT_DURATION_IN_MINS) as V2_IMPACT_MINS,
            SUM(v2.TOTAL_IMPACTED_SUB_CNT) as V2_TOTAL_SUBS,
            SUM(v2.SEVERELY_IMPACTED_SUB_CNT) as V2_SEVERELY_IMPACTED
        FROM {TABLES['customer_minutes']} v2
        WHERE {date_filter}
        GROUP BY v2.SITE_ID, v2.LOCAL_DATE_PART
    ),
    combined AS (
        SELECT 
            COALESCE(v1.SITE_ID, v2.SITE_ID) as SITE_ID,
            COALESCE(v1.DATE_VALUE, v2.DATE_VALUE) as DATE_VALUE,
            COALESCE(v1.V1_IMPACT_MINS, 0) as V1_IMPACT_MINS,
            COALESCE(v2.V2_IMPACT_MINS, 0) as V2_IMPACT_MINS,
            COALESCE(v1.V1_TOTAL_SUBS, 0) as V1_TOTAL_SUBS,
            COALESCE(v2.V2_TOTAL_SUBS, 0) as V2_TOTAL_SUBS,
            COALESCE(v2.V2_SEVERELY_IMPACTED, 0) as V2_SEVERELY_IMPACTED
        FROM v1_by_site_date v1
        FULL OUTER JOIN v2_by_site_date v2 
            ON v1.SITE_ID = v2.SITE_ID AND v1.DATE_VALUE = v2.DATE_VALUE
    )
    SELECT 
        c.SITE_ID,
        c.DATE_VALUE,
        COALESCE(nms.SITE_TYPE, 'Unknown') as SITE_TYPE,
        nms.MARKET_ID,
        COALESCE(nms.REGION_ID, 'Unknown') as REGION_ID,
        COALESCE(nms.FOCUS_CATEGORY, 'Unknown') as FOCUS_CATEGORY,
        c.V1_IMPACT_MINS,
        c.V2_IMPACT_MINS,
        c.V1_TOTAL_SUBS,
        c.V2_TOTAL_SUBS,
        c.V2_SEVERELY_IMPACTED,
        stf.S_COVERAGE_CLASSIFICATION as COVERAGE_CLASS
    FROM combined c
    LEFT JOIN non_macro_sites nms ON c.SITE_ID = nms.SITE_ID
    LEFT JOIN BDM_NDW_MAGENTABUILT_REFERENCE_DB.MAGENTABUILT_REFERENCE.SITE_TRACKER_FOPS stf 
        ON c.SITE_ID = stf.SITE_ID
    WHERE nms.SITE_ID IS NOT NULL
    ORDER BY c.DATE_VALUE, c.SITE_ID
    """
    
    return run_query(_conn, query)

def aggregate_nonmacro_by_type(master_df):
    """Aggregate master data by SITE_TYPE using pandas"""
    if master_df.empty:
        return pd.DataFrame()
    
    # Aggregate by site first, then by type
    site_agg = master_df.groupby(['SITE_ID', 'SITE_TYPE']).agg({
        'V1_IMPACT_MINS': 'sum',
        'V2_IMPACT_MINS': 'sum',
        'V1_TOTAL_SUBS': 'sum',
        'V2_TOTAL_SUBS': 'sum',
        'V2_SEVERELY_IMPACTED': 'sum'
    }).reset_index()
    
    # Now aggregate by type
    type_agg = site_agg.groupby('SITE_TYPE').agg({
        'SITE_ID': 'nunique',
        'V1_IMPACT_MINS': 'sum',
        'V2_IMPACT_MINS': 'sum',
        'V1_TOTAL_SUBS': 'sum',
        'V2_TOTAL_SUBS': 'sum',
        'V2_SEVERELY_IMPACTED': 'sum'
    }).reset_index()
    
    type_agg.columns = ['SITE_TYPE', 'TOTAL_SITES', 'V1_TOTAL_IMPACT_MINS', 'V2_TOTAL_IMPACT_MINS', 
                        'V1_TOTAL_SUBS', 'V2_TOTAL_SUBS', 'V2_SEVERELY_IMPACTED']
    type_agg['IMPACT_MINS_DELTA'] = type_agg['V1_TOTAL_IMPACT_MINS'] - type_agg['V2_TOTAL_IMPACT_MINS']
    type_agg['TOTAL_SUBS_DELTA'] = type_agg['V1_TOTAL_SUBS'] - type_agg['V2_TOTAL_SUBS']
    
    # Count sites with data in each version
    v1_sites = master_df[master_df['V1_IMPACT_MINS'] > 0].groupby('SITE_TYPE')['SITE_ID'].nunique().reset_index()
    v1_sites.columns = ['SITE_TYPE', 'V1_SITES_WITH_DATA']
    v2_sites = master_df[master_df['V2_IMPACT_MINS'] > 0].groupby('SITE_TYPE')['SITE_ID'].nunique().reset_index()
    v2_sites.columns = ['SITE_TYPE', 'V2_SITES_WITH_DATA']
    
    type_agg = type_agg.merge(v1_sites, on='SITE_TYPE', how='left').merge(v2_sites, on='SITE_TYPE', how='left')
    type_agg['V1_SITES_WITH_DATA'] = type_agg['V1_SITES_WITH_DATA'].fillna(0).astype(int)
    type_agg['V2_SITES_WITH_DATA'] = type_agg['V2_SITES_WITH_DATA'].fillna(0).astype(int)
    
    return type_agg.sort_values('V1_TOTAL_IMPACT_MINS', ascending=False)

def aggregate_nonmacro_by_market(master_df):
    """Aggregate master data by MARKET using pandas"""
    if master_df.empty:
        return pd.DataFrame()
    
    # Normalize market names to Global Market ID format BEFORE aggregation
    master_df = master_df.copy()
    master_df['MARKET_ID'] = master_df['MARKET_ID'].apply(lambda x: get_canonical_market_name(x, 'availability') if pd.notna(x) else x)
    
    # Aggregate by site first, then by market
    site_agg = master_df.groupby(['SITE_ID', 'MARKET_ID']).agg({
        'V1_IMPACT_MINS': 'sum',
        'V2_IMPACT_MINS': 'sum',
        'V1_TOTAL_SUBS': 'sum',
        'V2_TOTAL_SUBS': 'sum',
        'V2_SEVERELY_IMPACTED': 'sum'
    }).reset_index()
    
    # Filter out null markets
    site_agg = site_agg[site_agg['MARKET_ID'].notna()]
    
    # Now aggregate by market
    market_agg = site_agg.groupby('MARKET_ID').agg({
        'SITE_ID': 'nunique',
        'V1_IMPACT_MINS': 'sum',
        'V2_IMPACT_MINS': 'sum',
        'V1_TOTAL_SUBS': 'sum',
        'V2_TOTAL_SUBS': 'sum',
        'V2_SEVERELY_IMPACTED': 'sum'
    }).reset_index()
    
    market_agg.columns = ['MARKET_ID', 'TOTAL_SITES', 'V1_TOTAL_IMPACT_MINS', 'V2_TOTAL_IMPACT_MINS',
                          'V1_TOTAL_SUBS', 'V2_TOTAL_SUBS', 'V2_SEVERELY_IMPACTED']
    market_agg['IMPACT_MINS_DELTA'] = market_agg['V1_TOTAL_IMPACT_MINS'] - market_agg['V2_TOTAL_IMPACT_MINS']
    
    # Filter to only markets with data
    market_agg = market_agg[(market_agg['V1_TOTAL_IMPACT_MINS'] > 0) | (market_agg['V2_TOTAL_IMPACT_MINS'] > 0)]
    
    return market_agg.sort_values('IMPACT_MINS_DELTA', ascending=False)

def aggregate_nonmacro_daily(master_df):
    """Aggregate master data by DATE using pandas"""
    if master_df.empty:
        return pd.DataFrame()
    
    daily_agg = master_df.groupby('DATE_VALUE').agg({
        'V1_IMPACT_MINS': 'sum',
        'V2_IMPACT_MINS': 'sum',
        'V1_TOTAL_SUBS': 'sum',
        'V2_TOTAL_SUBS': 'sum',
        'V2_SEVERELY_IMPACTED': 'sum',
        'SITE_ID': 'nunique'
    }).reset_index()
    
    daily_agg.columns = ['DATE_VALUE', 'V1_IMPACT_MINS', 'V2_IMPACT_MINS', 'V1_TOTAL_SUBS', 
                         'V2_TOTAL_SUBS', 'V2_SEVERELY_IMPACTED', 'SITE_COUNT']
    daily_agg['IMPACT_MINS_DELTA'] = daily_agg['V1_IMPACT_MINS'] - daily_agg['V2_IMPACT_MINS']
    
    return daily_agg.sort_values('DATE_VALUE')

def aggregate_nonmacro_by_focus(master_df):
    """Aggregate master data by FOCUS_CATEGORY using pandas"""
    if master_df.empty:
        return pd.DataFrame()
    
    # Aggregate by site first, then by focus category
    site_agg = master_df.groupby(['SITE_ID', 'FOCUS_CATEGORY']).agg({
        'V1_IMPACT_MINS': 'sum',
        'V2_IMPACT_MINS': 'sum',
        'V1_TOTAL_SUBS': 'sum',
        'V2_TOTAL_SUBS': 'sum',
        'V2_SEVERELY_IMPACTED': 'sum'
    }).reset_index()
    
    # Now aggregate by focus category
    focus_agg = site_agg.groupby('FOCUS_CATEGORY').agg({
        'SITE_ID': 'nunique',
        'V1_IMPACT_MINS': 'sum',
        'V2_IMPACT_MINS': 'sum',
        'V1_TOTAL_SUBS': 'sum',
        'V2_TOTAL_SUBS': 'sum',
        'V2_SEVERELY_IMPACTED': 'sum'
    }).reset_index()
    
    focus_agg.columns = ['FOCUS_CATEGORY', 'SITE_COUNT', 'V1_IMPACT_MINS', 'V2_IMPACT_MINS',
                         'V1_TOTAL_SUBS', 'V2_TOTAL_SUBS', 'V2_SEVERELY_IMPACTED']
    focus_agg['IMPACT_MINS_DELTA'] = focus_agg['V1_IMPACT_MINS'] - focus_agg['V2_IMPACT_MINS']
    
    # Get V1 and V2 site counts separately
    v1_sites = master_df[master_df['V1_IMPACT_MINS'] > 0].groupby('FOCUS_CATEGORY')['SITE_ID'].nunique().reset_index()
    v1_sites.columns = ['FOCUS_CATEGORY', 'V1_SITE_COUNT']
    v2_sites = master_df[master_df['V2_IMPACT_MINS'] > 0].groupby('FOCUS_CATEGORY')['SITE_ID'].nunique().reset_index()
    v2_sites.columns = ['FOCUS_CATEGORY', 'V2_SITE_COUNT']
    
    focus_agg = focus_agg.merge(v1_sites, on='FOCUS_CATEGORY', how='left').merge(v2_sites, on='FOCUS_CATEGORY', how='left')
    focus_agg['V1_SITE_COUNT'] = focus_agg['V1_SITE_COUNT'].fillna(0).astype(int)
    focus_agg['V2_SITE_COUNT'] = focus_agg['V2_SITE_COUNT'].fillna(0).astype(int)
    
    # Filter to only categories with data
    focus_agg = focus_agg[(focus_agg['V1_IMPACT_MINS'] > 0) | (focus_agg['V2_IMPACT_MINS'] > 0)]
    
    return focus_agg.sort_values('V1_IMPACT_MINS', ascending=False)

def aggregate_coverage_by_version(master_df, version='both'):
    """Aggregate coverage classification by version using pandas"""
    if master_df.empty:
        return pd.DataFrame()
    
    if version == 'v1':
        filtered = master_df[master_df['V1_IMPACT_MINS'] > 0]
    elif version == 'v2':
        filtered = master_df[master_df['V2_IMPACT_MINS'] > 0]
    else:
        filtered = master_df[(master_df['V1_IMPACT_MINS'] > 0) | (master_df['V2_IMPACT_MINS'] > 0)]
    
    if filtered.empty:
        return pd.DataFrame()
    
    coverage_agg = filtered.groupby('COVERAGE_CLASS')['SITE_ID'].nunique().reset_index()
    coverage_agg.columns = ['COVERAGE_CLASS', 'SITE_COUNT']
    coverage_agg['COVERAGE_CLASS'] = coverage_agg['COVERAGE_CLASS'].fillna('Unknown')
    
    return coverage_agg.sort_values('SITE_COUNT', ascending=False)

# Colors for site types
SITE_TYPE_COLORS = {
    'DAS': '#e20074',
    'Micro': '#22c55e',
    'Pico': '#f59e0b',
    'Temp/Toy': '#8b5cf6',
    'Enterprise Small Cell RAN': '#06b6d4',
    'Unknown': '#6b7280',
    None: '#6b7280'
}

# Colors for coverage classification
COVERAGE_CLASS_COLORS = {
    'Standard': '#6b7280',
    'Silver': '#94a3b8',
    'Bronze': '#cd7f32',
    'Platinum': '#e5e4e2',
    'Gold': '#ffd700',
    'Unknown': '#374151'
}

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_nonmacro_coverage_breakdown(_conn, days, filters=None, version='both'):
    """Get coverage classification breakdown for non-macro sites with impact data
    
    Args:
        version: 'v1' for V1 table only, 'v2' for V2 table only, 'both' for combined
    """
    conn = _conn
    date_filter = f"LOCAL_DATE_PART >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    if version == 'v1':
        sites_cte = f"""
        SELECT DISTINCT SITE_ID
        FROM {TABLES['customer_minutes_v1']}
        WHERE {date_filter}
          AND SITE_ID IN (
              SELECT DISTINCT SITE_ID FROM {TABLES['availability']}
              WHERE SITE_TYPE != 'Macro' OR SITE_TYPE IS NULL
          )
        """
    elif version == 'v2':
        sites_cte = f"""
        SELECT DISTINCT SITE_ID
        FROM {TABLES['customer_minutes']}
        WHERE {date_filter}
          AND SITE_ID IN (
              SELECT DISTINCT SITE_ID FROM {TABLES['availability']}
              WHERE SITE_TYPE != 'Macro' OR SITE_TYPE IS NULL
          )
        """
    else:
        sites_cte = f"""
        SELECT DISTINCT SITE_ID
        FROM {TABLES['customer_minutes_v1']}
        WHERE {date_filter}
          AND SITE_ID IN (
              SELECT DISTINCT SITE_ID FROM {TABLES['availability']}
              WHERE SITE_TYPE != 'Macro' OR SITE_TYPE IS NULL
          )
        UNION
        SELECT DISTINCT SITE_ID
        FROM {TABLES['customer_minutes']}
        WHERE {date_filter}
          AND SITE_ID IN (
              SELECT DISTINCT SITE_ID FROM {TABLES['availability']}
              WHERE SITE_TYPE != 'Macro' OR SITE_TYPE IS NULL
          )
        """
    
    query = f"""
    WITH sites_with_impact AS (
        {sites_cte}
    )
    SELECT 
        COALESCE(stf.S_COVERAGE_CLASSIFICATION, 'Unknown') as COVERAGE_CLASS,
        COUNT(DISTINCT swi.SITE_ID) as SITE_COUNT
    FROM sites_with_impact swi
    LEFT JOIN BDM_NDW_MAGENTABUILT_REFERENCE_DB.MAGENTABUILT_REFERENCE.SITE_TRACKER_FOPS stf 
        ON swi.SITE_ID = stf.SITE_ID
    GROUP BY COALESCE(stf.S_COVERAGE_CLASSIFICATION, 'Unknown')
    ORDER BY SITE_COUNT DESC
    """
    return run_query(conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_nonmacro_availability_by_focus_category(_conn, days, start_date=None, end_date=None):
    """Get Availability data by Focus Category for non-macro sites (cached 5 min)"""
    if start_date and end_date:
        date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'"
    else:
        date_filter_avail = f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    query = f"""
    SELECT 
        COALESCE(SITE_ID_FOCUS_CATEGORY, 'Unknown') as FOCUS_CATEGORY,
        SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME_SECS,
        SUM(TOTAL_DOWNTIME) / 60.0 as TOTAL_DOWNTIME_MINS,
        SUM(TOTAL_AVAILABILITY_N) as TOTAL_N,
        SUM(TOTAL_AVAILABILITY_D) as TOTAL_D,
        CASE WHEN SUM(TOTAL_AVAILABILITY_D) > 0 
             THEN (SUM(TOTAL_AVAILABILITY_N) / SUM(TOTAL_AVAILABILITY_D)) * 100 
             ELSE 0 END as AVAILABILITY_PCT,
        CASE WHEN SUM(TOTAL_AVAILABILITY_D) > 0 
             THEN (1 - (SUM(TOTAL_AVAILABILITY_N) / SUM(TOTAL_AVAILABILITY_D))) * 100 
             ELSE 0 END as UNAVAILABILITY_PCT,
        COUNT(DISTINCT SITE_ID) as SITE_COUNT,
        COUNT(DISTINCT DATE_VALUE) as DAYS_WITH_DATA,
        COUNT(DISTINCT CASE WHEN TOTAL_DOWNTIME > 0 THEN DATE_VALUE END) as DAYS_WITH_DOWNTIME
    FROM {TABLES['availability']}
    WHERE (SITE_TYPE != 'Macro' OR SITE_TYPE IS NULL)
      AND {date_filter_avail}
    GROUP BY SITE_ID_FOCUS_CATEGORY
    HAVING SUM(TOTAL_DOWNTIME) > 0
    ORDER BY TOTAL_DOWNTIME_SECS DESC
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_nonmacro_cottr_by_focus_category(_conn, days, start_date=None, end_date=None):
    """Get COTTR outage data by Focus Category for non-macro sites (cached 5 min)"""
    if start_date and end_date:
        date_filter_cottr = f"PER_DAY_LOCAL_DATE >= '{start_date}' AND PER_DAY_LOCAL_DATE <= '{end_date}'"
        date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'"
    else:
        date_filter_cottr = f"PER_DAY_LOCAL_DATE >= DATEADD(day, -{days}, CURRENT_DATE())"
        date_filter_avail = f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    query = f"""
    WITH non_macro_sites AS (
        SELECT DISTINCT SITE_ID
        FROM {TABLES['availability']}
        WHERE (SITE_TYPE != 'Macro' OR SITE_TYPE IS NULL)
          AND {date_filter_avail}
    )
    SELECT 
        COALESCE(c.SITE_ID_FOCUS_CATEGORY, 'Unknown') as FOCUS_CATEGORY,
        SUM(c.PER_DAY_OUTAGE_MINUTES) as COTTR_OUTAGE_MINS,
        COUNT(DISTINCT c.SITE_CD) as SITE_COUNT,
        COUNT(DISTINCT c.PER_DAY_LOCAL_DATE) as OUTAGE_DAYS,
        SUM(CASE WHEN c.SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' THEN c.PER_DAY_OUTAGE_MINUTES ELSE 0 END) as SERVICE_OUTAGE_MINS,
        SUM(CASE WHEN c.SERVICEIMPACTCRITERIA = 'SERVICE DEGRADATION' THEN c.PER_DAY_OUTAGE_MINUTES ELSE 0 END) as SERVICE_DEGRADATION_MINS
    FROM {TABLES['cottr']} c
    INNER JOIN non_macro_sites nms ON c.SITE_CD = nms.SITE_ID
    WHERE {date_filter_cottr} AND c.SITE_CD NOT LIKE 'USC%'
    GROUP BY c.SITE_ID_FOCUS_CATEGORY
    HAVING SUM(c.PER_DAY_OUTAGE_MINUTES) > 0
    ORDER BY COTTR_OUTAGE_MINS DESC
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_nonmacro_by_focus_category(_conn, days, start_date=None, end_date=None):
    """Get V1 vs V2 comparison by Focus Category for non-macro sites (cached 5 min)"""
    if start_date and end_date:
        date_filter = f"LOCAL_DATE_PART >= '{start_date}' AND LOCAL_DATE_PART <= '{end_date}'"
        date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'"
    else:
        date_filter = f"LOCAL_DATE_PART >= DATEADD(day, -{days}, CURRENT_DATE())"
        date_filter_avail = f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    query = f"""
    WITH non_macro_sites AS (
        SELECT DISTINCT SITE_ID, MAX(SITE_ID_FOCUS_CATEGORY) as FOCUS_CATEGORY
        FROM {TABLES['availability']}
        WHERE (SITE_TYPE != 'Macro' OR SITE_TYPE IS NULL)
          AND {date_filter_avail}
        GROUP BY SITE_ID
    ),
    v1_data AS (
        SELECT 
            nms.FOCUS_CATEGORY,
            SUM(v1.IMPACT_DURATION_IN_MINS) as IMPACT_MINS,
            SUM(v1.TOTAL_IMPACTED_SUB_CNT) as TOTAL_SUBS,
            COUNT(DISTINCT v1.SITE_ID) as SITE_COUNT
        FROM {TABLES['customer_minutes_v1']} v1
        JOIN non_macro_sites nms ON v1.SITE_ID = nms.SITE_ID
        WHERE {date_filter}
        GROUP BY nms.FOCUS_CATEGORY
    ),
    v2_data AS (
        SELECT 
            nms.FOCUS_CATEGORY,
            SUM(v2.IMPACT_DURATION_IN_MINS) as IMPACT_MINS,
            SUM(v2.TOTAL_IMPACTED_SUB_CNT) as TOTAL_SUBS,
            SUM(v2.SEVERELY_IMPACTED_SUB_CNT) as SEVERELY_IMPACTED,
            COUNT(DISTINCT v2.SITE_ID) as SITE_COUNT
        FROM {TABLES['customer_minutes']} v2
        JOIN non_macro_sites nms ON v2.SITE_ID = nms.SITE_ID
        WHERE {date_filter}
        GROUP BY nms.FOCUS_CATEGORY
    )
    SELECT 
        COALESCE(COALESCE(v1.FOCUS_CATEGORY, v2.FOCUS_CATEGORY), 'Unknown') as FOCUS_CATEGORY,
        COALESCE(v1.IMPACT_MINS, 0) as V1_IMPACT_MINS,
        COALESCE(v2.IMPACT_MINS, 0) as V2_IMPACT_MINS,
        COALESCE(v1.IMPACT_MINS, 0) - COALESCE(v2.IMPACT_MINS, 0) as IMPACT_MINS_DELTA,
        COALESCE(v1.TOTAL_SUBS, 0) as V1_TOTAL_SUBS,
        COALESCE(v2.TOTAL_SUBS, 0) as V2_TOTAL_SUBS,
        COALESCE(v2.SEVERELY_IMPACTED, 0) as V2_SEVERELY_IMPACTED,
        COALESCE(v1.SITE_COUNT, 0) as V1_SITE_COUNT,
        COALESCE(v2.SITE_COUNT, 0) as V2_SITE_COUNT
    FROM v1_data v1
    FULL OUTER JOIN v2_data v2 ON v1.FOCUS_CATEGORY = v2.FOCUS_CATEGORY
    WHERE COALESCE(v1.IMPACT_MINS, 0) > 0 OR COALESCE(v2.IMPACT_MINS, 0) > 0
    ORDER BY (COALESCE(v1.IMPACT_MINS, 0) + COALESCE(v2.IMPACT_MINS, 0)) DESC
    """
    return run_query(_conn, query)

# ==================== OEM COMPARISON CACHED FUNCTIONS ====================

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_oem_availability_data(_conn, start_date, end_date, days, site_type, market=None):
    """Cached OEM availability aggregates - single query for summary, market breakdown, and daily trends"""
    market_case_sql = get_market_case_sql()
    
    site_type_filter = get_site_type_sql_filter(site_type, 'a.')
    if start_date and end_date:
        date_filter = f"a.DATE_VALUE >= '{start_date}' AND a.DATE_VALUE <= '{end_date}'"
    else:
        date_filter = f"a.DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'availability', 'MARKET_ID', 'a.')
    
    # Combined query returns all data needed
    query = f"""
    WITH base_data AS (
        SELECT 
            a.DATE_VALUE,
            a.MARKET_ID,
            mt.M_OEM as OEM,
            COALESCE(a.SITE_ID_FOCUS_CATEGORY, 'Uncategorized') as FOCUS_CATEGORY,
            a.SITE_ID,
            a.TOTAL_DOWNTIME,
            a.TOTAL_AVAILABILITY_N,
            a.TOTAL_AVAILABILITY_D
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON {market_case_sql} = mt.M_CAPITAL_MARKET
        WHERE {date_filter} AND {site_type_filter} AND mt.M_OEM IS NOT NULL{market_filter}
    )
    SELECT 
        OEM,
        COUNT(DISTINCT SITE_ID) as SITE_COUNT,
        SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
        SUM(TOTAL_AVAILABILITY_N) as TOTAL_N,
        SUM(TOTAL_AVAILABILITY_D) as TOTAL_D,
        SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
        100 - (SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100) as UNAVAILABILITY_PCT,
        SUM(TOTAL_AVAILABILITY_D) * 0.0015 as SECONDS_BUDGET,
        SUM(TOTAL_DOWNTIME) - (SUM(TOTAL_AVAILABILITY_D) * 0.0015) as OVER_UNDER_BUDGET
    FROM base_data
    GROUP BY OEM
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_oem_market_breakdown(_conn, start_date, end_date, days, site_type, market=None):
    """Cached OEM availability by market"""
    market_case_sql = get_market_case_sql()
    site_type_filter = get_site_type_sql_filter(site_type, 'a.')
    if start_date and end_date:
        date_filter = f"a.DATE_VALUE >= '{start_date}' AND a.DATE_VALUE <= '{end_date}'"
    else:
        date_filter = f"a.DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'availability', 'MARKET_ID', 'a.')
    
    query = f"""
    SELECT 
        mt.M_OEM as OEM, a.MARKET_ID,
        COUNT(DISTINCT a.SITE_ID) as SITE_COUNT,
        SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
        SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
        100 - (SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100) as UNAVAILABILITY_PCT
    FROM {TABLES['availability']} a
    JOIN {TABLES['market_tracker']} mt ON {market_case_sql} = mt.M_CAPITAL_MARKET
    WHERE {date_filter} AND {site_type_filter} AND mt.M_OEM IS NOT NULL{market_filter}
    GROUP BY mt.M_OEM, a.MARKET_ID
    ORDER BY TOTAL_DOWNTIME DESC
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_oem_daily_trends(_conn, start_date, end_date, days, site_type, market=None):
    """Cached OEM daily availability trends"""
    market_case_sql = get_market_case_sql()
    site_type_filter = get_site_type_sql_filter(site_type, 'a.')
    if start_date and end_date:
        date_filter = f"a.DATE_VALUE >= '{start_date}' AND a.DATE_VALUE <= '{end_date}'"
    else:
        date_filter = f"a.DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'availability', 'MARKET_ID', 'a.')
    
    query = f"""
    SELECT 
        a.DATE_VALUE, mt.M_OEM as OEM,
        SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT,
        100 - (SUM(a.TOTAL_AVAILABILITY_N) / NULLIF(SUM(a.TOTAL_AVAILABILITY_D), 0) * 100) as UNAVAILABILITY_PCT,
        SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME
    FROM {TABLES['availability']} a
    JOIN {TABLES['market_tracker']} mt ON {market_case_sql} = mt.M_CAPITAL_MARKET
    WHERE {date_filter} AND {site_type_filter} AND mt.M_OEM IS NOT NULL{market_filter}
    GROUP BY a.DATE_VALUE, mt.M_OEM
    ORDER BY a.DATE_VALUE
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_oem_cottr_data(_conn, start_date, end_date, days, site_type, market=None):
    """Cached OEM COTTR outage data"""
    site_type_filter = f"c.SECTOR_TYPE_CATEGORY = '{site_type}'" if site_type else "1=1"
    if start_date and end_date:
        date_filter = f"c.LOCAL_START_TIMESTAMP >= '{start_date}' AND c.LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'"
    else:
        date_filter = f"c.LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'cottr', 'MKT_NAME', 'c.')
    
    query = f"""
    SELECT 
        mt.M_OEM as OEM,
        COUNT(DISTINCT c.SITE_CD) as SITE_COUNT,
        COUNT(*) as OUTAGE_COUNT,
        SUM(c.PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINUTES
    FROM {TABLES['cottr']} c
    JOIN {TABLES['market_tracker']} mt ON UPPER(c.MKT_NAME) = UPPER(mt.MARKET_ID)
    WHERE {date_filter} AND c.SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' AND {site_type_filter} AND mt.M_OEM IS NOT NULL AND c.SITE_CD NOT LIKE 'USC%'{market_filter}
    GROUP BY mt.M_OEM
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_oem_cottr_daily(_conn, start_date, end_date, days, site_type, market=None):
    """Cached OEM COTTR daily trends"""
    site_type_filter = f"c.SECTOR_TYPE_CATEGORY = '{site_type}'" if site_type else "1=1"
    if start_date and end_date:
        date_filter = f"c.LOCAL_START_TIMESTAMP >= '{start_date}' AND c.LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'"
    else:
        date_filter = f"c.LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'cottr', 'MKT_NAME', 'c.')
    
    query = f"""
    SELECT 
        c.PER_DAY_LOCAL_DATE as DATE_VALUE, mt.M_OEM as OEM,
        COUNT(*) as OUTAGE_COUNT,
        SUM(c.PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINUTES
    FROM {TABLES['cottr']} c
    JOIN {TABLES['market_tracker']} mt ON UPPER(c.MKT_NAME) = UPPER(mt.MARKET_ID)
    WHERE {date_filter} AND c.SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' AND {site_type_filter} AND mt.M_OEM IS NOT NULL AND c.SITE_CD NOT LIKE 'USC%'{market_filter}
    GROUP BY c.PER_DAY_LOCAL_DATE, mt.M_OEM
    ORDER BY c.PER_DAY_LOCAL_DATE
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_oem_customer_minutes(_conn, start_date, end_date, days, market=None):
    """Cached OEM customer minutes data"""
    if start_date and end_date:
        date_filter = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'"
    else:
        date_filter = f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'customer_minutes', 'MARKET', '')
    
    query = f"""
    SELECT 
        OEM, COUNT(DISTINCT SITE_ID) as SITE_COUNT,
        SUM(IMPACT_DURATION_IN_MINS) as TOTAL_CUSTOMER_MINUTES,
        SUM(TOTAL_IMPACTED_SUB_CNT) as TOTAL_IMPACTED_SUBS
    FROM {TABLES['customer_minutes']}
    WHERE {date_filter} AND OEM IS NOT NULL AND SITE_ID NOT LIKE 'USC%'{market_filter}
    GROUP BY OEM
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_oem_customer_minutes_daily(_conn, start_date, end_date, days, market=None):
    """Cached OEM customer minutes daily trends"""
    if start_date and end_date:
        date_filter = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'"
    else:
        date_filter = f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'customer_minutes', 'MARKET', '')
    
    query = f"""
    SELECT 
        LOCAL_DATE_PART as DATE_VALUE, OEM,
        SUM(IMPACT_DURATION_IN_MINS) as TOTAL_CUSTOMER_MINUTES,
        SUM(TOTAL_IMPACTED_SUB_CNT) as TOTAL_IMPACTED_SUBS
    FROM {TABLES['customer_minutes']}
    WHERE {date_filter} AND OEM IS NOT NULL AND SITE_ID NOT LIKE 'USC%'{market_filter}
    GROUP BY LOCAL_DATE_PART, OEM
    ORDER BY LOCAL_DATE_PART
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_oem_focus_category(_conn, start_date, end_date, days, site_type, market=None):
    """Cached OEM focus category breakdown"""
    market_case_sql = get_market_case_sql()
    site_type_filter = get_site_type_sql_filter(site_type, 'a.')
    if start_date and end_date:
        date_filter = f"a.DATE_VALUE >= '{start_date}' AND a.DATE_VALUE <= '{end_date}'"
    else:
        date_filter = f"a.DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'availability', 'MARKET_ID', 'a.')
    
    query = f"""
    SELECT 
        mt.M_OEM as OEM,
        COALESCE(a.SITE_ID_FOCUS_CATEGORY, 'Uncategorized') as FOCUS_CATEGORY,
        SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME
    FROM {TABLES['availability']} a
    JOIN {TABLES['market_tracker']} mt ON {market_case_sql} = mt.M_CAPITAL_MARKET
    WHERE {date_filter} AND {site_type_filter} AND mt.M_OEM IS NOT NULL{market_filter}
    GROUP BY mt.M_OEM, a.SITE_ID_FOCUS_CATEGORY
    ORDER BY mt.M_OEM, TOTAL_DOWNTIME DESC
    """
    return run_query(_conn, query)

# ==================== AAV ANALYSIS CACHED FUNCTIONS ====================

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_aav_availability_summary(_conn, start_date, end_date, days, market=None):
    """Cached AAV availability summary"""
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'availability', 'MARKET_ID', '')
    
    query = f"""
    SELECT 
        COALESCE(MB_PRIMARY_AAV_VENDOR_NAME, 'Unknown') as AAV_VENDOR,
        COUNT(DISTINCT SITE_ID) as SITE_COUNT,
        SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
        SUM(TOTAL_AVAILABILITY_N) as TOTAL_N,
        SUM(TOTAL_AVAILABILITY_D) as TOTAL_D,
        COUNT(DISTINCT CASE WHEN TOTAL_DOWNTIME > 0 THEN DATE_VALUE END) as DAYS_WITH_DOWNTIME
    FROM {TABLES['availability']}
    WHERE {date_filter} AND SITE_ID_FOCUS_CATEGORY = 'Transport - AAV'{market_filter}
    GROUP BY COALESCE(MB_PRIMARY_AAV_VENDOR_NAME, 'Unknown')
    ORDER BY TOTAL_DOWNTIME DESC
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_aav_cottr_market(_conn, start_date, end_date, days, market=None):
    """Cached AAV COTTR by market"""
    date_filter = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'cottr', 'MKT_NAME', '')
    
    query = f"""
    SELECT 
        COALESCE(MKT_NAME, 'Unknown') as MARKET,
        COUNT(DISTINCT SITE_CD) as SITE_COUNT,
        SUM(PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINUTES,
        COUNT(*) as OUTAGE_COUNT
    FROM {TABLES['cottr']}
    WHERE {date_filter} AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' AND SITE_ID_FOCUS_CATEGORY = 'Transport - AAV' AND SITE_CD NOT LIKE 'USC%'{market_filter}
    GROUP BY COALESCE(MKT_NAME, 'Unknown')
    ORDER BY TOTAL_OUTAGE_MINUTES DESC
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_aav_vendor_market_breakdown(_conn, start_date, end_date, days, market=None):
    """Cached AAV vendor by market breakdown"""
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'availability', 'MARKET_ID', '')
    
    query = f"""
    SELECT 
        COALESCE(MB_PRIMARY_AAV_VENDOR_NAME, 'Unknown') as AAV_VENDOR,
        MARKET_ID, COUNT(DISTINCT SITE_ID) as SITE_COUNT,
        SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
        SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT
    FROM {TABLES['availability']}
    WHERE {date_filter} AND SITE_ID_FOCUS_CATEGORY = 'Transport - AAV'{market_filter}
    GROUP BY COALESCE(MB_PRIMARY_AAV_VENDOR_NAME, 'Unknown'), MARKET_ID
    ORDER BY TOTAL_DOWNTIME DESC
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_aav_top_sites(_conn, start_date, end_date, days, market=None):
    """Cached AAV top sites by downtime"""
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'availability', 'MARKET_ID', '')
    
    query = f"""
    SELECT 
        SITE_ID, MARKET_ID,
        COALESCE(MB_PRIMARY_AAV_VENDOR_NAME, 'Unknown') as AAV_VENDOR,
        SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
        COUNT(DISTINCT CASE WHEN TOTAL_DOWNTIME > 0 THEN DATE_VALUE END) as DAYS_WITH_DOWNTIME,
        SUM(TOTAL_AVAILABILITY_N) / NULLIF(SUM(TOTAL_AVAILABILITY_D), 0) * 100 as AVAILABILITY_PCT
    FROM {TABLES['availability']}
    WHERE {date_filter} AND SITE_ID_FOCUS_CATEGORY = 'Transport - AAV'{market_filter}
    GROUP BY SITE_ID, MARKET_ID, COALESCE(MB_PRIMARY_AAV_VENDOR_NAME, 'Unknown')
    ORDER BY TOTAL_DOWNTIME DESC
    LIMIT 20
    """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_aav_daily_trend(_conn, start_date, end_date, days, market=None):
    """Cached AAV daily trend"""
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'availability', 'MARKET_ID', '')
    
    query = f"""
    SELECT 
        DATE_VALUE,
        COALESCE(MB_PRIMARY_AAV_VENDOR_NAME, 'Unknown') as AAV_VENDOR,
        SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
        COUNT(DISTINCT SITE_ID) as SITES_AFFECTED
    FROM {TABLES['availability']}
    WHERE {date_filter} AND SITE_ID_FOCUS_CATEGORY = 'Transport - AAV'{market_filter}
    GROUP BY DATE_VALUE, COALESCE(MB_PRIMARY_AAV_VENDOR_NAME, 'Unknown')
    ORDER BY DATE_VALUE
    """
    return run_query(_conn, query)

# ==================== HARDWARE ANALYSIS CACHED FUNCTIONS ====================

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_hardware_availability_kpi(_conn, start_date, end_date, market=None, oem=None, site_type=None):
    """Cached hardware availability KPI"""
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'"
    site_type_filter = get_site_type_sql_filter(site_type) if site_type else "1=1"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'availability', 'MARKET_ID', '')
    
    if oem:
        query = f"""
        SELECT 
            SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME_SECS,
            COUNT(DISTINCT a.SITE_ID) as AFFECTED_SITES,
            AVG(a.TOTAL_DOWNTIME) as AVG_DOWNTIME_PER_SITE,
            SUM(a.TOTAL_AVAILABILITY_N) as TOTAL_N,
            SUM(a.TOTAL_AVAILABILITY_D) as TOTAL_D
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE a.SITE_ID_FOCUS_CATEGORY IN ('Hardware', 'Hardware - Antenna System')
          AND a.{date_filter.replace('DATE_VALUE', 'DATE_VALUE')}{market_filter.replace('MARKET_ID', 'a.MARKET_ID')}
          AND mt.M_OEM = '{oem}'
          AND {site_type_filter.replace('SITE_TYPE', 'a.SITE_TYPE')}
        """
    else:
        query = f"""
        SELECT 
            SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME_SECS,
            COUNT(DISTINCT SITE_ID) as AFFECTED_SITES,
            AVG(TOTAL_DOWNTIME) as AVG_DOWNTIME_PER_SITE,
            SUM(TOTAL_AVAILABILITY_N) as TOTAL_N,
            SUM(TOTAL_AVAILABILITY_D) as TOTAL_D
        FROM {TABLES['availability']}
        WHERE SITE_ID_FOCUS_CATEGORY IN ('Hardware', 'Hardware - Antenna System')
          AND {date_filter}{market_filter}
          AND {site_type_filter}
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_hardware_cottr_kpi(_conn, start_date, end_date, market=None, oem=None):
    """Cached hardware COTTR KPI"""
    date_filter = f"PER_DAY_LOCAL_DATE >= '{start_date}' AND PER_DAY_LOCAL_DATE <= '{end_date}'"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'cottr', 'MKT_NAME', '')
    
    if oem:
        # Join with MARKET_TRACKER for OEM filtering
        query = f"""
        SELECT 
            SUM(c.PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINS,
            COUNT(DISTINCT c.SITE_CD) as AFFECTED_SITES,
            COUNT(*) as OUTAGE_DAYS
        FROM {TABLES['cottr']} c
        JOIN {TABLES['market_tracker']} mt ON UPPER(c.MKT_NAME) = UPPER(mt.MARKET_ID)
        WHERE c.SITE_ID_FOCUS_CATEGORY IN ('Hardware', 'Hardware - Antenna System')
          AND c.SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
          AND c.SITE_CD NOT LIKE 'USC%'
          AND c.{date_filter}{market_filter.replace('MKT_NAME', 'c.MKT_NAME')}
          AND mt.M_OEM = '{oem}'
        """
    else:
        query = f"""
        SELECT 
            SUM(PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINS,
            COUNT(DISTINCT SITE_CD) as AFFECTED_SITES,
            COUNT(*) as OUTAGE_DAYS
        FROM {TABLES['cottr']}
        WHERE SITE_ID_FOCUS_CATEGORY IN ('Hardware', 'Hardware - Antenna System')
          AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
          AND SITE_CD NOT LIKE 'USC%'
          AND {date_filter}{market_filter}
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_hardware_customer_minutes_kpi(_conn, start_date, end_date, market=None, oem=None):
    """Cached hardware customer minutes KPI"""
    date_filter = f"LOCAL_DATE_PART >= '{start_date}' AND LOCAL_DATE_PART <= '{end_date}'"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'customer_minutes', 'MARKET', '')
    
    if oem:
        # Filter by OEM using customer_minutes OEM column
        query = f"""
        SELECT 
            SUM(cm.IMPACT_DURATION_IN_MINS) as TOTAL_CM,
            SUM(cm.TOTAL_IMPACTED_SUB_CNT) as TOTAL_SUBS
        FROM {TABLES['customer_minutes']} cm
        INNER JOIN (
            SELECT DISTINCT SITE_CD 
            FROM {TABLES['cottr']} 
            WHERE SITE_ID_FOCUS_CATEGORY IN ('Hardware', 'Hardware - Antenna System')
              AND SITE_CD NOT LIKE 'USC%'
        ) hw ON cm.SITE_ID = hw.SITE_CD
        WHERE {date_filter} AND cm.SITE_ID NOT LIKE 'USC%'{market_filter}
          AND cm.OEM = '{oem}'
        """
    else:
        query = f"""
        SELECT 
            SUM(cm.IMPACT_DURATION_IN_MINS) as TOTAL_CM,
            SUM(cm.TOTAL_IMPACTED_SUB_CNT) as TOTAL_SUBS
        FROM {TABLES['customer_minutes']} cm
        INNER JOIN (
            SELECT DISTINCT SITE_CD 
            FROM {TABLES['cottr']} 
            WHERE SITE_ID_FOCUS_CATEGORY IN ('Hardware', 'Hardware - Antenna System')
              AND SITE_CD NOT LIKE 'USC%'
        ) hw ON cm.SITE_ID = hw.SITE_CD
        WHERE {date_filter} AND cm.SITE_ID NOT LIKE 'USC%'{market_filter}
        """
    return run_query(_conn, query)

@st.cache_data(ttl=DATA_CACHE_TTL, show_spinner=False)
def get_hardware_category_breakdown(_conn, start_date, end_date, market=None, oem=None, site_type=None):
    """Cached hardware category breakdown"""
    date_filter = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'"
    site_type_filter = get_site_type_sql_filter(site_type) if site_type else "1=1"
    
    # OPTIMIZED: Use memoized helper for market filter
    market_filter = build_market_sql_filter(market, 'availability', 'MARKET_ID', '')
    
    if oem:
        # Join with MARKET_TRACKER for OEM filtering
        query = f"""
        SELECT 
            a.SITE_ID_FOCUS_CATEGORY,
            SUM(a.TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
            COUNT(DISTINCT a.SITE_ID) as SITE_COUNT,
            SUM(a.TOTAL_DOWNTIME) / NULLIF(COUNT(DISTINCT a.SITE_ID), 0) as AVG_DOWNTIME_PER_SITE
        FROM {TABLES['availability']} a
        JOIN {TABLES['market_tracker']} mt ON UPPER(REPLACE(a.MARKET_ID, ' ', '')) = UPPER(mt.M_CAPITAL_MARKET)
        WHERE a.SITE_ID_FOCUS_CATEGORY IN ('Hardware', 'Hardware - Antenna System')
          AND a.{date_filter}{market_filter.replace('MARKET_ID', 'a.MARKET_ID')}
          AND mt.M_OEM = '{oem}'
          AND {site_type_filter.replace('SITE_TYPE', 'a.SITE_TYPE')}
        GROUP BY a.SITE_ID_FOCUS_CATEGORY
        ORDER BY TOTAL_DOWNTIME DESC
        """
    else:
        query = f"""
        SELECT 
            SITE_ID_FOCUS_CATEGORY,
            SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME,
            COUNT(DISTINCT SITE_ID) as SITE_COUNT,
            SUM(TOTAL_DOWNTIME) / NULLIF(COUNT(DISTINCT SITE_ID), 0) as AVG_DOWNTIME_PER_SITE
        FROM {TABLES['availability']}
        WHERE SITE_ID_FOCUS_CATEGORY IN ('Hardware', 'Hardware - Antenna System')
          AND {date_filter}{market_filter}
          AND {site_type_filter}
        GROUP BY SITE_ID_FOCUS_CATEGORY
        ORDER BY TOTAL_DOWNTIME DESC
        """
    return run_query(_conn, query)

def build_coverage_badges_html(coverage_data):
    """Build HTML for coverage classification badges"""
    if coverage_data.empty:
        return ""
    
    coverage_order = ['Standard', 'Silver', 'Bronze', 'Platinum', 'Gold', 'Unknown']
    
    coverage_html = '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">'
    for cov_class in coverage_order:
        row = coverage_data[coverage_data['COVERAGE_CLASS'] == cov_class]
        if not row.empty:
            count = int(row['SITE_COUNT'].iloc[0])
            color = COVERAGE_CLASS_COLORS.get(cov_class, '#6b7280')
            coverage_html += f'''
            <div style="background:{color};color:#000;padding:3px 8px;border-radius:4px;font-size:0.75rem;font-weight:bold;">
                {cov_class}: {count:,}
            </div>'''
    coverage_html += '</div>'
    return coverage_html

# ==================== INACTIVE SECTOR DASHBOARD ====================

@st.cache_data(ttl=SHORT_CACHE_TTL, show_spinner=False, hash_funcs={type(None): lambda _: None})
def get_inactive_sector_data_v2(_conn, start_date, end_date, days, market=None):
    """Cached query for inactive sector data - single optimized query with Helix flags (5 min cache)"""
    
    if start_date and end_date:
        date_filter = f"CAST(sec.SEC_SECTOR_STATUS_TIMESTAMP AS DATE) >= '{start_date}' AND CAST(sec.SEC_SECTOR_STATUS_TIMESTAMP AS DATE) <= '{end_date}'"
    else:
        date_filter = f"sec.SEC_SECTOR_STATUS_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Market filter - handle both single market (string) and multiple markets (list)
    if market:
        if isinstance(market, str):
            market_list = [market]
        else:
            market_list = market
        # Get all market IDs for the selection
        all_market_ids = []
        for m in market_list:
            if m:
                all_market_ids.extend(get_market_ids_for_filter(m, 'availability'))
        all_market_ids = [mid for mid in dict.fromkeys(all_market_ids) if mid]
        
        if all_market_ids:
            if len(all_market_ids) == 1:
                market_filter = f"AND UPPER(rt.MARKET_ID) = '{all_market_ids[0].upper()}'"
            else:
                market_list_str = "', '".join([mid.upper() for mid in all_market_ids])
                market_filter = f"AND UPPER(rt.MARKET_ID) IN ('{market_list_str}')"
        else:
            market_filter = ""
    else:
        market_filter = ""
    
    # Single optimized query with Helix flags from CR and Incidents
    query = f"""
    WITH inactive_sectors AS (
        SELECT 
            sec.SITE_ID,
            sec.SEC_CELL_NAME_ACTUAL,
            sec.SEC_SECTOR_STATUS_TIMESTAMP,
            CAST(sec.SEC_SECTOR_STATUS_TIMESTAMP AS DATE) as STATUS_DATE,
            sec.SEC_MODIFIED_USER_NAME,
            sec.SEC_TECHNOLOGY,
            sec.SEC_NOTES_HISTORY as SEC_SECTOR_NOTES,
            rt.MARKET_ID,
            mt.REGION_ID,
            mt.M_OEM as OEM
        FROM {TABLES['sector_tracker']} sec
        LEFT JOIN {TABLES['site_tracker']} st ON sec.SITE_ID = st.SITE_ID
        LEFT JOIN {TABLES['ring_tracker']} rt ON st.RING_ID = rt.RING_ID
        LEFT JOIN {TABLES['market_tracker']} mt ON REPLACE(rt.MARKET_ID, ' ', '') = mt.M_CAPITAL_MARKET
        WHERE sec.SEC_SECTOR_STATUS = 'Inactive'
          AND {date_filter}
          AND sec.SITE_ID NOT LIKE 'USC%'
          {market_filter}
    ),
    cr_helix AS (
        SELECT DISTINCT cr.CONFIG_ITEM as SITE_ID, 'Yes' as CR_HELIX_FLAG
        FROM {TABLES['change_record']} cr
        JOIN inactive_sectors isec ON cr.CONFIG_ITEM = isec.SITE_ID
        WHERE (cr.PLANNED_START_DATE >= DATEADD(month, -3, isec.SEC_SECTOR_STATUS_TIMESTAMP)
               OR cr.PLANNED_END_DATE >= DATEADD(month, -3, isec.SEC_SECTOR_STATUS_TIMESTAMP)
               OR cr.OPENED_DATE >= DATEADD(month, -3, isec.SEC_SECTOR_STATUS_TIMESTAMP))
          AND (LOWER(COALESCE(cr.SHORT_DESCRIPTION, '')) LIKE '%helix%'
               OR LOWER(COALESCE(cr.DESCRIPTION, '')) LIKE '%helix%')
    ),
    incident_helix AS (
        SELECT DISTINCT inc.CONFIG_ITEM as SITE_ID, 'Yes' as INC_HELIX_FLAG
        FROM {TABLES['incident_all']} inc
        JOIN inactive_sectors isec ON inc.CONFIG_ITEM = isec.SITE_ID
        WHERE inc.OPENED_DATE >= DATEADD(month, -3, isec.SEC_SECTOR_STATUS_TIMESTAMP)
          AND (LOWER(COALESCE(inc.SHORT_DESCRIPTION, '')) LIKE '%helix%'
               OR LOWER(COALESCE(inc.DESCRIPTION, '')) LIKE '%helix%')
    ),
    cr_decom AS (
        SELECT DISTINCT cr.CONFIG_ITEM as SITE_ID, 'Yes' as CR_DECOM_FLAG
        FROM {TABLES['change_record']} cr
        JOIN inactive_sectors isec ON cr.CONFIG_ITEM = isec.SITE_ID
        WHERE (cr.PLANNED_START_DATE >= DATEADD(month, -3, isec.SEC_SECTOR_STATUS_TIMESTAMP)
               OR cr.PLANNED_END_DATE >= DATEADD(month, -3, isec.SEC_SECTOR_STATUS_TIMESTAMP)
               OR cr.OPENED_DATE >= DATEADD(month, -3, isec.SEC_SECTOR_STATUS_TIMESTAMP))
          AND (LOWER(COALESCE(cr.SHORT_DESCRIPTION, '')) LIKE '%decom%'
               OR LOWER(COALESCE(cr.DESCRIPTION, '')) LIKE '%decom%')
    ),
    incident_decom AS (
        SELECT DISTINCT inc.CONFIG_ITEM as SITE_ID, 'Yes' as INC_DECOM_FLAG
        FROM {TABLES['incident_all']} inc
        JOIN inactive_sectors isec ON inc.CONFIG_ITEM = isec.SITE_ID
        WHERE inc.OPENED_DATE >= DATEADD(month, -3, isec.SEC_SECTOR_STATUS_TIMESTAMP)
          AND (LOWER(COALESCE(inc.SHORT_DESCRIPTION, '')) LIKE '%decom%'
               OR LOWER(COALESCE(inc.DESCRIPTION, '')) LIKE '%decom%')
    ),
    nest_helix AS (
        SELECT DISTINCT nest.CONFIGITEM as SITE_ID, 'Yes' as NEST_HELIX_FLAG
        FROM {TABLES['nest_state_change']} nest
        JOIN inactive_sectors isec ON nest.CONFIGITEM = isec.SITE_ID
        WHERE nest.STATETRANSFERBEGINSAT >= DATEADD(month, -3, isec.SEC_SECTOR_STATUS_TIMESTAMP)
          AND LOWER(COALESCE(nest.NOTES, '')) LIKE '%helix%'
    ),
    nest_decom AS (
        SELECT DISTINCT nest.CONFIGITEM as SITE_ID, 'Yes' as NEST_DECOM_FLAG
        FROM {TABLES['nest_state_change']} nest
        JOIN inactive_sectors isec ON nest.CONFIGITEM = isec.SITE_ID
        WHERE nest.STATETRANSFERBEGINSAT >= DATEADD(month, -3, isec.SEC_SECTOR_STATUS_TIMESTAMP)
          AND LOWER(COALESCE(nest.NOTES, '')) LIKE '%decom%'
    )
    SELECT 
        isec.*,
        COALESCE(crh.CR_HELIX_FLAG, 'No') as CR_HELIX_FLAG,
        COALESCE(inch.INC_HELIX_FLAG, 'No') as INC_HELIX_FLAG,
        COALESCE(crd.CR_DECOM_FLAG, 'No') as CR_DECOM_FLAG,
        COALESCE(incd.INC_DECOM_FLAG, 'No') as INC_DECOM_FLAG,
        COALESCE(nesth.NEST_HELIX_FLAG, 'No') as NEST_HELIX_FLAG,
        COALESCE(nestd.NEST_DECOM_FLAG, 'No') as NEST_DECOM_FLAG,
        CASE WHEN LOWER(COALESCE(isec.SEC_SECTOR_NOTES, '')) LIKE '%helix%' THEN 'Yes' ELSE 'No' END as NOTES_HELIX_FLAG,
        CASE WHEN LOWER(COALESCE(isec.SEC_SECTOR_NOTES, '')) LIKE '%decom%' OR LOWER(COALESCE(isec.SEC_SECTOR_NOTES, '')) LIKE '%decomm%' THEN 'Yes' ELSE 'No' END as NOTES_DECOM_FLAG
    FROM inactive_sectors isec
    LEFT JOIN cr_helix crh ON isec.SITE_ID = crh.SITE_ID
    LEFT JOIN incident_helix inch ON isec.SITE_ID = inch.SITE_ID
    LEFT JOIN cr_decom crd ON isec.SITE_ID = crd.SITE_ID
    LEFT JOIN incident_decom incd ON isec.SITE_ID = incd.SITE_ID
    LEFT JOIN nest_helix nesth ON isec.SITE_ID = nesth.SITE_ID
    LEFT JOIN nest_decom nestd ON isec.SITE_ID = nestd.SITE_ID
    LIMIT 5000
    """
    return run_query(_conn, query)

def inactive_sector_dashboard(conn, days, filters=None):
    """Inactive Sector Dashboard - Shows sectors changed to Inactive status"""
    
    st.markdown('<div class="section-header">📡 Inactive Sector Analysis</div>', unsafe_allow_html=True)
    st.markdown("<span style='font-size:0.9rem;color:#888;'>Tracking sectors with SEC_SECTOR_STATUS = 'Inactive'</span>", unsafe_allow_html=True)
    
    # Date and market filters
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    market = filters.get('market') if filters else None
    market_display = get_market_display_name(market)
    
    # Show market filter indicator
    if market:
        st.info(f"📍 Filtered to market: **{market_display}**")
    
    with st.spinner("Loading inactive sector data..."):
        # Single cached query with market filter
        inactive_data = get_inactive_sector_data_v2(conn, start_date, end_date, days, market)
    
    if inactive_data.empty:
        st.info("No inactive sectors found for the selected date range.")
        return
    
    # Normalize market names to Global Market ID format at source
    if 'MARKET_ID' in inactive_data.columns:
        inactive_data = normalize_market_column(inactive_data, 'MARKET_ID', 'availability')
    
    # Aggregate using pandas (fast, no additional DB calls)
    market_summary = inactive_data.groupby('MARKET_ID').agg({
        'SITE_ID': 'nunique',
        'SEC_CELL_NAME_ACTUAL': 'nunique'
    }).reset_index()
    market_summary.columns = ['MARKET_ID', 'SITE_COUNT', 'SECTOR_COUNT']
    market_summary = market_summary.sort_values('SECTOR_COUNT', ascending=False)
    
    daily_trend = inactive_data.groupby('STATUS_DATE').agg({
        'SITE_ID': 'nunique',
        'SEC_CELL_NAME_ACTUAL': 'nunique'
    }).reset_index()
    daily_trend.columns = ['STATUS_DATE', 'SITE_COUNT', 'SECTOR_COUNT']
    daily_trend = daily_trend.sort_values('STATUS_DATE')
    
    user_summary = inactive_data.groupby('SEC_MODIFIED_USER_NAME').agg({
        'SITE_ID': 'nunique',
        'SEC_CELL_NAME_ACTUAL': 'nunique'
    }).reset_index()
    user_summary.columns = ['SEC_MODIFIED_USER_NAME', 'SITE_COUNT', 'SECTOR_COUNT']
    user_summary = user_summary.sort_values('SECTOR_COUNT', ascending=False)
    
    tech_summary = inactive_data.groupby('SEC_TECHNOLOGY').agg({
        'SITE_ID': 'nunique',
        'SEC_CELL_NAME_ACTUAL': 'nunique'
    }).reset_index()
    tech_summary.columns = ['SEC_TECHNOLOGY', 'SITE_COUNT', 'SECTOR_COUNT']
    tech_summary = tech_summary.sort_values('SECTOR_COUNT', ascending=False)
    
    # ===== KPI Summary Cards =====
    st.markdown("### 📊 Inactive Sector Summary")
    
    total_sectors = inactive_data['SEC_CELL_NAME_ACTUAL'].nunique()
    total_sites = inactive_data['SITE_ID'].nunique()
    total_markets = inactive_data['MARKET_ID'].nunique()
    total_users = inactive_data['SEC_MODIFIED_USER_NAME'].nunique()
    
    kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
    
    with kpi_col1:
        st.markdown(f"""
        <div style='background:linear-gradient(135deg,#1e1e2e,#2d2d3d);padding:15px;border-radius:10px;border-left:4px solid #e20074;'>
            <div style='color:#888;font-size:0.85rem;'>Total Inactive Sectors</div>
            <div style='color:#e20074;font-size:2rem;font-weight:bold;'>{total_sectors:,}</div>
            <div style='color:#888;font-size:0.75rem;'>SEC_CELL_NAME_ACTUAL</div>
        </div>
        """, unsafe_allow_html=True)
    
    with kpi_col2:
        st.markdown(f"""
        <div style='background:linear-gradient(135deg,#1e1e2e,#2d2d3d);padding:15px;border-radius:10px;border-left:4px solid #3b82f6;'>
            <div style='color:#888;font-size:0.85rem;'>Unique Sites</div>
            <div style='color:#3b82f6;font-size:2rem;font-weight:bold;'>{total_sites:,}</div>
            <div style='color:#888;font-size:0.75rem;'>SITE_ID</div>
        </div>
        """, unsafe_allow_html=True)
    
    with kpi_col3:
        st.markdown(f"""
        <div style='background:linear-gradient(135deg,#1e1e2e,#2d2d3d);padding:15px;border-radius:10px;border-left:4px solid #22c55e;'>
            <div style='color:#888;font-size:0.85rem;'>Markets Affected</div>
            <div style='color:#22c55e;font-size:2rem;font-weight:bold;'>{total_markets:,}</div>
            <div style='color:#888;font-size:0.75rem;'>Unique markets</div>
        </div>
        """, unsafe_allow_html=True)
    
    with kpi_col4:
        st.markdown(f"""
        <div style='background:linear-gradient(135deg,#1e1e2e,#2d2d3d);padding:15px;border-radius:10px;border-left:4px solid #f59e0b;'>
            <div style='color:#888;font-size:0.85rem;'>Modified By Users</div>
            <div style='color:#f59e0b;font-size:2rem;font-weight:bold;'>{total_users:,}</div>
            <div style='color:#888;font-size:0.75rem;'>SEC_MODIFIED_USER_NAME</div>
        </div>
        """, unsafe_allow_html=True)
    
    # Exclude Helix/Decom Filter
    exclude_col1, exclude_col2 = st.columns([1, 3])
    with exclude_col1:
        exclude_helix_decom = st.checkbox("Exclude sites with Helix/Decom flags", key="exclude_helix_decom")
    
    # Apply exclusion filter for display data
    display_data = inactive_data.copy()
    if exclude_helix_decom:
        helix_decom_mask = (
            (display_data.get('CR_HELIX_FLAG', 'No') == 'Yes') |
            (display_data.get('INC_HELIX_FLAG', 'No') == 'Yes') |
            (display_data.get('NEST_HELIX_FLAG', 'No') == 'Yes') |
            (display_data.get('CR_DECOM_FLAG', 'No') == 'Yes') |
            (display_data.get('INC_DECOM_FLAG', 'No') == 'Yes') |
            (display_data.get('NEST_DECOM_FLAG', 'No') == 'Yes')
        )
        display_data = display_data[~helix_decom_mask]
        st.info(f"Showing {display_data['SITE_ID'].nunique():,} sites after excluding Helix/Decom matches")
        
        # Recalculate aggregations for filtered data
        market_summary = display_data.groupby('MARKET_ID').agg({
            'SITE_ID': 'nunique',
            'SEC_CELL_NAME_ACTUAL': 'nunique'
        }).reset_index()
        market_summary.columns = ['MARKET_ID', 'SITE_COUNT', 'SECTOR_COUNT']
        market_summary = market_summary.sort_values('SECTOR_COUNT', ascending=False)
        
        daily_trend = display_data.groupby('STATUS_DATE').agg({
            'SITE_ID': 'nunique',
            'SEC_CELL_NAME_ACTUAL': 'nunique'
        }).reset_index()
        daily_trend.columns = ['STATUS_DATE', 'SITE_COUNT', 'SECTOR_COUNT']
        daily_trend = daily_trend.sort_values('STATUS_DATE')
    
    # Row 2: CR, INC, NEST Combined Tiles (Past 3 Months)
    cr_helix_yes = inactive_data[inactive_data['CR_HELIX_FLAG'] == 'Yes']['SITE_ID'].nunique() if 'CR_HELIX_FLAG' in inactive_data.columns else 0
    inc_helix_yes = inactive_data[inactive_data['INC_HELIX_FLAG'] == 'Yes']['SITE_ID'].nunique() if 'INC_HELIX_FLAG' in inactive_data.columns else 0
    nest_helix_yes = inactive_data[inactive_data['NEST_HELIX_FLAG'] == 'Yes']['SITE_ID'].nunique() if 'NEST_HELIX_FLAG' in inactive_data.columns else 0
    cr_decom_yes = inactive_data[inactive_data['CR_DECOM_FLAG'] == 'Yes']['SITE_ID'].nunique() if 'CR_DECOM_FLAG' in inactive_data.columns else 0
    inc_decom_yes = inactive_data[inactive_data['INC_DECOM_FLAG'] == 'Yes']['SITE_ID'].nunique() if 'INC_DECOM_FLAG' in inactive_data.columns else 0
    nest_decom_yes = inactive_data[inactive_data['NEST_DECOM_FLAG'] == 'Yes']['SITE_ID'].nunique() if 'NEST_DECOM_FLAG' in inactive_data.columns else 0
    cr_helix_pct = (cr_helix_yes / total_sites * 100) if total_sites > 0 else 0
    inc_helix_pct = (inc_helix_yes / total_sites * 100) if total_sites > 0 else 0
    nest_helix_pct = (nest_helix_yes / total_sites * 100) if total_sites > 0 else 0
    cr_decom_pct = (cr_decom_yes / total_sites * 100) if total_sites > 0 else 0
    inc_decom_pct = (inc_decom_yes / total_sites * 100) if total_sites > 0 else 0
    nest_decom_pct = (nest_decom_yes / total_sites * 100) if total_sites > 0 else 0
    
    st.markdown("#### 🔍 CR/Incident/NEST Correlation (Past 3 Months)")
    corr_col1, corr_col2 = st.columns(2)
    
    with corr_col1:
        st.markdown(f"""
        <div style='background:linear-gradient(135deg,#1e1e2e,#2d2d3d);padding:15px;border-radius:10px;border-left:4px solid #E20074;'>
            <div style='color:#E20074;font-size:0.9rem;font-weight:bold;margin-bottom:10px;'>HELIX Matches</div>
            <div style='display:flex;justify-content:space-between;'>
                <div style='text-align:center;'>
                    <div style='color:#888;font-size:0.75rem;'>CR</div>
                    <div style='color:#E20074;font-size:1.6rem;font-weight:bold;'>{cr_helix_yes:,}</div>
                    <div style='color:#888;font-size:0.65rem;'>{cr_helix_pct:.1f}%</div>
                </div>
                <div style='text-align:center;'>
                    <div style='color:#888;font-size:0.75rem;'>INC</div>
                    <div style='color:#ec4899;font-size:1.6rem;font-weight:bold;'>{inc_helix_yes:,}</div>
                    <div style='color:#888;font-size:0.65rem;'>{inc_helix_pct:.1f}%</div>
                </div>
                <div style='text-align:center;'>
                    <div style='color:#888;font-size:0.75rem;'>NEST</div>
                    <div style='color:#06b6d4;font-size:1.6rem;font-weight:bold;'>{nest_helix_yes:,}</div>
                    <div style='color:#888;font-size:0.65rem;'>{nest_helix_pct:.1f}%</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with corr_col2:
        st.markdown(f"""
        <div style='background:linear-gradient(135deg,#1e1e2e,#2d2d3d);padding:15px;border-radius:10px;border-left:4px solid #f97316;'>
            <div style='color:#f97316;font-size:0.9rem;font-weight:bold;margin-bottom:10px;'>DECOM Matches</div>
            <div style='display:flex;justify-content:space-between;'>
                <div style='text-align:center;'>
                    <div style='color:#888;font-size:0.75rem;'>CR</div>
                    <div style='color:#f97316;font-size:1.6rem;font-weight:bold;'>{cr_decom_yes:,}</div>
                    <div style='color:#888;font-size:0.65rem;'>{cr_decom_pct:.1f}%</div>
                </div>
                <div style='text-align:center;'>
                    <div style='color:#888;font-size:0.75rem;'>INC</div>
                    <div style='color:#ef4444;font-size:1.6rem;font-weight:bold;'>{inc_decom_yes:,}</div>
                    <div style='color:#888;font-size:0.65rem;'>{inc_decom_pct:.1f}%</div>
                </div>
                <div style='text-align:center;'>
                    <div style='color:#888;font-size:0.75rem;'>NEST</div>
                    <div style='color:#861B54;font-size:1.6rem;font-weight:bold;'>{nest_decom_yes:,}</div>
                    <div style='color:#888;font-size:0.65rem;'>{nest_decom_pct:.1f}%</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # ===== Row 1: Daily Trend & By Market =====
    st.markdown("### 📈 Inactive Sectors Over Time")
    
    row1_col1, row1_col2 = st.columns(2)
    
    with row1_col1:
        st.markdown("##### Daily Trend - Sectors Changed to Inactive")
        if not daily_trend.empty:
            daily_trend['STATUS_DATE'] = pd.to_datetime(daily_trend['STATUS_DATE'])
            daily_trend = daily_trend.sort_values('STATUS_DATE')
            
            fig_daily = go.Figure()
            fig_daily.add_trace(go.Bar(
                x=daily_trend['STATUS_DATE'],
                y=daily_trend['SECTOR_COUNT'],
                name='Sectors',
                marker_color='#e20074',
                hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Sectors: %{y:,}<extra></extra>'
            ))
            fig_daily.add_trace(go.Scatter(
                x=daily_trend['STATUS_DATE'],
                y=daily_trend['SITE_COUNT'],
                name='Sites',
                mode='lines+markers',
                line=dict(color='#3b82f6', width=2),
                marker=dict(size=6),
                yaxis='y2',
                hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Sites: %{y:,}<extra></extra>'
            ))
            
            fig_daily.update_layout(
                template='plotly_white',
                height=400,
                font=dict(size=13),
                xaxis=dict(title='Date', tickfont=dict(size=11)),
                yaxis=dict(title='Sector Count', tickfont=dict(size=11), side='left'),
                yaxis2=dict(title='Site Count', tickfont=dict(size=11), overlaying='y', side='right'),
                legend=dict(orientation='h', yanchor='top', y=-0.15, xanchor='center', x=0.5),
                margin=dict(l=10, r=10, t=20, b=60)
            )
            st.plotly_chart(fig_daily, use_container_width=True, config=CHART_CONFIG, key="inactive_daily_trend")
        else:
            st.info("No daily trend data available.")
    
    with row1_col2:
        # Site Count by Region
        if 'REGION_ID' in display_data.columns:
            region_counts = display_data.groupby('REGION_ID')['SITE_ID'].nunique().reset_index()
            region_counts.columns = ['REGION_ID', 'SITE_COUNT']
            region_counts = region_counts.sort_values('SITE_COUNT', ascending=False)
            
            region_text = " | ".join([f"<span style='color:#000;font-weight:bold;'>{row['REGION_ID']}: {row['SITE_COUNT']:,}</span>" for _, row in region_counts.iterrows() if pd.notna(row['REGION_ID'])])
            st.markdown(f"""
            <div style='background:#f8f9fa;padding:8px 12px;border-radius:6px;margin-bottom:10px;'>
                <span style='color:#666;font-size:0.8rem;font-weight:600;'>Sites by Region: </span>
                <span style='font-size:0.8rem;'>{region_text}</span>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("##### Inactive Sectors by Market (Top 20)")
        if not market_summary.empty:
            market_summary = market_summary.dropna(subset=['MARKET_ID'])
            top_markets = market_summary.head(20).sort_values('SECTOR_COUNT', ascending=True)
            
            fig_market = go.Figure()
            fig_market.add_trace(go.Bar(
                y=top_markets['MARKET_ID'],
                x=top_markets['SECTOR_COUNT'],
                orientation='h',
                marker_color='#e20074',
                text=top_markets.apply(lambda r: f"  {r['SECTOR_COUNT']:,} sectors / {r['SITE_COUNT']:,} sites", axis=1),
                textposition='inside',
                insidetextanchor='start',
                textfont=dict(size=11, color='white', family='Arial Black'),
                cliponaxis=False,
                hoverinfo='skip'
            ))
            
            fig_market.update_layout(
                template='plotly_white',
                height=500,
                font=dict(size=13),
                xaxis=dict(title='Sector Count', tickfont=dict(size=11)),
                yaxis=dict(tickfont=dict(size=10)),
                margin=dict(l=10, r=20, t=20, b=40),
                bargap=0.15
            )
            st.plotly_chart(fig_market, use_container_width=True, config=CHART_CONFIG, key="inactive_by_market")
        else:
            st.info("No market data available.")
    
    st.divider()
    
    # ===== Row 2: By User & By Technology =====
    st.markdown("### 👤 Breakdown by User & Technology")
    
    row2_col1, row2_col2 = st.columns(2)
    
    with row2_col1:
        st.markdown("##### Inactive Sectors by Modified User (Top 15)")
        if not user_summary.empty:
            user_summary = user_summary.dropna(subset=['SEC_MODIFIED_USER_NAME'])
            user_summary = user_summary[user_summary['SEC_MODIFIED_USER_NAME'] != '']
            top_users = user_summary.head(15).sort_values('SECTOR_COUNT', ascending=True)
            
            fig_user = go.Figure()
            fig_user.add_trace(go.Bar(
                y=top_users['SEC_MODIFIED_USER_NAME'],
                x=top_users['SECTOR_COUNT'],
                orientation='h',
                marker_color='#f59e0b',
                text=top_users.apply(lambda r: f"  {r['SECTOR_COUNT']:,} sectors / {r['SITE_COUNT']:,} sites", axis=1),
                textposition='inside',
                insidetextanchor='start',
                textfont=dict(size=11, color='white', family='Arial Black'),
                cliponaxis=False,
                hoverinfo='skip'
            ))
            
            fig_user.update_layout(
                template='plotly_white',
                height=400,
                font=dict(size=13),
                xaxis=dict(title='Sector Count', tickfont=dict(size=11)),
                yaxis=dict(tickfont=dict(size=10)),
                margin=dict(l=10, r=20, t=20, b=40),
                bargap=0.15
            )
            st.plotly_chart(fig_user, use_container_width=True, config=CHART_CONFIG, key="inactive_by_user")
        else:
            st.info("No user data available.")
    
    with row2_col2:
        st.markdown("##### Inactive Sectors by Technology")
        if not tech_summary.empty:
            tech_summary = tech_summary.dropna(subset=['SEC_TECHNOLOGY'])
            tech_summary = tech_summary[tech_summary['SEC_TECHNOLOGY'] != '']
            
            fig_tech = go.Figure()
            fig_tech.add_trace(go.Bar(
                x=tech_summary['SEC_TECHNOLOGY'],
                y=tech_summary['SECTOR_COUNT'],
                marker_color='#22c55e',
                text=tech_summary.apply(lambda r: f"{r['SECTOR_COUNT']:,}<br>{r['SITE_COUNT']:,} sites", axis=1),
                textposition='inside',
                insidetextanchor='end',
                textfont=dict(size=11, color='white', family='Arial Black'),
                cliponaxis=False,
                hoverinfo='skip'
            ))
            
            fig_tech.update_layout(
                template='plotly_white',
                height=400,
                font=dict(size=13),
                xaxis=dict(title='Technology', tickfont=dict(size=11)),
                yaxis=dict(title='Sector Count', tickfont=dict(size=11)),
                margin=dict(l=10, r=10, t=20, b=40),
                bargap=0.15
            )
            st.plotly_chart(fig_tech, use_container_width=True, config=CHART_CONFIG, key="inactive_by_tech")
        else:
            st.info("No technology data available.")
    
    st.divider()
    
    # ===== Row 3: Detailed Data Table =====
    st.markdown("### 📋 Inactive Sector Details")
    
    if not inactive_data.empty:
        # Add filters for the table - Row 1
        st.markdown("**Filters:**")
        filter_row1_col1, filter_row1_col2, filter_row1_col3, filter_row1_col4 = st.columns(4)
        
        with filter_row1_col1:
            site_id_filter = st.text_input(
                "Filter by Site ID",
                value="",
                placeholder="Enter Site ID...",
                key="inactive_site_id_filter"
            )
        
        with filter_row1_col2:
            market_filter = st.selectbox(
                "Filter by Market",
                options=['All'] + sorted(inactive_data['MARKET_ID'].dropna().unique().tolist()),
                key="inactive_market_filter"
            )
        
        with filter_row1_col3:
            user_filter = st.selectbox(
                "Filter by User",
                options=['All'] + sorted(inactive_data['SEC_MODIFIED_USER_NAME'].dropna().unique().tolist()),
                key="inactive_user_filter"
            )
        
        with filter_row1_col4:
            tech_filter = st.selectbox(
                "Filter by Technology",
                options=['All'] + sorted(inactive_data['SEC_TECHNOLOGY'].dropna().unique().tolist()),
                key="inactive_tech_filter"
            )
        
        # Row 2 filters
        filter_row2_col1, filter_row2_col2, filter_row2_col3 = st.columns([2, 1, 1])
        
        with filter_row2_col1:
            notes_filter = st.text_input(
                "Filter by Sector Notes History",
                value="",
                placeholder="Search notes (e.g., helix, decom)...",
                key="inactive_notes_filter"
            )
        
        with filter_row2_col2:
            oem_options = ['All'] + sorted(inactive_data['OEM'].dropna().unique().tolist())
            oem_filter = st.selectbox(
                "Filter by OEM",
                options=oem_options,
                key="inactive_oem_filter"
            )
        
        # Apply filters (uses exclude_helix_decom from top filter)
        filtered_data = inactive_data.copy()
        if site_id_filter:
            filtered_data = filtered_data[filtered_data['SITE_ID'].str.contains(site_id_filter.upper(), case=False, na=False)]
        if market_filter != 'All':
            filtered_data = filtered_data[filtered_data['MARKET_ID'] == market_filter]
        if user_filter != 'All':
            filtered_data = filtered_data[filtered_data['SEC_MODIFIED_USER_NAME'] == user_filter]
        if tech_filter != 'All':
            filtered_data = filtered_data[filtered_data['SEC_TECHNOLOGY'] == tech_filter]
        if oem_filter != 'All':
            filtered_data = filtered_data[filtered_data['OEM'] == oem_filter]
        if notes_filter:
            filtered_data = filtered_data[filtered_data['SEC_SECTOR_NOTES'].str.contains(notes_filter, case=False, na=False)]
        
        # Apply Helix/Decom exclusion from top filter
        if exclude_helix_decom:
            helix_decom_cols = ['CR_HELIX_FLAG', 'INC_HELIX_FLAG', 'NEST_HELIX_FLAG', 
                               'CR_DECOM_FLAG', 'INC_DECOM_FLAG', 'NEST_DECOM_FLAG',
                               'NOTES_HELIX_FLAG', 'NOTES_DECOM_FLAG']
            for col in helix_decom_cols:
                if col in filtered_data.columns:
                    filtered_data = filtered_data[filtered_data[col] != 'Yes']
        
        st.markdown(f"**Showing {len(filtered_data):,} records**")
        
        # Display table with Helix, Decom, NEST, and Notes flags
        display_cols = ['SITE_ID', 'SEC_CELL_NAME_ACTUAL', 'MARKET_ID', 'OEM', 'SEC_TECHNOLOGY', 
                       'SEC_MODIFIED_USER_NAME', 'SEC_SECTOR_STATUS_TIMESTAMP', 'SEC_SECTOR_NOTES',
                       'NOTES_HELIX_FLAG', 'NOTES_DECOM_FLAG',
                       'CR_HELIX_FLAG', 'INC_HELIX_FLAG', 'NEST_HELIX_FLAG',
                       'CR_DECOM_FLAG', 'INC_DECOM_FLAG', 'NEST_DECOM_FLAG']
        display_data = filtered_data[[c for c in display_cols if c in filtered_data.columns]].copy()
        display_data = display_data.sort_values('SEC_SECTOR_STATUS_TIMESTAMP', ascending=False)
        
        st.dataframe(
            display_data.head(500),
            use_container_width=True,
            hide_index=True,
            height=400
        )
    else:
        st.info("No data available.")

def nonmacro_comparison_dashboard(conn, days, filters=None):
    """Non-Macro V1 vs V2 Comparison Dashboard - OPTIMIZED with batched queries"""
    
    st.markdown('<div class="section-header">📊 Non-Macro: V1 vs V2 Comparison</div>', unsafe_allow_html=True)
    st.markdown(f"<span style='font-size:0.85rem;color:#888;'>Comparing IMPACT_DURATION_IN_MINS between V1 and V2 tables for non-macro sites (DAS, Micro, Pico, etc.)</span>", unsafe_allow_html=True)
    
    # Inform user about site type filter
    current_site_type = filters.get('site_type') if filters else None
    if current_site_type == 'Macro':
        st.info("ℹ️ **Site Type filter is 'Macro'** - This dashboard analyzes only Non-Macro sites in the data below.")
    
    # Update active tab for filter defaulting on next interaction
    st.session_state.active_tab = "🔄 Non-Macro V1 vs V2"
    
    # ===== OPTIMIZED: Batch all data queries at start =====
    # Extract date filters once
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    
    # Show loading progress
    progress_placeholder = st.empty()
    progress_placeholder.info("⏳ Loading V1 vs V2 comparison data... (cached for 5 min after first load)")
    
    # All queries are cached by date params only (not full filters) for better cache hit rate
    master_data = get_nonmacro_master_data(conn, days, start_date, end_date)
    
    # Only load focus category data if master data loaded successfully
    if not master_data.empty:
        focus_cat_data = get_nonmacro_by_focus_category(conn, days, start_date, end_date)
        cottr_focus_data = get_nonmacro_cottr_by_focus_category(conn, days, start_date, end_date)
        avail_focus_data = get_nonmacro_availability_by_focus_category(conn, days, start_date, end_date)
    else:
        focus_cat_data = pd.DataFrame()
        cottr_focus_data = pd.DataFrame()
        avail_focus_data = pd.DataFrame()
    
    # Clear loading message
    progress_placeholder.empty()
    
    if master_data.empty:
        st.warning("No non-macro comparison data available for the selected time range.")
        return
    
    # ===== Aggregate data using pandas (fast, no additional DB calls) =====
    summary_by_type = aggregate_nonmacro_by_type(master_data)
    
    if summary_by_type.empty:
        st.warning("No non-macro comparison data available for the selected time range.")
        return
    
    # Calculate totals
    total_sites = summary_by_type['TOTAL_SITES'].sum()
    v1_total_mins = summary_by_type['V1_TOTAL_IMPACT_MINS'].sum()
    v2_total_mins = summary_by_type['V2_TOTAL_IMPACT_MINS'].sum()
    delta_mins = v1_total_mins - v2_total_mins
    v1_total_subs = summary_by_type['V1_TOTAL_SUBS'].sum()
    v2_total_subs = summary_by_type['V2_TOTAL_SUBS'].sum()
    delta_subs = v1_total_subs - v2_total_subs
    
    # KPI Cards
    kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
    
    with kpi_col1:
        st.markdown(f"""
        <div style='background:linear-gradient(135deg,#1e1e2e,#2d2d3d);padding:15px;border-radius:10px;border-left:4px solid #e20074;'>
            <div style='color:#888;font-size:0.8rem;'>Total Non-Macro Sites</div>
            <div style='color:#fff;font-size:1.8rem;font-weight:bold;'>{total_sites:,}</div>
            <div style='color:#888;font-size:0.75rem;'>DAS, Micro, Pico, etc.</div>
        </div>
        """, unsafe_allow_html=True)
    
    with kpi_col2:
        delta_color = '#22c55e' if delta_mins >= 0 else '#ef4444'
        delta_arrow = '▲' if delta_mins >= 0 else '▼'
        st.markdown(f"""
        <div style='background:linear-gradient(135deg,#1e1e2e,#2d2d3d);padding:15px;border-radius:10px;border-left:4px solid #3b82f6;'>
            <div style='color:#888;font-size:0.8rem;'>V1 Impact Minutes</div>
            <div style='color:#fff;font-size:1.8rem;font-weight:bold;'>{v1_total_mins:,.0f}</div>
            <div style='color:{delta_color};font-size:0.75rem;'>{delta_arrow} {abs(delta_mins):,.0f} vs V2</div>
        </div>
        """, unsafe_allow_html=True)
    
    with kpi_col3:
        st.markdown(f"""
        <div style='background:linear-gradient(135deg,#1e1e2e,#2d2d3d);padding:15px;border-radius:10px;border-left:4px solid #22c55e;'>
            <div style='color:#888;font-size:0.8rem;'>V2 Impact Minutes</div>
            <div style='color:#fff;font-size:1.8rem;font-weight:bold;'>{v2_total_mins:,.0f}</div>
            <div style='color:#888;font-size:0.75rem;'>Current version</div>
        </div>
        """, unsafe_allow_html=True)
    
    with kpi_col4:
        delta_pct = ((v1_total_mins - v2_total_mins) / v1_total_mins * 100) if v1_total_mins > 0 else 0
        pct_color = '#22c55e' if delta_pct >= 0 else '#ef4444'
        st.markdown(f"""
        <div style='background:linear-gradient(135deg,#1e1e2e,#2d2d3d);padding:15px;border-radius:10px;border-left:4px solid #f59e0b;'>
            <div style='color:#888;font-size:0.8rem;'>Delta (V1 - V2)</div>
            <div style='color:{pct_color};font-size:1.8rem;font-weight:bold;'>{delta_mins:+,.0f}</div>
            <div style='color:{pct_color};font-size:0.75rem;'>{delta_pct:+.1f}% difference</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # ===== ROW 1: Summary by Site Type =====
    st.markdown("### 📊 Comparison by Site Type")
    
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        st.markdown("##### Impact Minutes: V1 vs V2")
        
        # Calculate % change for each site type
        summary_by_type['PCT_CHANGE'] = summary_by_type.apply(
            lambda r: ((r['V2_TOTAL_IMPACT_MINS'] - r['V1_TOTAL_IMPACT_MINS']) / r['V1_TOTAL_IMPACT_MINS'] * 100) 
            if r['V1_TOTAL_IMPACT_MINS'] > 0 else 0, axis=1
        )
        
        fig_type = go.Figure()
        
        # V1 bars
        fig_type.add_trace(go.Bar(
            name='V1 (Original)',
            x=summary_by_type['SITE_TYPE'],
            y=summary_by_type['V1_TOTAL_IMPACT_MINS'],
            marker_color='#3b82f6',
            text=summary_by_type['V1_TOTAL_IMPACT_MINS'].apply(lambda x: f'{x:,.0f}'),
            textposition='outside'
        ))
        
        # V2 bars with % change in text
        fig_type.add_trace(go.Bar(
            name='V2 (Current)',
            x=summary_by_type['SITE_TYPE'],
            y=summary_by_type['V2_TOTAL_IMPACT_MINS'],
            marker_color='#22c55e',
            text=summary_by_type.apply(lambda r: f"{r['V2_TOTAL_IMPACT_MINS']:,.0f}<br><span style='color:{'#22c55e' if r['PCT_CHANGE'] <= 0 else '#ef4444'}'>{r['PCT_CHANGE']:+.1f}%</span>", axis=1),
            textposition='outside'
        ))
        
        fig_type.update_layout(
            template='plotly_white',
            height=450,
            barmode='group',
            font=dict(size=14),
            xaxis=dict(title='Site Type', tickfont=dict(size=12)),
            yaxis=dict(title='Impact Minutes', tickfont=dict(size=12)),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5, font=dict(size=12)),
            margin=dict(t=60, b=50)
        )
        st.plotly_chart(fig_type, use_container_width=True, config=CHART_CONFIG, key="nonmacro_type_comparison")
    
    with chart_col2:
        st.markdown("##### Delta by Site Type (V1 - V2)")
        
        # Sort by delta for waterfall effect
        sorted_data = summary_by_type.sort_values('IMPACT_MINS_DELTA', ascending=False)
        
        colors = ['#22c55e' if x >= 0 else '#ef4444' for x in sorted_data['IMPACT_MINS_DELTA']]
        
        fig_delta = go.Figure()
        
        # Add bars with delta value outside
        fig_delta.add_trace(go.Bar(
            x=sorted_data['SITE_TYPE'],
            y=sorted_data['IMPACT_MINS_DELTA'],
            marker_color=colors,
            text=sorted_data['IMPACT_MINS_DELTA'].apply(lambda x: f'{x:+,.0f}'),
            textposition='outside',
            hovertemplate='<b>%{x}</b><br>Delta: %{y:,.0f} mins<br>Sites: %{customdata:,}<extra></extra>',
            customdata=sorted_data['TOTAL_SITES']
        ))
        
        # Add site count annotations inside bars
        for i, row in sorted_data.reset_index(drop=True).iterrows():
            y_pos = row['IMPACT_MINS_DELTA'] / 2  # Middle of bar
            fig_delta.add_annotation(
                x=row['SITE_TYPE'],
                y=y_pos,
                text=f"{row['TOTAL_SITES']:,} sites",
                showarrow=False,
                font=dict(size=11, color='white'),
                bgcolor='rgba(0,0,0,0.5)',
                borderpad=3
            )
        
        fig_delta.add_hline(y=0, line_dash="dash", line_color="white", line_width=1)
        
        fig_delta.update_layout(
            template='plotly_white',
            height=400,
            font=dict(size=14),
            xaxis=dict(title='Site Type', tickfont=dict(size=12)),
            yaxis=dict(title='Delta (V1 - V2) Minutes', tickfont=dict(size=12)),
            margin=dict(t=60, b=50),
            showlegend=False
        )
        st.plotly_chart(fig_delta, use_container_width=True, config=CHART_CONFIG, key="nonmacro_delta_by_type")
    
    st.divider()
    
    # ===== ROW 2: V1 vs V2 by Market (Side by Side) =====
    st.markdown("### 🗺️ Impact Minutes by Market: V1 vs V2")
    
    # OPTIMIZED: Use pandas aggregation for coverage and market data
    coverage_v1 = aggregate_coverage_by_version(master_data, version='v1')
    coverage_v2 = aggregate_coverage_by_version(master_data, version='v2')
    
    market_data = aggregate_nonmacro_by_market(master_data)
    
    if not market_data.empty:
        # Sort by total impact (V1 + V2) to show most impacted markets
        market_data['TOTAL_IMPACT'] = market_data['V1_TOTAL_IMPACT_MINS'] + market_data['V2_TOTAL_IMPACT_MINS']
        
        # Calculate total across ALL markets (for percentage calculation)
        total_v1_all_markets = market_data['V1_TOTAL_IMPACT_MINS'].sum()
        total_v2_all_markets = market_data['V2_TOTAL_IMPACT_MINS'].sum()
        
        top_markets = market_data.nlargest(15, 'TOTAL_IMPACT')
        
        # Calculate what % of total the top 15 contribute
        top15_v1_pct = (top_markets['V1_TOTAL_IMPACT_MINS'].sum() / total_v1_all_markets * 100) if total_v1_all_markets > 0 else 0
        top15_v2_pct = (top_markets['V2_TOTAL_IMPACT_MINS'].sum() / total_v2_all_markets * 100) if total_v2_all_markets > 0 else 0
        
        mkt_col1, mkt_col2 = st.columns(2)
        
        with mkt_col1:
            st.markdown(f"##### V1 Impact Minutes by Market (Top 15 = {top15_v1_pct:.1f}% of total)")
            
            # Coverage badges for V1
            st.markdown(build_coverage_badges_html(coverage_v1), unsafe_allow_html=True)
            
            # Sort by V1 for this chart
            v1_sorted = top_markets.sort_values('V1_TOTAL_IMPACT_MINS', ascending=True)
            
            # Calculate percentage of TOTAL (all markets, not just top 15)
            v1_sorted['V1_PCT'] = (v1_sorted['V1_TOTAL_IMPACT_MINS'] / total_v1_all_markets * 100) if total_v1_all_markets > 0 else 0
            
            fig_v1_market = go.Figure()
            fig_v1_market.add_trace(go.Bar(
                y=v1_sorted['MARKET_ID'],
                x=v1_sorted['V1_TOTAL_IMPACT_MINS'],
                orientation='h',
                marker_color='#3b82f6',
                text=v1_sorted.apply(lambda row: f"{row['V1_PCT']:.1f}% ({row['TOTAL_SITES']:,} sites)", axis=1),
                textposition='inside',
                textfont=dict(color='white', size=11),
                insidetextanchor='end',
                hovertemplate='<b>%{y}</b><br>V1 Impact: %{x:,.0f} mins<br>Pct of Total: %{customdata[1]:.1f}%<br>Sites: %{customdata[0]:,}<extra></extra>',
                customdata=v1_sorted[['TOTAL_SITES', 'V1_PCT']].values
            ))
            
            fig_v1_market.update_layout(
                template='plotly_white',
                height=500,
                font=dict(size=14),
                xaxis=dict(title='V1 Impact Minutes', tickfont=dict(size=11)),
                yaxis=dict(tickfont=dict(size=10)),
                margin=dict(l=120, r=100, t=20, b=50)
            )
            st.plotly_chart(fig_v1_market, use_container_width=True, config=CHART_CONFIG, key="nonmacro_v1_by_market")
        
        with mkt_col2:
            st.markdown(f"##### V2 Impact Minutes by Market (Top 15 = {top15_v2_pct:.1f}% of total)")
            
            # Coverage badges for V2
            st.markdown(build_coverage_badges_html(coverage_v2), unsafe_allow_html=True)
            
            # Sort by V2 for this chart
            v2_sorted = top_markets.sort_values('V2_TOTAL_IMPACT_MINS', ascending=True)
            
            # Calculate percentage of TOTAL (all markets, not just top 15)
            v2_sorted['V2_PCT'] = (v2_sorted['V2_TOTAL_IMPACT_MINS'] / total_v2_all_markets * 100) if total_v2_all_markets > 0 else 0
            
            fig_v2_market = go.Figure()
            fig_v2_market.add_trace(go.Bar(
                y=v2_sorted['MARKET_ID'],
                x=v2_sorted['V2_TOTAL_IMPACT_MINS'],
                orientation='h',
                marker_color='#22c55e',
                text=v2_sorted.apply(lambda row: f"{row['V2_PCT']:.1f}% ({row['TOTAL_SITES']:,} sites)", axis=1),
                textposition='inside',
                textfont=dict(color='white', size=11),
                insidetextanchor='end',
                hovertemplate='<b>%{y}</b><br>V2 Impact: %{x:,.0f} mins<br>Pct of Total: %{customdata[1]:.1f}%<br>Sites: %{customdata[0]:,}<extra></extra>',
                customdata=v2_sorted[['TOTAL_SITES', 'V2_PCT']].values
            ))
            
            fig_v2_market.update_layout(
                template='plotly_white',
                height=500,
                font=dict(size=14),
                xaxis=dict(title='V2 Impact Minutes', tickfont=dict(size=11)),
                yaxis=dict(tickfont=dict(size=10)),
                margin=dict(l=120, r=100, t=20, b=50)
            )
            st.plotly_chart(fig_v2_market, use_container_width=True, config=CHART_CONFIG, key="nonmacro_v2_by_market")
    
    st.divider()
    
    # ===== ROW 3: COTTR Outage Analysis by Focus Category =====
    st.markdown("### ⚡ COTTR Outage Analysis by Focus Category")
    st.markdown("<span style='color:#888;font-size:0.85rem;'>COTTR outage minutes correlated with V1/V2 impact data for non-macro sites</span>", unsafe_allow_html=True)
    
    # Data already fetched at start of function (focus_cat_data, cottr_focus_data)
    
    if not cottr_focus_data.empty:
        cottr_col1, cottr_col2 = st.columns(2)
        
        with cottr_col1:
            st.markdown("##### COTTR Outage Minutes by Focus Category")
            
            cottr_sorted = cottr_focus_data.sort_values('COTTR_OUTAGE_MINS', ascending=True).tail(10)
            total_cottr = cottr_focus_data['COTTR_OUTAGE_MINS'].sum()
            cottr_sorted['PCT'] = (cottr_sorted['COTTR_OUTAGE_MINS'] / total_cottr * 100) if total_cottr > 0 else 0
            
            fig_cottr = go.Figure()
            fig_cottr.add_trace(go.Bar(
                y=cottr_sorted['FOCUS_CATEGORY'],
                x=cottr_sorted['COTTR_OUTAGE_MINS'],
                orientation='h',
                marker_color='#f97316',
                text=cottr_sorted.apply(lambda r: f"{r['COTTR_OUTAGE_MINS']:,.0f} ({r['PCT']:.1f}%)", axis=1),
                textposition='inside',
                textfont=dict(color='white', size=11),
                hovertemplate='<b>%{y}</b><br>COTTR Outage: %{x:,.0f} mins<br>Pct of Total: %{customdata[2]:.1f}%<br>Sites: %{customdata[0]:,}<br>Outage Days: %{customdata[1]:,}<extra></extra>',
                customdata=cottr_sorted[['SITE_COUNT', 'OUTAGE_DAYS', 'PCT']].values
            ))
            
            fig_cottr.update_layout(
                template='plotly_white',
                height=400,
                font=dict(size=14),
                xaxis=dict(title='COTTR Outage Minutes', tickfont=dict(size=12)),
                yaxis=dict(tickfont=dict(size=11)),
                margin=dict(l=150, r=50, t=30, b=50)
            )
            st.plotly_chart(fig_cottr, use_container_width=True, config=CHART_CONFIG, key="nonmacro_cottr_focus")
        
        with cottr_col2:
            st.markdown("##### Service Outage vs Degradation by Category")
            
            cottr_breakdown = cottr_focus_data.sort_values('COTTR_OUTAGE_MINS', ascending=True).tail(10)
            total_outage = cottr_focus_data['SERVICE_OUTAGE_MINS'].sum()
            total_degrad = cottr_focus_data['SERVICE_DEGRADATION_MINS'].sum()
            cottr_breakdown['OUTAGE_PCT'] = (cottr_breakdown['SERVICE_OUTAGE_MINS'] / total_outage * 100) if total_outage > 0 else 0
            cottr_breakdown['DEGRAD_PCT'] = (cottr_breakdown['SERVICE_DEGRADATION_MINS'] / total_degrad * 100) if total_degrad > 0 else 0
            
            fig_cottr_type = go.Figure()
            
            # Service Outage bars
            fig_cottr_type.add_trace(go.Bar(
                y=cottr_breakdown['FOCUS_CATEGORY'],
                x=cottr_breakdown['SERVICE_OUTAGE_MINS'],
                name='Service Outage',
                orientation='h',
                marker_color='#ef4444',
                text=cottr_breakdown.apply(lambda r: f"{r['OUTAGE_PCT']:.1f}%", axis=1),
                textposition='inside',
                textfont=dict(color='white', size=10),
                hovertemplate='<b>%{y}</b><br>Service Outage: %{x:,.0f} mins (%{customdata:.1f}%)<extra></extra>',
                customdata=cottr_breakdown['OUTAGE_PCT']
            ))
            
            # Service Degradation bars
            fig_cottr_type.add_trace(go.Bar(
                y=cottr_breakdown['FOCUS_CATEGORY'],
                x=cottr_breakdown['SERVICE_DEGRADATION_MINS'],
                name='Service Degradation',
                orientation='h',
                marker_color='#fbbf24',
                hovertemplate='<b>%{y}</b><br>Service Degradation: %{x:,.0f} mins (%{customdata:.1f}%)<extra></extra>',
                customdata=cottr_breakdown['DEGRAD_PCT']
            ))
            
            fig_cottr_type.update_layout(
                template='plotly_white',
                height=400,
                barmode='stack',
                font=dict(size=14),
                xaxis=dict(title='Minutes', tickfont=dict(size=12)),
                yaxis=dict(tickfont=dict(size=11)),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                margin=dict(l=150, r=50, t=30, b=50)
            )
            st.plotly_chart(fig_cottr_type, use_container_width=True, config=CHART_CONFIG, key="nonmacro_cottr_type")
        
        # COTTR vs V1/V2 Correlation chart
        if not focus_cat_data.empty:
            st.markdown("##### V1/V2 Impact vs COTTR Outage Correlation")
            
            # Merge COTTR with V1/V2 data
            merged_data = focus_cat_data.merge(
                cottr_focus_data[['FOCUS_CATEGORY', 'COTTR_OUTAGE_MINS', 'SITE_COUNT']], 
                on='FOCUS_CATEGORY', 
                how='inner',
                suffixes=('', '_COTTR')
            )
            
            if not merged_data.empty:
                corr_col1, corr_col2 = st.columns(2)
                
                with corr_col1:
                    st.markdown("###### V1 Impact vs COTTR Outage")
                    
                    fig_corr_v1 = go.Figure()
                    fig_corr_v1.add_trace(go.Scatter(
                        x=merged_data['COTTR_OUTAGE_MINS'],
                        y=merged_data['V1_IMPACT_MINS'],
                        mode='markers+text',
                        marker=dict(size=15, color='#3b82f6', opacity=0.7),
                        text=merged_data['FOCUS_CATEGORY'].apply(lambda x: x[:15] + '...' if len(str(x)) > 15 else x),
                        textposition='top center',
                        textfont=dict(size=9),
                        hovertemplate='<b>%{text}</b><br>COTTR: %{x:,.0f} mins<br>V1 Impact: %{y:,.0f} mins<extra></extra>'
                    ))
                    
                    fig_corr_v1.update_layout(
                        template='plotly_white',
                        height=350,
                        font=dict(size=12),
                        xaxis=dict(title='COTTR Outage Minutes', tickfont=dict(size=11)),
                        yaxis=dict(title='V1 Impact Minutes', tickfont=dict(size=11)),
                        margin=dict(l=70, r=30, t=30, b=50)
                    )
                    st.plotly_chart(fig_corr_v1, use_container_width=True, config=CHART_CONFIG, key="nonmacro_corr_v1")
                
                with corr_col2:
                    st.markdown("###### V2 Impact vs COTTR Outage")
                    
                    fig_corr_v2 = go.Figure()
                    fig_corr_v2.add_trace(go.Scatter(
                        x=merged_data['COTTR_OUTAGE_MINS'],
                        y=merged_data['V2_IMPACT_MINS'],
                        mode='markers+text',
                        marker=dict(size=15, color='#22c55e', opacity=0.7),
                        text=merged_data['FOCUS_CATEGORY'].apply(lambda x: x[:15] + '...' if len(str(x)) > 15 else x),
                        textposition='top center',
                        textfont=dict(size=9),
                        hovertemplate='<b>%{text}</b><br>COTTR: %{x:,.0f} mins<br>V2 Impact: %{y:,.0f} mins<extra></extra>'
                    ))
                    
                    fig_corr_v2.update_layout(
                        template='plotly_white',
                        height=350,
                        font=dict(size=12),
                        xaxis=dict(title='COTTR Outage Minutes', tickfont=dict(size=11)),
                        yaxis=dict(title='V2 Impact Minutes', tickfont=dict(size=11)),
                        margin=dict(l=70, r=30, t=30, b=50)
                    )
                    st.plotly_chart(fig_corr_v2, use_container_width=True, config=CHART_CONFIG, key="nonmacro_corr_v2")
    else:
        st.info("No COTTR data available for non-macro sites.")
    
    st.divider()
    
    # ===== ROW 3C: Availability Correlation by Focus Category =====
    st.markdown("### 📉 Availability Analysis by Focus Category")
    st.markdown("<span style='color:#888;font-size:0.85rem;'>Availability downtime correlated with V1/V2 impact data for non-macro sites</span>", unsafe_allow_html=True)
    
    # Data already fetched at start of function (avail_focus_data)
    
    if not avail_focus_data.empty:
        avail_col1, avail_col2 = st.columns(2)
        
        with avail_col1:
            st.markdown("##### Total Downtime by Focus Category")
            
            avail_sorted = avail_focus_data.sort_values('TOTAL_DOWNTIME_MINS', ascending=True).tail(10)
            total_downtime = avail_focus_data['TOTAL_DOWNTIME_MINS'].sum()
            avail_sorted['DOWNTIME_PCT'] = (avail_sorted['TOTAL_DOWNTIME_MINS'] / total_downtime * 100) if total_downtime > 0 else 0
            
            fig_avail = go.Figure()
            fig_avail.add_trace(go.Bar(
                y=avail_sorted['FOCUS_CATEGORY'],
                x=avail_sorted['TOTAL_DOWNTIME_MINS'],
                orientation='h',
                marker_color='#ef4444',
                text=avail_sorted.apply(lambda r: f"{r['TOTAL_DOWNTIME_MINS']:,.0f} ({r['DOWNTIME_PCT']:.1f}%)", axis=1),
                textposition='inside',
                textfont=dict(color='white', size=11),
                hovertemplate='<b>%{y}</b><br>Downtime: %{x:,.0f} mins<br>Pct of Total: %{customdata[2]:.1f}%<br>Sites: %{customdata[0]:,}<br>Days with Downtime: %{customdata[1]:,}<extra></extra>',
                customdata=avail_sorted[['SITE_COUNT', 'DAYS_WITH_DOWNTIME', 'DOWNTIME_PCT']].values
            ))
            
            fig_avail.update_layout(
                template='plotly_white',
                height=400,
                font=dict(size=14),
                xaxis=dict(title='Downtime (Minutes)', tickfont=dict(size=12)),
                yaxis=dict(tickfont=dict(size=11)),
                margin=dict(l=150, r=50, t=30, b=50)
            )
            st.plotly_chart(fig_avail, use_container_width=True, config=CHART_CONFIG, key="nonmacro_avail_focus")
        
        with avail_col2:
            st.markdown("##### Unavailability % by Focus Category")
            
            unavail_sorted = avail_focus_data.sort_values('UNAVAILABILITY_PCT', ascending=True).tail(10)
            
            fig_unavail = go.Figure()
            fig_unavail.add_trace(go.Bar(
                y=unavail_sorted['FOCUS_CATEGORY'],
                x=unavail_sorted['UNAVAILABILITY_PCT'],
                orientation='h',
                marker_color='#dc2626',
                text=unavail_sorted['UNAVAILABILITY_PCT'].apply(lambda x: f'{x:.4f}%'),
                textposition='inside',
                textfont=dict(color='white', size=11),
                hovertemplate='<b>%{y}</b><br>Unavailability: %{x:.4f}%<br>Sites: %{customdata[0]:,}<extra></extra>',
                customdata=unavail_sorted[['SITE_COUNT']].values
            ))
            
            fig_unavail.update_layout(
                template='plotly_white',
                height=400,
                font=dict(size=14),
                xaxis=dict(title='Unavailability %', tickfont=dict(size=12)),
                yaxis=dict(tickfont=dict(size=11)),
                margin=dict(l=150, r=50, t=30, b=50)
            )
            st.plotly_chart(fig_unavail, use_container_width=True, config=CHART_CONFIG, key="nonmacro_unavail_focus")
        
        # Availability vs V1/V2 Correlation charts
        if not focus_cat_data.empty:
            st.markdown("##### V1/V2 Impact vs Availability Downtime Correlation")
            
            # Merge Availability with V1/V2 data
            avail_merged = focus_cat_data.merge(
                avail_focus_data[['FOCUS_CATEGORY', 'TOTAL_DOWNTIME_MINS', 'UNAVAILABILITY_PCT', 'SITE_COUNT']], 
                on='FOCUS_CATEGORY', 
                how='inner',
                suffixes=('', '_AVAIL')
            )
            
            if not avail_merged.empty:
                avail_corr_col1, avail_corr_col2 = st.columns(2)
                
                with avail_corr_col1:
                    st.markdown("###### V1 Impact vs Availability Downtime")
                    
                    fig_avail_v1 = go.Figure()
                    fig_avail_v1.add_trace(go.Scatter(
                        x=avail_merged['TOTAL_DOWNTIME_MINS'],
                        y=avail_merged['V1_IMPACT_MINS'],
                        mode='markers+text',
                        marker=dict(size=15, color='#3b82f6', opacity=0.7),
                        text=avail_merged['FOCUS_CATEGORY'].apply(lambda x: x[:15] + '...' if len(str(x)) > 15 else x),
                        textposition='top center',
                        textfont=dict(size=9),
                        hovertemplate='<b>%{text}</b><br>Downtime: %{x:,.0f} mins<br>V1 Impact: %{y:,.0f} mins<extra></extra>'
                    ))
                    
                    fig_avail_v1.update_layout(
                        template='plotly_white',
                        height=350,
                        font=dict(size=12),
                        xaxis=dict(title='Availability Downtime (Minutes)', tickfont=dict(size=11)),
                        yaxis=dict(title='V1 Impact Minutes', tickfont=dict(size=11)),
                        margin=dict(l=70, r=30, t=30, b=50)
                    )
                    st.plotly_chart(fig_avail_v1, use_container_width=True, config=CHART_CONFIG, key="nonmacro_avail_corr_v1")
                
                with avail_corr_col2:
                    st.markdown("###### V2 Impact vs Availability Downtime")
                    
                    fig_avail_v2 = go.Figure()
                    fig_avail_v2.add_trace(go.Scatter(
                        x=avail_merged['TOTAL_DOWNTIME_MINS'],
                        y=avail_merged['V2_IMPACT_MINS'],
                        mode='markers+text',
                        marker=dict(size=15, color='#22c55e', opacity=0.7),
                        text=avail_merged['FOCUS_CATEGORY'].apply(lambda x: x[:15] + '...' if len(str(x)) > 15 else x),
                        textposition='top center',
                        textfont=dict(size=9),
                        hovertemplate='<b>%{text}</b><br>Downtime: %{x:,.0f} mins<br>V2 Impact: %{y:,.0f} mins<extra></extra>'
                    ))
                    
                    fig_avail_v2.update_layout(
                        template='plotly_white',
                        height=350,
                        font=dict(size=12),
                        xaxis=dict(title='Availability Downtime (Minutes)', tickfont=dict(size=11)),
                        yaxis=dict(title='V2 Impact Minutes', tickfont=dict(size=11)),
                        margin=dict(l=70, r=30, t=30, b=50)
                    )
                    st.plotly_chart(fig_avail_v2, use_container_width=True, config=CHART_CONFIG, key="nonmacro_avail_corr_v2")
        
        # Combined comparison: COTTR vs Availability vs V1/V2
        if not cottr_focus_data.empty and not focus_cat_data.empty:
            st.markdown("##### All Metrics Comparison by Focus Category")
            
            # Merge all three datasets
            all_metrics = focus_cat_data.merge(
                avail_focus_data[['FOCUS_CATEGORY', 'TOTAL_DOWNTIME_MINS', 'UNAVAILABILITY_PCT']], 
                on='FOCUS_CATEGORY', 
                how='outer'
            ).merge(
                cottr_focus_data[['FOCUS_CATEGORY', 'COTTR_OUTAGE_MINS']], 
                on='FOCUS_CATEGORY', 
                how='outer'
            ).fillna(0)
            
            # Sort by total V1+V2 impact
            all_metrics['TOTAL_V1V2'] = all_metrics['V1_IMPACT_MINS'] + all_metrics['V2_IMPACT_MINS']
            all_metrics = all_metrics.sort_values('TOTAL_V1V2', ascending=False).head(10)
            
            # Calculate percentages for each metric
            total_v1 = all_metrics['V1_IMPACT_MINS'].sum()
            total_v2 = all_metrics['V2_IMPACT_MINS'].sum()
            total_cottr = all_metrics['COTTR_OUTAGE_MINS'].sum()
            total_avail = all_metrics['TOTAL_DOWNTIME_MINS'].sum()
            
            all_metrics['V1_PCT'] = (all_metrics['V1_IMPACT_MINS'] / total_v1 * 100) if total_v1 > 0 else 0
            all_metrics['V2_PCT'] = (all_metrics['V2_IMPACT_MINS'] / total_v2 * 100) if total_v2 > 0 else 0
            all_metrics['COTTR_PCT'] = (all_metrics['COTTR_OUTAGE_MINS'] / total_cottr * 100) if total_cottr > 0 else 0
            all_metrics['AVAIL_PCT'] = (all_metrics['TOTAL_DOWNTIME_MINS'] / total_avail * 100) if total_avail > 0 else 0
            
            fig_all = go.Figure()
            
            fig_all.add_trace(go.Bar(
                name='V1 Impact',
                x=all_metrics['FOCUS_CATEGORY'],
                y=all_metrics['V1_IMPACT_MINS'],
                marker_color='#3b82f6',
                text=all_metrics['V1_PCT'].apply(lambda x: f'{x:.1f}%'),
                textposition='outside',
                textfont=dict(size=9),
                hovertemplate='<b>%{x}</b><br>V1 Impact: %{y:,.0f} mins (%{customdata:.1f}%)<extra></extra>',
                customdata=all_metrics['V1_PCT']
            ))
            
            fig_all.add_trace(go.Bar(
                name='V2 Impact',
                x=all_metrics['FOCUS_CATEGORY'],
                y=all_metrics['V2_IMPACT_MINS'],
                marker_color='#22c55e',
                text=all_metrics['V2_PCT'].apply(lambda x: f'{x:.1f}%'),
                textposition='outside',
                textfont=dict(size=9),
                hovertemplate='<b>%{x}</b><br>V2 Impact: %{y:,.0f} mins (%{customdata:.1f}%)<extra></extra>',
                customdata=all_metrics['V2_PCT']
            ))
            
            fig_all.add_trace(go.Bar(
                name='COTTR Outage',
                x=all_metrics['FOCUS_CATEGORY'],
                y=all_metrics['COTTR_OUTAGE_MINS'],
                marker_color='#f97316',
                text=all_metrics['COTTR_PCT'].apply(lambda x: f'{x:.1f}%'),
                textposition='outside',
                textfont=dict(size=9),
                hovertemplate='<b>%{x}</b><br>COTTR Outage: %{y:,.0f} mins (%{customdata:.1f}%)<extra></extra>',
                customdata=all_metrics['COTTR_PCT']
            ))
            
            fig_all.add_trace(go.Bar(
                name='Avail Downtime',
                x=all_metrics['FOCUS_CATEGORY'],
                y=all_metrics['TOTAL_DOWNTIME_MINS'],
                marker_color='#ef4444',
                text=all_metrics['AVAIL_PCT'].apply(lambda x: f'{x:.1f}%'),
                textposition='outside',
                textfont=dict(size=9),
                hovertemplate='<b>%{x}</b><br>Avail Downtime: %{y:,.0f} mins (%{customdata:.1f}%)<extra></extra>',
                customdata=all_metrics['AVAIL_PCT']
            ))
            
            fig_all.update_layout(
                template='plotly_white',
                height=500,
                barmode='group',
                font=dict(size=14),
                xaxis=dict(title='Focus Category', tickfont=dict(size=10), tickangle=-45),
                yaxis=dict(title='Minutes', tickfont=dict(size=12)),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                margin=dict(l=70, r=30, t=50, b=120)
            )
            st.plotly_chart(fig_all, use_container_width=True, config=CHART_CONFIG, key="nonmacro_all_metrics")
    else:
        st.info("No availability data available for non-macro sites.")
    
    st.divider()
    
    # ===== ROW 4: Daily Trend =====
    st.markdown("### 📈 Daily Trend Comparison")
    
    # OPTIMIZED: Use pandas aggregation instead of separate query
    daily_data = aggregate_nonmacro_daily(master_data)
    
    if not daily_data.empty:
        daily_data['DATE'] = pd.to_datetime(daily_data['DATE_VALUE']).dt.date
        daily_data = daily_data.sort_values('DATE')
        
        trend_col1, trend_col2 = st.columns(2)
        
        with trend_col1:
            st.markdown("##### Daily Impact Minutes: V1 vs V2")
            
            fig_trend = go.Figure()
            
            fig_trend.add_trace(go.Scatter(
                x=daily_data['DATE'],
                y=daily_data['V1_IMPACT_MINS'],
                mode='lines+markers',
                name='V1 (Original)',
                line=dict(color='#3b82f6', width=2),
                marker=dict(size=6)
            ))
            
            fig_trend.add_trace(go.Scatter(
                x=daily_data['DATE'],
                y=daily_data['V2_IMPACT_MINS'],
                mode='lines+markers',
                name='V2 (Current)',
                line=dict(color='#22c55e', width=2),
                marker=dict(size=6)
            ))
            
            fig_trend.update_layout(
                template='plotly_white',
                height=350,
                font=dict(size=14),
                xaxis=dict(tickformat='%b %d', tickfont=dict(size=12)),
                yaxis=dict(title='Impact Minutes', tickfont=dict(size=12)),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5, font=dict(size=12)),
                margin=dict(t=50, b=50)
            )
            st.plotly_chart(fig_trend, use_container_width=True, config=CHART_CONFIG, key="nonmacro_daily_trend")
        
        with trend_col2:
            # Calculate total delta sum
            total_delta = daily_data['IMPACT_MINS_DELTA'].sum()
            delta_color = '#22c55e' if total_delta >= 0 else '#ef4444'
            st.markdown(f"##### Daily Delta (V1 - V2) <span style='color:{delta_color};font-weight:bold;'>Sum: {total_delta:+,.0f}</span>", unsafe_allow_html=True)
            
            colors = ['#22c55e' if x >= 0 else '#ef4444' for x in daily_data['IMPACT_MINS_DELTA']]
            
            fig_delta_trend = go.Figure()
            fig_delta_trend.add_trace(go.Bar(
                x=daily_data['DATE'],
                y=daily_data['IMPACT_MINS_DELTA'],
                marker_color=colors,
                name='Delta'
            ))
            
            fig_delta_trend.add_hline(y=0, line_dash="dash", line_color="white", line_width=1)
            
            fig_delta_trend.update_layout(
                template='plotly_white',
                height=350,
                font=dict(size=14),
                xaxis=dict(tickformat='%b %d', tickfont=dict(size=12)),
                yaxis=dict(title='Delta (Minutes)', tickfont=dict(size=12)),
                margin=dict(t=50, b=50),
                showlegend=False
            )
            st.plotly_chart(fig_delta_trend, use_container_width=True, config=CHART_CONFIG, key="nonmacro_daily_delta")
    
    st.divider()
    
    # ===== NEW SECTION: Why Are Impact Minutes High? Deep Dive =====
    st.markdown("### 🔍 Why Are Impact Minutes High? - Deep Dive Analysis")
    st.markdown("<span style='color:#888;font-size:0.85rem;'>These charts help identify the root causes of high impact minutes</span>", unsafe_allow_html=True)
    
    # OPTIMIZED: Compute site-level aggregation once for all deep dive charts
    master_data['V1_HAS_IMPACT'] = (master_data['V1_IMPACT_MINS'] > 0).astype(int)
    master_data['V2_HAS_IMPACT'] = (master_data['V2_IMPACT_MINS'] > 0).astype(int)
    
    site_totals = master_data.groupby(['SITE_ID', 'SITE_TYPE', 'MARKET_ID']).agg({
        'V1_IMPACT_MINS': 'sum',
        'V2_IMPACT_MINS': 'sum',
        'V1_TOTAL_SUBS': 'sum',
        'V2_TOTAL_SUBS': 'sum',
        'DATE_VALUE': 'max',
        'REGION_ID': 'first',
        'V1_HAS_IMPACT': 'sum',
        'V2_HAS_IMPACT': 'sum'
    }).reset_index()
    site_totals.rename(columns={
        'DATE_VALUE': 'LAST_OUTAGE_DATE',
        'V1_HAS_IMPACT': 'V1_DAYS_IMPACTED',
        'V2_HAS_IMPACT': 'V2_DAYS_IMPACTED'
    }, inplace=True)
    
    site_totals['LAST_OUTAGE_STR'] = site_totals['LAST_OUTAGE_DATE'].apply(
        lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else 'N/A'
    )
    site_totals['REGION_ID'] = site_totals['REGION_ID'].fillna('Unknown')
    
    # Pre-compute totals for percentage calculations
    total_v1_mins = site_totals['V1_IMPACT_MINS'].sum()
    total_v2_mins = site_totals['V2_IMPACT_MINS'].sum()
    
    # Pre-compute boolean masks for repeated filtering (optimization)
    v1_has_impact = site_totals['V1_IMPACT_MINS'] > 0
    v2_has_impact = site_totals['V2_IMPACT_MINS'] > 0
    v1_has_subs = site_totals['V1_TOTAL_SUBS'] > 0
    v2_has_subs = site_totals['V2_TOTAL_SUBS'] > 0
    v1_has_days = site_totals['V1_DAYS_IMPACTED'] > 0
    v2_has_days = site_totals['V2_DAYS_IMPACTED'] > 0
    
    # ----- Chart 1 & 2: Top Sites by Impact Minutes -----
    deepdive_col1, deepdive_col2 = st.columns(2)
    
    with deepdive_col1:
        top_v1_sites = site_totals.nlargest(200, 'V1_IMPACT_MINS')
        
        # Calculate what % of total the top 200 contribute
        top200_v1_pct = (top_v1_sites['V1_IMPACT_MINS'].sum() / total_v1_mins * 100) if total_v1_mins > 0 else 0
        
        st.markdown(f"##### Top 200 Sites by V1 Impact Minutes ({top200_v1_pct:.1f}% of total)")
        
        # Calculate percentage for each site
        top_v1_sites = top_v1_sites.copy()
        top_v1_sites['V1_PCT'] = (top_v1_sites['V1_IMPACT_MINS'] / total_v1_mins * 100) if total_v1_mins > 0 else 0
        
        fig_top_v1 = go.Figure()
        fig_top_v1.add_trace(go.Bar(
            y=top_v1_sites['SITE_ID'].astype(str),
            x=top_v1_sites['V1_IMPACT_MINS'],
            orientation='h',
            marker_color='#3b82f6',
            text=top_v1_sites.apply(lambda r: f"{r['V1_PCT']:.1f}%", axis=1),
            textposition='inside',
            textfont=dict(color='white', size=14),
            insidetextanchor='end',
            hovertemplate='<b>%{y}</b><br>V1 Impact: %{x:,.0f} mins<br>Pct of Total: %{customdata[2]:.1f}%<br>Type: %{customdata[0]}<br>Market: %{customdata[1]}<br>Last Outage: %{customdata[3]}<extra></extra>',
            customdata=top_v1_sites[['SITE_TYPE', 'MARKET_ID', 'V1_PCT', 'LAST_OUTAGE_STR']].values
        ))
        
        # Height based on number of bars (35px per bar) for all 200 sites
        chart_height = len(top_v1_sites) * 35 + 80
        
        fig_top_v1.update_layout(
            template='plotly_white',
            height=chart_height,
            font=dict(size=14),
            xaxis=dict(title='V1 Impact Minutes', tickfont=dict(size=12)),
            yaxis=dict(tickfont=dict(size=11), autorange='reversed'),
            margin=dict(l=110, r=80, t=20, b=50)
        )
        
        # Wrap in scrollable container (show ~10 bars initially = 400px, scroll for rest)
        with st.container(height=450, border=False):
            st.plotly_chart(fig_top_v1, use_container_width=True, config=CHART_CONFIG, key="deepdive_top_v1_sites")
    
    with deepdive_col2:
        top_v2_sites = site_totals.nlargest(200, 'V2_IMPACT_MINS')
        
        # Calculate what % of total the top 200 contribute
        top200_v2_pct = (top_v2_sites['V2_IMPACT_MINS'].sum() / total_v2_mins * 100) if total_v2_mins > 0 else 0
        
        st.markdown(f"##### Top 200 Sites by V2 Impact Minutes ({top200_v2_pct:.1f}% of total)")
        
        # Calculate percentage for each site
        top_v2_sites = top_v2_sites.copy()
        top_v2_sites['V2_PCT'] = (top_v2_sites['V2_IMPACT_MINS'] / total_v2_mins * 100) if total_v2_mins > 0 else 0
        
        fig_top_v2 = go.Figure()
        fig_top_v2.add_trace(go.Bar(
            y=top_v2_sites['SITE_ID'].astype(str),
            x=top_v2_sites['V2_IMPACT_MINS'],
            orientation='h',
            marker_color='#22c55e',
            text=top_v2_sites.apply(lambda r: f"{r['V2_PCT']:.1f}%", axis=1),
            textposition='inside',
            textfont=dict(color='white', size=14),
            insidetextanchor='end',
            hovertemplate='<b>%{y}</b><br>V2 Impact: %{x:,.0f} mins<br>Pct of Total: %{customdata[2]:.1f}%<br>Type: %{customdata[0]}<br>Market: %{customdata[1]}<br>Last Outage: %{customdata[3]}<extra></extra>',
            customdata=top_v2_sites[['SITE_TYPE', 'MARKET_ID', 'V2_PCT', 'LAST_OUTAGE_STR']].values
        ))
        
        # Height based on number of bars (35px per bar) for all 200 sites
        chart_height = len(top_v2_sites) * 35 + 80
        
        fig_top_v2.update_layout(
            template='plotly_white',
            height=chart_height,
            font=dict(size=14),
            xaxis=dict(title='V2 Impact Minutes', tickfont=dict(size=12)),
            yaxis=dict(tickfont=dict(size=11), autorange='reversed'),
            margin=dict(l=110, r=80, t=20, b=50)
        )
        
        # Wrap in scrollable container (show ~10 bars initially = 450px, scroll for rest)
        with st.container(height=450, border=False):
            st.plotly_chart(fig_top_v2, use_container_width=True, config=CHART_CONFIG, key="deepdive_top_v2_sites")
    
    # ----- Chart 3 & 4: Impact Distribution & Average per Site -----
    deepdive_col3, deepdive_col4 = st.columns(2)
    
    with deepdive_col3:
        st.markdown("##### Impact Minutes Distribution (per Site)")
        st.markdown("<span style='color:#888;font-size:0.75rem;'>Are impacts concentrated in few sites or spread across many?</span>", unsafe_allow_html=True)
        
        # Create histogram of site-level impacts
        site_totals['TOTAL_IMPACT'] = site_totals['V1_IMPACT_MINS'] + site_totals['V2_IMPACT_MINS']
        
        fig_dist = go.Figure()
        
        # V1 histogram
        fig_dist.add_trace(go.Histogram(
            x=site_totals['V1_IMPACT_MINS'],
            name='V1 Impact',
            marker_color='#3b82f6',
            opacity=0.7,
            nbinsx=30
        ))
        
        # V2 histogram
        fig_dist.add_trace(go.Histogram(
            x=site_totals['V2_IMPACT_MINS'],
            name='V2 Impact',
            marker_color='#22c55e',
            opacity=0.7,
            nbinsx=30
        ))
        
        fig_dist.update_layout(
            template='plotly_white',
            height=400,
            barmode='overlay',
            font=dict(size=12),
            xaxis=dict(title='Impact Minutes per Site', tickfont=dict(size=11)),
            yaxis=dict(title='Number of Sites', tickfont=dict(size=11)),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5, font=dict(size=11)),
            margin=dict(t=50, b=50)
        )
        st.plotly_chart(fig_dist, use_container_width=True, config=CHART_CONFIG, key="deepdive_impact_distribution")
    
    with deepdive_col4:
        st.markdown("##### Average Impact per Site by Type")
        st.markdown("<span style='color:#888;font-size:0.75rem;'>Which site types have highest normalized impact?</span>", unsafe_allow_html=True)
        
        # Calculate average impact per site by type
        avg_by_type = site_totals.groupby('SITE_TYPE').agg({
            'V1_IMPACT_MINS': ['sum', 'count'],
            'V2_IMPACT_MINS': 'sum'
        }).reset_index()
        avg_by_type.columns = ['SITE_TYPE', 'V1_TOTAL', 'SITE_COUNT', 'V2_TOTAL']
        avg_by_type['V1_AVG'] = avg_by_type['V1_TOTAL'] / avg_by_type['SITE_COUNT']
        avg_by_type['V2_AVG'] = avg_by_type['V2_TOTAL'] / avg_by_type['SITE_COUNT']
        avg_by_type = avg_by_type.sort_values('V1_AVG', ascending=True)
        
        fig_avg = go.Figure()
        
        fig_avg.add_trace(go.Bar(
            y=avg_by_type['SITE_TYPE'],
            x=avg_by_type['V1_AVG'],
            orientation='h',
            name='V1 Avg',
            marker_color='#3b82f6',
            text=avg_by_type.apply(lambda r: f"{r['V1_AVG']:,.0f} ({r['SITE_COUNT']:,} sites)", axis=1),
            textposition='outside'
        ))
        
        fig_avg.add_trace(go.Bar(
            y=avg_by_type['SITE_TYPE'],
            x=avg_by_type['V2_AVG'],
            orientation='h',
            name='V2 Avg',
            marker_color='#22c55e',
            text=avg_by_type['V2_AVG'].apply(lambda x: f"{x:,.0f}"),
            textposition='outside'
        ))
        
        fig_avg.update_layout(
            template='plotly_white',
            height=400,
            barmode='group',
            font=dict(size=12),
            xaxis=dict(title='Avg Impact Minutes per Site', tickfont=dict(size=11)),
            yaxis=dict(tickfont=dict(size=11)),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5, font=dict(size=11)),
            margin=dict(l=100, r=120, t=50, b=50)
        )
        st.plotly_chart(fig_avg, use_container_width=True, config=CHART_CONFIG, key="deepdive_avg_by_type")
    
    # ----- Chart 5: Subscriber Impact Correlation -----
    st.markdown("##### Subscriber Count vs Impact Minutes Correlation")
    st.markdown("<span style='color:#888;font-size:0.75rem;'>Sites with higher subscriber counts should have proportionally higher impact - outliers may indicate issues</span>", unsafe_allow_html=True)
    
    corr_col1, corr_col2 = st.columns(2)
    
    # OPTIMIZED: Reuse site_totals computed above (already has REGION_ID and days impacted)
    
    with corr_col1:
        fig_corr_v1 = go.Figure()
        
        # Filter out zero values for better visualization
        corr_data_v1 = site_totals[v1_has_impact & v1_has_subs]
        
        if not corr_data_v1.empty:
            # Add traces by region for proper legend
            for region in ['Central', 'Northeast', 'South', 'West', 'Unknown']:
                region_data = corr_data_v1[corr_data_v1['REGION_ID'] == region]
                if not region_data.empty:
                    color = REGION_COLORS.get(region, DEFAULT_REGION_COLOR)
                    fig_corr_v1.add_trace(go.Scatter(
                        x=region_data['V1_TOTAL_SUBS'],
                        y=region_data['V1_IMPACT_MINS'],
                        mode='markers',
                        name=region,
                        marker=dict(size=8, color=color, opacity=0.7),
                        text=region_data.apply(lambda r: f"Site: {r['SITE_ID']}<br>Type: {r['SITE_TYPE']}<br>Market: {r['MARKET_ID']}<br>Region: {r['REGION_ID']}<br>Days Impacted: {int(r['V1_DAYS_IMPACTED'])}", axis=1),
                        hovertemplate='%{text}<br>Subscribers: %{x:,.0f}<br>Impact Mins: %{y:,.0f}<extra></extra>'
                    ))
            
            fig_corr_v1.update_layout(
                template='plotly_white',
                height=450,
                title=dict(text='V1: Subscribers vs Impact', font=dict(size=14)),
                font=dict(size=12),
                xaxis=dict(title='Total Impacted Subscribers', tickfont=dict(size=11), type='log'),
                yaxis=dict(title='Impact Minutes', tickfont=dict(size=11), type='log'),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5, font=dict(size=11), title_text='Region'),
                margin=dict(t=70, b=50)
            )
        st.plotly_chart(fig_corr_v1, use_container_width=True, config=CHART_CONFIG, key="deepdive_corr_v1")
    
    with corr_col2:
        fig_corr_v2 = go.Figure()
        
        corr_data_v2 = site_totals[v2_has_impact & v2_has_subs]
        
        if not corr_data_v2.empty:
            # Add traces by region for proper legend
            for region in ['Central', 'Northeast', 'South', 'West', 'Unknown']:
                region_data = corr_data_v2[corr_data_v2['REGION_ID'] == region]
                if not region_data.empty:
                    color = REGION_COLORS.get(region, DEFAULT_REGION_COLOR)
                    fig_corr_v2.add_trace(go.Scatter(
                        x=region_data['V2_TOTAL_SUBS'],
                        y=region_data['V2_IMPACT_MINS'],
                        mode='markers',
                        name=region,
                        marker=dict(size=8, color=color, opacity=0.7),
                        text=region_data.apply(lambda r: f"Site: {r['SITE_ID']}<br>Type: {r['SITE_TYPE']}<br>Market: {r['MARKET_ID']}<br>Region: {r['REGION_ID']}<br>Days Impacted: {int(r['V2_DAYS_IMPACTED'])}", axis=1),
                        hovertemplate='%{text}<br>Subscribers: %{x:,.0f}<br>Impact Mins: %{y:,.0f}<extra></extra>'
                    ))
            
            fig_corr_v2.update_layout(
                template='plotly_white',
                height=450,
                title=dict(text='V2: Subscribers vs Impact', font=dict(size=14)),
                font=dict(size=12),
                xaxis=dict(title='Total Impacted Subscribers', tickfont=dict(size=11), type='log'),
                yaxis=dict(title='Impact Minutes', tickfont=dict(size=11), type='log'),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5, font=dict(size=11), title_text='Region'),
                margin=dict(t=70, b=50)
            )
        st.plotly_chart(fig_corr_v2, use_container_width=True, config=CHART_CONFIG, key="deepdive_corr_v2")
    
    # ----- Chart 5b: Days Impacted vs Impact Minutes -----
    st.markdown("##### Days Impacted vs Impact Minutes")
    st.markdown("<span style='color:#888;font-size:0.75rem;'>Sites with more days impacted tend to have higher total impact - outliers may indicate severe single-day events</span>", unsafe_allow_html=True)
    
    days_col1, days_col2 = st.columns(2)
    
    with days_col1:
        fig_days_v1 = go.Figure()
        
        # Filter out zero values
        days_data_v1 = site_totals[v1_has_impact & v1_has_days]
        
        if not days_data_v1.empty:
            for region in ['Central', 'Northeast', 'South', 'West', 'Unknown']:
                region_data = days_data_v1[days_data_v1['REGION_ID'] == region]
                if not region_data.empty:
                    color = REGION_COLORS.get(region, DEFAULT_REGION_COLOR)
                    fig_days_v1.add_trace(go.Scatter(
                        x=region_data['V1_DAYS_IMPACTED'],
                        y=region_data['V1_IMPACT_MINS'],
                        mode='markers',
                        name=region,
                        marker=dict(size=8, color=color, opacity=0.7),
                        text=region_data.apply(lambda r: f"Site: {r['SITE_ID']}<br>Type: {r['SITE_TYPE']}<br>Market: {r['MARKET_ID']}<br>Region: {r['REGION_ID']}<br>Days Impacted: {int(r['V1_DAYS_IMPACTED'])}", axis=1),
                        hovertemplate='%{text}<br>Impact Mins: %{y:,.0f}<extra></extra>'
                    ))
            
            fig_days_v1.update_layout(
                template='plotly_white',
                height=450,
                title=dict(text='V1: Days Impacted vs Impact', font=dict(size=14)),
                font=dict(size=12),
                xaxis=dict(title='Days Impacted', tickfont=dict(size=11)),
                yaxis=dict(title='Impact Minutes', tickfont=dict(size=11), type='log'),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5, font=dict(size=11), title_text='Region'),
                margin=dict(t=70, b=50)
            )
        st.plotly_chart(fig_days_v1, use_container_width=True, config=CHART_CONFIG, key="deepdive_days_v1")
    
    with days_col2:
        fig_days_v2 = go.Figure()
        
        days_data_v2 = site_totals[v2_has_impact & v2_has_days]
        
        if not days_data_v2.empty:
            for region in ['Central', 'Northeast', 'South', 'West', 'Unknown']:
                region_data = days_data_v2[days_data_v2['REGION_ID'] == region]
                if not region_data.empty:
                    color = REGION_COLORS.get(region, DEFAULT_REGION_COLOR)
                    fig_days_v2.add_trace(go.Scatter(
                        x=region_data['V2_DAYS_IMPACTED'],
                        y=region_data['V2_IMPACT_MINS'],
                        mode='markers',
                        name=region,
                        marker=dict(size=8, color=color, opacity=0.7),
                        text=region_data.apply(lambda r: f"Site: {r['SITE_ID']}<br>Type: {r['SITE_TYPE']}<br>Market: {r['MARKET_ID']}<br>Region: {r['REGION_ID']}<br>Days Impacted: {int(r['V2_DAYS_IMPACTED'])}", axis=1),
                        hovertemplate='%{text}<br>Impact Mins: %{y:,.0f}<extra></extra>'
                    ))
            
            fig_days_v2.update_layout(
                template='plotly_white',
                height=450,
                title=dict(text='V2: Days Impacted vs Impact', font=dict(size=14)),
                font=dict(size=12),
                xaxis=dict(title='Days Impacted', tickfont=dict(size=11)),
                yaxis=dict(title='Impact Minutes', tickfont=dict(size=11), type='log'),
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5, font=dict(size=11), title_text='Region'),
                margin=dict(t=70, b=50)
            )
        st.plotly_chart(fig_days_v2, use_container_width=True, config=CHART_CONFIG, key="deepdive_days_v2")
    
    # ----- Chart 6: Impact Concentration - Pareto Analysis -----
    st.markdown("##### Impact Concentration (Pareto Analysis)")
    st.markdown("<span style='color:#888;font-size:0.75rem;'>What % of sites account for 80% of impact minutes?</span>", unsafe_allow_html=True)
    
    pareto_col1, pareto_col2 = st.columns(2)
    
    with pareto_col1:
        # V1 Pareto - use site_totals for region breakdown
        v1_sorted = site_totals[v1_has_impact].sort_values('V1_IMPACT_MINS', ascending=False)
        if not v1_sorted.empty:
            v1_sorted['CUMULATIVE_MINS'] = v1_sorted['V1_IMPACT_MINS'].cumsum()
            v1_sorted['CUMULATIVE_PCT'] = v1_sorted['CUMULATIVE_MINS'] / v1_sorted['V1_IMPACT_MINS'].sum() * 100
            v1_sorted['SITE_RANK'] = range(1, len(v1_sorted) + 1)
            v1_sorted['SITE_PCT'] = v1_sorted['SITE_RANK'] / len(v1_sorted) * 100
            
            # Find 80% point
            pct_80_idx = (v1_sorted['CUMULATIVE_PCT'] >= 80).idxmax()
            sites_for_80 = v1_sorted.loc[pct_80_idx, 'SITE_RANK']
            sites_pct_for_80 = v1_sorted.loc[pct_80_idx, 'SITE_PCT']
            
            # Get region breakdown for sites in 80%
            top_80_sites_v1 = v1_sorted[v1_sorted['SITE_RANK'] <= sites_for_80]
            region_counts_v1 = top_80_sites_v1['REGION_ID'].value_counts().to_dict()
            region_breakdown_v1 = " | ".join([f"{r}: {c}" for r, c in sorted(region_counts_v1.items())])
            
            # Title with concentration info and region breakdown
            st.markdown(f"**V1 Impact Concentration** <span style='font-size:0.85rem;color:#f59e0b;margin-left:10px;'>{sites_for_80:,} sites ({sites_pct_for_80:.1f}%) = 80% of impact</span> <span style='font-size:0.85rem;color:#888;margin-left:10px;'>{region_breakdown_v1}</span>", unsafe_allow_html=True)
            
            fig_pareto_v1 = go.Figure()
            
            fig_pareto_v1.add_trace(go.Scatter(
                x=v1_sorted['SITE_PCT'],
                y=v1_sorted['CUMULATIVE_PCT'],
                mode='lines',
                name='Cumulative %',
                line=dict(color='#3b82f6', width=3),
                fill='tozeroy',
                fillcolor='rgba(59, 130, 246, 0.2)'
            ))
            
            # Add 80% reference lines
            fig_pareto_v1.add_hline(y=80, line_dash="dash", line_color="#f59e0b", line_width=2)
            fig_pareto_v1.add_vline(x=sites_pct_for_80, line_dash="dash", line_color="#f59e0b", line_width=2)
            
            fig_pareto_v1.add_annotation(
                x=sites_pct_for_80 + 5, y=85,
                text=f"{sites_for_80:,} sites ({sites_pct_for_80:.1f}%)<br>= 80% of V1 impact",
                showarrow=False,
                font=dict(size=11, color='#f59e0b'),
                bgcolor='rgba(0,0,0,0.7)',
                borderpad=5
            )
            
            fig_pareto_v1.update_layout(
                template='plotly_white',
                height=350,
                font=dict(size=12),
                xaxis=dict(title='% of Sites (ranked by impact)', tickfont=dict(size=11), range=[0, 100]),
                yaxis=dict(title='Cumulative % of Impact', tickfont=dict(size=11), range=[0, 105]),
                margin=dict(t=20, b=50),
                showlegend=False
            )
            st.plotly_chart(fig_pareto_v1, use_container_width=True, config=CHART_CONFIG, key="deepdive_pareto_v1")
    
    with pareto_col2:
        # V2 Pareto - use site_totals for region breakdown
        v2_sorted = site_totals[v2_has_impact].sort_values('V2_IMPACT_MINS', ascending=False)
        if not v2_sorted.empty:
            v2_sorted['CUMULATIVE_MINS'] = v2_sorted['V2_IMPACT_MINS'].cumsum()
            v2_sorted['CUMULATIVE_PCT'] = v2_sorted['CUMULATIVE_MINS'] / v2_sorted['V2_IMPACT_MINS'].sum() * 100
            v2_sorted['SITE_RANK'] = range(1, len(v2_sorted) + 1)
            v2_sorted['SITE_PCT'] = v2_sorted['SITE_RANK'] / len(v2_sorted) * 100
            
            # Find 80% point
            pct_80_idx_v2 = (v2_sorted['CUMULATIVE_PCT'] >= 80).idxmax()
            sites_for_80_v2 = v2_sorted.loc[pct_80_idx_v2, 'SITE_RANK']
            sites_pct_for_80_v2 = v2_sorted.loc[pct_80_idx_v2, 'SITE_PCT']
            
            # Get region breakdown for sites in 80%
            top_80_sites_v2 = v2_sorted[v2_sorted['SITE_RANK'] <= sites_for_80_v2]
            region_counts_v2 = top_80_sites_v2['REGION_ID'].value_counts().to_dict()
            region_breakdown_v2 = " | ".join([f"{r}: {c}" for r, c in sorted(region_counts_v2.items())])
            
            # Title with concentration info and region breakdown
            st.markdown(f"**V2 Impact Concentration** <span style='font-size:0.85rem;color:#f59e0b;margin-left:10px;'>{sites_for_80_v2:,} sites ({sites_pct_for_80_v2:.1f}%) = 80% of impact</span> <span style='font-size:0.85rem;color:#888;margin-left:10px;'>{region_breakdown_v2}</span>", unsafe_allow_html=True)
            
            fig_pareto_v2 = go.Figure()
            
            fig_pareto_v2.add_trace(go.Scatter(
                x=v2_sorted['SITE_PCT'],
                y=v2_sorted['CUMULATIVE_PCT'],
                mode='lines',
                name='Cumulative %',
                line=dict(color='#22c55e', width=3),
                fill='tozeroy',
                fillcolor='rgba(34, 197, 94, 0.2)'
            ))
            
            # Add 80% reference lines
            fig_pareto_v2.add_hline(y=80, line_dash="dash", line_color="#f59e0b", line_width=2)
            fig_pareto_v2.add_vline(x=sites_pct_for_80_v2, line_dash="dash", line_color="#f59e0b", line_width=2)
            
            fig_pareto_v2.add_annotation(
                x=sites_pct_for_80_v2 + 5, y=85,
                text=f"{sites_for_80_v2:,} sites ({sites_pct_for_80_v2:.1f}%)<br>= 80% of V2 impact",
                showarrow=False,
                font=dict(size=11, color='#f59e0b'),
                bgcolor='rgba(0,0,0,0.7)',
                borderpad=5
            )
            
            fig_pareto_v2.update_layout(
                template='plotly_white',
                height=350,
                font=dict(size=12),
                xaxis=dict(title='% of Sites (ranked by impact)', tickfont=dict(size=11), range=[0, 100]),
                yaxis=dict(title='Cumulative % of Impact', tickfont=dict(size=11), range=[0, 105]),
                margin=dict(t=20, b=50),
                showlegend=False
            )
            st.plotly_chart(fig_pareto_v2, use_container_width=True, config=CHART_CONFIG, key="deepdive_pareto_v2")
    
    st.divider()
    
    # ===== ROW 3: By Market =====
    st.markdown("### 🗺️ Comparison by Market (Top 20 by Delta)")
    
    # OPTIMIZED: Reuse market_data already aggregated above (no extra query)
    
    if not market_data.empty:
        # Get top 20 by absolute delta
        market_data['ABS_DELTA'] = market_data['IMPACT_MINS_DELTA'].abs()
        top_markets = market_data.nlargest(20, 'ABS_DELTA')
        
        market_col1, market_col2 = st.columns(2)
        
        with market_col1:
            st.markdown("##### Markets with Largest Positive Delta (V1 > V2)")
            
            pos_markets = top_markets[top_markets['IMPACT_MINS_DELTA'] > 0].head(10)
            
            if not pos_markets.empty:
                fig_pos = go.Figure()
                fig_pos.add_trace(go.Bar(
                    y=pos_markets['MARKET_ID'],
                    x=pos_markets['IMPACT_MINS_DELTA'],
                    orientation='h',
                    marker_color='#22c55e',
                    text=pos_markets['IMPACT_MINS_DELTA'].apply(lambda x: f'+{x:,.0f}'),
                    textposition='outside'
                ))
                
                fig_pos.update_layout(
                    template='plotly_white',
                    height=400,
                    font=dict(size=14),
                    xaxis=dict(title='Delta (V1 - V2) Minutes', tickfont=dict(size=12)),
                    yaxis=dict(autorange='reversed', tickfont=dict(size=11)),
                    margin=dict(l=120, r=80)
                )
                st.plotly_chart(fig_pos, use_container_width=True, config=CHART_CONFIG, key="nonmacro_pos_markets")
            else:
                st.info("No markets with V1 > V2")
        
        with market_col2:
            st.markdown("##### Markets with Largest Negative Delta (V2 > V1)")
            
            neg_markets = top_markets[top_markets['IMPACT_MINS_DELTA'] < 0].head(10)
            
            if not neg_markets.empty:
                fig_neg = go.Figure()
                fig_neg.add_trace(go.Bar(
                    y=neg_markets['MARKET_ID'],
                    x=neg_markets['IMPACT_MINS_DELTA'].abs(),
                    orientation='h',
                    marker_color='#ef4444',
                    text=neg_markets['IMPACT_MINS_DELTA'].apply(lambda x: f'{x:,.0f}'),
                    textposition='outside'
                ))
                
                fig_neg.update_layout(
                    template='plotly_white',
                    height=400,
                    font=dict(size=14),
                    xaxis=dict(title='Delta (V2 - V1) Minutes', tickfont=dict(size=12)),
                    yaxis=dict(autorange='reversed', tickfont=dict(size=11)),
                    margin=dict(l=120, r=80)
                )
                st.plotly_chart(fig_neg, use_container_width=True, config=CHART_CONFIG, key="nonmacro_neg_markets")
            else:
                st.info("No markets with V2 > V1")
    
    st.divider()
    
    # ===== ROW: Per-Site Normalized Metrics =====
    st.markdown("### 📈 Per-Site Normalized Metrics")
    
    # Calculate totals for normalization
    v1_sites_with_impact = len(master_data[master_data['V1_IMPACT_MINS'] > 0]['SITE_ID'].unique())
    v2_sites_with_impact = len(master_data[master_data['V2_IMPACT_MINS'] > 0]['SITE_ID'].unique())
    
    # Per Impacted Site metrics
    st.markdown("**Per Impacted Site** - <span style='color:#888;font-size:0.8rem;'>Divided by sites with impact (CM site counts)</span>", unsafe_allow_html=True)
    
    norm_col1, norm_col2, norm_col3, norm_col4 = st.columns(4)
    
    with norm_col1:
        v1_mins_per_site = v1_total_mins / v1_sites_with_impact if v1_sites_with_impact > 0 else 0
        v2_mins_per_site = v2_total_mins / v2_sites_with_impact if v2_sites_with_impact > 0 else 0
        better = "V2" if v2_mins_per_site < v1_mins_per_site else "V1"
        better_color = "#22c55e" if better == "V2" else "#3b82f6"
        st.markdown(f"""
        <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
            <div style='color: #888; font-size: 0.8rem;'>Impact Mins/Impacted Site</div>
            <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                <div><span style='color: #3b82f6; font-size: 1.3rem; font-weight: bold;'>{v1_mins_per_site:,.1f}</span><br><span style='color:#888;font-size:0.7rem;'>V1</span></div>
                <div><span style='color: #22c55e; font-size: 1.3rem; font-weight: bold;'>{v2_mins_per_site:,.1f}</span><br><span style='color:#888;font-size:0.7rem;'>V2</span></div>
            </div>
            <div style='color: {better_color}; font-size: 0.75rem; margin-top: 5px;'>🏆 {better} better</div>
        </div>
        """, unsafe_allow_html=True)
    
    with norm_col2:
        v1_subs_per_site = v1_total_subs / v1_sites_with_impact if v1_sites_with_impact > 0 else 0
        v2_subs_per_site = v2_total_subs / v2_sites_with_impact if v2_sites_with_impact > 0 else 0
        better = "V2" if v2_subs_per_site < v1_subs_per_site else "V1"
        better_color = "#22c55e" if better == "V2" else "#3b82f6"
        st.markdown(f"""
        <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
            <div style='color: #888; font-size: 0.8rem;'>Impacted Subs/Impacted Site</div>
            <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                <div><span style='color: #3b82f6; font-size: 1.3rem; font-weight: bold;'>{v1_subs_per_site:,.1f}</span><br><span style='color:#888;font-size:0.7rem;'>V1</span></div>
                <div><span style='color: #22c55e; font-size: 1.3rem; font-weight: bold;'>{v2_subs_per_site:,.1f}</span><br><span style='color:#888;font-size:0.7rem;'>V2</span></div>
            </div>
            <div style='color: {better_color}; font-size: 0.75rem; margin-top: 5px;'>🏆 {better} better</div>
        </div>
        """, unsafe_allow_html=True)
    
    with norm_col3:
        # Sites with impact counts
        st.markdown(f"""
        <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
            <div style='color: #888; font-size: 0.8rem;'>Sites with Impact</div>
            <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                <div><span style='color: #3b82f6; font-size: 1.3rem; font-weight: bold;'>{v1_sites_with_impact:,}</span><br><span style='color:#888;font-size:0.7rem;'>V1</span></div>
                <div><span style='color: #22c55e; font-size: 1.3rem; font-weight: bold;'>{v2_sites_with_impact:,}</span><br><span style='color:#888;font-size:0.7rem;'>V2</span></div>
            </div>
            <div style='color: #888; font-size: 0.75rem; margin-top: 5px;'>Site count comparison</div>
        </div>
        """, unsafe_allow_html=True)
    
    with norm_col4:
        # Average impact per site comparison
        v1_avg = v1_total_mins / total_sites if total_sites > 0 else 0
        v2_avg = v2_total_mins / total_sites if total_sites > 0 else 0
        pct_diff = ((v1_avg - v2_avg) / v1_avg * 100) if v1_avg > 0 else 0
        diff_color = "#22c55e" if pct_diff > 0 else "#ef4444"
        st.markdown(f"""
        <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
            <div style='color: #888; font-size: 0.8rem;'>Avg Impact/Total Site</div>
            <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                <div><span style='color: #3b82f6; font-size: 1.3rem; font-weight: bold;'>{v1_avg:,.1f}</span><br><span style='color:#888;font-size:0.7rem;'>V1</span></div>
                <div><span style='color: #22c55e; font-size: 1.3rem; font-weight: bold;'>{v2_avg:,.1f}</span><br><span style='color:#888;font-size:0.7rem;'>V2</span></div>
            </div>
            <div style='color: {diff_color}; font-size: 0.75rem; margin-top: 5px;'>{pct_diff:+.1f}% difference</div>
        </div>
        """, unsafe_allow_html=True)
    
    # Per Total Site metrics
    st.markdown("<div style='margin-top:15px;'></div>", unsafe_allow_html=True)
    st.markdown("**Per Total Site** - <span style='color:#888;font-size:0.8rem;'>Divided by all non-macro sites ({:,} total)</span>".format(total_sites), unsafe_allow_html=True)
    
    norm_col5, norm_col6, norm_col7, norm_col8 = st.columns(4)
    
    with norm_col5:
        v1_mins_total = v1_total_mins / total_sites if total_sites > 0 else 0
        v2_mins_total = v2_total_mins / total_sites if total_sites > 0 else 0
        better = "V2" if v2_mins_total < v1_mins_total else "V1"
        better_color = "#22c55e" if better == "V2" else "#3b82f6"
        st.markdown(f"""
        <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
            <div style='color: #888; font-size: 0.8rem;'>Impact Mins/Total Site</div>
            <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                <div><span style='color: #3b82f6; font-size: 1.3rem; font-weight: bold;'>{v1_mins_total:,.2f}</span><br><span style='color:#888;font-size:0.7rem;'>V1</span></div>
                <div><span style='color: #22c55e; font-size: 1.3rem; font-weight: bold;'>{v2_mins_total:,.2f}</span><br><span style='color:#888;font-size:0.7rem;'>V2</span></div>
            </div>
            <div style='color: {better_color}; font-size: 0.75rem; margin-top: 5px;'>🏆 {better} better</div>
        </div>
        """, unsafe_allow_html=True)
    
    with norm_col6:
        v1_subs_total = v1_total_subs / total_sites if total_sites > 0 else 0
        v2_subs_total = v2_total_subs / total_sites if total_sites > 0 else 0
        better = "V2" if v2_subs_total < v1_subs_total else "V1"
        better_color = "#22c55e" if better == "V2" else "#3b82f6"
        st.markdown(f"""
        <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
            <div style='color: #888; font-size: 0.8rem;'>Impacted Subs/Total Site</div>
            <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                <div><span style='color: #3b82f6; font-size: 1.3rem; font-weight: bold;'>{v1_subs_total:,.2f}</span><br><span style='color:#888;font-size:0.7rem;'>V1</span></div>
                <div><span style='color: #22c55e; font-size: 1.3rem; font-weight: bold;'>{v2_subs_total:,.2f}</span><br><span style='color:#888;font-size:0.7rem;'>V2</span></div>
            </div>
            <div style='color: {better_color}; font-size: 0.75rem; margin-top: 5px;'>🏆 {better} better</div>
        </div>
        """, unsafe_allow_html=True)
    
    with norm_col7:
        # Percentage of sites impacted
        v1_pct_impacted = (v1_sites_with_impact / total_sites * 100) if total_sites > 0 else 0
        v2_pct_impacted = (v2_sites_with_impact / total_sites * 100) if total_sites > 0 else 0
        better = "V2" if v2_pct_impacted < v1_pct_impacted else "V1"
        better_color = "#22c55e" if better == "V2" else "#3b82f6"
        st.markdown(f"""
        <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
            <div style='color: #888; font-size: 0.8rem;'>% Sites Impacted</div>
            <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                <div><span style='color: #3b82f6; font-size: 1.3rem; font-weight: bold;'>{v1_pct_impacted:.1f}%</span><br><span style='color:#888;font-size:0.7rem;'>V1</span></div>
                <div><span style='color: #22c55e; font-size: 1.3rem; font-weight: bold;'>{v2_pct_impacted:.1f}%</span><br><span style='color:#888;font-size:0.7rem;'>V2</span></div>
            </div>
            <div style='color: {better_color}; font-size: 0.75rem; margin-top: 5px;'>🏆 {better} better</div>
        </div>
        """, unsafe_allow_html=True)
    
    with norm_col8:
        # Delta per site
        delta_per_site = delta_mins / total_sites if total_sites > 0 else 0
        delta_color = "#22c55e" if delta_per_site > 0 else "#ef4444"
        st.markdown(f"""
        <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
            <div style='color: #888; font-size: 0.8rem;'>Delta (V1-V2)/Total Site</div>
            <div style='margin-top: 15px;'>
                <span style='color: {delta_color}; font-size: 1.5rem; font-weight: bold;'>{delta_per_site:+,.2f}</span>
            </div>
            <div style='color: #888; font-size: 0.75rem; margin-top: 10px;'>mins saved per site</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # ===== ROW 4: Data Tables =====
    st.markdown("### 📋 Detailed Data")
    
    table_tab1, table_tab2, table_tab3 = st.tabs(["By Site Type", "By Market", "Site-Level Detail"])
    
    with table_tab1:
        if not summary_by_type.empty:
            display_cols = ['SITE_TYPE', 'TOTAL_SITES', 'V1_SITES_WITH_DATA', 'V2_SITES_WITH_DATA',
                          'V1_TOTAL_IMPACT_MINS', 'V2_TOTAL_IMPACT_MINS', 'IMPACT_MINS_DELTA',
                          'V1_TOTAL_SUBS', 'V2_TOTAL_SUBS', 'TOTAL_SUBS_DELTA']
            st.dataframe(summary_by_type[display_cols], use_container_width=True, hide_index=True)
    
    with table_tab2:
        if not market_data.empty:
            display_cols = ['MARKET_ID', 'TOTAL_SITES', 'V1_TOTAL_IMPACT_MINS', 'V2_TOTAL_IMPACT_MINS', 
                          'IMPACT_MINS_DELTA', 'V1_TOTAL_SUBS', 'V2_TOTAL_SUBS']
            st.dataframe(market_data[display_cols].head(50), use_container_width=True, hide_index=True)
    
    with table_tab3:
        # OPTIMIZED: Aggregate site-level data from master_data
        if not master_data.empty:
            site_data = master_data.groupby(['SITE_ID', 'SITE_TYPE', 'MARKET_ID']).agg({
                'V1_IMPACT_MINS': 'sum',
                'V2_IMPACT_MINS': 'sum',
                'V1_TOTAL_SUBS': 'sum',
                'V2_TOTAL_SUBS': 'sum'
            }).reset_index()
            site_data['IMPACT_MINS_DELTA'] = site_data['V1_IMPACT_MINS'] - site_data['V2_IMPACT_MINS']
            site_data = site_data.sort_values('IMPACT_MINS_DELTA', key=abs, ascending=False)
            
            display_cols = ['SITE_ID', 'SITE_TYPE', 'MARKET_ID', 'V1_IMPACT_MINS', 'V2_IMPACT_MINS', 
                          'IMPACT_MINS_DELTA', 'V1_TOTAL_SUBS', 'V2_TOTAL_SUBS']
            st.dataframe(site_data[display_cols].head(100), use_container_width=True, hide_index=True)

def aav_analysis_dashboard(conn, days, filters=None):
    """AAV Analysis Dashboard - Analyze Transport-AAV vendor impact"""
    
    st.markdown('<div class="section-header">📡 AAV Vendor Analysis - Transport Impact</div>', unsafe_allow_html=True)
    st.markdown("<span style='color:#888;font-size:0.85rem;'>Analyzing Alternative Access Vendor (AAV) impact on network availability and outages</span>", unsafe_allow_html=True)
    
    # Build date filters
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    date_filter_avail = f"DATE_VALUE >= '{start_date}' AND DATE_VALUE <= '{end_date}'" if start_date and end_date else f"DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
    date_filter_cottr = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'" if start_date and end_date else f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Build market filters - handle single and multi-market selection
    market_selection = filters.get('market') if filters else None
    market_display = get_market_display_name(market_selection)
    
    # Build SQL market filter for multiple markets
    if market_selection:
        if isinstance(market_selection, str):
            market_selection = [market_selection]
        # Get all market IDs for the selection
        all_avail_ids = []
        all_cottr_ids = []
        for m in market_selection:
            all_avail_ids.extend(get_market_ids_for_filter(m, 'availability'))
            all_cottr_ids.extend(get_market_ids_for_filter(m, 'cottr'))
        all_avail_ids = list(dict.fromkeys(all_avail_ids))
        all_cottr_ids = list(dict.fromkeys(all_cottr_ids))
        
        if len(all_avail_ids) == 1:
            market_filter_avail = f" AND UPPER(MARKET_ID) = '{all_avail_ids[0].upper()}'"
        else:
            avail_list = "', '".join([m.upper() for m in all_avail_ids])
            market_filter_avail = f" AND UPPER(MARKET_ID) IN ('{avail_list}')"
        if len(all_cottr_ids) == 1:
            market_filter_cottr = f" AND UPPER(MKT_NAME) = '{all_cottr_ids[0].upper()}'"
        else:
            cottr_list = "', '".join([m.upper() for m in all_cottr_ids])
            market_filter_cottr = f" AND UPPER(MKT_NAME) IN ('{cottr_list}')"
        # Pass full market selection to cached functions (they handle lists)
        market_selection_param = market_selection
    else:
        market_filter_avail = ""
        market_filter_cottr = ""
        market_selection_param = None
    
    # ===== ROW 1: KPI Summary Cards =====
    st.markdown("### 📊 AAV Impact Summary")
    
    with st.spinner("Loading AAV data..."):
        results = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(get_aav_availability_summary, conn, start_date, end_date, days, market_selection_param): 'aav_avail',
                executor.submit(get_aav_cottr_market, conn, start_date, end_date, days, market_selection_param): 'aav_cottr_market',
                executor.submit(get_aav_vendor_market_breakdown, conn, start_date, end_date, days, market_selection_param): 'aav_vendor_market',
                executor.submit(get_aav_top_sites, conn, start_date, end_date, days, market_selection_param): 'aav_top_sites',
                executor.submit(get_aav_daily_trend, conn, start_date, end_date, days, market_selection_param): 'aav_daily',
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception:
                    results[key] = pd.DataFrame()
        
        aav_avail = results.get('aav_avail', pd.DataFrame())
        aav_cottr_market = results.get('aav_cottr_market', pd.DataFrame())
        aav_vendor_market = results.get('aav_vendor_market', pd.DataFrame())
        aav_top_sites = results.get('aav_top_sites', pd.DataFrame())
        aav_daily = results.get('aav_daily', pd.DataFrame())
    
    # KPI Cards
    if not aav_avail.empty:
        # Convert numeric columns to proper types
        aav_avail['TOTAL_DOWNTIME'] = pd.to_numeric(aav_avail['TOTAL_DOWNTIME'], errors='coerce').fillna(0)
        aav_avail['SITE_COUNT'] = pd.to_numeric(aav_avail['SITE_COUNT'], errors='coerce').fillna(0)
        
        total_downtime = aav_avail['TOTAL_DOWNTIME'].sum()
        total_sites = int(aav_avail['SITE_COUNT'].sum())
        total_vendors = len(aav_avail[aav_avail['AAV_VENDOR'] != 'Unknown'])
        worst_vendor = aav_avail.iloc[0]['AAV_VENDOR'] if not aav_avail.empty else 'N/A'
        worst_vendor_downtime = aav_avail.iloc[0]['TOTAL_DOWNTIME'] if not aav_avail.empty else 0
        
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        
        with kpi1:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Total AAV Downtime</div>
                <div class="metric-value-magenta">{format_number(total_downtime)} sec</div>
            </div>
            """, unsafe_allow_html=True)
        
        with kpi2:
            st.markdown(f"""
            <div class="metric-card-orange">
                <div class="metric-label">Sites Affected</div>
                <div class="metric-value-orange">{total_sites:,}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with kpi3:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">AAV Vendors</div>
                <div class="metric-value-magenta">{total_vendors}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with kpi4:
            st.markdown(f"""
            <div class="metric-card-orange">
                <div class="metric-label">Worst Vendor</div>
                <div class="metric-value-orange" style="font-size:1rem;">{shorten_aav_vendor(worst_vendor, 15)}</div>
                <div class="metric-source">{format_number(worst_vendor_downtime)} sec</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No AAV data available for the selected time period.")
        return
    
    st.divider()
    
    # ===== ROW 2: Vendor Analysis =====
    st.markdown("### 📈 AAV Vendor Comparison")
    
    vendor_col1, vendor_col2 = st.columns(2)
    
    with vendor_col1:
        st.markdown("**Downtime by AAV Vendor (Availability)**")
        if not aav_avail.empty:
            # Create bar chart
            fig_vendor = go.Figure()
            
            # Get top 10 vendors
            top_vendors = aav_avail.head(10)
            
            fig_vendor.add_trace(go.Bar(
                y=top_vendors['AAV_VENDOR'].apply(lambda x: shorten_aav_vendor(x, 25)),
                x=top_vendors['TOTAL_DOWNTIME'],
                orientation='h',
                marker_color='#e20074',
                text=[format_number(x) for x in top_vendors['TOTAL_DOWNTIME']],
                textposition='auto',
                textfont=dict(color='white', size=10)
            ))
            
            fig_vendor.update_layout(
                template='plotly_white',
                height=400,
                margin=dict(l=150, r=20, t=30, b=50),
                xaxis_title="Total Downtime (seconds)",
                yaxis=dict(autorange='reversed'),
                showlegend=False
            )
            st.plotly_chart(fig_vendor, use_container_width=True, config=CHART_CONFIG)
    
    with vendor_col2:
        st.markdown("**Sites Affected by AAV Vendor**")
        if not aav_avail.empty:
            # Create pie chart
            top_vendors = aav_avail.head(8)
            
            fig_pie = go.Figure(data=[go.Pie(
                labels=top_vendors['AAV_VENDOR'].apply(lambda x: shorten_aav_vendor(x, 20)),
                values=top_vendors['SITE_COUNT'],
                hole=0.4,
                marker_colors=['#e20074', '#ff4d9a', '#ff80b6', '#666666', '#888888', '#aaaaaa', '#cccccc', '#eeeeee']
            )])
            
            fig_pie.update_layout(
                template='plotly_white',
                height=400,
                margin=dict(l=20, r=20, t=30, b=50),
                showlegend=True,
                legend=dict(orientation='h', yanchor='bottom', y=-0.2)
            )
            st.plotly_chart(fig_pie, use_container_width=True, config=CHART_CONFIG)
    
    st.divider()
    
    # ===== ROW 3: Top Sites and Market Analysis =====
    st.markdown("### 🔍 Detailed Analysis")
    
    detail_col1, detail_col2 = st.columns(2)
    
    with detail_col1:
        st.markdown("**Top 15 Sites by AAV Downtime**")
        if not aav_top_sites.empty:
            # Normalize market names to Global Market ID format
            if 'MARKET_ID' in aav_top_sites.columns:
                aav_top_sites = normalize_market_column(aav_top_sites, 'MARKET_ID', 'availability')
            # Convert numeric columns
            aav_top_sites['TOTAL_DOWNTIME'] = pd.to_numeric(aav_top_sites['TOTAL_DOWNTIME'], errors='coerce').fillna(0)
            aav_top_sites['DAYS_WITH_DOWNTIME'] = pd.to_numeric(aav_top_sites['DAYS_WITH_DOWNTIME'], errors='coerce').fillna(0)
            aav_top_sites['AVAILABILITY_PCT'] = pd.to_numeric(aav_top_sites['AVAILABILITY_PCT'], errors='coerce').fillna(0)
            
            # Display as styled list
            sites_html = '<div style="max-height:400px;overflow-y:auto;">'
            for idx, row in aav_top_sites.head(15).iterrows():
                site_id = row['SITE_ID']
                market = row['MARKET_ID']
                vendor = shorten_aav_vendor(row['AAV_VENDOR'], 20)
                downtime = row['TOTAL_DOWNTIME']
                days = row['DAYS_WITH_DOWNTIME']
                avail = row['AVAILABILITY_PCT'] if pd.notna(row['AVAILABILITY_PCT']) else 0
                
                avail_color = "#22c55e" if avail >= 99.85 else "#f59e0b" if avail >= 99.0 else "#ef4444"
                
                sites_html += f'<div class="market-box" style="height:auto;padding:8px;"><div style="display:flex;justify-content:space-between;align-items:center;"><div><div style="font-size:0.85rem;font-weight:bold;">{site_id}</div><div style="font-size:0.7rem;color:#666;">{market} | {vendor}</div></div><div style="text-align:right;"><div style="font-size:0.85rem;font-weight:bold;color:#e20074;">{format_number(downtime)} sec</div><div style="font-size:0.7rem;color:{avail_color};">{avail:.2f}% | {int(days)} days</div></div></div></div>'
            sites_html += '</div>'
            st.markdown(sites_html, unsafe_allow_html=True)
    
    with detail_col2:
        st.markdown("**AAV Impact by Market (COTTR)**")
        if not aav_cottr_market.empty:
            # Normalize market names to Global Market ID format
            if 'MARKET' in aav_cottr_market.columns:
                aav_cottr_market = normalize_market_column(aav_cottr_market, 'MARKET', 'cottr')
            # Convert numeric columns
            aav_cottr_market['TOTAL_OUTAGE_MINUTES'] = pd.to_numeric(aav_cottr_market['TOTAL_OUTAGE_MINUTES'], errors='coerce').fillna(0)
            aav_cottr_market['SITE_COUNT'] = pd.to_numeric(aav_cottr_market['SITE_COUNT'], errors='coerce').fillna(0)
            aav_cottr_market['OUTAGE_COUNT'] = pd.to_numeric(aav_cottr_market['OUTAGE_COUNT'], errors='coerce').fillna(0)
            
            # Display as styled list
            market_html = '<div style="max-height:400px;overflow-y:auto;">'
            total_mins = aav_cottr_market['TOTAL_OUTAGE_MINUTES'].sum()
            
            for idx, row in aav_cottr_market.head(15).iterrows():
                market = row['MARKET']
                sites = row['SITE_COUNT']
                mins = row['TOTAL_OUTAGE_MINUTES']
                outages = row['OUTAGE_COUNT']
                pct = (mins / total_mins * 100) if total_mins > 0 else 0
                
                market_html += f'<div class="market-box" style="height:auto;padding:8px;"><div style="display:flex;justify-content:space-between;align-items:center;"><div><div style="font-size:0.85rem;font-weight:bold;">{market}</div><div style="font-size:0.7rem;color:#666;">{int(sites)} sites | {int(outages)} outages</div></div><div style="text-align:right;"><div style="font-size:0.85rem;font-weight:bold;color:#f59e0b;">{format_number(mins)} mins</div><div style="font-size:0.7rem;color:#888;">{pct:.1f}% of total</div></div></div></div>'
            market_html += '</div>'
            st.markdown(market_html, unsafe_allow_html=True)
    
    st.divider()
    
    # ===== ROW 4: Daily Trend =====
    st.markdown("### 📉 AAV Downtime Trend")
    
    if not aav_daily.empty:
        # Convert numeric columns
        aav_daily['TOTAL_DOWNTIME'] = pd.to_numeric(aav_daily['TOTAL_DOWNTIME'], errors='coerce').fillna(0)
        
        # Get top 5 vendors for the trend
        top_5_vendors = aav_avail.head(5)['AAV_VENDOR'].tolist()
        
        fig_trend = go.Figure()
        
        colors = ['#e20074', '#ff4d9a', '#666666', '#f59e0b', '#22c55e']
        
        for idx, vendor in enumerate(top_5_vendors):
            vendor_data = aav_daily[aav_daily['AAV_VENDOR'] == vendor]
            if not vendor_data.empty:
                fig_trend.add_trace(go.Scatter(
                    x=vendor_data['DATE_VALUE'],
                    y=vendor_data['TOTAL_DOWNTIME'],
                    name=shorten_aav_vendor(vendor, 20),
                    line=dict(color=colors[idx % len(colors)], width=2),
                    mode='lines+markers'
                ))
        
        fig_trend.update_layout(
            template='plotly_white',
            height=350,
            margin=dict(l=50, r=20, t=30, b=50),
            xaxis_title="Date",
            yaxis_title="Downtime (seconds)",
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5),
            hovermode='x unified'
        )
        st.plotly_chart(fig_trend, use_container_width=True, config=CHART_CONFIG)
    
    st.divider()
    
    # ===== ROW 5: Vendor Detail Table =====
    st.markdown("### 📋 AAV Vendor Detail Table")
    
    if not aav_avail.empty:
        display_df = aav_avail.copy()
        display_df['AAV_VENDOR'] = display_df['AAV_VENDOR'].apply(lambda x: shorten_aav_vendor(x, 30))
        display_df['TOTAL_N'] = pd.to_numeric(display_df['TOTAL_N'], errors='coerce').fillna(0).astype(float)
        display_df['TOTAL_D'] = pd.to_numeric(display_df['TOTAL_D'], errors='coerce').fillna(0).astype(float)
        avail_pct = (display_df['TOTAL_N'] / display_df['TOTAL_D'].replace(0, float('nan')) * 100)
        display_df['AVAILABILITY_PCT'] = avail_pct.astype(float).round(2)
        display_df = display_df[['AAV_VENDOR', 'SITE_COUNT', 'TOTAL_DOWNTIME', 'DAYS_WITH_DOWNTIME', 'AVAILABILITY_PCT']]
        display_df.columns = ['AAV Vendor', 'Sites', 'Total Downtime (sec)', 'Days with Downtime', 'Availability %']
        
        st.dataframe(display_df, use_container_width=True, height=300)

def oem_comparison_dashboard(conn, days, filters=None):
    """OEM Comparison Dashboard - Compare Ericsson vs Nokia across all KPIs"""
    
    st.markdown('<div class="section-header">⚡ OEM Comparison: Ericsson vs Nokia</div>', unsafe_allow_html=True)
    
    # Use global Site Type filter
    site_type = filters.get('site_type') if filters else 'Macro'
    site_type_filter_avail = get_site_type_sql_filter(site_type, 'a.')
    # For COTTR, Non-Macro means SECTOR_TYPE_CATEGORY != 'Macro'
    if site_type == 'Non-Macro':
        site_type_filter_cottr = "(c.SECTOR_TYPE_CATEGORY != 'Macro' OR c.SECTOR_TYPE_CATEGORY IS NULL)"
    elif site_type:
        site_type_filter_cottr = f"c.SECTOR_TYPE_CATEGORY = '{site_type}'"
    else:
        site_type_filter_cottr = "1=1"
    site_types_display = site_type if site_type else 'All'
    
    st.markdown(f"<span style='font-size:0.85rem;color:#888;'>Comparing performance metrics between Ericsson and Nokia markets | Site Type: {site_types_display}</span>", unsafe_allow_html=True)
    
    start_date = filters.get('start_date') if filters else None
    end_date = filters.get('end_date') if filters else None
    market_selection = filters.get('market') if filters else None
    market_display = get_market_display_name(market_selection)
    
    # Format dates - use alias 'a' for availability queries
    if start_date and end_date:
        date_filter_avail = f"a.DATE_VALUE >= '{start_date}' AND a.DATE_VALUE <= '{end_date}'"
        date_filter_cottr = f"c.LOCAL_START_TIMESTAMP >= '{start_date}' AND c.LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'"
        date_filter_cm = f"LOCAL_START_TIMESTAMP >= '{start_date}' AND LOCAL_START_TIMESTAMP <= '{end_date} 23:59:59'"
    else:
        date_filter_avail = f"a.DATE_VALUE >= DATEADD(day, -{days}, CURRENT_DATE())"
        date_filter_cottr = f"c.LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
        date_filter_cm = f"LOCAL_START_TIMESTAMP >= DATEADD(day, -{days}, CURRENT_DATE())"
    
    # Build market filters - handle single and multi-market selection
    if market_selection:
        if isinstance(market_selection, str):
            market_selection_list = [market_selection]
        else:
            market_selection_list = market_selection
        # Get all market IDs for the selection
        all_avail_ids = []
        all_cottr_ids = []
        all_cm_ids = []
        for m in market_selection_list:
            all_avail_ids.extend(get_market_ids_for_filter(m, 'availability'))
            all_cottr_ids.extend(get_market_ids_for_filter(m, 'cottr'))
            all_cm_ids.extend(get_market_ids_for_filter(m, 'customer_minutes'))
        all_avail_ids = list(dict.fromkeys(all_avail_ids))
        all_cottr_ids = list(dict.fromkeys(all_cottr_ids))
        all_cm_ids = list(dict.fromkeys(all_cm_ids))
        
        if len(all_avail_ids) == 1:
            market_filter_avail = f" AND UPPER(a.MARKET_ID) = '{all_avail_ids[0].upper()}'"
        else:
            avail_list = "', '".join([m.upper() for m in all_avail_ids])
            market_filter_avail = f" AND UPPER(a.MARKET_ID) IN ('{avail_list}')"
        if len(all_cottr_ids) == 1:
            market_filter_cottr = f" AND UPPER(c.MKT_NAME) = '{all_cottr_ids[0].upper()}'"
        else:
            cottr_list = "', '".join([m.upper() for m in all_cottr_ids])
            market_filter_cottr = f" AND UPPER(c.MKT_NAME) IN ('{cottr_list}')"
        if len(all_cm_ids) == 1:
            market_filter_cm = f" AND UPPER(MARKET) = '{all_cm_ids[0].upper()}'"
        else:
            cm_list = "', '".join([m.upper() for m in all_cm_ids])
            market_filter_cm = f" AND UPPER(MARKET) IN ('{cm_list}')"
        # Pass full market selection to cached functions (they handle lists)
        market_param = market_selection_list
    else:
        market_filter_avail = ""
        market_filter_cottr = ""
        market_filter_cm = ""
        market_param = None
    
    AVAILABILITY_GOAL = 99.85
    
    with st.spinner("Loading OEM comparison data..."):
        results = {}
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(get_oem_availability_data, conn, start_date, end_date, days, site_type, market_param): 'avail_oem',
                executor.submit(get_oem_market_breakdown, conn, start_date, end_date, days, site_type, market_param): 'avail_market',
                executor.submit(get_oem_daily_trends, conn, start_date, end_date, days, site_type, market_param): 'avail_daily',
                executor.submit(get_oem_cottr_data, conn, start_date, end_date, days, site_type, market_param): 'cottr_oem',
                executor.submit(get_oem_cottr_daily, conn, start_date, end_date, days, site_type, market_param): 'cottr_daily',
                executor.submit(get_oem_customer_minutes, conn, start_date, end_date, days, market_param): 'cm_oem',
                executor.submit(get_oem_customer_minutes_daily, conn, start_date, end_date, days, market_param): 'cm_daily',
                executor.submit(get_oem_focus_category, conn, start_date, end_date, days, site_type, market_param): 'focus_oem',
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception:
                    results[key] = pd.DataFrame()
        
        avail_oem = results.get('avail_oem', pd.DataFrame())
        avail_market = results.get('avail_market', pd.DataFrame())
        avail_daily = results.get('avail_daily', pd.DataFrame())
        cottr_oem = results.get('cottr_oem', pd.DataFrame())
        cottr_daily = results.get('cottr_daily', pd.DataFrame())
        cm_oem = results.get('cm_oem', pd.DataFrame())
        cm_daily = results.get('cm_daily', pd.DataFrame())
        focus_oem = results.get('focus_oem', pd.DataFrame())
        
        if avail_oem.empty:
            st.warning("No OEM comparison data available.")
            return
        
        # Normalize market names to Global Market ID format
        if not avail_market.empty and 'MARKET_ID' in avail_market.columns:
            avail_market = normalize_market_column(avail_market, 'MARKET_ID', 'availability')
    
    if avail_oem.empty:
        st.warning("No OEM comparison data available.")
        return
    
    # Convert to float
    for col in ['TOTAL_DOWNTIME', 'TOTAL_N', 'TOTAL_D', 'AVAILABILITY_PCT', 'UNAVAILABILITY_PCT', 'SECONDS_BUDGET', 'OVER_UNDER_BUDGET']:
        if col in avail_oem.columns:
            avail_oem[col] = avail_oem[col].astype(float)
    
    # ===== ROW 1: HIGH-LEVEL KPI COMPARISON =====
    # Calculate unique site counts from all 3 KPI sources
    avail_site_count = int(avail_oem['SITE_COUNT'].sum())
    cottr_site_count = int(cottr_oem['SITE_COUNT'].sum()) if not cottr_oem.empty and 'SITE_COUNT' in cottr_oem.columns else 0
    cm_site_count = int(cm_oem['SITE_COUNT'].sum()) if not cm_oem.empty and 'SITE_COUNT' in cm_oem.columns else 0
    
    st.markdown("### 📊 OEM Summary Comparison")
    
    # Show site count comparison across all 3 KPIs
    st.markdown(f"""
    <div style='background:#f8f9fa;padding:10px 15px;border-radius:8px;margin-bottom:15px;display:flex;gap:30px;flex-wrap:wrap;'>
        <div><span style='color:#888;font-size:0.85rem;'>Unique Sites by KPI Source (with OEM mapped):</span></div>
        <div><span style='color:#4CAF50;font-weight:bold;'>Availability:</span> <span style='color:white;'>{avail_site_count:,}</span></div>
        <div><span style='color:#FF9800;font-weight:bold;'>COTTR:</span> <span style='color:white;'>{cottr_site_count:,}</span></div>
        <div><span style='color:#e20074;font-weight:bold;'>Customer Minutes:</span> <span style='color:white;'>{cm_site_count:,}</span></div>
    </div>
    """, unsafe_allow_html=True)
    
    # Get Ericsson and Nokia data - use indexed lookup for efficiency (single filter per DataFrame)
    avail_by_oem = avail_oem.set_index('OEM') if not avail_oem.empty else pd.DataFrame()
    ericsson_avail = avail_by_oem.loc['Ericsson'] if 'Ericsson' in avail_by_oem.index else None
    nokia_avail = avail_by_oem.loc['Nokia'] if 'Nokia' in avail_by_oem.index else None
    
    cottr_by_oem = cottr_oem.set_index('OEM') if not cottr_oem.empty else pd.DataFrame()
    ericsson_cottr = cottr_by_oem.loc['Ericsson'] if 'Ericsson' in cottr_by_oem.index else None
    nokia_cottr = cottr_by_oem.loc['Nokia'] if 'Nokia' in cottr_by_oem.index else None
    
    cm_by_oem = cm_oem.set_index('OEM') if not cm_oem.empty else pd.DataFrame()
    ericsson_cm = cm_by_oem.loc['Ericsson'] if 'Ericsson' in cm_by_oem.index else None
    nokia_cm = cm_by_oem.loc['Nokia'] if 'Nokia' in cm_by_oem.index else None
    
    # KPI Cards - Side by Side comparison (narrower width with spacing)
    spacer1, col1, spacer2, col2, spacer3 = st.columns([0.5, 2, 0.5, 2, 0.5])
    
    with col1:
        st.markdown("""
        <div style='background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); padding: 15px; border-radius: 10px; border-left: 4px solid #0066cc;'>
            <h3 style='color: #0066cc; margin: 0;'>📘 Ericsson</h3>
        </div>
        """, unsafe_allow_html=True)
        
        if ericsson_avail is None:
            # Show message when market has no Ericsson sites
            market_selection = filters.get('market') if filters else None
            if market_selection:
                st.info(f"ℹ️ Market has 0 sites that are Ericsson")
            else:
                st.info("ℹ️ No Ericsson data available")
        elif ericsson_avail is not None:
            e_sites = int(ericsson_avail['SITE_COUNT'])
            e_avail = ericsson_avail['AVAILABILITY_PCT']
            e_unavail = ericsson_avail['UNAVAILABILITY_PCT']
            e_downtime = ericsson_avail['TOTAL_DOWNTIME']
            e_budget = ericsson_avail['SECONDS_BUDGET']
            e_over = ericsson_avail['OVER_UNDER_BUDGET']
            
            e_status = "✅" if e_avail >= AVAILABILITY_GOAL else "❌"
            e_budget_status = "🟢 Under" if e_over <= 0 else "🔴 Over"
            
            st.markdown(f"""
            <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                <div style='display: flex; justify-content: space-between;'>
                    <span style='color: #888;'>Site Count</span>
                    <span style='color: white; font-weight: bold;'>{e_sites:,}</span>
                </div>
            </div>
            <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                <div style='display: flex; justify-content: space-between;'>
                    <span style='color: #888;'>Availability</span>
                    <span style='color: {"#00ff00" if e_avail >= AVAILABILITY_GOAL else "#ff4444"}; font-weight: bold;'>{e_status} {e_avail:.2f}%</span>
                </div>
            </div>
            <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                <div style='display: flex; justify-content: space-between;'>
                    <span style='color: #888;'>Unavailability</span>
                    <span style='color: #e20074; font-weight: bold;'>{e_unavail:.2f}%</span>
                </div>
            </div>
            <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                <div style='display: flex; justify-content: space-between;'>
                    <span style='color: #888;'>Total Downtime</span>
                    <span style='color: white; font-weight: bold;'>{e_downtime/1_000_000:,.1f}M sec</span>
                </div>
            </div>
            <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                <div style='display: flex; justify-content: space-between;'>
                    <span style='color: #888;'>Budget (0.15%)</span>
                    <span style='color: white;'>{e_budget/1_000_000:,.1f}M sec</span>
                </div>
            </div>
            <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                <div style='display: flex; justify-content: space-between;'>
                    <span style='color: #888;'>Over/Under Budget</span>
                    <span style='color: {"#00ff00" if e_over <= 0 else "#ff4444"}; font-weight: bold;'>{e_budget_status} {abs(e_over)/1_000_000:,.1f}M sec</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if ericsson_cottr is not None and ericsson_cottr.get('OUTAGE_COUNT') is not None:
                e_outages = int(ericsson_cottr['OUTAGE_COUNT'] or 0)
                e_outage_mins = float(ericsson_cottr['TOTAL_OUTAGE_MINUTES'] or 0)
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                    <div style='display: flex; justify-content: space-between;'>
                        <span style='color: #888;'>Service Outages</span>
                        <span style='color: orange; font-weight: bold;'>{e_outages:,}</span>
                    </div>
                </div>
                <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                    <div style='display: flex; justify-content: space-between;'>
                        <span style='color: #888;'>Service Outage Minutes</span>
                        <span style='color: orange; font-weight: bold;'>{e_outage_mins:,.0f}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            if ericsson_cm is not None and ericsson_cm.get('TOTAL_CUSTOMER_MINUTES') is not None:
                e_cm = float(ericsson_cm['TOTAL_CUSTOMER_MINUTES'] or 0)
                e_subs = int(ericsson_cm['TOTAL_IMPACTED_SUBS'] or 0)
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                    <div style='display: flex; justify-content: space-between;'>
                        <span style='color: #888;'>Customer Minutes</span>
                        <span style='color: #e20074; font-weight: bold;'>{e_cm:,.0f}</span>
                    </div>
                </div>
                <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                    <div style='display: flex; justify-content: space-between;'>
                        <span style='color: #888;'>Impacted Subs</span>
                        <span style='color: #e20074; font-weight: bold;'>{e_subs:,}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
        <div style='background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); padding: 15px; border-radius: 10px; border-left: 4px solid #ff6600;'>
            <h3 style='color: #ff6600; margin: 0;'>📙 Nokia</h3>
        </div>
        """, unsafe_allow_html=True)
        
        if nokia_avail is None:
            # Show message when market has no Nokia sites
            market_selection = filters.get('market') if filters else None
            if market_selection:
                st.info(f"ℹ️ Market has 0 sites that are Nokia")
            else:
                st.info("ℹ️ No Nokia data available")
        elif nokia_avail is not None:
            n_sites = int(nokia_avail['SITE_COUNT'])
            n_avail = nokia_avail['AVAILABILITY_PCT']
            n_unavail = nokia_avail['UNAVAILABILITY_PCT']
            n_downtime = nokia_avail['TOTAL_DOWNTIME']
            n_budget = nokia_avail['SECONDS_BUDGET']
            n_over = nokia_avail['OVER_UNDER_BUDGET']
            
            n_status = "✅" if n_avail >= AVAILABILITY_GOAL else "❌"
            n_budget_status = "🟢 Under" if n_over <= 0 else "🔴 Over"
            
            st.markdown(f"""
            <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                <div style='display: flex; justify-content: space-between;'>
                    <span style='color: #888;'>Site Count</span>
                    <span style='color: white; font-weight: bold;'>{n_sites:,}</span>
                </div>
            </div>
            <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                <div style='display: flex; justify-content: space-between;'>
                    <span style='color: #888;'>Availability</span>
                    <span style='color: {"#00ff00" if n_avail >= AVAILABILITY_GOAL else "#ff4444"}; font-weight: bold;'>{n_status} {n_avail:.2f}%</span>
                </div>
            </div>
            <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                <div style='display: flex; justify-content: space-between;'>
                    <span style='color: #888;'>Unavailability</span>
                    <span style='color: #e20074; font-weight: bold;'>{n_unavail:.2f}%</span>
                </div>
            </div>
            <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                <div style='display: flex; justify-content: space-between;'>
                    <span style='color: #888;'>Total Downtime</span>
                    <span style='color: white; font-weight: bold;'>{n_downtime/1_000_000:,.1f}M sec</span>
                </div>
            </div>
            <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                <div style='display: flex; justify-content: space-between;'>
                    <span style='color: #888;'>Budget (0.15%)</span>
                    <span style='color: white;'>{n_budget/1_000_000:,.1f}M sec</span>
                </div>
            </div>
            <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                <div style='display: flex; justify-content: space-between;'>
                    <span style='color: #888;'>Over/Under Budget</span>
                    <span style='color: {"#00ff00" if n_over <= 0 else "#ff4444"}; font-weight: bold;'>{n_budget_status} {abs(n_over)/1_000_000:,.1f}M sec</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if nokia_cottr is not None and nokia_cottr.get('OUTAGE_COUNT') is not None:
                n_outages = int(nokia_cottr['OUTAGE_COUNT'] or 0)
                n_outage_mins = float(nokia_cottr['TOTAL_OUTAGE_MINUTES'] or 0)
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                    <div style='display: flex; justify-content: space-between;'>
                        <span style='color: #888;'>Service Outages</span>
                        <span style='color: orange; font-weight: bold;'>{n_outages:,}</span>
                    </div>
                </div>
                <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                    <div style='display: flex; justify-content: space-between;'>
                        <span style='color: #888;'>Service Outage Minutes</span>
                        <span style='color: orange; font-weight: bold;'>{n_outage_mins:,.0f}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            if nokia_cm is not None and nokia_cm.get('TOTAL_CUSTOMER_MINUTES') is not None:
                n_cm = float(nokia_cm['TOTAL_CUSTOMER_MINUTES'] or 0)
                n_subs = int(nokia_cm['TOTAL_IMPACTED_SUBS'] or 0)
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                    <div style='display: flex; justify-content: space-between;'>
                        <span style='color: #888;'>Customer Minutes</span>
                        <span style='color: #e20074; font-weight: bold;'>{n_cm:,.0f}</span>
                    </div>
                </div>
                <div style='background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0;'>
                    <div style='display: flex; justify-content: space-between;'>
                        <span style='color: #888;'>Impacted Subs</span>
                        <span style='color: #e20074; font-weight: bold;'>{n_subs:,}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
    
    st.divider()
    
    # ===== ROW 2: PER-SITE NORMALIZED METRICS =====
    st.markdown("### 📈 Per-Site Normalized Metrics")
    
    # Check which OEMs have data
    has_ericsson = ericsson_avail is not None
    has_nokia = nokia_avail is not None
    
    if has_ericsson and has_nokia:
        # Both OEMs have data - show comparison tiles
        e_total_sites = int(ericsson_avail['SITE_COUNT'])
        n_total_sites = int(nokia_avail['SITE_COUNT'])
        
        # COTTR site counts (sites with outages)
        e_cottr_sites = int(ericsson_cottr['SITE_COUNT'] or 0) if ericsson_cottr is not None and ericsson_cottr.get('SITE_COUNT') is not None else 0
        n_cottr_sites = int(nokia_cottr['SITE_COUNT'] or 0) if nokia_cottr is not None and nokia_cottr.get('SITE_COUNT') is not None else 0
        
        # CM site counts (sites with customer impact)
        e_cm_sites = int(ericsson_cm['SITE_COUNT'] or 0) if ericsson_cm is not None and ericsson_cm.get('SITE_COUNT') is not None else 0
        n_cm_sites = int(nokia_cm['SITE_COUNT'] or 0) if nokia_cm is not None and nokia_cm.get('SITE_COUNT') is not None else 0
        
        # ===== ROW 2A: Per Impacted Site (using source-specific site counts) =====
        st.markdown("<span style='color:#888;font-size:0.85rem;'>**Per Impacted Site** - Divided by sites with incidents (COTTR/CM site counts)</span>", unsafe_allow_html=True)
        
        norm_col0, norm_col1, norm_col2, norm_col3 = st.columns(4)
        
        # Availability % comparison tile
        with norm_col0:
            e_avail_pct = float(ericsson_avail['AVAILABILITY_PCT'] or 0) if ericsson_avail is not None and ericsson_avail.get('AVAILABILITY_PCT') is not None else 0
            n_avail_pct = float(nokia_avail['AVAILABILITY_PCT'] or 0) if nokia_avail is not None and nokia_avail.get('AVAILABILITY_PCT') is not None else 0
            better = "Ericsson" if e_avail_pct > n_avail_pct else "Nokia"
            st.markdown(f"""
            <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
                <div style='color: #888; font-size: 0.8rem;'>Availability %</div>
                <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                    <div>
                        <div style='color: #0066cc; font-size: 1.2rem; font-weight: bold;'>{e_avail_pct:.2f}%</div>
                        <div style='color: #888; font-size: 0.7rem;'>Ericsson</div>
                    </div>
                    <div>
                        <div style='color: #ff6600; font-size: 1.2rem; font-weight: bold;'>{n_avail_pct:.2f}%</div>
                        <div style='color: #888; font-size: 0.7rem;'>Nokia</div>
                    </div>
                </div>
                <div style='color: #00ff00; font-size: 0.75rem; margin-top: 5px;'>🏆 {better} better</div>
            </div>
            """, unsafe_allow_html=True)
        
        # Outage minutes per impacted site
        if ericsson_cottr is not None and nokia_cottr is not None and e_cottr_sites > 0 and n_cottr_sites > 0:
            e_outage_per_impacted = float(ericsson_cottr['TOTAL_OUTAGE_MINUTES'] or 0) / e_cottr_sites
            n_outage_per_impacted = float(nokia_cottr['TOTAL_OUTAGE_MINUTES'] or 0) / n_cottr_sites
            
            with norm_col1:
                better = "Ericsson" if e_outage_per_impacted < n_outage_per_impacted else "Nokia"
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
                    <div style='color: #888; font-size: 0.8rem;'>Outage Mins/Impacted Site</div>
                    <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                        <div>
                            <div style='color: #0066cc; font-size: 1.2rem; font-weight: bold;'>{e_outage_per_impacted:,.1f}</div>
                            <div style='color: #888; font-size: 0.7rem;'>Ericsson</div>
                        </div>
                        <div>
                            <div style='color: #ff6600; font-size: 1.2rem; font-weight: bold;'>{n_outage_per_impacted:,.1f}</div>
                            <div style='color: #888; font-size: 0.7rem;'>Nokia</div>
                        </div>
                    </div>
                    <div style='color: #00ff00; font-size: 0.75rem; margin-top: 5px;'>🏆 {better} better</div>
                </div>
                """, unsafe_allow_html=True)
        
        # Customer minutes per impacted site
        if ericsson_cm is not None and nokia_cm is not None and e_cm_sites > 0 and n_cm_sites > 0:
            e_cm_per_impacted = float(ericsson_cm['TOTAL_CUSTOMER_MINUTES'] or 0) / e_cm_sites
            n_cm_per_impacted = float(nokia_cm['TOTAL_CUSTOMER_MINUTES'] or 0) / n_cm_sites
            
            with norm_col2:
                better = "Ericsson" if e_cm_per_impacted < n_cm_per_impacted else "Nokia"
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
                    <div style='color: #888; font-size: 0.8rem;'>Customer Mins/Impacted Site</div>
                    <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                        <div>
                            <div style='color: #0066cc; font-size: 1.2rem; font-weight: bold;'>{e_cm_per_impacted:,.1f}</div>
                            <div style='color: #888; font-size: 0.7rem;'>Ericsson</div>
                        </div>
                        <div>
                            <div style='color: #ff6600; font-size: 1.2rem; font-weight: bold;'>{n_cm_per_impacted:,.1f}</div>
                            <div style='color: #888; font-size: 0.7rem;'>Nokia</div>
                        </div>
                    </div>
                    <div style='color: #00ff00; font-size: 0.75rem; margin-top: 5px;'>🏆 {better} better</div>
                </div>
                """, unsafe_allow_html=True)
            
            # Impacted subs per impacted site
            e_subs_per_impacted = float(ericsson_cm['TOTAL_IMPACTED_SUBS'] or 0) / e_cm_sites
            n_subs_per_impacted = float(nokia_cm['TOTAL_IMPACTED_SUBS'] or 0) / n_cm_sites
            
            with norm_col3:
                better = "Ericsson" if e_subs_per_impacted < n_subs_per_impacted else "Nokia"
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
                    <div style='color: #888; font-size: 0.8rem;'>Impacted Subs/Impacted Site</div>
                    <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                        <div>
                            <div style='color: #0066cc; font-size: 1.2rem; font-weight: bold;'>{e_subs_per_impacted:,.1f}</div>
                            <div style='color: #888; font-size: 0.7rem;'>Ericsson</div>
                        </div>
                        <div>
                            <div style='color: #ff6600; font-size: 1.2rem; font-weight: bold;'>{n_subs_per_impacted:,.1f}</div>
                            <div style='color: #888; font-size: 0.7rem;'>Nokia</div>
                        </div>
                    </div>
                    <div style='color: #00ff00; font-size: 0.75rem; margin-top: 5px;'>🏆 {better} better</div>
                </div>
                """, unsafe_allow_html=True)
        
        # ===== ROW 2B: Per Total Site (using Availability site counts) =====
        st.markdown("<span style='color:#888;font-size:0.85rem;margin-top:15px;display:block;'>**Per Total Site** - Divided by all sites (Availability site counts)</span>", unsafe_allow_html=True)
        
        norm_col3b, norm_col4, norm_col5, norm_col6 = st.columns(4)
        
        # Downtime Seconds per Total Site
        with norm_col3b:
            e_downtime = float(ericsson_avail['TOTAL_DOWNTIME'] or 0) if ericsson_avail is not None else 0
            n_downtime = float(nokia_avail['TOTAL_DOWNTIME'] or 0) if nokia_avail is not None else 0
            e_downtime_per_site = e_downtime / e_total_sites if e_total_sites > 0 else 0
            n_downtime_per_site = n_downtime / n_total_sites if n_total_sites > 0 else 0
            better = "Ericsson" if e_downtime_per_site < n_downtime_per_site else "Nokia"
            st.markdown(f"""
            <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
                <div style='color: #888; font-size: 0.8rem;'>Downtime Secs/Total Site</div>
                <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                    <div>
                        <div style='color: #0066cc; font-size: 1.2rem; font-weight: bold;'>{e_downtime_per_site:,.1f}</div>
                        <div style='color: #888; font-size: 0.7rem;'>Ericsson</div>
                    </div>
                    <div>
                        <div style='color: #ff6600; font-size: 1.2rem; font-weight: bold;'>{n_downtime_per_site:,.1f}</div>
                        <div style='color: #888; font-size: 0.7rem;'>Nokia</div>
                    </div>
                </div>
                <div style='color: #00ff00; font-size: 0.75rem; margin-top: 5px;'>🏆 {better} better</div>
            </div>
            """, unsafe_allow_html=True)
        
        # Outage minutes per total site
        if ericsson_cottr is not None and nokia_cottr is not None:
            e_outage_per_total = float(ericsson_cottr['TOTAL_OUTAGE_MINUTES'] or 0) / e_total_sites if e_total_sites > 0 else 0
            n_outage_per_total = float(nokia_cottr['TOTAL_OUTAGE_MINUTES'] or 0) / n_total_sites if n_total_sites > 0 else 0
            
            with norm_col4:
                better = "Ericsson" if e_outage_per_total < n_outage_per_total else "Nokia"
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
                    <div style='color: #888; font-size: 0.8rem;'>Outage Mins/Total Site</div>
                    <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                        <div>
                            <div style='color: #0066cc; font-size: 1.2rem; font-weight: bold;'>{e_outage_per_total:,.2f}</div>
                            <div style='color: #888; font-size: 0.7rem;'>Ericsson</div>
                        </div>
                        <div>
                            <div style='color: #ff6600; font-size: 1.2rem; font-weight: bold;'>{n_outage_per_total:,.2f}</div>
                            <div style='color: #888; font-size: 0.7rem;'>Nokia</div>
                        </div>
                    </div>
                    <div style='color: #00ff00; font-size: 0.75rem; margin-top: 5px;'>🏆 {better} better</div>
                </div>
                """, unsafe_allow_html=True)
        
        # Customer minutes per total site
        if ericsson_cm is not None and nokia_cm is not None:
            e_cm_per_total = float(ericsson_cm['TOTAL_CUSTOMER_MINUTES'] or 0) / e_total_sites if e_total_sites > 0 else 0
            n_cm_per_total = float(nokia_cm['TOTAL_CUSTOMER_MINUTES'] or 0) / n_total_sites if n_total_sites > 0 else 0
            
            with norm_col5:
                better = "Ericsson" if e_cm_per_total < n_cm_per_total else "Nokia"
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
                    <div style='color: #888; font-size: 0.8rem;'>Customer Mins/Total Site</div>
                    <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                        <div>
                            <div style='color: #0066cc; font-size: 1.2rem; font-weight: bold;'>{e_cm_per_total:,.2f}</div>
                            <div style='color: #888; font-size: 0.7rem;'>Ericsson</div>
                        </div>
                        <div>
                            <div style='color: #ff6600; font-size: 1.2rem; font-weight: bold;'>{n_cm_per_total:,.2f}</div>
                            <div style='color: #888; font-size: 0.7rem;'>Nokia</div>
                        </div>
                    </div>
                    <div style='color: #00ff00; font-size: 0.75rem; margin-top: 5px;'>🏆 {better} better</div>
                </div>
                """, unsafe_allow_html=True)
            
            # Impacted subs per total site
            e_subs_per_total = float(ericsson_cm['TOTAL_IMPACTED_SUBS'] or 0) / e_total_sites if e_total_sites > 0 else 0
            n_subs_per_total = float(nokia_cm['TOTAL_IMPACTED_SUBS'] or 0) / n_total_sites if n_total_sites > 0 else 0
            
            with norm_col6:
                better = "Ericsson" if e_subs_per_total < n_subs_per_total else "Nokia"
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center;'>
                    <div style='color: #888; font-size: 0.8rem;'>Impacted Subs/Total Site</div>
                    <div style='display: flex; justify-content: space-around; margin-top: 10px;'>
                        <div>
                            <div style='color: #0066cc; font-size: 1.2rem; font-weight: bold;'>{e_subs_per_total:,.2f}</div>
                            <div style='color: #888; font-size: 0.7rem;'>Ericsson</div>
                        </div>
                        <div>
                            <div style='color: #ff6600; font-size: 1.2rem; font-weight: bold;'>{n_subs_per_total:,.2f}</div>
                            <div style='color: #888; font-size: 0.7rem;'>Nokia</div>
                        </div>
                    </div>
                    <div style='color: #00ff00; font-size: 0.75rem; margin-top: 5px;'>🏆 {better} better</div>
                </div>
                """, unsafe_allow_html=True)
    elif has_ericsson or has_nokia:
        # Only one OEM has data - show single-OEM metrics with /impacted and /total
        oem_name = "Ericsson" if has_ericsson else "Nokia"
        oem_color = "#0066cc" if has_ericsson else "#ff6600"
        oem_avail = ericsson_avail if has_ericsson else nokia_avail
        oem_cottr = ericsson_cottr if has_ericsson else nokia_cottr
        oem_cm = ericsson_cm if has_ericsson else nokia_cm
        
        total_sites = int(oem_avail['SITE_COUNT'])  # Total sites for this OEM
        cottr_sites = int(oem_cottr['SITE_COUNT']) if oem_cottr is not None else 0
        cm_sites = int(oem_cm['SITE_COUNT']) if oem_cm is not None else 0
        
        missing_oem = "Nokia" if has_ericsson else "Ericsson"
        market_selection = filters.get('market') if filters else None
        market_label = get_market_display_name(market_selection) if market_selection else "National"
        st.info(f"ℹ️ Market has 0 sites that are {missing_oem} - showing {oem_name} metrics only")
        
        st.markdown(f"<span style='color:#888;font-size:0.85rem;'>**{oem_name} Metrics** | Total Sites: {total_sites:,} ({market_label})</span>", unsafe_allow_html=True)
        
        single_col1, single_col2, single_col3 = st.columns(3)
        
        with single_col1:
            avail_pct = float(oem_avail['AVAILABILITY_PCT'])
            downtime = float(oem_avail['TOTAL_DOWNTIME'])
            downtime_per_total = downtime / total_sites if total_sites > 0 else 0
            st.markdown(f"""
            <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; border-left: 4px solid {oem_color};'>
                <div style='color: #888; font-size: 0.85rem; text-align: center;'>Availability & Downtime</div>
                <div style='text-align: center; margin-top: 10px;'>
                    <div style='color: {oem_color}; font-size: 1.5rem; font-weight: bold;'>{avail_pct:.2f}%</div>
                    <div style='color: #888; font-size: 0.75rem;'>Availability</div>
                </div>
                <div style='margin-top: 12px; border-top: 1px solid #333; padding-top: 10px;'>
                    <div style='display: flex; justify-content: space-between; align-items: center;'>
                        <span style='color: #aaa; font-size: 0.85rem;'>Downtime/Total Site:</span>
                        <span style='color: #00ff00; font-size: 1.2rem; font-weight: bold;'>{downtime_per_total:,.1f} sec</span>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        with single_col2:
            if oem_cottr is not None and cottr_sites > 0:
                outage_mins = float(oem_cottr['TOTAL_OUTAGE_MINUTES'])
                outage_per_impacted = outage_mins / cottr_sites
                outage_per_total = outage_mins / total_sites if total_sites > 0 else 0
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; border-left: 4px solid {oem_color};'>
                    <div style='color: #888; font-size: 0.85rem; text-align: center;'>Outage Minutes</div>
                    <div style='margin-top: 12px;'>
                        <div style='display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid #333;'>
                            <span style='color: #aaa; font-size: 0.85rem;'>/Impacted Sites ({cottr_sites:,}):</span>
                            <span style='color: {oem_color}; font-size: 1.2rem; font-weight: bold;'>{outage_per_impacted:,.1f}</span>
                        </div>
                        <div style='display: flex; justify-content: space-between; align-items: center; padding: 8px 0;'>
                            <span style='color: #aaa; font-size: 0.85rem;'>/Total Sites ({total_sites:,}):</span>
                            <span style='color: #00ff00; font-size: 1.2rem; font-weight: bold;'>{outage_per_total:,.2f}</span>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center; border-left: 4px solid #555;'>
                    <div style='color: #888; font-size: 0.85rem;'>Outage Minutes</div>
                    <div style='color: #888; font-size: 1rem; margin-top: 10px;'>No data</div>
                </div>
                """, unsafe_allow_html=True)
        
        with single_col3:
            if oem_cm is not None and cm_sites > 0:
                cm_total = float(oem_cm['TOTAL_CUSTOMER_MINUTES'])
                cm_per_impacted = cm_total / cm_sites
                cm_per_total = cm_total / total_sites if total_sites > 0 else 0
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; border-left: 4px solid {oem_color};'>
                    <div style='color: #888; font-size: 0.85rem; text-align: center;'>Customer Minutes</div>
                    <div style='margin-top: 12px;'>
                        <div style='display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid #333;'>
                            <span style='color: #aaa; font-size: 0.85rem;'>/Impacted Sites ({cm_sites:,}):</span>
                            <span style='color: {oem_color}; font-size: 1.2rem; font-weight: bold;'>{cm_per_impacted:,.1f}</span>
                        </div>
                        <div style='display: flex; justify-content: space-between; align-items: center; padding: 8px 0;'>
                            <span style='color: #aaa; font-size: 0.85rem;'>/Total Sites ({total_sites:,}):</span>
                            <span style='color: #00ff00; font-size: 1.2rem; font-weight: bold;'>{cm_per_total:,.2f}</span>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 10px; text-align: center; border-left: 4px solid #555;'>
                    <div style='color: #888; font-size: 0.85rem;'>Customer Minutes</div>
                    <div style='color: #888; font-size: 1rem; margin-top: 10px;'>No data</div>
                </div>
                """, unsafe_allow_html=True)
    
    st.divider()
    
    # ===== ROW 3: DAILY TRENDS =====
    st.markdown("### 📉 Daily Trends Comparison")
    
    trend_col1, trend_col2 = st.columns(2)
    
    with trend_col1:
        if not avail_daily.empty:
            st.markdown("##### Availability % Trend")
            fig_avail_trend = go.Figure()
            
            for oem in ['Ericsson', 'Nokia']:
                oem_data = avail_daily[avail_daily['OEM'] == oem]
                if not oem_data.empty:
                    color = '#e20074' if oem == 'Ericsson' else '#b8005c'
                    fig_avail_trend.add_trace(go.Scatter(
                        x=oem_data['DATE_VALUE'],
                        y=oem_data['AVAILABILITY_PCT'],
                        name=oem,
                        line=dict(color=color, width=2),
                        mode='lines+markers'
                    ))
            
            fig_avail_trend.add_hline(y=AVAILABILITY_GOAL, line_dash="dash", line_color="#e20074", 
                                      annotation_text=f"Goal: {AVAILABILITY_GOAL}%")
            fig_avail_trend.update_layout(
                template='plotly_white',
                height=300,
                margin=dict(l=50, r=20, t=30, b=50),
                legend=dict(orientation='h', yanchor='bottom', y=1.02),
                yaxis=dict(title='Availability %', tickformat='.2f')
            )
            st.plotly_chart(fig_avail_trend, use_container_width=True, config=CHART_CONFIG, key="oem_avail_trend")
    
    with trend_col2:
        if not avail_daily.empty:
            st.markdown("##### Unavailability % Trend")
            fig_unavail_trend = go.Figure()
            
            for oem in ['Ericsson', 'Nokia']:
                oem_data = avail_daily[avail_daily['OEM'] == oem]
                if not oem_data.empty:
                    color = '#e20074' if oem == 'Ericsson' else '#b8005c'
                    fig_unavail_trend.add_trace(go.Scatter(
                        x=oem_data['DATE_VALUE'],
                        y=oem_data['UNAVAILABILITY_PCT'],
                        name=oem,
                        line=dict(color=color, width=2),
                        mode='lines+markers'
                    ))
            
            fig_unavail_trend.add_hline(y=0.15, line_dash="dash", line_color="#e20074", 
                                        annotation_text="Budget: 0.15%")
            fig_unavail_trend.update_layout(
                template='plotly_white',
                height=300,
                margin=dict(l=50, r=20, t=30, b=50),
                legend=dict(orientation='h', yanchor='bottom', y=1.02),
                yaxis=dict(title='Unavailability %', tickformat='.4f')
            )
            st.plotly_chart(fig_unavail_trend, use_container_width=True, config=CHART_CONFIG, key="oem_unavail_trend")
    
    trend_col3, trend_col4 = st.columns(2)
    
    with trend_col3:
        if not cottr_daily.empty:
            st.markdown("##### Service Outage Minutes Trend")
            fig_cottr_trend = go.Figure()
            
            for oem in ['Ericsson', 'Nokia']:
                oem_data = cottr_daily[cottr_daily['OEM'] == oem]
                if not oem_data.empty:
                    color = '#e20074' if oem == 'Ericsson' else '#b8005c'
                    fig_cottr_trend.add_trace(go.Scatter(
                        x=oem_data['DATE_VALUE'],
                        y=oem_data['TOTAL_OUTAGE_MINUTES'],
                        name=oem,
                        line=dict(color=color, width=2),
                        mode='lines+markers'
                    ))
            
            fig_cottr_trend.update_layout(
                template='plotly_white',
                height=300,
                margin=dict(l=50, r=20, t=30, b=50),
                legend=dict(orientation='h', yanchor='bottom', y=1.02),
                yaxis=dict(title='Service Outage Minutes')
            )
            st.plotly_chart(fig_cottr_trend, use_container_width=True, config=CHART_CONFIG, key="oem_cottr_trend")
    
    with trend_col4:
        if not cm_daily.empty:
            st.markdown("##### Customer Minutes Trend")
            fig_cm_trend = go.Figure()
            
            for oem in ['Ericsson', 'Nokia']:
                oem_data = cm_daily[cm_daily['OEM'] == oem]
                if not oem_data.empty:
                    color = '#e20074' if oem == 'Ericsson' else '#b8005c'
                    fig_cm_trend.add_trace(go.Scatter(
                        x=oem_data['DATE_VALUE'],
                        y=oem_data['TOTAL_CUSTOMER_MINUTES'],
                        name=oem,
                        line=dict(color=color, width=2),
                        mode='lines+markers'
                    ))
            
            fig_cm_trend.update_layout(
                template='plotly_white',
                height=300,
                margin=dict(l=50, r=20, t=30, b=50),
                legend=dict(orientation='h', yanchor='bottom', y=1.02),
                yaxis=dict(title='Customer Minutes')
            )
            st.plotly_chart(fig_cm_trend, use_container_width=True, config=CHART_CONFIG, key="oem_cm_trend")
    
    st.divider()
    
    # ===== ROW 4: BAR CHART COMPARISONS =====
    st.markdown("### 📊 Side-by-Side Comparisons")
    
    bar_col1, bar_col2 = st.columns(2)
    
    with bar_col1:
        # Total metrics comparison bar chart
        if not avail_oem.empty:
            st.markdown("##### Total Downtime by OEM")
            fig_downtime = go.Figure()
            fig_downtime.add_trace(go.Bar(
                x=avail_oem['OEM'],
                y=avail_oem['TOTAL_DOWNTIME'],
                marker_color=['#e20074', '#b8005c'],
                text=[f"{x:,.0f}" for x in avail_oem['TOTAL_DOWNTIME']],
                textposition='outside'
            ))
            fig_downtime.update_layout(
                template='plotly_white',
                height=300,
                margin=dict(l=50, r=20, t=30, b=50),
                yaxis=dict(title='Downtime (seconds)')
            )
            st.plotly_chart(fig_downtime, use_container_width=True, config=CHART_CONFIG, key="oem_downtime_bar")
    
    with bar_col2:
        # Budget comparison
        if not avail_oem.empty:
            st.markdown("##### Budget vs Actual Downtime")
            fig_budget = go.Figure()
            
            fig_budget.add_trace(go.Bar(
                name='Actual Downtime',
                x=avail_oem['OEM'],
                y=avail_oem['TOTAL_DOWNTIME'],
                marker_color=['#e20074', '#b8005c']
            ))
            fig_budget.add_trace(go.Bar(
                name='Budget (0.15%)',
                x=avail_oem['OEM'],
                y=avail_oem['SECONDS_BUDGET'],
                marker_color=['rgba(226,0,116,0.3)', 'rgba(184,0,92,0.3)']
            ))
            
            fig_budget.update_layout(
                template='plotly_white',
                height=300,
                barmode='group',
                margin=dict(l=50, r=20, t=30, b=50),
                yaxis=dict(title='Seconds'),
                legend=dict(orientation='h', yanchor='bottom', y=1.02)
            )
            st.plotly_chart(fig_budget, use_container_width=True, config=CHART_CONFIG, key="oem_budget_bar")
    
    st.divider()
    
    # ===== ROW 5: FOCUS CATEGORY BREAKDOWN =====
    st.markdown("### 🎯 Downtime by Focus Category")
    
    if not focus_oem.empty:
        focus_col1, focus_col2 = st.columns(2)
        
        with focus_col1:
            ericsson_focus = focus_oem[focus_oem['OEM'] == 'Ericsson'].head(10)
            st.markdown("##### Ericsson - Top Focus Categories")
            if not ericsson_focus.empty:
                fig_e_focus = go.Figure()
                fig_e_focus.add_trace(go.Bar(
                    y=ericsson_focus['FOCUS_CATEGORY'],
                    x=ericsson_focus['TOTAL_DOWNTIME'],
                    orientation='h',
                    marker_color='#e20074',
                    text=[f"{x:,.0f}" for x in ericsson_focus['TOTAL_DOWNTIME']],
                    textposition='outside'
                ))
                fig_e_focus.update_layout(
                    template='plotly_white',
                    height=400,
                    margin=dict(l=150, r=50, t=30, b=50),
                    xaxis=dict(title='Downtime (seconds)'),
                    yaxis=dict(autorange='reversed')
                )
                st.plotly_chart(fig_e_focus, use_container_width=True, config=CHART_CONFIG, key="oem_e_focus")
            else:
                st.info("ℹ️ Market has 0 sites that are Ericsson")
        
        with focus_col2:
            nokia_focus = focus_oem[focus_oem['OEM'] == 'Nokia'].head(10)
            st.markdown("##### Nokia - Top Focus Categories")
            if not nokia_focus.empty:
                fig_n_focus = go.Figure()
                fig_n_focus.add_trace(go.Bar(
                    y=nokia_focus['FOCUS_CATEGORY'],
                    x=nokia_focus['TOTAL_DOWNTIME'],
                    orientation='h',
                    marker_color='#b8005c',
                    text=[f"{x:,.0f}" for x in nokia_focus['TOTAL_DOWNTIME']],
                    textposition='outside'
                ))
                fig_n_focus.update_layout(
                    template='plotly_white',
                    height=400,
                    margin=dict(l=150, r=50, t=30, b=50),
                    xaxis=dict(title='Downtime (seconds)'),
                    yaxis=dict(autorange='reversed')
                )
                st.plotly_chart(fig_n_focus, use_container_width=True, config=CHART_CONFIG, key="oem_n_focus")
            else:
                st.info("ℹ️ Market has 0 sites that are Nokia")
    
    st.divider()
    
    # ===== ROW 6: TOP MARKETS BY OEM =====
    st.markdown("### 🏆 Top Degraded Markets by OEM")
    
    if not avail_market.empty:
        mkt_col1, mkt_col2 = st.columns(2)
        
        with mkt_col1:
            ericsson_mkts = avail_market[avail_market['OEM'] == 'Ericsson'].nlargest(10, 'TOTAL_DOWNTIME')
            st.markdown("##### Ericsson - Top 10 Markets by Downtime")
            if not ericsson_mkts.empty:
                for _, row in ericsson_mkts.iterrows():
                    unavail_pct = float(row['UNAVAILABILITY_PCT'])
                    status = "🔴" if unavail_pct > 0.15 else "🟢"
                    st.markdown(f"""
                    <div style='background: #f8f9fa; padding: 8px 12px; border-radius: 5px; margin: 3px 0; border-left: 3px solid #0066cc;'>
                        <div style='display: flex; justify-content: space-between; align-items: center;'>
                            <span style='color: white; font-weight: bold;'>{row['MARKET_ID']}</span>
                            <span style='color: #e20074;'>{status} {unavail_pct:.4f}%</span>
                        </div>
                        <div style='color: #888; font-size: 0.8rem;'>{float(row['TOTAL_DOWNTIME']):,.0f} sec | {int(row['SITE_COUNT']):,} sites</div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("ℹ️ Market has 0 sites that are Ericsson")
        
        with mkt_col2:
            nokia_mkts = avail_market[avail_market['OEM'] == 'Nokia'].nlargest(10, 'TOTAL_DOWNTIME')
            st.markdown("##### Nokia - Top 10 Markets by Downtime")
            if not nokia_mkts.empty:
                for _, row in nokia_mkts.iterrows():
                    unavail_pct = float(row['UNAVAILABILITY_PCT'])
                    status = "🔴" if unavail_pct > 0.15 else "🟢"
                    st.markdown(f"""
                    <div style='background: #f8f9fa; padding: 8px 12px; border-radius: 5px; margin: 3px 0; border-left: 3px solid #ff6600;'>
                        <div style='display: flex; justify-content: space-between; align-items: center;'>
                            <span style='color: white; font-weight: bold;'>{row['MARKET_ID']}</span>
                            <span style='color: #e20074;'>{status} {unavail_pct:.4f}%</span>
                        </div>
                        <div style='color: #888; font-size: 0.8rem;'>{float(row['TOTAL_DOWNTIME']):,.0f} sec | {int(row['SITE_COUNT']):,} sites</div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("ℹ️ Market has 0 sites that are Nokia")

def hardware_analysis_dashboard(conn, days, filters):
    """Hardware Analysis - Deep dive into Hardware and Hardware - Antenna System categories"""
    st.markdown('<div class="section-header">🔧 Hardware Analysis Dashboard</div>', unsafe_allow_html=True)
    st.markdown("Analysis of Hardware and Hardware - Antenna System focus categories")
    
    # Use global filter dates
    hw_start_date = filters.get('start_date') if filters and filters.get('start_date') else (date.today() - timedelta(days=days))
    hw_end_date = filters.get('end_date') if filters and filters.get('end_date') else date.today()
    market_selection = filters.get('market') if filters else None
    
    # Hardware focus categories - constant
    HARDWARE_CATEGORIES = "'Hardware', 'Hardware - Antenna System'"
    
    # Build filter clauses once (reused throughout) - handle multi-market selection
    if market_selection:
        if isinstance(market_selection, str):
            market_selection_list = [market_selection]
        else:
            market_selection_list = market_selection
        # Get all market IDs for the selection
        all_avail_ids = []
        all_cottr_ids = []
        all_cm_ids = []
        for m in market_selection_list:
            all_avail_ids.extend(get_market_ids_for_filter(m, 'availability'))
            all_cottr_ids.extend(get_market_ids_for_filter(m, 'cottr'))
            all_cm_ids.extend(get_market_ids_for_filter(m, 'customer_minutes'))
        all_avail_ids = list(dict.fromkeys(all_avail_ids))
        all_cottr_ids = list(dict.fromkeys(all_cottr_ids))
        all_cm_ids = list(dict.fromkeys(all_cm_ids))
        
        if len(all_avail_ids) == 1:
            market_filter_avail = f" AND UPPER(MARKET_ID) = '{all_avail_ids[0].upper()}'"
        else:
            avail_list = "', '".join([m.upper() for m in all_avail_ids])
            market_filter_avail = f" AND UPPER(MARKET_ID) IN ('{avail_list}')"
        if len(all_cottr_ids) == 1:
            market_filter_cottr = f" AND UPPER(MKT_NAME) = '{all_cottr_ids[0].upper()}'"
        else:
            cottr_list = "', '".join([m.upper() for m in all_cottr_ids])
            market_filter_cottr = f" AND UPPER(MKT_NAME) IN ('{cottr_list}')"
        if len(all_cm_ids) == 1:
            market_filter_cm = f" AND UPPER(MARKET) = '{all_cm_ids[0].upper()}'"
        else:
            cm_list = "', '".join([m.upper() for m in all_cm_ids])
            market_filter_cm = f" AND UPPER(MARKET) IN ('{cm_list}')"
        # Pass full market selection to cached functions (they handle lists)
        market_param = market_selection_list
    else:
        market_filter_avail = ""
        market_filter_cottr = ""
        market_filter_cm = ""
        market_param = None
    
    # Get site type filter from global filters
    site_type = filters.get('site_type') if filters else 'Macro'
    if site_type == 'Non-Macro':
        site_type_filter_avail = " AND (SITE_TYPE != 'Macro' OR SITE_TYPE IS NULL)"
    elif site_type and site_type != '(All)':
        site_type_filter_avail = f" AND SITE_TYPE = '{site_type}'"
    else:
        site_type_filter_avail = ""
    
    # Get OEM filter for inline queries
    oem_filter = filters.get('oem') if filters else None
    
    # Build site type filter for COTTR (uses SECTOR_TYPE_CATEGORY instead of SITE_TYPE)
    if site_type == 'Non-Macro':
        site_type_filter_cottr = " AND (SECTOR_TYPE_CATEGORY != 'Macro' OR SECTOR_TYPE_CATEGORY IS NULL)"
    elif site_type and site_type != '(All)':
        site_type_filter_cottr = f" AND SECTOR_TYPE_CATEGORY = '{site_type}'"
    else:
        site_type_filter_cottr = ""
    
    # Pre-build all filter clauses
    date_filter = f" AND DATE_VALUE >= '{hw_start_date}' AND DATE_VALUE <= '{hw_end_date}'{market_filter_avail}{site_type_filter_avail}"
    date_filter_cottr = f" AND PER_DAY_LOCAL_DATE >= '{hw_start_date}' AND PER_DAY_LOCAL_DATE <= '{hw_end_date}'{market_filter_cottr}{site_type_filter_cottr} AND SITE_CD NOT LIKE 'USC%'"
    cm_filter = f" AND LOCAL_DATE_PART >= '{hw_start_date}' AND LOCAL_DATE_PART <= '{hw_end_date}' AND SITE_ID NOT LIKE 'USC%'{market_filter_cm}"
    
    # Add OEM filter to date_filter for availability queries
    if oem_filter:
        oem_avail_join = f"JOIN {TABLES['market_tracker']} mt ON REPLACE(MARKET_ID, ' ', '') = mt.M_CAPITAL_MARKET"
        oem_avail_where = f" AND mt.M_OEM = '{oem_filter}'"
    else:
        oem_avail_join = ""
        oem_avail_where = ""
    
    # Add OEM filter to date_filter_cottr for COTTR queries  
    if oem_filter:
        oem_cottr_join = f"JOIN {TABLES['market_tracker']} mt ON UPPER(MKT_NAME) = UPPER(mt.MARKET_ID)"
        oem_cottr_where = f" AND mt.M_OEM = '{oem_filter}'"
    else:
        oem_cottr_join = ""
        oem_cottr_where = ""
    
    # Use local variable for hardware_categories to avoid repeated string creation
    hardware_categories = HARDWARE_CATEGORIES
    
    # OPTIMIZED: Fetch ALL data in parallel at the start
    with st.spinner("Loading Hardware data..."):
        # Define all queries to run in parallel
        def fetch_avail_kpi():
            return get_hardware_availability_kpi(conn, hw_start_date, hw_end_date, market_param, oem_filter, site_type)
        
        def fetch_cottr_kpi():
            return get_hardware_cottr_kpi(conn, hw_start_date, hw_end_date, market_param, oem_filter)
        
        def fetch_cm_kpi():
            return get_hardware_customer_minutes_kpi(conn, hw_start_date, hw_end_date, market_param, oem_filter)
        
        def fetch_breakdown():
            return get_hardware_category_breakdown(conn, hw_start_date, hw_end_date, market_param, oem_filter, site_type)
        
        def fetch_trend():
            trend_q = f"""
            SELECT DATE_VALUE, SITE_ID_FOCUS_CATEGORY, SUM(TOTAL_DOWNTIME) as DAILY_DOWNTIME, COUNT(DISTINCT SITE_ID) as SITES_AFFECTED
            FROM {TABLES['availability']}
            WHERE SITE_ID_FOCUS_CATEGORY IN ({hardware_categories}) {date_filter}
            GROUP BY DATE_VALUE, SITE_ID_FOCUS_CATEGORY ORDER BY DATE_VALUE
            """
            return run_query(conn, trend_q)
        
        def fetch_top_sites_avail():
            q = f"""
            SELECT SITE_ID, MARKET_ID, SITE_ID_FOCUS_CATEGORY, SITE_ID_DETAIL_CATEGORY, SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME, COUNT(DISTINCT DATE_VALUE) as DAYS_IMPACTED, MAX(DATE_VALUE) as LAST_IMPACT_DATE
            FROM {TABLES['availability']}
            WHERE SITE_ID_FOCUS_CATEGORY IN ({hardware_categories}) {date_filter}
            GROUP BY SITE_ID, MARKET_ID, SITE_ID_FOCUS_CATEGORY, SITE_ID_DETAIL_CATEGORY ORDER BY TOTAL_DOWNTIME DESC LIMIT 100
            """
            return run_query(conn, q)
        
        def fetch_top_sites_cottr():
            q = f"""
            SELECT SITE_CD, MKT_NAME as MARKET_ID, SITE_ID_FOCUS_CATEGORY, SITE_ID_DETAIL_CATEGORY, SUM(PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINS, COUNT(*) as OUTAGE_DAYS, MAX(DATE_VALUE) as LAST_IMPACT_DATE
            FROM {TABLES['cottr']}
            WHERE SITE_ID_FOCUS_CATEGORY IN ({hardware_categories}) AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' {date_filter_cottr}
            GROUP BY SITE_CD, MKT_NAME, SITE_ID_FOCUS_CATEGORY, SITE_ID_DETAIL_CATEGORY ORDER BY TOTAL_OUTAGE_MINS DESC LIMIT 100
            """
            return run_query(conn, q)
        
        def fetch_cottr_breakdown():
            q = f"""
            SELECT SITE_ID_FOCUS_CATEGORY, SUM(PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINS, COUNT(DISTINCT SITE_CD) as SITE_COUNT, COUNT(*) as OUTAGE_DAYS
            FROM {TABLES['cottr']}
            WHERE SITE_ID_FOCUS_CATEGORY IN ({hardware_categories}) AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' AND SITE_CD NOT LIKE 'USC%' {date_filter_cottr}
            GROUP BY SITE_ID_FOCUS_CATEGORY ORDER BY TOTAL_OUTAGE_MINS DESC
            """
            return run_query(conn, q)
        
        def fetch_market_avail():
            q = f"""
            SELECT MARKET_ID, SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME, COUNT(DISTINCT SITE_ID) as SITE_COUNT
            FROM {TABLES['availability']}
            WHERE SITE_ID_FOCUS_CATEGORY IN ({hardware_categories}) {date_filter}
            GROUP BY MARKET_ID ORDER BY TOTAL_DOWNTIME DESC LIMIT 15
            """
            return run_query(conn, q)
        
        def fetch_market_cottr():
            q = f"""
            SELECT MKT_NAME as MARKET_ID, SUM(PER_DAY_OUTAGE_MINUTES) as TOTAL_OUTAGE_MINS, COUNT(DISTINCT SITE_CD) as SITE_COUNT
            FROM {TABLES['cottr']}
            WHERE SITE_ID_FOCUS_CATEGORY IN ({hardware_categories}) AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE' {date_filter_cottr}
            GROUP BY MKT_NAME ORDER BY TOTAL_OUTAGE_MINS DESC LIMIT 15
            """
            return run_query(conn, q)
        
        def fetch_oem():
            q = f"""
            SELECT VENDOR as OEM, SITE_ID_FOCUS_CATEGORY, SUM(TOTAL_DOWNTIME) as TOTAL_DOWNTIME, COUNT(DISTINCT SITE_ID) as SITE_COUNT
            FROM {TABLES['availability']}
            WHERE SITE_ID_FOCUS_CATEGORY IN ({hardware_categories}) AND VENDOR IS NOT NULL {date_filter}
            GROUP BY VENDOR, SITE_ID_FOCUS_CATEGORY ORDER BY TOTAL_DOWNTIME DESC
            """
            return run_query(conn, q)
        
        def fetch_overall_nd():
            q = f"""
            SELECT SUM(TOTAL_DOWNTIME) as ALL_DOWNTIME, SUM(TOTAL_AVAILABILITY_N) as ALL_N, SUM(TOTAL_AVAILABILITY_D) as ALL_D
            FROM {TABLES['availability']}
            WHERE DATE_VALUE >= '{hw_start_date}' AND DATE_VALUE <= '{hw_end_date}'{market_filter_avail}{site_type_filter_avail}
            """
            return run_query(conn, q)
        
        def fetch_spares_data():
            return get_hardware_spares_data(conn, hw_start_date, hw_end_date, market_selection, site_type)
        
        def fetch_cottr_spares_data():
            return get_hardware_spares_cottr_data(conn, hw_start_date, hw_end_date, market_selection, site_type)
        
        # Run all queries in parallel with reduced workers for stability
        results = {}
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(fetch_avail_kpi): 'avail_data',
                executor.submit(fetch_cottr_kpi): 'cottr_data',
                executor.submit(fetch_cm_kpi): 'cm_data',
                executor.submit(fetch_breakdown): 'breakdown_df',
                executor.submit(fetch_trend): 'trend_df',
                executor.submit(fetch_top_sites_avail): 'sites_avail',
                executor.submit(fetch_top_sites_cottr): 'sites_cottr',
                executor.submit(fetch_cottr_breakdown): 'cottr_breakdown',
                executor.submit(fetch_market_avail): 'market_avail',
                executor.submit(fetch_market_cottr): 'market_cottr',
                executor.submit(fetch_oem): 'oem_df',
                executor.submit(fetch_overall_nd): 'overall_nd',
                executor.submit(fetch_spares_data): 'spares_data',
                executor.submit(fetch_cottr_spares_data): 'cottr_spares_data',
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception:
                    results[key] = pd.DataFrame()
        
        avail_data = results.get('avail_data', pd.DataFrame())
        cottr_data = results.get('cottr_data', pd.DataFrame())
        cm_data = results.get('cm_data', pd.DataFrame())
        breakdown_df = results.get('breakdown_df', pd.DataFrame())
        trend_df = results.get('trend_df', pd.DataFrame())
        sites_avail = results.get('sites_avail', pd.DataFrame())
        sites_cottr = results.get('sites_cottr', pd.DataFrame())
        cottr_breakdown = results.get('cottr_breakdown', pd.DataFrame())
        market_avail = results.get('market_avail', pd.DataFrame())
        market_cottr = results.get('market_cottr', pd.DataFrame())
        oem_df = results.get('oem_df', pd.DataFrame())
        overall_nd = results.get('overall_nd', pd.DataFrame())
        spares_data_for_skus = results.get('spares_data', pd.DataFrame())
        cottr_spares_data_cached = results.get('cottr_spares_data', pd.DataFrame())
    if not spares_data_for_skus.empty:
        sku_dedup_cols = [c for c in ['TROUBLE TICKET', 'SITE', 'MARKET', 'REF_SKU', 'REF_SKU_DESC',
                          'ORDER STATUS', 'ORDER CREATE DATE', 'FAILURE CODE', 'STAGING_KPI_GROUPS'
                          ] if c in spares_data_for_skus.columns]
        spares_data_for_skus = spares_data_for_skus.drop_duplicates(subset=sku_dedup_cols)
    sites_with_orders = 0
    spares_downtime = 0
    if not spares_data_for_skus.empty and 'SITE' in spares_data_for_skus.columns:
        sites_with_orders = spares_data_for_skus['SITE'].nunique()
        if 'TOTAL_DOWNTIME' in spares_data_for_skus.columns:
            spares_downtime = spares_data_for_skus['TOTAL_DOWNTIME'].sum()
    
    # KPI Section
    st.markdown("### 📊 Hardware KPIs Overview")
    
    kpi_col1, kpi_col2, kpi_col3 = st.columns(3)
    
    # KPI 1: Availability/Downtime
    with kpi_col1:
        try:
            if not avail_data.empty:
                total_downtime = float(avail_data['TOTAL_DOWNTIME_SECS'].iloc[0] or 0)
                affected_sites = int(avail_data['AFFECTED_SITES'].iloc[0] or 0)
                hw_unavail = 0.0
                if not overall_nd.empty:
                    all_downtime = float(overall_nd['ALL_DOWNTIME'].iloc[0] or 0)
                    all_n = float(overall_nd['ALL_N'].iloc[0] or 0)
                    all_d = float(overall_nd['ALL_D'].iloc[0] or 0)
                    overall_unavail = (100 - (all_n / all_d * 100)) if all_d > 0 else 0
                    hw_unavail = (total_downtime / all_downtime * overall_unavail) if all_downtime > 0 else 0
                spares_pct = (spares_downtime / total_downtime * 100) if total_downtime > 0 else 0
                sites_pct = (sites_with_orders / affected_sites * 100) if affected_sites > 0 else 0
                st.markdown(f"""
                <div style='background: linear-gradient(135deg, #7f1d1d, #991b1b); padding: 20px; border-radius: 10px; position: relative; min-height: 140px;'>
                    <div style='position: absolute; top: 12px; right: 16px; color: #fbbf24; font-size: 1rem; font-weight: bold;'>Unavail: {hw_unavail:.2f}%</div>
                    <div style='color: #fca5a5; font-size: 0.9rem;'>📉 Total Downtime</div>
                    <div style='color: white; font-size: 2rem; font-weight: bold;'>{format_number(total_downtime)} sec</div>
                    <div style='color: #fecaca; font-size: 0.85rem;'>{format_number(total_downtime/3600)} hours | {format_number(affected_sites)} sites</div>
                    <div style='position: absolute; bottom: 12px; right: 16px; color: #86efac; font-size: 0.8rem; text-align: right;'>🔧 {format_number(sites_with_orders)} of {format_number(affected_sites)} sites with spare orders ({sites_pct:.1f}%)<br><span style='color: #fde047;'>{format_number(spares_downtime)} sec ({spares_pct:.1f}% of total)</span></div>
                </div>
                """, unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Availability query error: {e}")
    
    # KPI 2: COTTR Outage Minutes
    with kpi_col2:
        try:
            if not cottr_data.empty:
                total_mins = float(cottr_data['TOTAL_OUTAGE_MINS'].iloc[0] or 0)
                outage_days = int(cottr_data['OUTAGE_DAYS'].iloc[0] or 0)
                st.markdown(f"""
                <div style='background: linear-gradient(135deg, #7c2d12, #9a3412); padding: 20px; border-radius: 10px; min-height: 140px;'>
                    <div style='color: #fed7aa; font-size: 0.9rem;'>⚡ COTTR Service Outage</div>
                    <div style='color: white; font-size: 2rem; font-weight: bold;'>{format_number(total_mins)} mins</div>
                    <div style='color: #ffedd5; font-size: 0.85rem;'>{format_number(total_mins/60)} hours | {format_number(outage_days)} outage days</div>
                </div>
                """, unsafe_allow_html=True)
        except Exception as e:
            st.error(f"COTTR query error: {e}")
    
    # KPI 3: Customer Minutes (using cached data from above)
    with kpi_col3:
        try:
            if not cm_data.empty:
                total_cm = float(cm_data['TOTAL_CM'].iloc[0] or 0)
                total_subs = int(cm_data['TOTAL_SUBS'].iloc[0] or 0)
                st.markdown(f"""
                <div style='background: linear-gradient(135deg, #581c87, #7c3aed); padding: 20px; border-radius: 10px; min-height: 140px;'>
                    <div style='color: #e9d5ff; font-size: 0.9rem;'>👥 Customer Impact</div>
                    <div style='color: white; font-size: 2rem; font-weight: bold;'>{format_number(total_cm)} CM</div>
                    <div style='color: #f3e8ff; font-size: 0.85rem;'>{format_number(total_subs)} impacted subscribers</div>
                </div>
                """, unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Customer Minutes query error: {e}")
    
    st.markdown("---")
    
    # Hardware vs Hardware-Antenna breakdown (already fetched in parallel)
    # Top Markets by Hardware Issues
    st.markdown("### 🗺️ Top Markets by Hardware Issues")
    
    market_col1, market_col2 = st.columns(2)
    
    with market_col1:
        try:
            if not market_avail.empty:
                market_avail['TOTAL_DOWNTIME'] = pd.to_numeric(market_avail['TOTAL_DOWNTIME'], errors='coerce').fillna(0).astype(float)
                all_dt = float(overall_nd['ALL_DOWNTIME'].iloc[0] or 0) if not overall_nd.empty else 0
                all_n_val = float(overall_nd['ALL_N'].iloc[0] or 0) if not overall_nd.empty else 0
                all_d_val = float(overall_nd['ALL_D'].iloc[0] or 0) if not overall_nd.empty else 0
                ov_unavail = (100 - (all_n_val / all_d_val * 100)) if all_d_val > 0 else 0
                hw_total_dt = float(avail_data['TOTAL_DOWNTIME_SECS'].iloc[0] or 0) if not avail_data.empty else 0
                market_avail['UNAVAIL_PCT'] = (market_avail['TOTAL_DOWNTIME'] / all_dt * ov_unavail) if all_dt > 0 else 0
                market_avail['PCT_OF_HW'] = (market_avail['TOTAL_DOWNTIME'] / hw_total_dt * 100) if hw_total_dt > 0 else 0
                market_avail['SITE_COUNT'] = pd.to_numeric(market_avail['SITE_COUNT'], errors='coerce').fillna(0).astype(int)
                top15_unavail_sum = market_avail['UNAVAIL_PCT'].sum()
                top15_pct_of_hw = (market_avail['TOTAL_DOWNTIME'].sum() / hw_total_dt * 100) if hw_total_dt > 0 else 0
                st.markdown(f"##### Top 15 Markets - Availability Downtime")
                st.markdown(f"<span style='font-size:0.85rem;color:#aaaaaa;'>Top 15 = <b>{top15_unavail_sum:.2f}%</b> Unavail | <b>{top15_pct_of_hw:.2f}%</b> of Hardware Downtime</span>", unsafe_allow_html=True)
                ma_sorted = market_avail.sort_values('TOTAL_DOWNTIME', ascending=True)
                dt_vals = ma_sorted['TOTAL_DOWNTIME'].values
                dt_min, dt_max = dt_vals.min(), dt_vals.max()
                normed = [(v - dt_min) / (dt_max - dt_min) if dt_max > dt_min else 0.5 for v in dt_vals]
                bar_colors = [pc.sample_colorscale(TMOBILE_COLORSCALE, [n])[0] for n in normed]
                hover_texts = []
                for _, row in ma_sorted.iterrows():
                    hover_texts.append(
                        f"<b>{row['MARKET_ID']}</b><br>"
                        f"Total Downtime: {row['TOTAL_DOWNTIME']:,.0f} sec<br>"
                        f"Sites Affected: {int(row['SITE_COUNT'])}<br>"
                        f"Unavailability: {row['UNAVAIL_PCT']:.4f}%<br>"
                        f"Share of HW Downtime: {row['PCT_OF_HW']:.2f}%"
                    )
                # Create text with both unavail % and site count
                bar_text = [f"{row['UNAVAIL_PCT']:.4f}% | {int(row['SITE_COUNT'])} sites" for _, row in ma_sorted.iterrows()]
                fig3 = go.Figure(go.Bar(
                    x=ma_sorted['TOTAL_DOWNTIME'],
                    y=ma_sorted['MARKET_ID'],
                    orientation='h',
                    marker_color=bar_colors,
                    text=bar_text,
                    textposition='inside',
                    textfont=dict(color='white', size=12, family='Arial Black'),
                    insidetextanchor='end',
                    hoverinfo='skip',
                ))
                fig3.update_layout(
                    template='plotly_white',
                    height=550,
                    showlegend=False,
                    hovermode=False,
                    margin=dict(t=10, b=40, l=120),
                    yaxis=dict(tickfont=dict(size=12)),
                )
                st.plotly_chart(fig3, use_container_width=True, config=CHART_CONFIG, key="hw_market_avail")
        except Exception as e:
            st.error(f"Market availability error: {e}")
    
    with market_col2:
        # Already fetched in parallel
        try:
            if not market_cottr.empty:
                st.markdown("##### Top 15 Markets - COTTR Outage Minutes")
                # Create custom text with outage mins and site count
                market_cottr_sorted = market_cottr.sort_values('TOTAL_OUTAGE_MINS', ascending=True)
                market_cottr_sorted['TOTAL_OUTAGE_MINS'] = pd.to_numeric(market_cottr_sorted['TOTAL_OUTAGE_MINS'], errors='coerce').fillna(0).astype(float)
                market_cottr_sorted['SITE_COUNT'] = pd.to_numeric(market_cottr_sorted['SITE_COUNT'], errors='coerce').fillna(0).astype(int)
                cottr_bar_text = [f"{int(row['TOTAL_OUTAGE_MINS']):,} mins | {int(row['SITE_COUNT'])} sites" for _, row in market_cottr_sorted.iterrows()]
                cottr_vals = market_cottr_sorted['TOTAL_OUTAGE_MINS'].values
                cottr_min, cottr_max = float(cottr_vals.min()), float(cottr_vals.max())
                cottr_normed = [(float(v) - cottr_min) / (cottr_max - cottr_min) if cottr_max > cottr_min else 0.5 for v in cottr_vals]
                cottr_colors = [pc.sample_colorscale(TMOBILE_COLORSCALE, [n])[0] for n in cottr_normed]
                fig4 = go.Figure(go.Bar(
                    x=market_cottr_sorted['TOTAL_OUTAGE_MINS'],
                    y=market_cottr_sorted['MARKET_ID'],
                    orientation='h',
                    marker_color=cottr_colors,
                    text=cottr_bar_text,
                    textposition='inside',
                    textfont=dict(color='white', size=12, family='Arial Black'),
                    insidetextanchor='end',
                    hoverinfo='skip',
                ))
                fig4.update_layout(
                    template='plotly_white',
                    height=550,
                    showlegend=False,
                    hovermode=False,
                    margin=dict(t=10, b=40, l=120),
                    yaxis=dict(tickfont=dict(size=12)),
                )
                st.plotly_chart(fig4, use_container_width=True, config=CHART_CONFIG, key="hw_market_cottr")
        except Exception as e:
            st.error(f"Market COTTR error: {e}")
    
    st.markdown("---")
    
    # Daily Trend Analysis (already fetched in parallel)
    st.markdown("### 📈 Daily Trend Analysis")
    
    try:
        if not trend_df.empty:
            trend_df['DAILY_DOWNTIME'] = pd.to_numeric(trend_df['DAILY_DOWNTIME'], errors='coerce').fillna(0).astype(float)
            fig5 = px.line(
                trend_df,
                x='DATE_VALUE',
                y='DAILY_DOWNTIME',
                color='SITE_ID_FOCUS_CATEGORY',
                title='Daily Hardware Downtime Trend',
                color_discrete_sequence=['#e20074', '#b8005c']
            )
            for cat in trend_df['SITE_ID_FOCUS_CATEGORY'].unique():
                cat_data = trend_df[trend_df['SITE_ID_FOCUS_CATEGORY'] == cat].sort_values('DATE_VALUE')
                if len(cat_data) >= 2:
                    x_num = np.arange(len(cat_data))
                    coeffs = np.polyfit(x_num, cat_data['DAILY_DOWNTIME'].values, 1)
                    trend_vals = np.polyval(coeffs, x_num)
                    fig5.add_scatter(
                        x=cat_data['DATE_VALUE'], y=trend_vals,
                        mode='lines', name=f'{cat} Trend',
                        line=dict(dash='dot', color='#ff80aa', width=2),
                        showlegend=True
                    )
            fig5.update_layout(
                template='plotly_white',
                height=350
            )
            st.plotly_chart(fig5, use_container_width=True, config=CHART_CONFIG, key="hw_daily_trend")
    except Exception as e:
        st.error(f"Trend error: {e}")
    
    st.markdown("---")
    
    # Top Sites with Hardware Issues (already fetched in parallel)
    st.markdown("### 🏗️ Top Sites with Hardware Issues")
    
    site_skus = pd.DataFrame()
    if not spares_data_for_skus.empty and 'SITE_ID' in spares_data_for_skus.columns and 'REF_SKU_DESC' in spares_data_for_skus.columns:
        site_skus = spares_data_for_skus.groupby('SITE_ID').agg({
            'REF_SKU_DESC': lambda x: ', '.join(x.dropna().unique()[:3]),
            'REF_SKU': 'nunique',
            'TROUBLE TICKET': 'nunique'
        }).reset_index()
        site_skus.columns = ['SITE_ID', 'SKUS_ORDERED', 'UNIQUE_SKUS', 'UNIQUE_TICKETS']
    
    def format_kmb(val):
        """Format number as K/M/B"""
        try:
            v = float(val)
            if v >= 1_000_000:
                return f"{v/1_000_000:.1f}M"
            elif v >= 1_000:
                return f"{v/1_000:.0f}K"
            return f"{int(v)}"
        except (ValueError, TypeError):
            return str(val)
    
    def make_plotly_table(df, title, downtime_col, key, hover_col=None):
        """Render a scrollable Plotly table with single scrollbar"""
        cols = list(df.columns)
        col_rename = {
            'SITE_ID_FOCUS_CATEGORY': 'FOCUS',
            'SITE_ID_DETAIL_CATEGORY': 'DETAIL',
            'TOTAL_DOWNTIME': 'DOWNTIME',
            'TOTAL_OUTAGE_MINS': 'OUTAGE_MINS',
            'DAYS_IMPACTED': 'DAYS',
            'OUTAGE_DAYS': 'DAYS',
            'UNIQUE_SKUS': '# SKUs',
            'SKUS_ORDERED': 'SKU_DESC',
        }
        header_labels = [col_rename.get(c, c) for c in cols]
        
        cell_values = []
        hover_texts = None
        for col in cols:
            if col == downtime_col:
                cell_values.append([format_kmb(v) for v in df[col]])
            elif col == hover_col:
                full_texts = df[col].fillna('-').astype(str).tolist()
                truncated = [t[:20] + '...' if len(t) > 20 else t for t in full_texts]
                cell_values.append(truncated)
                hover_texts = full_texts
            else:
                cell_values.append(df[col].astype(str).tolist())
        
        # Build custom hover text per row showing full SKU desc
        if hover_col and hover_texts:
            n_rows = len(df)
            suffix = [[f"SKUs: {hover_texts[r]}" for r in range(n_rows)]] * len(cols)
        else:
            suffix = None
        
        fig = go.Figure(data=[go.Table(
            columnwidth=[80, 90, 70, 90, 70, 60, 60, 60, 120],
            header=dict(
                values=[f"<b>{c}</b>" for c in header_labels],
                fill_color='#e20074',
                font=dict(color='white', size=11),
                align='left',
                height=30
            ),
            cells=dict(
                values=cell_values,
                fill_color=[['#ffffff', '#f8f9fa'] * (len(df) // 2 + 1)][:1] * len(cols),
                font=dict(color='#333333', size=11),
                align='left',
                height=28,
                suffix=None
            )
        )])
        fig.update_layout(
            title=dict(text=title, font=dict(size=14, color='#333333')),
            margin=dict(l=0, r=0, t=30, b=0),
            height=400,
            paper_bgcolor='rgba(0,0,0,0)',
        )
        st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key=key)
    
    hw_total_avail = float(avail_data['TOTAL_DOWNTIME_SECS'].iloc[0] or 0) if not avail_data.empty else 0
    hw_total_cottr = float(cottr_data['TOTAL_OUTAGE_MINS'].iloc[0] or 0) if not cottr_data.empty else 0

    site_col1, site_col2 = st.columns(2)
    
    with site_col1:
        try:
            if not sites_avail.empty:
                display_avail = sites_avail.copy()
                if not site_skus.empty:
                    display_avail = display_avail.merge(site_skus, on='SITE_ID', how='left')
                    display_avail['UNIQUE_SKUS'] = display_avail['UNIQUE_SKUS'].fillna(0).astype(int)
                    display_avail['UNIQUE_TICKETS'] = display_avail['UNIQUE_TICKETS'].fillna(0).astype(int)
                else:
                    display_avail['UNIQUE_SKUS'] = 0
                    display_avail['UNIQUE_TICKETS'] = 0
                if 'SKUS_ORDERED' not in display_avail.columns:
                    display_avail['SKUS_ORDERED'] = '-'
                display_avail['TOTAL_DOWNTIME'] = pd.to_numeric(display_avail['TOTAL_DOWNTIME'], errors='coerce').fillna(0)
                display_avail['% OF TOTAL'] = display_avail['TOTAL_DOWNTIME'].apply(
                    lambda x: f"{(x / hw_total_avail * 100):.2f}%" if hw_total_avail > 0 else "0%"
                )
                top100_avail = display_avail.head(100)
                top100_sum = top100_avail['TOTAL_DOWNTIME'].sum()
                top100_pct = (top100_sum / hw_total_avail * 100) if hw_total_avail > 0 else 0
                show_cols = [c for c in ['SITE_ID', 'MARKET_ID', 'SITE_ID_DETAIL_CATEGORY',
                             'TOTAL_DOWNTIME', '% OF TOTAL', 'DAYS_IMPACTED', 'LAST_IMPACT_DATE', 'UNIQUE_TICKETS', 'UNIQUE_SKUS', 'SKUS_ORDERED'] if c in display_avail.columns]
                with st.expander(f"View all top 100 sites - Availability Downtime (Top 100 = {top100_pct:.1f}% of total HW downtime)"):
                    st.dataframe(display_avail[show_cols].head(100), use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Top sites avail error: {e}")
    
    with site_col2:
        try:
            if not sites_cottr.empty:
                display_cottr = sites_cottr.copy()
                if not site_skus.empty:
                    display_cottr = display_cottr.merge(site_skus, left_on='SITE_CD', right_on='SITE_ID', how='left')
                    display_cottr['UNIQUE_SKUS'] = display_cottr['UNIQUE_SKUS'].fillna(0).astype(int)
                    display_cottr['UNIQUE_TICKETS'] = display_cottr['UNIQUE_TICKETS'].fillna(0).astype(int)
                    if 'SITE_ID_y' in display_cottr.columns:
                        display_cottr = display_cottr.drop(columns=['SITE_ID_y'])
                    if 'SITE_ID_x' in display_cottr.columns:
                        display_cottr = display_cottr.rename(columns={'SITE_ID_x': 'SITE_ID'})
                else:
                    display_cottr['UNIQUE_SKUS'] = 0
                    display_cottr['UNIQUE_TICKETS'] = 0
                if 'SKUS_ORDERED' not in display_cottr.columns:
                    display_cottr['SKUS_ORDERED'] = '-'
                display_cottr['TOTAL_OUTAGE_MINS'] = pd.to_numeric(display_cottr['TOTAL_OUTAGE_MINS'], errors='coerce').fillna(0)
                display_cottr['% OF TOTAL'] = display_cottr['TOTAL_OUTAGE_MINS'].apply(
                    lambda x: f"{(x / hw_total_cottr * 100):.2f}%" if hw_total_cottr > 0 else "0%"
                )
                top100_cottr = display_cottr.head(100)
                top100_cottr_sum = top100_cottr['TOTAL_OUTAGE_MINS'].sum()
                top100_cottr_pct = (top100_cottr_sum / hw_total_cottr * 100) if hw_total_cottr > 0 else 0
                show_cols_c = [c for c in ['SITE_CD', 'MARKET_ID', 'SITE_ID_DETAIL_CATEGORY',
                             'TOTAL_OUTAGE_MINS', '% OF TOTAL', 'OUTAGE_DAYS', 'LAST_IMPACT_DATE', 'UNIQUE_TICKETS', 'UNIQUE_SKUS', 'SKUS_ORDERED'] if c in display_cottr.columns]
                with st.expander(f"View all top 100 sites - COTTR Outage Minutes (Top 100 = {top100_cottr_pct:.1f}% of total COTTR mins)"):
                    st.dataframe(display_cottr[show_cols_c].head(100), use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Top sites COTTR error: {e}")
    
    st.markdown("---")
    
    # OEM Analysis for Hardware Issues (already fetched in parallel)
    st.markdown("### 🏭 OEM Analysis for Hardware Issues")
    
    try:
        if not oem_df.empty:
            fig6 = px.bar(
                oem_df,
                x='OEM',
                y='TOTAL_DOWNTIME',
                color='SITE_ID_FOCUS_CATEGORY',
                barmode='group',
                title='Hardware Downtime by OEM',
                color_discrete_sequence=['#e20074', '#b8005c']
            )
            fig6.update_layout(
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font_color='#333333',
                height=350
            )
            st.plotly_chart(fig6, use_container_width=True, config=CHART_CONFIG, key="hw_oem_analysis")
    except Exception as e:
        st.error(f"OEM analysis error: {e}")
    
    st.markdown("---")
    
    # ========== SPARES ANALYSIS SECTION ==========
    st.markdown("### 📦 Hardware Spares Analysis")
    st.markdown("SKU orders correlated with Hardware focus category outages (joined on TOP_RECORDID = TROUBLE TICKET)")
    
    # Add explanatory note about date correlation
    with st.expander("ℹ️ How Spares Correlation Works", expanded=False):
        st.markdown("""
        **Correlation Logic:**
        - **Outage dates** are filtered by your selected date range
        - Hardware outage tickets (`TOP_RECORDID`) are matched to spare orders (`TROUBLE TICKET`)
        - If the **ticket number matches**, the spare order is included — no date window restriction
        
        **This means:** Any spare order linked to a hardware outage ticket within your date range will appear,
        regardless of when the order was placed. This provides the most complete picture of parts ordered for each incident.
        """)
    
    try:
        # Reuse already-fetched spares data from parallel block
        spares_data = spares_data_for_skus.copy() if not spares_data_for_skus.empty else get_hardware_spares_data(
            conn, 
            hw_start_date, 
            hw_end_date, 
            market_selection,
            site_type
        )
        
        if not spares_data.empty:
            # Deduplicate on core spares columns only (exclude availability-side columns
            # like TOTAL_DOWNTIME, DATE_VALUE, OEM that can vary per outage day)
            dedup_cols = [c for c in ['TROUBLE TICKET', 'SITE', 'MARKET', 'REF_SKU', 'REF_SKU_DESC',
                          'ORDER STATUS', 'ORDER CREATE DATE', 'FAILURE CODE', 'STAGING_KPI_GROUPS'
                          ] if c in spares_data.columns]
            spares_data = spares_data.drop_duplicates(subset=dedup_cols)
            # Show summary metrics
            spares_kpi1, spares_kpi2, spares_kpi3, spares_kpi4 = st.columns(4)
            
            with spares_kpi1:
                total_orders = len(spares_data)
                st.metric("Total Spare Orders", f"{total_orders:,}")
            
            with spares_kpi2:
                unique_skus = spares_data['REF_SKU'].nunique() if 'REF_SKU' in spares_data.columns else 0
                st.metric("Unique SKUs", f"{unique_skus:,}")
            
            with spares_kpi3:
                unique_tickets = spares_data['TROUBLE TICKET'].nunique() if 'TROUBLE TICKET' in spares_data.columns else 0
                st.metric("Unique Tickets", f"{unique_tickets:,}")
            
            with spares_kpi4:
                unique_sites = spares_data['SITE'].nunique() if 'SITE' in spares_data.columns else 0
                st.metric("Sites with Spares", f"{unique_sites:,}")
            
            st.markdown("")
            
            # Row 1: Top SKUs and Order Status
            spares_col1, spares_col2 = st.columns(2)
            
            with spares_col1:
                st.markdown("##### Top 15 SKUs Ordered for Hardware Issues")
                if 'REF_SKU_DESC' in spares_data.columns:
                    # Get order count and unique site count per SKU
                    sku_counts = spares_data.groupby(['REF_SKU', 'REF_SKU_DESC']).agg({
                        'SITE_ID': 'nunique' if 'SITE_ID' in spares_data.columns else 'count'
                    }).reset_index()
                    sku_counts.columns = ['REF_SKU', 'REF_SKU_DESC', 'SITE_COUNT']
                    sku_order_counts = spares_data.groupby(['REF_SKU', 'REF_SKU_DESC']).size().reset_index(name='ORDER_COUNT')
                    sku_counts = sku_counts.merge(sku_order_counts, on=['REF_SKU', 'REF_SKU_DESC'])
                    sku_counts = sku_counts.sort_values('ORDER_COUNT', ascending=False).head(15)
                    sku_counts['SKU_LABEL'] = sku_counts['REF_SKU'].astype(str) + ' - ' + sku_counts['REF_SKU_DESC'].astype(str).str[:30]
                    sku_counts = sku_counts.sort_values('ORDER_COUNT', ascending=True)  # For horizontal bar
                    
                    # Create bar text with order count and site count
                    bar_text = [f"{row['ORDER_COUNT']} orders | {row['SITE_COUNT']} sites" for _, row in sku_counts.iterrows()]
                    
                    fig_sku = go.Figure(go.Bar(
                        x=sku_counts['ORDER_COUNT'],
                        y=sku_counts['SKU_LABEL'],
                        orientation='h',
                        marker_color=sku_counts['ORDER_COUNT'],
                        marker_colorscale=TMOBILE_COLORSCALE,
                        text=bar_text,
                        textposition='inside',
                        textfont=dict(color='white', size=11, family='Arial Black'),
                        insidetextanchor='end',
                        hoverinfo='skip',
                    ))
                    fig_sku.update_layout(
                        template='plotly_white',
                        height=500,
                        showlegend=False,
                        hovermode=False,
                        xaxis_title='Order Count',
                        yaxis_title='',
                        margin=dict(l=200),
                    )
                    st.plotly_chart(fig_sku, use_container_width=True, config=CHART_CONFIG, key="hw_top_skus")
            
            with spares_col2:
                st.markdown("##### Order Status Distribution")
                if 'ORDER STATUS' in spares_data.columns:
                    status_counts = spares_data['ORDER STATUS'].value_counts().reset_index()
                    status_counts.columns = ['STATUS', 'COUNT']
                    
                    fig_status = px.pie(
                        status_counts,
                        values='COUNT',
                        names='STATUS',
                        title='',
                        color_discrete_sequence=['#e20074', '#ff3399', '#b8005c', '#ff80aa', '#6b0037', '#ff4d8d', '#9e0057', '#c9006a']
                    )
                    fig_status.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#333333',
                        height=450
                    )
                    fig_status.update_traces(textposition='inside', textinfo='percent+label')
                    st.plotly_chart(fig_status, use_container_width=True, config=CHART_CONFIG, key="hw_order_status")
            
            # Row 2: Orders Over Time and Failure Codes
            spares_col3, spares_col4 = st.columns(2)
            
            with spares_col3:
                st.markdown("##### Hardware Spare Orders Over Time")
                if 'ORDER CREATE DATE' in spares_data.columns:
                    spares_filtered = spares_data.copy()
                    spares_filtered['ORDER CREATE DATE'] = pd.to_datetime(spares_filtered['ORDER CREATE DATE'], errors='coerce')
                    spares_filtered = spares_filtered.dropna(subset=['ORDER CREATE DATE'])
                    if hw_start_date:
                        spares_filtered = spares_filtered[spares_filtered['ORDER CREATE DATE'].dt.date >= (hw_start_date if isinstance(hw_start_date, date) else datetime.strptime(str(hw_start_date), '%Y-%m-%d').date())]
                    if hw_end_date:
                        spares_filtered = spares_filtered[spares_filtered['ORDER CREATE DATE'].dt.date <= (hw_end_date if isinstance(hw_end_date, date) else datetime.strptime(str(hw_end_date), '%Y-%m-%d').date())]
                    orders_by_date = spares_filtered.groupby(spares_filtered['ORDER CREATE DATE'].dt.date).size().reset_index(name='ORDER_COUNT')
                    orders_by_date.columns = ['DATE', 'ORDER_COUNT']
                    
                    fig_trend = px.area(
                        orders_by_date,
                        x='DATE',
                        y='ORDER_COUNT',
                        title='',
                        color_discrete_sequence=['#e20074']
                    )
                    fig_trend.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#333333',
                        height=350,
                        xaxis_title='Order Date',
                        yaxis_title='Orders'
                    )
                    st.plotly_chart(fig_trend, use_container_width=True, config=CHART_CONFIG, key="hw_orders_trend")
            
            with spares_col4:
                st.markdown("##### Top Failure Codes")
                if 'FAILURE CODE' in spares_data.columns:
                    failure_counts = spares_data['FAILURE CODE'].fillna('Unknown').value_counts().head(10).reset_index()
                    failure_counts.columns = ['FAILURE_CODE', 'COUNT']
                    
                    fig_failure = px.bar(
                        failure_counts,
                        x='COUNT',
                        y='FAILURE_CODE',
                        orientation='h',
                        title='',
                        color='COUNT',
                        color_continuous_scale=TMOBILE_COLORSCALE_WARM,
                    )
                    fig_failure.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#333333',
                        height=350,
                        yaxis={'categoryorder': 'total ascending'},
                        showlegend=False,
                        coloraxis_showscale=False,
                        xaxis_title='Count',
                        yaxis_title=''
                    )
                    st.plotly_chart(fig_failure, use_container_width=True, config=CHART_CONFIG, key="hw_failure_codes")
            
            # Row 2.5: SKU by Downtime Analysis
            st.markdown("---")
            st.markdown("#### 📊 SKU Impact on Downtime")
            spares_col_sku1, spares_col_sku2 = st.columns(2)
            
            with spares_col_sku1:
                st.markdown("##### Top SKUs by Availability Downtime (seconds)")
                if 'REF_SKU_DESC' in spares_data.columns and 'TOTAL_DOWNTIME' in spares_data.columns:
                    sku_downtime = spares_data.groupby(['REF_SKU', 'REF_SKU_DESC']).agg({
                        'TOTAL_DOWNTIME': 'sum',
                        'TROUBLE TICKET': 'nunique',
                        'SITE_ID': 'nunique' if 'SITE_ID' in spares_data.columns else 'count'
                    }).reset_index()
                    sku_downtime.columns = ['REF_SKU', 'REF_SKU_DESC', 'TOTAL_DOWNTIME', 'TICKET_COUNT', 'SITE_COUNT']
                    sku_downtime = sku_downtime.sort_values('TOTAL_DOWNTIME', ascending=False).head(15)
                    sku_downtime['SKU_LABEL'] = sku_downtime['REF_SKU'].astype(str) + ' - ' + sku_downtime['REF_SKU_DESC'].astype(str).str[:25]
                    sku_downtime = sku_downtime.sort_values('TOTAL_DOWNTIME', ascending=True)  # For horizontal bar
                    
                    # Create bar text with downtime and site count
                    def format_downtime(val):
                        if val >= 1_000_000:
                            return f"{val/1_000_000:.1f}M"
                        elif val >= 1_000:
                            return f"{val/1_000:.0f}K"
                        return f"{int(val)}"
                    bar_text_dt = [f"{format_downtime(row['TOTAL_DOWNTIME'])} sec | {row['SITE_COUNT']} sites" for _, row in sku_downtime.iterrows()]
                    
                    fig_sku_dt = go.Figure(go.Bar(
                        x=sku_downtime['TOTAL_DOWNTIME'],
                        y=sku_downtime['SKU_LABEL'],
                        orientation='h',
                        marker_color=sku_downtime['TOTAL_DOWNTIME'],
                        marker_colorscale=TMOBILE_COLORSCALE,
                        text=bar_text_dt,
                        textposition='inside',
                        textfont=dict(color='white', size=11, family='Arial Black'),
                        insidetextanchor='end',
                        hoverinfo='skip',
                    ))
                    fig_sku_dt.update_layout(
                        template='plotly_white',
                        height=500,
                        showlegend=False,
                        hovermode=False,
                        xaxis_title='Total Downtime (sec)',
                        yaxis_title='',
                        margin=dict(l=200),
                    )
                    st.plotly_chart(fig_sku_dt, use_container_width=True, config=CHART_CONFIG, key="hw_sku_downtime")
                else:
                    st.info("Downtime data not available for SKU analysis")
            
            with spares_col_sku2:
                st.markdown("##### Top SKUs by Availability Outage Count")
                if 'REF_SKU_DESC' in spares_data.columns and 'TROUBLE TICKET' in spares_data.columns:
                    sku_outages = spares_data.groupby(['REF_SKU', 'REF_SKU_DESC']).agg({
                        'TROUBLE TICKET': 'nunique',
                        'SITE': 'nunique',
                        'TOTAL_DOWNTIME': 'mean'
                    }).reset_index()
                    sku_outages.columns = ['REF_SKU', 'REF_SKU_DESC', 'OUTAGE_COUNT', 'SITES_AFFECTED', 'AVG_DOWNTIME']
                    sku_outages = sku_outages.sort_values('OUTAGE_COUNT', ascending=False).head(15)
                    sku_outages['SKU_LABEL'] = sku_outages['REF_SKU'].astype(str) + ' - ' + sku_outages['REF_SKU_DESC'].astype(str).str[:25]
                    sku_outages = sku_outages.sort_values('OUTAGE_COUNT', ascending=True)  # For horizontal bar
                    
                    # Create bar text with outage count and site count
                    bar_text_outage = [f"{row['OUTAGE_COUNT']} outages | {row['SITES_AFFECTED']} sites" for _, row in sku_outages.iterrows()]
                    
                    fig_sku_outage = go.Figure(go.Bar(
                        x=sku_outages['OUTAGE_COUNT'],
                        y=sku_outages['SKU_LABEL'],
                        orientation='h',
                        marker_color=sku_outages['SITES_AFFECTED'],
                        marker_colorscale=TMOBILE_COLORSCALE_WARM,
                        text=bar_text_outage,
                        textposition='inside',
                        textfont=dict(color='white', size=11, family='Arial Black'),
                        insidetextanchor='end',
                        hoverinfo='skip',
                    ))
                    fig_sku_outage.update_layout(
                        template='plotly_white',
                        height=500,
                        showlegend=False,
                        hovermode=False,
                        xaxis_title='Unique Outages (Tickets)',
                        yaxis_title='',
                        margin=dict(l=200),
                    )
                    st.plotly_chart(fig_sku_outage, use_container_width=True, config=CHART_CONFIG, key="hw_sku_outages")
                else:
                    st.info("Outage data not available for SKU analysis")
            
            # Row 2.6: COTTR-based SKU Analysis
            st.markdown("---")
            st.markdown("#### 📈 SKU Impact on COTTR Service Outages")
            
            # Reuse already-fetched COTTR spares data from parallel block
            cottr_spares_data = cottr_spares_data_cached.copy() if not cottr_spares_data_cached.empty else get_hardware_spares_cottr_data(
                conn, 
                hw_start_date, 
                hw_end_date, 
                market_selection,
                site_type
            )
            
            if not cottr_spares_data.empty:
                # Deduplicate on core spares columns only
                cottr_dedup_cols = [c for c in ['TROUBLE TICKET', 'SITE', 'MARKET', 'REF_SKU', 'REF_SKU_DESC',
                                  'ORDER STATUS', 'ORDER CREATE DATE', 'FAILURE CODE', 'STAGING_KPI_GROUPS'
                                  ] if c in cottr_spares_data.columns]
                cottr_spares_data = cottr_spares_data.drop_duplicates(subset=cottr_dedup_cols)
                spares_col_cottr1, spares_col_cottr2 = st.columns(2)
                
                with spares_col_cottr1:
                    st.markdown("##### Top SKUs by Service Outages")
                    if 'REF_SKU_DESC' in cottr_spares_data.columns and 'OUTAGE_MINUTES' in cottr_spares_data.columns:
                        sku_cottr = cottr_spares_data.groupby(['REF_SKU', 'REF_SKU_DESC']).agg({
                            'OUTAGE_MINUTES': 'sum',
                            'TROUBLE TICKET': 'nunique',
                            'SITE': 'nunique' if 'SITE' in cottr_spares_data.columns else 'count'
                        }).reset_index()
                        sku_cottr.columns = ['REF_SKU', 'REF_SKU_DESC', 'TOTAL_OUTAGE_MINS', 'TICKET_COUNT', 'SITE_COUNT']
                        sku_cottr = sku_cottr.sort_values('TOTAL_OUTAGE_MINS', ascending=False).head(15)
                        sku_cottr['SKU_LABEL'] = sku_cottr['REF_SKU'].astype(str) + ' - ' + sku_cottr['REF_SKU_DESC'].astype(str).str[:25]
                        sku_cottr = sku_cottr.sort_values('TOTAL_OUTAGE_MINS', ascending=True)
                        
                        cottr_bar_text = [f"{int(row['TOTAL_OUTAGE_MINS']):,} mins | {row['SITE_COUNT']} sites" for _, row in sku_cottr.iterrows()]
                        fig_sku_cottr = go.Figure(go.Bar(
                            x=sku_cottr['TOTAL_OUTAGE_MINS'],
                            y=sku_cottr['SKU_LABEL'],
                            orientation='h',
                            marker_color=sku_cottr['TOTAL_OUTAGE_MINS'],
                            marker_colorscale=TMOBILE_COLORSCALE,
                            text=cottr_bar_text,
                            textposition='inside',
                            textfont=dict(color='white', size=11, family='Arial Black'),
                            insidetextanchor='end',
                            hoverinfo='skip',
                        ))
                        fig_sku_cottr.update_layout(
                            template='plotly_white',
                            height=500,
                            showlegend=False,
                            hovermode=False,
                            xaxis_title='Total Outage Minutes',
                            yaxis_title='',
                            margin=dict(l=200),
                        )
                        st.plotly_chart(fig_sku_cottr, use_container_width=True, config=CHART_CONFIG, key="hw_sku_cottr_mins")
                    else:
                        st.info("COTTR outage data not available")
                
                with spares_col_cottr2:
                    st.markdown("##### Top SKUs by COTTR Outage Count")
                    if 'REF_SKU_DESC' in cottr_spares_data.columns and 'TROUBLE TICKET' in cottr_spares_data.columns:
                        sku_cottr_outages = cottr_spares_data.groupby(['REF_SKU', 'REF_SKU_DESC']).agg({
                            'TROUBLE TICKET': 'nunique',
                            'SITE': 'nunique' if 'SITE' in cottr_spares_data.columns else 'count',
                            'OUTAGE_MINUTES': 'mean'
                        }).reset_index()
                        sku_cottr_outages.columns = ['REF_SKU', 'REF_SKU_DESC', 'OUTAGE_COUNT', 'SITES_AFFECTED', 'AVG_OUTAGE_MINS']
                        sku_cottr_outages = sku_cottr_outages.sort_values('OUTAGE_COUNT', ascending=False).head(15)
                        sku_cottr_outages['SKU_LABEL'] = sku_cottr_outages['REF_SKU'].astype(str) + ' - ' + sku_cottr_outages['REF_SKU_DESC'].astype(str).str[:25]
                        sku_cottr_outages = sku_cottr_outages.sort_values('OUTAGE_COUNT', ascending=True)
                        
                        cottr_outage_bar_text = [f"{row['OUTAGE_COUNT']} outages | {row['SITES_AFFECTED']} sites" for _, row in sku_cottr_outages.iterrows()]
                        
                        fig_cottr_outage = go.Figure(go.Bar(
                            x=sku_cottr_outages['OUTAGE_COUNT'],
                            y=sku_cottr_outages['SKU_LABEL'],
                            orientation='h',
                            marker_color=sku_cottr_outages['SITES_AFFECTED'],
                            marker_colorscale=TMOBILE_COLORSCALE_WARM,
                            text=cottr_outage_bar_text,
                            textposition='inside',
                            textfont=dict(color='white', size=11, family='Arial Black'),
                            insidetextanchor='end',
                            hoverinfo='skip',
                        ))
                        fig_cottr_outage.update_layout(
                            template='plotly_white',
                            height=500,
                            showlegend=False,
                            hovermode=False,
                            xaxis_title='Unique Outages (Tickets)',
                            yaxis_title='',
                            margin=dict(l=200),
                        )
                        st.plotly_chart(fig_cottr_outage, use_container_width=True, config=CHART_CONFIG, key="hw_sku_cottr_outage_count")
                    else:
                        st.info("COTTR outage count data not available")
            else:
                st.info("No COTTR spare orders found for the selected filters.")
            
            # Row 2.7: SKU by OEM Analysis
            st.markdown("---")
            st.markdown("#### 🏭 SKU Analysis by OEM (Ericsson vs Nokia)")
            
            if 'OEM' in spares_data.columns:
                # Filter data by OEM
                ericsson_data = spares_data[spares_data['OEM'] == 'Ericsson']
                nokia_data = spares_data[spares_data['OEM'] == 'Nokia']
                unknown_data = spares_data[spares_data['OEM'] == 'Unknown']
                
                spares_col_oem1, spares_col_oem2 = st.columns(2)
                
                with spares_col_oem1:
                    st.markdown("##### 🔵 Ericsson - Top SKUs by Order Count")
                    if not ericsson_data.empty and 'REF_SKU_DESC' in ericsson_data.columns:
                        sku_ericsson = ericsson_data.groupby(['REF_SKU', 'REF_SKU_DESC']).agg({
                            'TROUBLE TICKET': 'nunique',
                            'TOTAL_DOWNTIME': 'sum',
                            'SITE': 'nunique' if 'SITE' in ericsson_data.columns else 'count'
                        }).reset_index()
                        sku_ericsson.columns = ['REF_SKU', 'REF_SKU_DESC', 'ORDER_COUNT', 'TOTAL_DOWNTIME', 'SITE_COUNT']
                        sku_ericsson = sku_ericsson.sort_values('ORDER_COUNT', ascending=False).head(15)
                        sku_ericsson['SKU_SHORT'] = sku_ericsson['REF_SKU'].astype(str) + ' - ' + sku_ericsson['REF_SKU_DESC'].astype(str).str[:20]
                        sku_ericsson = sku_ericsson.sort_values('ORDER_COUNT', ascending=True)
                        ericsson_bar_text = [f"{row['ORDER_COUNT']} orders | {row['SITE_COUNT']} sites" for _, row in sku_ericsson.iterrows()]
                        fig_ericsson = go.Figure(go.Bar(
                            x=sku_ericsson['ORDER_COUNT'],
                            y=sku_ericsson['SKU_SHORT'],
                            orientation='h',
                            marker_color=sku_ericsson['ORDER_COUNT'],
                            marker_colorscale=TMOBILE_COLORSCALE,
                            text=ericsson_bar_text,
                            textposition='inside',
                            textfont=dict(color='white', size=11, family='Arial Black'),
                            insidetextanchor='end',
                            hoverinfo='skip',
                        ))
                        fig_ericsson.update_layout(
                            template='plotly_white',
                            height=500,
                            showlegend=False,
                            hovermode=False,
                            xaxis_title='Order Count',
                            yaxis_title='',
                            margin=dict(l=200),
                        )
                        st.plotly_chart(fig_ericsson, use_container_width=True, config=CHART_CONFIG, key="hw_sku_ericsson")
                        st.caption(f"Total: {len(ericsson_data):,} orders | {ericsson_data['TROUBLE TICKET'].nunique():,} tickets")
                    else:
                        st.info("No Ericsson data available")
                
                with spares_col_oem2:
                    st.markdown("##### 🟠 Nokia - Top SKUs by Order Count")
                    if not nokia_data.empty and 'REF_SKU_DESC' in nokia_data.columns:
                        sku_nokia = nokia_data.groupby(['REF_SKU', 'REF_SKU_DESC']).agg({
                            'TROUBLE TICKET': 'nunique',
                            'TOTAL_DOWNTIME': 'sum',
                            'SITE': 'nunique' if 'SITE' in nokia_data.columns else 'count'
                        }).reset_index()
                        sku_nokia.columns = ['REF_SKU', 'REF_SKU_DESC', 'ORDER_COUNT', 'TOTAL_DOWNTIME', 'SITE_COUNT']
                        sku_nokia = sku_nokia.sort_values('ORDER_COUNT', ascending=False).head(15)
                        sku_nokia['SKU_SHORT'] = sku_nokia['REF_SKU'].astype(str) + ' - ' + sku_nokia['REF_SKU_DESC'].astype(str).str[:20]
                        sku_nokia = sku_nokia.sort_values('ORDER_COUNT', ascending=True)
                        
                        nokia_bar_text = [f"{row['ORDER_COUNT']} orders | {row['SITE_COUNT']} sites" for _, row in sku_nokia.iterrows()]
                        fig_nokia = go.Figure(go.Bar(
                            x=sku_nokia['ORDER_COUNT'],
                            y=sku_nokia['SKU_SHORT'],
                            orientation='h',
                            marker_color=sku_nokia['ORDER_COUNT'],
                            marker_colorscale=TMOBILE_COLORSCALE_WARM,
                            text=nokia_bar_text,
                            textposition='inside',
                            textfont=dict(color='white', size=11, family='Arial Black'),
                            insidetextanchor='end',
                            hoverinfo='skip',
                        ))
                        fig_nokia.update_layout(
                            template='plotly_white',
                            height=500,
                            showlegend=False,
                            hovermode=False,
                            xaxis_title='Order Count',
                            yaxis_title='',
                            margin=dict(l=200),
                        )
                        st.plotly_chart(fig_nokia, use_container_width=True, config=CHART_CONFIG, key="hw_sku_nokia")
                        st.caption(f"Total: {len(nokia_data):,} orders | {nokia_data['TROUBLE TICKET'].nunique():,} tickets")
                    else:
                        st.info("No Nokia data available")
                
                # OEM Summary KPIs
                st.markdown("##### OEM Summary")
                oem_summary = spares_data.groupby('OEM').agg({
                    'TROUBLE TICKET': 'nunique',
                    'REF_SKU': 'nunique',
                    'SITE': 'nunique',
                    'TOTAL_DOWNTIME': 'sum'
                }).reset_index()
                oem_summary.columns = ['OEM', 'Unique Tickets', 'Unique SKUs', 'Sites Affected', 'Total Downtime (sec)']
                oem_summary['Total Downtime (sec)'] = oem_summary['Total Downtime (sec)'].apply(lambda x: f"{x:,.0f}")
                
                # Show Unknown OEM details if any exist
                if not unknown_data.empty:
                    with st.expander(f"⚠️ Unknown OEM Records ({len(unknown_data):,} orders)", expanded=False):
                        st.markdown("**Markets without OEM mapping in MARKET_TRACKER:**")
                        unknown_markets = unknown_data.groupby('MARKET_ID').agg({
                            'TROUBLE TICKET': 'nunique',
                            'SITE': 'nunique'
                        }).reset_index()
                        unknown_markets.columns = ['Market ID', 'Tickets', 'Sites']
                        unknown_markets = unknown_markets.sort_values('Tickets', ascending=False)
                        st.dataframe(unknown_markets, use_container_width=True, hide_index=True)
                st.dataframe(oem_summary, use_container_width=True, hide_index=True)
            else:
                st.info("OEM data not available in the current dataset.")
            
            # Row 3: Market Distribution and Staging KPI
            spares_col5, spares_col6 = st.columns(2)
            
            with spares_col5:
                st.markdown("##### Orders by Market")
                if 'MARKET' in spares_data.columns:
                    site_col_for_mkt = 'SITE' if 'SITE' in spares_data.columns else 'SITE_ID' if 'SITE_ID' in spares_data.columns else None
                    if site_col_for_mkt:
                        market_counts = spares_data.groupby('MARKET').agg(
                            COUNT=('MARKET', 'size'),
                            SITE_COUNT=(site_col_for_mkt, 'nunique')
                        ).reset_index()
                    else:
                        market_counts = spares_data['MARKET'].value_counts().head(15).reset_index()
                        market_counts.columns = ['MARKET', 'COUNT']
                        market_counts['SITE_COUNT'] = 0
                    market_counts = market_counts.sort_values('COUNT', ascending=False).head(15)
                    market_counts = market_counts.sort_values('COUNT', ascending=True)
                    
                    mkt_bar_text = [f"{row['COUNT']} orders | {row['SITE_COUNT']} sites" for _, row in market_counts.iterrows()]
                    fig_market = go.Figure(go.Bar(
                        x=market_counts['COUNT'],
                        y=market_counts['MARKET'],
                        orientation='h',
                        marker_color=market_counts['COUNT'],
                        marker_colorscale=TMOBILE_COLORSCALE,
                        text=mkt_bar_text,
                        textposition='inside',
                        textfont=dict(color='white', size=11, family='Arial Black'),
                        insidetextanchor='end',
                        hoverinfo='skip',
                    ))
                    fig_market.update_layout(
                        template='plotly_white',
                        height=450,
                        showlegend=False,
                        hovermode=False,
                        xaxis_title='Orders',
                        yaxis_title='',
                        margin=dict(l=160),
                    )
                    st.plotly_chart(fig_market, use_container_width=True, config=CHART_CONFIG, key="hw_orders_market")
            
            with spares_col6:
                st.markdown("##### Staging KPI Distribution")
                if 'STAGING_KPI_GROUPS' in spares_data.columns:
                    staging_counts = spares_data['STAGING_KPI_GROUPS'].fillna('Unknown').value_counts().reset_index()
                    staging_counts.columns = ['KPI_GROUP', 'COUNT']
                    
                    fig_staging = px.pie(
                        staging_counts,
                        values='COUNT',
                        names='KPI_GROUP',
                        title='',
                        color_discrete_sequence=px.colors.sequential.Viridis
                    )
                    fig_staging.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#333333',
                        height=400
                    )
                    fig_staging.update_traces(textposition='inside', textinfo='percent+label')
                    st.plotly_chart(fig_staging, use_container_width=True, config=CHART_CONFIG, key="hw_staging_kpi")
            
            # Detailed table with filters
            st.markdown("##### 📋 Hardware Spares Detail Table")
            
            # Quick filters for the table
            filter_col1, filter_col2, filter_col3 = st.columns(3)
            
            with filter_col1:
                # Market filter
                if 'MARKET' in spares_data.columns:
                    market_options = ['All Markets'] + sorted(spares_data['MARKET'].dropna().unique().tolist())
                    selected_table_market = st.selectbox("Filter by Market", options=market_options, key="hw_spares_market_filter")
                else:
                    selected_table_market = 'All Markets'
            
            with filter_col2:
                # Site filter - combine SITE (spares) and SITE_ID (availability) for full coverage
                site_values = set()
                if 'SITE' in spares_data.columns:
                    site_values.update(spares_data['SITE'].dropna().unique())
                if 'SITE_ID' in spares_data.columns:
                    site_values.update(spares_data['SITE_ID'].dropna().unique())
                if site_values:
                    site_options = ['All Sites'] + sorted(site_values)
                    selected_table_site = st.selectbox("Filter by Site", options=site_options, key="hw_spares_site_filter")
                else:
                    selected_table_site = 'All Sites'
            
            with filter_col3:
                # Order Status filter
                if 'ORDER STATUS' in spares_data.columns:
                    status_options = ['All Statuses'] + sorted(spares_data['ORDER STATUS'].dropna().unique().tolist())
                    selected_table_status = st.selectbox("Filter by Status", options=status_options, key="hw_spares_status_filter")
                else:
                    selected_table_status = 'All Statuses'
            
            display_cols = ['TMS#', 'TROUBLE TICKET', 'SITE_ID', 'MARKET', 'REF_SKU', 'REF_SKU_DESC', 
                          'ORDER STATUS', 'ORDER CREATE DATE', 'FAILURE CODE', 'STAGING_KPI_GROUPS',
                          'SITE_ID_FOCUS_CATEGORY']
            available_cols = [c for c in display_cols if c in spares_data.columns]
            display_df = spares_data[available_cols].copy()
            
            # Apply table filters
            if selected_table_market != 'All Markets' and 'MARKET' in display_df.columns:
                display_df = display_df[display_df['MARKET'] == selected_table_market]
            if selected_table_site != 'All Sites':
                site_mask = pd.Series(False, index=display_df.index)
                if 'SITE' in display_df.columns:
                    site_mask = site_mask | (display_df['SITE'] == selected_table_site)
                if 'SITE_ID' in display_df.columns:
                    site_mask = site_mask | (display_df['SITE_ID'] == selected_table_site)
                display_df = display_df[site_mask]
            if selected_table_status != 'All Statuses' and 'ORDER STATUS' in display_df.columns:
                display_df = display_df[display_df['ORDER STATUS'] == selected_table_status]
            
            # Format date
            if 'ORDER CREATE DATE' in display_df.columns:
                display_df['ORDER CREATE DATE'] = pd.to_datetime(display_df['ORDER CREATE DATE']).dt.strftime('%Y-%m-%d')
            
            # Remove duplicate rows
            display_df = display_df.drop_duplicates()
            
            # Show row count
            st.caption(f"Showing {len(display_df):,} records")
            
            # Single scrollbar: let the dataframe handle all scrolling internally
            st.markdown("""<style>
            .spares-detail [data-testid="stDataFrame"] > div {overflow: hidden !important;}
            </style><div class="spares-detail">""", unsafe_allow_html=True)
            st.dataframe(display_df, use_container_width=True, height=500, hide_index=True)
            st.markdown("</div>", unsafe_allow_html=True)
            
            # Download button (downloads filtered data)
            csv_data = display_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Hardware Spares Data",
                data=csv_data,
                file_name="hardware_spares_data.csv",
                mime="text/csv",
                key="download_hw_spares"
            )
        else:
            st.info("No spare orders found matching Hardware focus category outages in the selected date range.")
    except Exception as e:
        st.error(f"Spares analysis error: {e}")

def lse_data_dashboard(conn, days, filters):
    """LSE Data Analysis - Correlate incidents with COTTR service outages"""
    st.markdown('<div class="section-header">📋 LSE Data Analysis</div>', unsafe_allow_html=True)
    st.markdown("Correlate Parent Incident Numbers with COTTR Service Outages")
    
    # User input for incident numbers
    st.markdown("### 🎫 Enter Parent Incident Numbers")
    default_incidents = "INC118253396,INC124963888,INC116876374,INC122774333"
    incident_input = st.text_area(
        "Enter PARENT_INCIDENT_NUMBERs (comma-separated):",
        value=default_incidents,
        height=100,
        help="Enter incident numbers separated by commas. Example: INC118253396,INC124963888"
    )
    
    # Parse incident numbers
    incident_list = [inc.strip().strip("'\"") for inc in incident_input.split(',') if inc.strip()]
    
    if not incident_list:
        st.warning("Please enter at least one incident number.")
        return
    
    # Format for SQL IN clause
    incident_sql_list = "'" + "','".join(incident_list) + "'"
    
    st.markdown(f"**Analyzing {len(incident_list)} incident(s):** {', '.join(incident_list[:5])}{'...' if len(incident_list) > 5 else ''}")
    
    analyze_btn = st.button("🔍 Analyze Incidents", type="primary", use_container_width=True)
    
    if analyze_btn or st.session_state.get('lse_analyzed'):
        st.session_state['lse_analyzed'] = True
        
        with st.spinner("Fetching incident data..."):
            # Step 1: Get incident details with parent description, dates, and COTTR outage minutes
            # Using 24-hour window from PARENT_OPENED_DATE instead of RESOLVED_DATE
            incident_query = f"""
            WITH incidents AS (
                SELECT 
                    child.INCIDENT_NUMBER,
                    child.PARENT_INCIDENT_NUMBER,
                    child.CONFIG_ITEM,
                    child.OPENED_DATE,
                    child.RESOLVED_DATE,
                    child.SHORT_DESCRIPTION,
                    child.PRIORITY,
                    child.STATE,
                    parent.SHORT_DESCRIPTION as PARENT_DESCRIPTION,
                    parent.OPENED_DATE as PARENT_OPENED_DATE,
                    DATEADD(hour, 24, parent.OPENED_DATE) as PARENT_24HR_END
                FROM {TABLES['incident_all']} child
                LEFT JOIN {TABLES['incident_all']} parent 
                    ON child.PARENT_INCIDENT_NUMBER = parent.INCIDENT_NUMBER
                WHERE child.PARENT_INCIDENT_NUMBER IN ({incident_sql_list})
                  AND child.CONFIG_ITEM IS NOT NULL
            )
            SELECT 
                i.*,
                COALESCE(SUM(c.PER_DAY_OUTAGE_MINUTES), 0) as COTTR_OUTAGE_MINS
            FROM incidents i
            LEFT JOIN {TABLES['cottr']} c
                ON c.SITE_CD = i.CONFIG_ITEM
                AND c.PER_DAY_LOCAL_DATE >= DATE(i.PARENT_OPENED_DATE)
                AND c.PER_DAY_LOCAL_DATE <= DATE(i.PARENT_24HR_END)
                AND c.SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
                AND c.SITE_CD NOT LIKE 'USC%'
            GROUP BY 
                i.INCIDENT_NUMBER,
                i.PARENT_INCIDENT_NUMBER,
                i.CONFIG_ITEM,
                i.OPENED_DATE,
                i.RESOLVED_DATE,
                i.SHORT_DESCRIPTION,
                i.PRIORITY,
                i.STATE,
                i.PARENT_DESCRIPTION,
                i.PARENT_OPENED_DATE,
                i.PARENT_24HR_END
            ORDER BY i.OPENED_DATE DESC
            """
            
            try:
                incidents_df = run_query(conn, incident_query)
            except Exception as e:
                st.error(f"Error fetching incidents: {e}")
                return
            
            if incidents_df.empty:
                st.warning("No incidents found with CONFIG_ITEM for the provided PARENT_INCIDENT_NUMBERs.")
                return
            
            st.markdown("---")
            st.markdown("### 📋 Related Incidents Found")
            st.dataframe(incidents_df, use_container_width=True, height=200)
            st.markdown(f"**Total child incidents:** {len(incidents_df)}")
            
            # Get date range from PARENT incidents (using 24-hour window)
            incidents_df['OPENED_DATE'] = pd.to_datetime(incidents_df['OPENED_DATE'])
            incidents_df['RESOLVED_DATE'] = pd.to_datetime(incidents_df['RESOLVED_DATE'])
            incidents_df['PARENT_OPENED_DATE'] = pd.to_datetime(incidents_df['PARENT_OPENED_DATE'])
            incidents_df['PARENT_24HR_END'] = pd.to_datetime(incidents_df['PARENT_24HR_END'])
            
            # Use PARENT dates for the overall date range (24-hour window from opened)
            min_date = incidents_df['PARENT_OPENED_DATE'].min()
            max_date = incidents_df['PARENT_24HR_END'].max()
            
            st.markdown(f"**Parent Incident Analysis Window (24-hour):** {min_date.strftime('%Y-%m-%d %H:%M')} to {max_date.strftime('%Y-%m-%d %H:%M')}")
            
            # Get unique CONFIG_ITEMs (site IDs)
            config_items = incidents_df['CONFIG_ITEM'].dropna().unique().tolist()
            config_items_sql = "'" + "','".join(config_items) + "'"
            
            st.markdown("---")
            st.markdown("### 🔗 COTTR Correlation Analysis")
            
            # Step 2: Query COTTR for these sites during PARENT incident 24-hour window
            cottr_correlated_query = f"""
            WITH incident_sites AS (
                SELECT DISTINCT
                    child.CONFIG_ITEM,
                    child.INCIDENT_NUMBER,
                    child.PARENT_INCIDENT_NUMBER,
                    DATE(parent.OPENED_DATE) as PARENT_OPENED,
                    DATE(DATEADD(hour, 24, parent.OPENED_DATE)) as PARENT_24HR_END
                FROM {TABLES['incident_all']} child
                LEFT JOIN {TABLES['incident_all']} parent
                    ON child.PARENT_INCIDENT_NUMBER = parent.INCIDENT_NUMBER
                WHERE child.PARENT_INCIDENT_NUMBER IN ({incident_sql_list})
                  AND child.CONFIG_ITEM IS NOT NULL
            )
            SELECT 
                c.SITE_CD,
                i.PARENT_INCIDENT_NUMBER,
                i.PARENT_OPENED,
                i.PARENT_24HR_END,
                c.PER_DAY_LOCAL_DATE,
                c.SERVICEIMPACTCRITERIA,
                c.SITE_ID_SUMMARY_CATEGORY,
                c.SITE_ID_FOCUS_CATEGORY,
                c.PER_DAY_OUTAGE_MINUTES,
                c.MKT_NAME,
                i.INCIDENT_NUMBER
            FROM {TABLES['cottr']} c
            INNER JOIN incident_sites i
                ON c.SITE_CD = i.CONFIG_ITEM
                AND c.PER_DAY_LOCAL_DATE >= i.PARENT_OPENED
                AND c.PER_DAY_LOCAL_DATE <= i.PARENT_24HR_END
            WHERE c.SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
              AND c.SITE_CD NOT LIKE 'USC%'
            ORDER BY c.SITE_CD, c.PER_DAY_LOCAL_DATE
            """
            
            try:
                cottr_correlated = run_query(conn, cottr_correlated_query)
            except Exception as e:
                st.error(f"Error fetching COTTR data: {e}")
                cottr_correlated = pd.DataFrame()
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### ✅ Correlated Service Outages")
                st.markdown("Sites from incidents that had SERVICE OUTAGE during 24-hour window")
                
                if not cottr_correlated.empty:
                    st.dataframe(cottr_correlated, use_container_width=True, height=300)
                    
                    # Summary stats
                    corr_sites = cottr_correlated['SITE_CD'].nunique()
                    corr_outages = len(cottr_correlated)
                    corr_mins = cottr_correlated['PER_DAY_OUTAGE_MINUTES'].sum()
                    
                    st.markdown(f"""
                    <div style='background: linear-gradient(135deg, #1a472a, #2d5a3d); padding: 15px; border-radius: 8px; margin-top: 10px;'>
                        <div style='color: #4ade80; font-size: 1.5rem; font-weight: bold;'>{corr_sites} Sites Confirmed</div>
                        <div style='color: #86efac;'>{corr_outages} outage days | {corr_mins:,.0f} total mins</div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.info("No SERVICE OUTAGE found for incident sites during the incident period.")
            
            # Step 3: Find other Transport sites with SERVICE OUTAGE (uncorrelated)
            with col2:
                st.markdown("#### ⚠️ Potentially Related (Uncorrelated)")
                st.markdown("Other Transport sites with SERVICE OUTAGE during 24-hour window")
                
                uncorrelated_query = f"""
                SELECT 
                    SITE_CD,
                    PER_DAY_LOCAL_DATE,
                    SERVICEIMPACTCRITERIA,
                    SITE_ID_SUMMARY_CATEGORY,
                    SITE_ID_FOCUS_CATEGORY,
                    PER_DAY_OUTAGE_MINUTES,
                    MKT_NAME
                FROM {TABLES['cottr']}
                WHERE SITE_CD NOT IN ({config_items_sql})
                  AND SITE_CD NOT LIKE 'USC%'
                  AND PER_DAY_LOCAL_DATE >= '{min_date.strftime('%Y-%m-%d')}'
                  AND PER_DAY_LOCAL_DATE <= '{max_date.strftime('%Y-%m-%d')}'
                  AND SERVICEIMPACTCRITERIA = 'SERVICE OUTAGE'
                  AND SITE_ID_SUMMARY_CATEGORY = 'Transport'
                ORDER BY PER_DAY_LOCAL_DATE, SITE_CD
                """
                
                try:
                    uncorrelated_df = run_query(conn, uncorrelated_query)
                except Exception as e:
                    st.error(f"Error fetching uncorrelated data: {e}")
                    uncorrelated_df = pd.DataFrame()
                
                if not uncorrelated_df.empty:
                    st.dataframe(uncorrelated_df, use_container_width=True, height=300)
                    
                    uncorr_sites = uncorrelated_df['SITE_CD'].nunique()
                    uncorr_outages = len(uncorrelated_df)
                    uncorr_mins = uncorrelated_df['PER_DAY_OUTAGE_MINUTES'].sum()
                    
                    st.markdown(f"""
                    <div style='background: linear-gradient(135deg, #7f1d1d, #991b1b); padding: 15px; border-radius: 8px; margin-top: 10px;'>
                        <div style='color: #fca5a5; font-size: 1.5rem; font-weight: bold;'>{uncorr_sites} Sites Flagged</div>
                        <div style='color: #fecaca;'>{uncorr_outages} outage days | {uncorr_mins:,.0f} total mins</div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.info("No additional Transport SERVICE OUTAGE sites found in this period.")
            
            # Charts
            st.markdown("---")
            st.markdown("### 📊 Visualization")
            
            chart_col1, chart_col2 = st.columns(2)
            
            with chart_col1:
                # Chart 1: Correlated outages by day
                if not cottr_correlated.empty:
                    daily_corr = cottr_correlated.groupby('PER_DAY_LOCAL_DATE').agg({
                        'SITE_CD': 'nunique',
                        'PER_DAY_OUTAGE_MINUTES': 'sum'
                    }).reset_index()
                    daily_corr.columns = ['Date', 'Sites', 'Outage Minutes']
                    
                    fig1 = px.bar(
                        daily_corr,
                        x='Date',
                        y='Outage Minutes',
                        title='Correlated Sites - Daily Outage Minutes',
                        color_discrete_sequence=['#4ade80']
                    )
                    fig1.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#333333',
                        height=350
                    )
                    st.plotly_chart(fig1, use_container_width=True, config=CHART_CONFIG, key="lse_corr_daily")
            
            with chart_col2:
                # Chart 2: Uncorrelated outages by day
                if not uncorrelated_df.empty:
                    daily_uncorr = uncorrelated_df.groupby('PER_DAY_LOCAL_DATE').agg({
                        'SITE_CD': 'nunique',
                        'PER_DAY_OUTAGE_MINUTES': 'sum'
                    }).reset_index()
                    daily_uncorr.columns = ['Date', 'Sites', 'Outage Minutes']
                    
                    fig2 = px.bar(
                        daily_uncorr,
                        x='Date',
                        y='Outage Minutes',
                        title='Uncorrelated Transport Sites - Daily Outage Minutes',
                        color_discrete_sequence=['#f87171']
                    )
                    fig2.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#333333',
                        height=350
                    )
                    st.plotly_chart(fig2, use_container_width=True, config=CHART_CONFIG, key="lse_uncorr_daily")
            
            # Chart 3: Category breakdown
            st.markdown("### 📈 Category Breakdown")
            
            cat_col1, cat_col2 = st.columns(2)
            
            with cat_col1:
                if not cottr_correlated.empty:
                    cat_corr = cottr_correlated.groupby('SITE_ID_FOCUS_CATEGORY')['PER_DAY_OUTAGE_MINUTES'].sum().reset_index()
                    cat_corr.columns = ['Focus Category', 'Outage Minutes']
                    cat_corr = cat_corr.sort_values('Outage Minutes', ascending=True)
                    
                    fig3 = px.bar(
                        cat_corr,
                        x='Outage Minutes',
                        y='Focus Category',
                        orientation='h',
                        title='Correlated - Outage by Focus Category',
                        color_discrete_sequence=['#22c55e']
                    )
                    fig3.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#333333',
                        height=350
                    )
                    st.plotly_chart(fig3, use_container_width=True, config=CHART_CONFIG, key="lse_corr_cat")
            
            with cat_col2:
                if not uncorrelated_df.empty:
                    cat_uncorr = uncorrelated_df.groupby('SITE_ID_FOCUS_CATEGORY')['PER_DAY_OUTAGE_MINUTES'].sum().reset_index()
                    cat_uncorr.columns = ['Focus Category', 'Outage Minutes']
                    cat_uncorr = cat_uncorr.sort_values('Outage Minutes', ascending=True)
                    
                    fig4 = px.bar(
                        cat_uncorr,
                        x='Outage Minutes',
                        y='Focus Category',
                        orientation='h',
                        title='Uncorrelated Transport - Outage by Focus Category',
                        color_discrete_sequence=['#ef4444']
                    )
                    fig4.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#333333',
                        height=350
                    )
                    st.plotly_chart(fig4, use_container_width=True, config=CHART_CONFIG, key="lse_uncorr_cat")
            
            # Market breakdown chart
            st.markdown("### 🗺️ Market Distribution")
            
            all_outages = pd.concat([
                cottr_correlated.assign(Type='Correlated') if not cottr_correlated.empty else pd.DataFrame(),
                uncorrelated_df.assign(Type='Uncorrelated') if not uncorrelated_df.empty else pd.DataFrame()
            ])
            
            if not all_outages.empty:
                # Normalize market names to Global Market ID format before aggregation
                if 'MKT_NAME' in all_outages.columns:
                    all_outages = normalize_market_column(all_outages, 'MKT_NAME', 'cottr')
                market_summary = all_outages.groupby(['MKT_NAME', 'Type']).agg({
                    'SITE_CD': 'nunique',
                    'PER_DAY_OUTAGE_MINUTES': 'sum'
                }).reset_index()
                market_summary.columns = ['Market', 'Type', 'Sites', 'Outage Minutes']
                
                fig5 = px.bar(
                    market_summary,
                    x='Market',
                    y='Outage Minutes',
                    color='Type',
                    barmode='group',
                    title='Service Outages by Market',
                    color_discrete_map={'Correlated': '#22c55e', 'Uncorrelated': '#ef4444'}
                )
                fig5.update_layout(
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    font_color='#333333',
                    height=400,
                    xaxis_tickangle=-45
                )
                st.plotly_chart(fig5, use_container_width=True, config=CHART_CONFIG, key="lse_market_dist")

# ==================== DATA PRE-LOADING SYSTEM ====================
def preload_critical_data(conn, days, filters):
    """Pre-load all critical data for instant tab switching"""
    init_session_state_cache()
    
    if st.session_state.get('preload_complete'):
        return  # Already preloaded
    
    # Generate cache key based on current filters
    filters_hash = hashlib.md5(str(filters).encode()).hexdigest()[:8]
    
    # List of critical data to preload (function, cache_key)
    preload_tasks = []
    
    try:
        # Pre-fetch filter options (used by sidebar)
        if 'filter_options' not in st.session_state.data_cache:
            filter_opts = get_filter_options(conn)
            cache_data_in_session('filter_options', filter_opts)
        
        # Pre-fetch market list
        if 'market_list' not in st.session_state.data_cache:
            markets = get_market_list(conn)
            cache_data_in_session('market_list', markets)
        
        # Pre-fetch combined daily data (used by multiple tabs)
        cache_key = f'combined_daily_{days}_{filters_hash}'
        if cache_key not in st.session_state.data_cache:
            try:
                data = get_combined_daily_data_cached(conn, days, filters_hash)
                if data is not None:
                    cache_data_in_session(cache_key, data)
                    # Also save to disk for persistence
                    save_to_disk_cache(cache_key, data)
            except Exception:
                pass
        
        st.session_state.preload_complete = True
        
    except Exception as e:
        pass  # Silently fail - preloading is optional optimization

def preload_default_data_on_startup(conn):
    """
    Preload default 'last 7 days' data immediately on startup.
    This runs ONCE when the app first loads to ensure instant response.
    """
    if st.session_state.get('startup_preload_complete'):
        return  # Already done
    
    try:
        default_start = (date.today() - timedelta(days=7)).strftime('%Y-%m-%d')
        default_end = date.today().strftime('%Y-%m-%d')
        default_filters = {
            'market': None,
            'site': None,
            'outage_type': None,
            'focus_category': None,
            'top_source': None,
            'site_type': 'Macro',
            'oem': None,
            'cohort': None,
            'cohort_markets': None,
            'start_date': default_start,
            'end_date': default_end
        }
        default_filters_hash = filters_to_hashable(default_filters)
        
        default_avail_filter = build_filter_clause(default_filters, 'availability')
        startup_fns = [
            lambda: get_combined_daily_data_cached(conn, 7, default_filters_hash),
            lambda: get_focus_category_totals_cached(conn, 7, default_filters_hash),
            lambda: get_focus_category_totals_cottr_cached(conn, 7, default_filters_hash),
            lambda: get_market_totals_cached(conn, 7, default_filters_hash),
            lambda: get_market_by_summary_category_cached(conn, 7, default_filters_hash),
            lambda: get_market_by_focus_category_cached(conn, 7, default_filters_hash),
            lambda: get_cottr_market_by_focus_category_cached(conn, 7, default_filters_hash),
            lambda: get_cottr_by_summary_category_cached(conn, 7, default_filters_hash),
            lambda: get_availability_with_downtime_by_summary_cached(conn, 7, default_filters_hash),
            lambda: get_impacted_subs_by_market_cached(conn, 7, default_filters_hash),
            lambda: get_impacted_subs_by_market_and_category_cached(conn, 7, default_filters_hash),
            lambda: get_market_daily_availability_cached(conn, 7, default_filters_hash),
            lambda: get_unavailability_data(conn, default_start, default_end, 7, ('Macro',), default_avail_filter, None),
            lambda: get_unavailability_all_sites_data(conn, default_start, default_end, 7, ('Macro',), default_avail_filter, None),
        ]
        with ThreadPoolExecutor(max_workers=min(len(startup_fns), MAX_CONCURRENT_QUERIES)) as executor:
            futures = [executor.submit(fn) for fn in startup_fns]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    pass
        
        st.session_state.startup_preload_complete = True
        
        # DISABLED for production: Background preloading of markets causes connection exhaustion
        # Data will be cached on-demand instead
        # preload_common_markets_background(conn)
        
    except Exception:
        pass  # Silently fail

def preload_common_markets_background(conn):
    """
    Preload data for common/popular markets in the background.
    This runs after the initial page load to cache data for frequently accessed markets.
    Preloads top 30 markets (Cohort 1 + some Cohort 2) for instant access.
    """
    if st.session_state.get('markets_preload_complete'):
        return  # Already done
    
    try:
        # Top 30 markets to preload - using Global Market IDs
        # Prioritizes Cohort 1 (major metros) + high-traffic Cohort 2 markets
        MARKETS_TO_PRELOAD = [
            # Cohort 1 - Major Metros (all 25)
            'Atlanta', 'Austin', 'Chicago', 'Dallas', 'Denver', 'Detroit',
            'Houston', 'Kansas City', 'Los Angeles', 'Miami', 'Minneapolis',
            'Mobile', 'New England', 'New Jersey', 'New York', 'North Carolina',
            'Oklahoma City', 'Philadelphia', 'Phoenix', 'Salt Lake City',
            'San Francisco', 'Seattle', 'Southern California', 'St. Louis', 'Washington DC',
            # Top Cohort 2 markets (5 more)
            'Jacksonville', 'Orlando', 'Tampa', 'Sacramento', 'Nashville'
        ]
        
        default_start = (date.today() - timedelta(days=7)).strftime('%Y-%m-%d')
        default_end = date.today().strftime('%Y-%m-%d')
        
        def preload_market_data(market):
            """Preload data for a single market"""
            try:
                market_filters = {
                    'market': market,
                    'site': None,
                    'outage_type': None,
                    'focus_category': None,
                    'top_source': None,
                    'site_type': 'Macro',
                    'oem': None,
                    'cohort': None,
                    'cohort_markets': None,
                    'start_date': default_start,
                    'end_date': default_end
                }
                market_filters_hash = filters_to_hashable(market_filters)
                
                # Preload core data for this market
                get_combined_daily_data_cached(conn, 7, market_filters_hash)
                get_focus_category_totals_cached(conn, 7, market_filters_hash)
                get_market_by_focus_category_cached(conn, 7, market_filters_hash)
                get_cottr_market_by_focus_category_cached(conn, 7, market_filters_hash)
                
            except Exception:
                pass  # Silently fail for individual markets
        
        # Preload markets in parallel (use PRELOAD_WORKERS for faster preloading)
        with ThreadPoolExecutor(max_workers=PRELOAD_WORKERS) as executor:
            futures = [executor.submit(preload_market_data, market) for market in MARKETS_TO_PRELOAD]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass
        
        st.session_state.markets_preload_complete = True
        
    except Exception:
        pass  # Silently fail

def main():
    # OPTIMIZATION: Clear per-render cache at start of each page load
    clear_render_cache()
    
    icon_path = os.path.join(os.path.dirname(__file__), 'dashboard_icon.png')
    if os.path.exists(icon_path):
        with open(icon_path, 'rb') as f:
            icon_base64 = base64.b64encode(f.read()).decode()
        st.markdown(f'<div class="main-header"><img src="data:image/png;base64,{icon_base64}" style="height:65px;vertical-align:middle;margin-right:15px;">Network Insights Dashboard</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="main-header">📊 Network Insights Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Combined view: Availability + COTTR + Customer Minutes</div>', unsafe_allow_html=True)
    
    # Set user email (used for admin check and connection)
    _cfg = load_config()
    user_email = (
        "sis_user@t-mobile.com" if IS_RUNNING_IN_SIS else (
            (_cfg.get('user_email') if _cfg else None) or 'shawn.rivera@t-mobile.com'
        )
    )
    
    # Auto-connect on page load (both SiS and local development)
    if not st.session_state.get('connected'):
        if IS_RUNNING_IN_SIS:
            conn = get_connection()
        else:
            conn = get_connection(user_email)
        
        if conn:
            st.session_state['connected'] = True
            st.session_state['connection'] = conn
            if not st.session_state.get('preload_started'):
                st.session_state['preload_started'] = True
                preload_thread = threading.Thread(target=preload_default_data_on_startup, args=(conn,), daemon=True)
                preload_thread.start()
    
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Show email for local development (read-only info)
        if not IS_RUNNING_IN_SIS:
            st.text_input("T-Mobile Email", value=user_email, key="email", disabled=True)
        
        days = st.selectbox("Time Range", options=[1, 3, 7, 14, 30], index=2,
                           format_func=lambda x: f"Last {x} day{'s' if x > 1 else ''}")
        
        st.divider()
        st.header("📊 Data Sources")
        st.markdown("""
        <div style='font-size: 0.85rem;'>
        <b style='color: #e20074;'>●</b> Customer Minutes V2<br>
        <b style='color: #22c55e;'>●</b> All In Availability<br>
        <b style='color: #f59e0b;'>●</b> COTTR
        </div>
        """, unsafe_allow_html=True)
        
        # Show connection status
        if st.session_state.get('connected'):
            st.success("✅ Connected to Snowflake")
    
    if not st.session_state.get('connected'):
        st.error("❌ Failed to connect to Snowflake. Please check your credentials.")
        return
    
    conn = st.session_state.get('connection')
    
    # Load OEM mappings from MARKET_TRACKER (once per session)
    load_oem_cohort_mappings(conn)
    
    filter_options = get_filter_options(conn)
    markets = get_market_list(conn)
    
    with st.sidebar:
        # Placeholder for active filters (will be filled after filters are defined)
        active_filters_placeholder = st.empty()
        
        st.divider()
        st.header("🔍 Filters")
        
        date_col1, date_col2 = st.columns(2)
        with date_col1:
            start_date = st.date_input("Start Date", value=date.today() - timedelta(days=days))
        with date_col2:
            end_date = st.date_input("End Date", value=date.today())
        
        site_id_input = st.text_input("Site ID", placeholder="e.g., DCY0503A")
        site_filter = site_id_input.strip() if site_id_input else None
        
        # Multi-select for markets (empty selection = all markets)
        # Display format: "Market (OEM)" but filter uses just "Market"
        selected_markets_display = st.multiselect("Market Id", options=markets, default=[], placeholder="All Markets")
        # Extract just the market names for filtering
        selected_markets = [extract_market_from_display(m) for m in selected_markets_display] if selected_markets_display else []
        market_filter = selected_markets if selected_markets else None
        
        outage_options = ["(All)"] + filter_options.get('outage_type', [])
        selected_outage = st.selectbox("Outage Type", options=outage_options, index=0)
        outage_filter = None if selected_outage == "(All)" else selected_outage
        
        focus_options = ["(All)"] + filter_options.get('focus_category', [])
        selected_focus = st.selectbox("Site Id Focus Category", options=focus_options, index=0)
        focus_filter = None if selected_focus == "(All)" else selected_focus
        
        source_options = ["(All)"] + filter_options.get('top_source', [])
        selected_source = st.selectbox("Top Source Name", options=source_options, index=0)
        source_filter = None if selected_source == "(All)" else selected_source
        
        site_type_options = ["Macro", "Non-Macro", "(All)"]
        # Default to Non-Macro when on the Non-Macro V1 vs V2 tab or when auto-switch is triggered
        if st.session_state.get('nonmacro_auto_switch'):
            default_site_type_index = 1  # Non-Macro
            st.session_state.nonmacro_auto_switch = False  # Reset the flag
        elif st.session_state.get('active_tab') == "🔄 Non-Macro V1 vs V2":
            default_site_type_index = 1  # Non-Macro
        else:
            default_site_type_index = 0  # Macro
        selected_site_type = st.selectbox("Site Type", options=site_type_options, index=default_site_type_index, key="site_type_select")
        site_type_filter = None if selected_site_type == "(All)" else selected_site_type
        
        filters = {
            'market': market_filter,
            'site': site_filter,
            'outage_type': outage_filter,
            'focus_category': focus_filter,
            'top_source': source_filter,
            'site_type': site_type_filter,
            'oem': None,
            'cohort': None,
            'cohort_markets': None,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d')
        }
        
        # Show active filters summary with highlighting (at the top using placeholder)
        active_filters = []
        if market_filter:
            if len(market_filter) == 1:
                active_filters.append(f"🎯 Market: **{market_filter[0]}**")
            else:
                active_filters.append(f"🎯 Markets: **{len(market_filter)} selected**")
        if site_filter:
            active_filters.append(f"📍 Site: **{site_filter}**")
        if site_type_filter:
            active_filters.append(f"🏗️ Type: **{site_type_filter}**")
        if outage_filter:
            active_filters.append(f"⚡ Outage: **{outage_filter}**")
        if focus_filter:
            active_filters.append(f"🔍 Focus: **{focus_filter}**")
        
        # Render active filters at the top using the placeholder
        if active_filters:
            filter_items = []
            for f in active_filters:
                parts = f.split('**')
                if len(parts) >= 3:
                    filter_items.append(f'{parts[0]}<b style="color:#e20074;">{parts[1]}</b>{parts[2] if len(parts) > 2 else ""}')
                else:
                    filter_items.append(f)
            with active_filters_placeholder.container():
                st.markdown("### 🔔 Active Filters")
                st.markdown(f"""
                <div style='background: linear-gradient(135deg, #f8f9fa, #e9ecef); padding: 12px; border-radius: 8px; border-left: 4px solid #e20074; color: white; font-size: 0.9rem;'>
                    {' <span style="color:#666; margin: 0 5px;">|</span> '.join(filter_items)}
                </div>
                """, unsafe_allow_html=True)
    
    # OPTIMIZATION: Preload common data once per filter set (deduped in preload_common_data)
    preload_common_data(conn, days, filters)

    _export_key = (days, filters_to_hashable(filters))
    if st.session_state.get('combined_daily_csv_key') != _export_key:
        out_path = export_combined_daily_csv(conn, days, filters)
        if out_path:
            st.session_state['combined_daily_csv_key'] = _export_key
            st.session_state['combined_daily_csv_path'] = out_path

    # Cache control in sidebar
    with st.sidebar:
        st.divider()
        st.markdown("### ⚡ Performance")
        cache, _ = get_query_cache()
        cache_count = len(cache)
        cache_hours = DATA_CACHE_TTL // 3600
        st.caption(f"Cached queries: {cache_count} (TTL: {cache_hours}h)")
        st.caption("Data auto-refreshes every 24 hours")
        if st.session_state.get('combined_daily_csv_path'):
            st.caption(f"Combined daily CSV: `{os.path.basename(st.session_state['combined_daily_csv_path'])}`")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Clear Cache", use_container_width=True, help="Clear query cache"):
                clear_query_cache()
                st.success("Query cache cleared!")
                st.rerun()
        with col2:
            if st.button("🔃 Force Refresh", use_container_width=True, help="Force refresh all data"):
                clear_query_cache()
                st.cache_data.clear()
                # Clear preload cache key to force re-preload
                if 'preload_cache_key' in st.session_state:
                    del st.session_state['preload_cache_key']
                st.success("All data refreshed!")
                st.rerun()
    
    # Dashboard tabs with lazy loading
    # NOTE: Region Availability and Area Availability tabs removed but functions preserved:
    #   - region_availability_summary(conn, days, filters)
    #   - area_availability_summary(conn, days, filters)
    
    # Admin users who can see restricted tabs (OEM Comparison, Executive 2, AAV Analysis, Hardware, Data Diagnostics)
    ADMIN_EMAILS = ['shawn.rivera@t-mobile.com', 'srivera12']
    is_admin = any(admin.lower() in user_email.lower() for admin in ADMIN_EMAILS) if user_email else False
    
    # Tab names - conditionally include admin-only tabs (fully hidden for non-admins)
    # Public tabs available to all users
    TAB_NAMES = [
        "🎯 Executive Summary",
        "🏗️ Site Analysis", 
        "📉 Unavailability",
        "🔄 Non-Macro V1 vs V2",
        "📡 Inactive Sector",
        "📋 LSE Data",
        "⚡ OEM Comparison",
        "🔧 Hardware",
    ]
    
    # Admin-only tabs (hidden from non-admins)
    ADMIN_TAB_NAMES = [
        "🧪 Exec Summary V2",
        "📡 AAV Analysis",
        "🔧 Data Diagnostics",
    ]
    
    if is_admin:
        TAB_NAMES.extend(ADMIN_TAB_NAMES)
    
    # OPTIMIZATION: Use selectbox for tab selection to enable true lazy loading
    # This prevents all tabs from loading their data on every filter change
    selected_tab = st.selectbox(
        "📊 Select Dashboard",
        options=TAB_NAMES,
        index=TAB_NAMES.index(st.session_state.get('selected_tab', TAB_NAMES[0])) if st.session_state.get('selected_tab') in TAB_NAMES else 0,
        key="tab_selector",
        label_visibility="collapsed"
    )
    st.session_state.selected_tab = selected_tab
    
    st.divider()
    
    # Global loading placeholder - shows "Loading..." banner during data fetch
    loading_placeholder = st.empty()
    loading_placeholder.markdown(
        '<div style="text-align:center;padding:20px;color:#e20074;font-size:1.1rem;font-weight:600;">'
        '⏳ Loading data... please wait</div>',
        unsafe_allow_html=True
    )
    
    # OPTIMIZATION: Only load the selected dashboard (true lazy loading)
    # This dramatically speeds up filter changes since only 1 dashboard loads instead of all
    if selected_tab == "🎯 Executive Summary":
        executive_summary_dashboard(conn, days, filters)
    elif selected_tab == "🏗️ Site Analysis":
        site_analysis_dashboard(conn, days, filters)
    elif selected_tab == "📉 Unavailability":
        unavailability_dashboard(conn, days, filters)
    elif selected_tab == "🔄 Non-Macro V1 vs V2":
        nonmacro_comparison_dashboard(conn, days, filters)
    elif selected_tab == "📡 Inactive Sector":
        inactive_sector_dashboard(conn, days, filters)
    elif selected_tab == "📋 LSE Data":
        lse_data_dashboard(conn, days, filters)
    elif selected_tab == "⚡ OEM Comparison":
        oem_comparison_dashboard(conn, days, filters)
    elif selected_tab == "🔧 Hardware":
        hardware_analysis_dashboard(conn, days, filters)
    # Admin-only dashboards
    elif is_admin and selected_tab == "🧪 Exec Summary V2":
        executive_summary_dashboard_v2(conn, days, filters)
    elif is_admin and selected_tab == "📡 AAV Analysis":
        aav_analysis_dashboard(conn, days, filters)
    elif is_admin and selected_tab == "🔧 Data Diagnostics":
        st.markdown('<div class="section-header">🔧 Data Diagnostics</div>', unsafe_allow_html=True)
        
        # Show current filter values for debugging
        st.markdown("### 🔍 Current Filter Values")
        market_val = filters.get('market')
        if market_val:
            market_display_debug = market_val if isinstance(market_val, list) else [market_val]
        else:
            market_display_debug = '(All)'
        filter_debug = {
            'Market': market_display_debug,
            'Site': filters.get('site') or '(None)',
            'Start Date': filters.get('start_date'),
            'End Date': filters.get('end_date'),
            'Outage Type': filters.get('outage_type') or '(All)',
            'Vendor': filters.get('vendor') or '(All)',
            'Focus Category': filters.get('focus_category') or '(All)',
        }
        st.json(filter_debug)
        
        # Show generated SQL filter clauses
        st.markdown("### 📝 Generated SQL Filter Clauses")
        avail_clause = build_filter_clause(filters, 'availability')
        cottr_clause = build_filter_clause(filters, 'cottr')
        cm_clause = build_filter_clause(filters, 'customer_minutes')
        st.code(f"Availability: {avail_clause or '(none)'}", language="sql")
        st.code(f"COTTR: {cottr_clause or '(none)'}", language="sql")
        st.code(f"Customer Minutes: {cm_clause or '(none)'}", language="sql")
        
        st.divider()
        st.markdown("### 🏷️ Market Abbreviation Lookup")
        st.markdown("This table shows the MARKET_ID to M_MARKET_ABBREVATION mapping from MARKET_TRACKER.")
        
        with st.expander("View Market Abbreviation Mapping", expanded=True):
            market_abbrev_query = """
            SELECT MARKET_ID, M_MARKET_ABBREVATION
            FROM BDM_NDW_MAGENTABUILT_REFERENCE_DB.MAGENTABUILT_REFERENCE.MARKET_TRACKER
            WHERE M_MARKET_ABBREVATION IS NOT NULL
              AND M_MARKET_ABBREVATION != ''
            ORDER BY MARKET_ID
            """
            try:
                market_abbrev_data = run_query(conn, market_abbrev_query)
                if not market_abbrev_data.empty:
                    st.markdown("#### MARKET_TRACKER Reference Table")
                    st.dataframe(market_abbrev_data, height=300, use_container_width=True)
                    st.markdown(f"**Total Mappings in MARKET_TRACKER:** {len(market_abbrev_data)}")
                    
                    # Cross-check with dashboard markets
                    st.markdown("---")
                    st.markdown("#### Cross-Check: Dashboard Markets vs MARKET_TRACKER")
                    
                    # Get unique markets from availability table
                    dashboard_markets_query = f"""
                    SELECT DISTINCT MARKET_ID 
                    FROM {TABLES['availability']}
                    ORDER BY MARKET_ID
                    """
                    dashboard_markets = run_query(conn, dashboard_markets_query)
                    
                    if not dashboard_markets.empty:
                        # Merge to find matches
                        merged = dashboard_markets.merge(
                            market_abbrev_data, 
                            on='MARKET_ID', 
                            how='left'
                        )
                        merged['HAS_ABBREV'] = merged['M_MARKET_ABBREVATION'].notna()
                        
                        matched = merged[merged['HAS_ABBREV'] == True]
                        unmatched = merged[merged['HAS_ABBREV'] == False]
                        
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.markdown(f"✅ **Markets WITH Abbreviation:** {len(matched)}")
                            if not matched.empty:
                                st.dataframe(matched[['MARKET_ID', 'M_MARKET_ABBREVATION']], height=400, use_container_width=True)
                        
                        with col_b:
                            st.markdown(f"⚠️ **Markets WITHOUT Abbreviation:** {len(unmatched)}")
                            if not unmatched.empty:
                                st.dataframe(unmatched[['MARKET_ID']], height=400, use_container_width=True)
                            else:
                                st.success("All dashboard markets have abbreviations!")
                        
                        # Show potential matches for unmatched markets
                        st.markdown("---")
                        st.markdown("#### 🔍 Side-by-Side Comparison")
                        st.markdown("Compare dashboard market names with MARKET_TRACKER to find naming differences:")
                        
                        comp_col1, comp_col2 = st.columns(2)
                        with comp_col1:
                            st.markdown("**Dashboard Markets (Availability)**")
                            st.dataframe(dashboard_markets.sort_values('MARKET_ID'), height=300, use_container_width=True)
                        
                        with comp_col2:
                            st.markdown("**MARKET_TRACKER (MARKET_ID)**")
                            st.dataframe(market_abbrev_data[['MARKET_ID', 'M_MARKET_ABBREVATION']].sort_values('MARKET_ID'), height=300, use_container_width=True)
                else:
                    st.warning("No market abbreviation data found.")
            except Exception as e:
                st.error(f"Error loading market abbreviations: {e}")
            
            st.divider()
            st.markdown("### 🔎 Search Schema Columns")
            with st.expander("Search for Coverage/SLA Columns in MAGENTABUILT_REFERENCE", expanded=True):
                try:
                    # Search all tables in the schema for columns containing Coverage or SLA
                    search_cols_query = """
                    SELECT TABLE_NAME, COLUMN_NAME
                    FROM BDM_NDW_MAGENTABUILT_REFERENCE_DB.INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_SCHEMA = 'MAGENTABUILT_REFERENCE'
                      AND (UPPER(COLUMN_NAME) LIKE '%COVERAGE%' 
                           OR UPPER(COLUMN_NAME) LIKE '%SLA%'
                           OR UPPER(COLUMN_NAME) LIKE '%BUSINESS%CUSTOMER%')
                    ORDER BY TABLE_NAME, COLUMN_NAME
                    """
                    search_results = run_query(conn, search_cols_query)
                    if not search_results.empty:
                        st.markdown("**Columns containing 'Coverage', 'SLA', or 'Business Customer':**")
                        st.dataframe(search_results, height=400, use_container_width=True)
                        st.markdown(f"**Found:** {len(search_results)} columns")
                    else:
                        st.warning("No columns found matching 'Coverage', 'SLA', or 'Business Customer'.")
                except Exception as e:
                    st.error(f"Error: {e}")
            
            st.divider()
            st.markdown("### 🏢 SITE_TRACKER Columns")
            with st.expander("View SITE_TRACKER Column Names", expanded=False):
                try:
                    site_tracker_cols_query = """
                    SELECT COLUMN_NAME 
                    FROM BDM_NDW_MAGENTABUILT_REFERENCE_DB.INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_NAME = 'SITE_TRACKER' AND TABLE_SCHEMA = 'MAGENTABUILT_REFERENCE'
                    ORDER BY ORDINAL_POSITION
                    """
                    site_tracker_cols = run_query(conn, site_tracker_cols_query)
                    if not site_tracker_cols.empty:
                        st.dataframe(site_tracker_cols, height=400, use_container_width=True)
                        st.markdown(f"**Total Columns:** {len(site_tracker_cols)}")
                    else:
                        st.warning("Could not retrieve SITE_TRACKER columns.")
                except Exception as e:
                    st.error(f"Error: {e}")
            
            st.divider()
            st.markdown("### 🗺️ Market Name Comparison")
            st.markdown("""
            This section compares market names across all three data sources to identify naming discrepancies 
            that might affect filtering.
            """)
            
            with st.spinner("Loading market comparison data..."):
                avail_markets, cottr_markets, cm_markets = get_market_comparison(conn)
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("#### Availability Markets")
                st.markdown(f"**Count:** {len(avail_markets)}")
                if not avail_markets.empty:
                    st.dataframe(avail_markets[['MARKET_NAME']].sort_values('MARKET_NAME'), height=400, use_container_width=True)
            
            with col2:
                st.markdown("#### COTTR Markets")
                st.markdown(f"**Count:** {len(cottr_markets)}")
                if not cottr_markets.empty:
                    st.dataframe(cottr_markets[['MARKET_NAME']].sort_values('MARKET_NAME'), height=400, use_container_width=True)
            
            with col3:
                st.markdown("#### Customer Minutes Markets")
                st.markdown(f"**Count:** {len(cm_markets)}")
                if not cm_markets.empty:
                    st.dataframe(cm_markets[['MARKET_NAME']].sort_values('MARKET_NAME'), height=400, use_container_width=True)
            
            st.divider()
            
            # Market matching analysis
            st.markdown("### 🔍 Market Matching Analysis")
            st.markdown("""
            This shows which Availability markets can be matched in COTTR and Customer Minutes tables.
            
            **Note:** Some markets have custom mappings (shown in 'Mapped Name' column):
            """)
            
            # Show current mappings
            if MARKET_NAME_MAPPINGS:
                st.markdown("**Current Mappings:**")
                for avail_name, mapping in MARKET_NAME_MAPPINGS.items():
                    if isinstance(mapping, dict):
                        cottr_map = mapping.get('cottr', avail_name)
                        cm_map = mapping.get('customer_minutes', avail_name)
                        st.markdown(f"- **{avail_name}** → COTTR: `{cottr_map}`, Customer Minutes: `{cm_map}`")
                    else:
                        st.markdown(f"- **{avail_name}** → `{mapping}`")
            
            if not avail_markets.empty:
                avail_list = avail_markets['MARKET_NAME'].tolist()
                cottr_list = cottr_markets['MARKET_NAME'].tolist() if not cottr_markets.empty else []
                cm_list = cm_markets['MARKET_NAME'].tolist() if not cm_markets.empty else []
                
                match_results = []
                for avail_mkt in avail_list:
                    # Get mapped names for each table type
                    cottr_mapped = get_mapped_market_name(avail_mkt, 'cottr')
                    cm_mapped = get_mapped_market_name(avail_mkt, 'customer_minutes')
                    
                    # Check COTTR matches using COTTR-specific mapped name
                    cottr_matches = [m for m in cottr_list if cottr_mapped.upper() in m.upper()]
                    # Check Customer Minutes matches using CM-specific mapped name
                    cm_matches = [m for m in cm_list if cm_mapped.upper() in m.upper()]
                    
                    # Build mapped name display
                    mapped_display = []
                    if cottr_mapped != avail_mkt:
                        mapped_display.append(f"COTTR: {cottr_mapped}")
                    if cm_mapped != avail_mkt:
                        mapped_display.append(f"CM: {cm_mapped}")
                    
                    match_results.append({
                        'Availability_Market': avail_mkt,
                        'Mapped_Name': ', '.join(mapped_display) if mapped_display else '-',
                        'COTTR_Matches': ', '.join(cottr_matches) if cottr_matches else '❌ NO MATCH',
                        'CustomerMinutes_Matches': ', '.join(cm_matches) if cm_matches else '❌ NO MATCH',
                        'COTTR_Found': '✅' if cottr_matches else '❌',
                        'CM_Found': '✅' if cm_matches else '❌'
                    })
                
                match_df = pd.DataFrame(match_results)
                
                # Summary stats
                cottr_matched = len([r for r in match_results if r['COTTR_Found'] == '✅'])
                cm_matched = len([r for r in match_results if r['CM_Found'] == '✅'])
                
                stat_col1, stat_col2, stat_col3 = st.columns(3)
                with stat_col1:
                    st.metric("Total Availability Markets", len(avail_list))
                with stat_col2:
                    st.metric("Matched in COTTR", f"{cottr_matched}/{len(avail_list)}", 
                             delta=f"{cottr_matched/len(avail_list)*100:.0f}%" if avail_list else "0%")
                with stat_col3:
                    st.metric("Matched in Customer Minutes", f"{cm_matched}/{len(avail_list)}",
                             delta=f"{cm_matched/len(avail_list)*100:.0f}%" if avail_list else "0%")
                
                # Show unmatched markets first
                st.markdown("#### ⚠️ Markets with Missing Data (need mappings added)")
                unmatched_df = match_df[(match_df['COTTR_Found'] == '❌') | (match_df['CM_Found'] == '❌')]
                if not unmatched_df.empty:
                    st.dataframe(unmatched_df[['Availability_Market', 'Mapped_Name', 'COTTR_Matches', 'CustomerMinutes_Matches']], 
                               use_container_width=True, height=300)
                else:
                    st.success("All markets have matching data in both COTTR and Customer Minutes!")
                
                with st.expander("📋 View Full Market Matching Table"):
                    st.dataframe(match_df, use_container_width=True, height=500)

    # Clear the loading banner once dashboard has rendered
    loading_placeholder.empty()

if __name__ == "__main__":
    main()