#!/usr/bin/env python3
"""
Streamlit Health Metrics Correlation Explorer
Ad-hoc analysis tool for discovering correlations between health metrics.

Requirements:
    pip install streamlit plotly duckdb pandas --break-system-packages

Usage:
    streamlit run hdp_correlation_explorer.py
    # Opens at http://localhost:8501
"""

import streamlit as st
import duckdb
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from pathlib import Path

# Page config
st.set_page_config(
    page_title="Health Metrics Correlation Explorer",
    page_icon="🔍",
    layout="wide"
)

# Configuration
DATA_DIR = Path("~/Data").expanduser()


@st.cache_resource
def get_db_connection():
    """Cached database connection"""
    return duckdb.connect()


@st.cache_data(ttl=300)  # Cache for 5 minutes
def query_metric_data(metric_name, category, start_date, end_date):
    """Query and cache metric data"""
    conn = get_db_connection()

    # Adjust queries based on your schema
    if category == 'Labs':
        query = f"""
        SELECT date, numeric_value as value
        FROM read_parquet('Data/Silver/labs_results/**/*.parquet')
        WHERE biomarker_name = '{metric_name}'
          AND date BETWEEN '{start_date}' AND '{end_date}'
        ORDER BY date
        """
    elif category == 'Training':
        if metric_name == 'Total Meters':
            query = f"""
            SELECT date, SUM(distance_meters) as value
            FROM read_parquet('Data/Silver/concept2_workouts/**/*.parquet')
            WHERE date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY date
            ORDER BY date
            """
        elif metric_name == 'Total Volume':
            query = f"""
            SELECT date, SUM(volume_kg) as value
            FROM read_parquet('Data/Silver/jefit_workouts/**/*.parquet')
            WHERE date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY date
            ORDER BY date
            """
    elif category == 'Recovery':
        query = f"""
        SELECT date, {metric_name.lower().replace(' ', '_')} as value
        FROM read_parquet('Data/Silver/oura_daily_summary/**/*.parquet')
        WHERE date BETWEEN '{start_date}' AND '{end_date}'
        ORDER BY date
        """
    elif category == 'Supplements':
        query = f"""
        SELECT date, SUM(dose_amount_mg) as value
        FROM read_parquet('Data/Silver/protocols_doses/**/*.parquet')
        WHERE compound_name = '{metric_name}'
          AND date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY date
        ORDER BY date
        """
    else:
        return pd.DataFrame(columns=['date', 'value'])

    try:
        df = conn.execute(query).fetchdf()
        return df
    except Exception as e:
        st.error(f"Error querying {metric_name}: {e}")
        return pd.DataFrame(columns=['date', 'value'])


def create_multi_axis_chart(selected_metrics, start_date, end_date):
    """Create Plotly chart with multiple y-axes"""

    fig = go.Figure()

    # Group metrics by unit to share y-axes
    unit_groups = {}
    for metric in selected_metrics:
        unit = metric['unit']
        if unit not in unit_groups:
            unit_groups[unit] = []
        unit_groups[unit].append(metric)

    # Create y-axis mapping
    yaxis_map = {}
    for i, unit in enumerate(unit_groups.keys()):
        yaxis_map[unit] = f'y{i+1}' if i > 0 else 'y'

    # Add traces
    for metric in selected_metrics:
        df = query_metric_data(
            metric['name'],
            metric['category'],
            start_date,
            end_date
        )

        if df.empty:
            continue

        yaxis = yaxis_map[metric['unit']]

        fig.add_trace(go.Scatter(
            x=df['date'],
            y=df['value'],
            name=f"{metric['name']} ({metric['unit']})",
            mode='lines+markers',
            yaxis=yaxis,
            hovertemplate='%{x}<br>%{y:.1f} ' + metric['unit'] + '<extra></extra>'
        ))

    # Configure layout
    layout = {
        'template': 'plotly_dark',
        'title': 'Health Metrics Correlation Explorer',
        'xaxis': {'title': 'Date'},
        'hovermode': 'x unified',
        'height': 700,
        'showlegend': True,
        'legend': {'x': 1.05, 'y': 1},
        'paper_bgcolor': 'rgba(0,0,0,0)',
        'plot_bgcolor': 'rgba(0,0,0,0)',
    }

    # Configure y-axes
    for i, unit in enumerate(unit_groups.keys()):
        if i == 0:
            layout['yaxis'] = {
                'title': unit,
                'side': 'left'
            }
        else:
            position = 1.0 + (0.08 * (i - 1))
            layout[f'yaxis{i+1}'] = {
                'title': unit,
                'overlaying': 'y',
                'side': 'right',
                'anchor': 'free',
                'position': position
            }

    fig.update_layout(**layout)

    return fig


# Main app
def main():
    st.title("🔍 Health Metrics Correlation Explorer")
    st.markdown("**Temporal correlation discovery through interactive overlay analysis**")

    # Sidebar: Date range selection
    st.sidebar.header("Date Range")

    col1, col2 = st.sidebar.columns(2)
    with col1:
        start_date = st.date_input(
            "Start",
            value=datetime.now() - timedelta(days=180),
            max_value=datetime.now()
        )
    with col2:
        end_date = st.date_input(
            "End",
            value=datetime.now(),
            max_value=datetime.now()
        )

    # Sidebar: Metric selection
    st.sidebar.header("Metrics to Plot")

    # Define available metrics
    available_metrics = {
        'Labs': {
            'Ferritin': 'ng/mL',
            'Hemoglobin': 'g/dL',
            'Hematocrit': '%',
            'Creatinine': 'mg/dL',
            'eGFR': 'mL/min',
            'HDL': 'mg/dL',
            'LDL': 'mg/dL',
            'Total Cholesterol': 'mg/dL',
            'Triglycerides': 'mg/dL',
            'A1C': '%',
            'Glucose': 'mg/dL',
            'Testosterone': 'ng/dL',
            'Free Testosterone': 'pg/mL',
            'SHBG': 'nmol/L',
        },
        'Training': {
            'Total Meters': 'meters',
            'Total Calories': 'kcal',
            'Average Watts': 'watts',
            'Total Volume': 'kg',
            'Max Heart Rate': 'bpm',
        },
        'Recovery': {
            'HRV': 'ms',
            'Readiness Score': 'score',
            'Sleep Score': 'score',
            'Resting HR': 'bpm',
            'Total Sleep': 'hours',
        },
        'Supplements': {
            'Iron': 'mg',
            'Niacin': 'mg',
            'Fish Oil': 'mg',
            'HGH': 'IU',
            'Testosterone': 'mg',
        }
    }

    # Metric selection interface
    selected_metrics = []

    for category, metrics in available_metrics.items():
        with st.sidebar.expander(f"{category}"):
            for metric_name, unit in metrics.items():
                if st.checkbox(f"{metric_name} ({unit})", key=f"{category}_{metric_name}"):
                    selected_metrics.append({
                        'name': metric_name,
                        'category': category,
                        'unit': unit
                    })

    # Preset correlation analyses
    st.sidebar.header("Quick Presets")

    if st.sidebar.button("Iron Repletion Analysis"):
        selected_metrics = [
            {'name': 'Ferritin', 'category': 'Labs', 'unit': 'ng/mL'},
            {'name': 'Hemoglobin', 'category': 'Labs', 'unit': 'g/dL'},
            {'name': 'Iron', 'category': 'Supplements', 'unit': 'mg'},
            {'name': 'Total Meters', 'category': 'Training', 'unit': 'meters'},
        ]

    if st.sidebar.button("Kidney Function Trend"):
        selected_metrics = [
            {'name': 'Creatinine', 'category': 'Labs', 'unit': 'mg/dL'},
            {'name': 'eGFR', 'category': 'Labs', 'unit': 'mL/min'},
            {'name': 'HGH', 'category': 'Supplements', 'unit': 'IU'},
        ]

    if st.sidebar.button("Training vs Recovery"):
        selected_metrics = [
            {'name': 'Total Meters', 'category': 'Training', 'unit': 'meters'},
            {'name': 'HRV', 'category': 'Recovery', 'unit': 'ms'},
            {'name': 'Readiness Score', 'category': 'Recovery', 'unit': 'score'},
        ]

    if st.sidebar.button("Lipid Recovery"):
        selected_metrics = [
            {'name': 'HDL', 'category': 'Labs', 'unit': 'mg/dL'},
            {'name': 'LDL', 'category': 'Labs', 'unit': 'mg/dL'},
            {'name': 'Niacin', 'category': 'Supplements', 'unit': 'mg'},
            {'name': 'Fish Oil', 'category': 'Supplements', 'unit': 'mg'},
        ]

    # Main chart area
    if len(selected_metrics) == 0:
        st.info("Select metrics from the sidebar to begin correlation analysis")

        # Show some example insights
        st.markdown("### Example Correlation Discoveries")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("""
            **Training Volume -> Recovery Impact**
            - Overlay: Total Meters + HRV + Readiness Score
            - Look for: HRV drops 1-2 days after high volume
            - Insight: Optimal recovery timing
            """)

            st.markdown("""
            **Supplement Efficacy**
            - Overlay: Iron dose + Ferritin + Training capacity
            - Look for: Ferritin rise correlating with dose
            - Insight: Dose-response relationship
            """)

        with col2:
            st.markdown("""
            **Compound Side Effects**
            - Overlay: HGH dose + Creatinine + eGFR
            - Look for: Kidney markers changing with HGH start
            - Insight: Causal relationship timing
            """)

            st.markdown("""
            **Performance Predictors**
            - Overlay: Sleep Score + Max HR + Readiness
            - Look for: Poor sleep -> reduced max HR next day
            - Insight: Deload indicators
            """)

    else:
        # Display selected metrics count
        st.info(f"Plotting {len(selected_metrics)} metrics over {(end_date - start_date).days} days")

        # Create and display chart
        fig = create_multi_axis_chart(selected_metrics, start_date, end_date)
        st.plotly_chart(fig, width="stretch")

        # Data table (expandable)
        with st.expander("View Raw Data"):
            for metric in selected_metrics:
                st.markdown(f"**{metric['name']}** ({metric['unit']})")
                df = query_metric_data(
                    metric['name'],
                    metric['category'],
                    start_date,
                    end_date
                )
                st.dataframe(df)

        # Export options
        st.markdown("### Export")
        col1, col2 = st.columns(2)

        with col1:
            if st.button("Download as HTML"):
                fig.write_html("/tmp/health_metrics.html")
                st.success("Saved to /tmp/health_metrics.html")

        with col2:
            if st.button("Download as PNG"):
                fig.write_image("/tmp/health_metrics.png", width=1600, height=900)
                st.success("Saved to /tmp/health_metrics.png")


if __name__ == '__main__':
    main()
