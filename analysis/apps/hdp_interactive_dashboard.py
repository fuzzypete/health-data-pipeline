#!/usr/bin/env python3
"""
Interactive Health Metrics Dashboard
Uses Plotly for dynamic multi-axis charts with toggle controls

Requirements:
    pip install plotly duckdb pandas --break-system-packages

Usage:
    python hdp_interactive_dashboard.py
    # Opens in browser with interactive controls
"""

import duckdb
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
DATA_DIR = Path("~/Data").expanduser()  # Adjust to your HDP location
DB_PATH = DATA_DIR / "health_metrics.duckdb"  # Or use in-memory queries


class HealthDashboard:
    """Interactive dashboard for health metrics correlation analysis"""
    
    def __init__(self, start_date=None, end_date=None):
        """
        Initialize dashboard with optional date range
        
        Args:
            start_date: Start date (default: 6 months ago)
            end_date: End date (default: today)
        """
        self.conn = duckdb.connect()
        
        # Default date range: last 6 months
        self.end_date = end_date or datetime.now()
        self.start_date = start_date or (self.end_date - timedelta(days=180))
        
        # Available metric categories
        self.metrics = {
            'labs': self._get_lab_metrics(),
            'training': self._get_training_metrics(),
            'recovery': self._get_recovery_metrics(),
            'supplements': self._get_supplement_metrics()
        }
    
    def _get_lab_metrics(self):
        """Query available lab biomarkers"""
        # Example - adjust based on your actual schema
        query = f"""
        SELECT DISTINCT biomarker_name, unit
        FROM read_parquet('Data/Silver/labs_results/**/*.parquet')
        WHERE date BETWEEN '{self.start_date.date()}' AND '{self.end_date.date()}'
        ORDER BY biomarker_name
        """
        try:
            df = self.conn.execute(query).fetchdf()
            return {row['biomarker_name']: row['unit'] for _, row in df.iterrows()}
        except:
            # Fallback if schema different
            return {
                'Ferritin': 'ng/mL',
                'Hemoglobin': 'g/dL',
                'Creatinine': 'mg/dL',
                'HDL': 'mg/dL',
                'Testosterone': 'ng/dL'
            }
    
    def _get_training_metrics(self):
        """Query available training metrics"""
        return {
            'Total Meters': 'meters',
            'Total Calories': 'kcal',
            'Average Watts': 'watts',
            'Training Volume': 'kg'
        }
    
    def _get_recovery_metrics(self):
        """Query available recovery metrics"""
        return {
            'HRV': 'ms',
            'Readiness Score': 'score',
            'Sleep Score': 'score',
            'Resting HR': 'bpm'
        }
    
    def _get_supplement_metrics(self):
        """Query available supplement doses"""
        return {
            'Iron': 'mg',
            'Niacin': 'mg',
            'Fish Oil': 'mg',
            'HGH': 'IU'
        }
    
    def query_metric(self, metric_name, category):
        """
        Query time-series data for a specific metric
        
        Args:
            metric_name: Name of metric (e.g., 'Ferritin')
            category: Category ('labs', 'training', 'recovery', 'supplements')
        
        Returns:
            DataFrame with columns: date, value
        """
        if category == 'labs':
            query = f"""
            SELECT date, numeric_value as value
            FROM read_parquet('Data/Silver/labs_results/**/*.parquet')
            WHERE biomarker_name = '{metric_name}'
              AND date BETWEEN '{self.start_date.date()}' AND '{self.end_date.date()}'
            ORDER BY date
            """
        elif category == 'training':
            # Example for Concept2 data
            query = f"""
            SELECT date, SUM(distance_meters) as value
            FROM read_parquet('Data/Silver/concept2_workouts/**/*.parquet')
            WHERE date BETWEEN '{self.start_date.date()}' AND '{self.end_date.date()}'
            GROUP BY date
            ORDER BY date
            """
        elif category == 'supplements':
            query = f"""
            SELECT date, SUM(dose_amount_mg) as value
            FROM read_parquet('Data/Silver/protocols_doses/**/*.parquet')
            WHERE compound_name = '{metric_name}'
              AND date BETWEEN '{self.start_date.date()}' AND '{self.end_date.date()}'
            GROUP BY date
            ORDER BY date
            """
        else:
            # Fallback: return empty DataFrame
            return pd.DataFrame(columns=['date', 'value'])
        
        try:
            return self.conn.execute(query).fetchdf()
        except Exception as e:
            print(f"Error querying {metric_name}: {e}")
            return pd.DataFrame(columns=['date', 'value'])
    
    def create_overlay_chart(self, metrics_to_plot):
        """
        Create interactive chart with multiple metrics overlaid
        
        Args:
            metrics_to_plot: List of tuples (metric_name, category)
                Example: [('Ferritin', 'labs'), ('Total Meters', 'training')]
        
        Returns:
            Plotly Figure object
        """
        fig = go.Figure()
        
        # Track y-axes for different units
        unit_to_yaxis = {}
        yaxis_count = 1
        
        for metric_name, category in metrics_to_plot:
            # Get data
            df = self.query_metric(metric_name, category)
            if df.empty:
                continue
            
            # Get unit
            unit = self.metrics[category].get(metric_name, '')
            
            # Assign y-axis (group metrics with same unit)
            if unit not in unit_to_yaxis:
                unit_to_yaxis[unit] = f'y{yaxis_count}' if yaxis_count > 1 else 'y'
                yaxis_count += 1
            
            yaxis = unit_to_yaxis[unit]
            
            # Add trace
            fig.add_trace(go.Scatter(
                x=df['date'],
                y=df['value'],
                name=f"{metric_name} ({unit})",
                mode='lines+markers',
                yaxis=yaxis,
                visible=True,  # All visible by default
                hovertemplate='%{x}<br>%{y:.1f} ' + unit + '<extra></extra>'
            ))
        
        # Configure layout with multiple y-axes
        layout_updates = {
            'title': 'Health Metrics Timeline',
            'xaxis': {'title': 'Date'},
            'hovermode': 'x unified',
            'height': 600
        }
        
        # Add y-axis configurations
        for i, (unit, yaxis_name) in enumerate(unit_to_yaxis.items()):
            if i == 0:
                # Primary y-axis
                layout_updates['yaxis'] = {
                    'title': unit,
                    'side': 'left'
                }
            else:
                # Secondary y-axes
                position = 0.05 * (i - 1)  # Offset each axis
                layout_updates[f'yaxis{i+1}'] = {
                    'title': unit,
                    'overlaying': 'y',
                    'side': 'right',
                    'position': 1 - position if i % 2 == 1 else position
                }
        
        # Add toggle buttons for each trace
        buttons = []
        for i, (metric_name, category) in enumerate(metrics_to_plot):
            visible = [j == i for j in range(len(metrics_to_plot))]
            buttons.append(dict(
                label=metric_name,
                method='update',
                args=[{'visible': visible}]
            ))
        
        # Add "Show All" button
        buttons.insert(0, dict(
            label='Show All',
            method='update',
            args=[{'visible': [True] * len(metrics_to_plot)}]
        ))
        
        layout_updates['updatemenus'] = [
            dict(
                type='buttons',
                direction='down',
                x=1.15,
                y=1.0,
                buttons=buttons
            )
        ]
        
        fig.update_layout(**layout_updates)
        
        return fig


def example_usage():
    """Example: Correlate iron status with training volume"""
    
    # Initialize dashboard
    dashboard = HealthDashboard(
        start_date=datetime(2025, 1, 1),
        end_date=datetime.now()
    )
    
    # Define metrics to overlay
    metrics_to_plot = [
        ('Ferritin', 'labs'),
        ('Hemoglobin', 'labs'),
        ('Total Meters', 'training'),
        ('Iron', 'supplements'),
    ]
    
    # Create chart
    fig = dashboard.create_overlay_chart(metrics_to_plot)
    
    # Display in browser
    fig.show()
    
    # Or save to HTML
    fig.write_html('/mnt/user-data/outputs/health_metrics_dashboard.html')
    print("Dashboard saved to health_metrics_dashboard.html")


def correlation_analysis_example():
    """Example: Find correlations between training and recovery"""
    
    dashboard = HealthDashboard()
    
    # Hypothesis: High training volume → lower HRV next day
    metrics_to_plot = [
        ('Total Meters', 'training'),
        ('HRV', 'recovery'),
        ('Readiness Score', 'recovery')
    ]
    
    fig = dashboard.create_overlay_chart(metrics_to_plot)
    fig.update_layout(title='Training Load vs Recovery Metrics')
    fig.show()


def supplement_efficacy_example():
    """Example: Did iron supplementation work?"""
    
    dashboard = HealthDashboard(
        start_date=datetime(2025, 10, 1),  # Start of iron protocol
        end_date=datetime.now()
    )
    
    metrics_to_plot = [
        ('Ferritin', 'labs'),
        ('Iron', 'supplements'),
        ('Hemoglobin', 'labs'),
        ('Total Meters', 'training')  # Training capacity proxy
    ]
    
    fig = dashboard.create_overlay_chart(metrics_to_plot)
    fig.update_layout(title='Iron Supplementation Efficacy')
    fig.show()


if __name__ == '__main__':
    # Run example
    example_usage()
    
    # Uncomment to try other examples:
    # correlation_analysis_example()
    # supplement_efficacy_example()
