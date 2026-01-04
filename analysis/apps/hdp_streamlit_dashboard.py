#!/usr/bin/env python3
"""
Streamlit Dashboard Entry Point

This file delegates to hdp_dashboard.py for the main HDP Dashboard.
For the correlation explorer tool, see hdp_correlation_explorer.py
"""

# Import and run the main dashboard
# Note: hdp_dashboard.py handles st.set_page_config() and all rendering
from hdp_dashboard import main

main()
