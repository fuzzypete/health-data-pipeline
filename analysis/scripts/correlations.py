#!/usr/bin/env python3
"""
Interactive Health Metrics Correlation Explorer
Configured for YOUR Health Data Pipeline schema

Usage:
    python analysis/scripts/correlations.py --analysis iron
    python analysis/scripts/correlations.py --analysis kidney
"""

import duckdb
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.pipeline.common.config import get_config


class HealthDashboard:
    """Interactive dashboard for health metrics correlation analysis"""
    
    def __init__(self, start_date=None, end_date=None):
        """Initialize dashboard with date range"""
        self.conn = duckdb.connect()
        
        # Get data paths from config
        config = get_config()
        self.data_root = config.get_data_dir('parquet')
        
        # Default date range: last 6 months
        self.end_date = end_date or datetime.now()
        self.start_date = start_date or (self.end_date - timedelta(days=180))
        
        print(f"📊 Dashboard initialized")
        print(f"   Date range: {self.start_date.date()} to {self.end_date.date()}")
        print(f"   Data root: {self.data_root}")
    
    def query_metric(self, metric_name, category):
        """Query time-series data for a specific metric"""
        
        if category == 'labs':
            # Labs: marker, value, date columns
            query = f"""
            SELECT 
                date,
                value
            FROM read_parquet('{self.data_root}/labs/**/*.parquet')
            WHERE marker = '{metric_name}'
              AND date BETWEEN DATE '{self.start_date.date()}' AND DATE '{self.end_date.date()}'
              AND value IS NOT NULL
            ORDER BY date
            """
            
        elif category == 'training':
            if 'Meters' in metric_name or 'Distance' in metric_name:
                # Concept2: distance_m, date columns
                query = f"""
                SELECT 
                    date,
                    SUM(distance_m) as value
                FROM read_parquet('{self.data_root}/workouts/**/*.parquet')
                WHERE source = 'Concept2'
                  AND date BETWEEN DATE '{self.start_date.date()}' AND DATE '{self.end_date.date()}'
                  AND distance_m IS NOT NULL
                GROUP BY date
                ORDER BY date
                """
            elif 'Volume' in metric_name:
                # JEFIT: total_volume_lbs (converting to kg)
                query = f"""
                SELECT 
                    date,
                    SUM(total_volume_lbs * 0.453592) as value
                FROM read_parquet('{self.data_root}/workouts/**/*.parquet')
                WHERE source = 'JEFIT'
                  AND date BETWEEN DATE '{self.start_date.date()}' AND DATE '{self.end_date.date()}'
                  AND total_volume_lbs IS NOT NULL
                GROUP BY date
                ORDER BY date
                """
            elif 'HR' in metric_name:
                # Heart rate metrics
                if 'Max' in metric_name:
                    field = 'max_hr_bpm'
                elif 'Avg' in metric_name:
                    field = 'avg_hr_bpm'
                else:
                    field = 'avg_hr_bpm'
                    
                query = f"""
                SELECT 
                    date,
                    AVG({field}) as value
                FROM read_parquet('{self.data_root}/workouts/**/*.parquet')
                WHERE source = 'Concept2'
                  AND date BETWEEN DATE '{self.start_date.date()}' AND DATE '{self.end_date.date()}'
                  AND {field} IS NOT NULL
                GROUP BY date
                ORDER BY date
                """
            else:
                return pd.DataFrame(columns=['date', 'value'])
                
        elif category == 'recovery':
            # Note: minute_facts not verified - may need adjustment
            metric_map = {
                'HRV': 'hrv_ms',
                'Readiness Score': 'readiness_score',
                'Sleep Score': 'sleep_score',
                'Resting HR': 'resting_hr_bpm'
            }
            
            field = metric_map.get(metric_name)
            if not field:
                return pd.DataFrame(columns=['date', 'value'])
                
            # Try minute_facts, fallback to empty if table doesn't exist
            try:
                query = f"""
                SELECT 
                    CAST(timestamp_utc AS DATE) as date,
                    AVG({field}) as value
                FROM read_parquet('{self.data_root}/minute_facts/**/*.parquet')
                WHERE source = 'Oura'
                  AND {field} IS NOT NULL
                  AND CAST(timestamp_utc AS DATE) BETWEEN DATE '{self.start_date.date()}' AND DATE '{self.end_date.date()}'
                GROUP BY CAST(timestamp_utc AS DATE)
                ORDER BY date
                """
            except:
                return pd.DataFrame(columns=['date', 'value'])
            
        elif category == 'supplements':
            # Protocol: start_date, end_date, compound_name, dosage
            # Need to expand date ranges to daily values
            query = f"""
            WITH date_series AS (
                SELECT UNNEST(generate_series(
                    DATE '{self.start_date.date()}',
                    DATE '{self.end_date.date()}',
                    INTERVAL 1 DAY
                ))::DATE as date
            ),
            daily_doses AS (
                SELECT 
                    d.date,
                    COALESCE(SUM(p.dosage), 0) as value
                FROM date_series d
                LEFT JOIN read_parquet('{self.data_root}/protocol_history/**/*.parquet') p
                    ON d.date BETWEEN p.start_date AND COALESCE(p.end_date, CURRENT_DATE)
                    AND p.compound_name = '{metric_name}'
                GROUP BY d.date
            )
            SELECT date, value
            FROM daily_doses
            WHERE value > 0
            ORDER BY date
            """
        else:
            return pd.DataFrame(columns=['date', 'value'])
        
        try:
            df = self.conn.execute(query).fetchdf()
            print(f"   ✓ Loaded {len(df)} points for {metric_name}")
            return df
        except Exception as e:
            print(f"   ✗ Error loading {metric_name}: {e}")
            return pd.DataFrame(columns=['date', 'value'])
    
    def create_overlay_chart(self, metrics_to_plot):
        """
        Create interactive chart with multiple metrics overlaid
        
        Args:
            metrics_to_plot: List of tuples (metric_name, category)
                Example: [
                    ('Ferritin', 'labs'),
                    ('Total Meters', 'training')
                ]
        """
        print(f"\n📈 Creating overlay chart with {len(metrics_to_plot)} metrics...")
        
        fig = go.Figure()
        
        # Define units for each metric
        unit_map = {
            'labs': {
                'Ferritin': 'ng/mL',
                'Hemoglobin': 'g/dL',
                'Hematocrit': '%',
                'Creatinine': 'mg/dL',
                'eGFR': 'mL/min',
                'HDL': 'mg/dL',
                'LDL': 'mg/dL',
                'Testosterone': 'ng/dL',
                'Free Testosterone': 'pg/mL',
                'SHBG': 'nmol/L',
            },
            'training': {
                'Total Meters': 'meters',
                'Total Volume': 'kg',
                'Max HR': 'bpm',
                'Avg HR': 'bpm',
            },
            'recovery': {
                'HRV': 'ms',
                'Readiness Score': 'score',
                'Sleep Score': 'score',
                'Resting HR': 'bpm',
            },
            'supplements': {
                'Iron': 'mg',
                'Niacin ER': 'mg',
                'Fish Oil': 'mg',
                'HGH': 'IU',
            }
        }
        
        # Track y-axes for different units
        unit_to_yaxis = {}
        yaxis_count = 1
        
        for metric_name, category in metrics_to_plot:
            df = self.query_metric(metric_name, category)
            if df.empty:
                continue
            
            # Get unit
            unit = unit_map.get(category, {}).get(metric_name, '')
            
            # Assign y-axis
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
                visible=True,
                hovertemplate='%{x}<br>%{y:.1f} ' + unit + '<extra></extra>'
            ))
        
        # Configure layout with multiple y-axes
        layout_updates = {
            'title': 'Health Metrics Correlation Explorer',
            'xaxis': {'title': 'Date'},
            'hovermode': 'x unified',
            'height': 700,
            'showlegend': True,
        }
        
        # Add y-axis configurations
        for i, (unit, yaxis_name) in enumerate(unit_to_yaxis.items()):
            if i == 0:
                layout_updates['yaxis'] = {
                    'title': unit,
                    'side': 'left'
                }
            elif i == 1:
                # First right axis at position 1.0
                layout_updates['yaxis2'] = {
                    'title': unit,
                    'overlaying': 'y',
                    'side': 'right'
                }
            else:
                # Additional right axes anchored to x-axis with offset
                layout_updates[f'yaxis{i+1}'] = {
                    'title': unit,
                    'overlaying': 'y',
                    'side': 'right',
                    'anchor': 'free',
                    'position': 0.85 - (0.05 * (i - 2))  # 0.85, 0.80, 0.75...
                }
        
        fig.update_layout(**layout_updates)
        
        print("✅ Chart created successfully\n")
        return fig


def example_iron_repletion():
    """Example: Iron repletion efficacy analysis"""
    print("=" * 60)
    print("IRON REPLETION CORRELATION ANALYSIS")
    print("=" * 60)
    
    dashboard = HealthDashboard(
        start_date=datetime(2025, 10, 1),
        end_date=datetime.now()
    )
    
    metrics = [
        ('Ferritin', 'labs'),
        ('Iron', 'supplements'),
        ('Hemoglobin', 'labs'),
        ('Total Meters', 'training'),
    ]
    
    fig = dashboard.create_overlay_chart(metrics)
    fig.update_layout(title='Iron Supplementation Efficacy - Oct 2025 to Present')
    
    # Save and show
    output_path = Path('analysis/outputs/iron_correlation.html')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_path))
    
    print(f"💾 Saved to: {output_path}")
    print(f"🌐 Opening in browser...")
    fig.show()


def example_kidney_function():
    """Example: HGH → Kidney function analysis"""
    print("=" * 60)
    print("HGH → KIDNEY FUNCTION CORRELATION ANALYSIS")
    print("=" * 60)
    
    dashboard = HealthDashboard(
        start_date=datetime(2024, 1, 1),
        end_date=datetime.now()
    )
    
    metrics = [
        ('Creatinine', 'labs'),
        ('eGFR', 'labs'),
        ('HGH', 'supplements'),
    ]
    
    fig = dashboard.create_overlay_chart(metrics)
    fig.update_layout(
        title='HGH → Kidney Function Temporal Correlation',
        annotations=[
            dict(
                x='2025-05-17',
                y=1.02,
                text='HGH Started',
                showarrow=True,
                arrowhead=2
            ),
            dict(
                x='2025-11-24',
                y=1.32,
                text='HGH Reduced',
                showarrow=True,
                arrowhead=2
            )
        ]
    )
    
    # Save and show
    output_path = Path('analysis/outputs/kidney_correlation.html')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_path))
    
    print(f"💾 Saved to: {output_path}")
    print(f"🌐 Opening in browser...")
    fig.show()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Health metrics correlation explorer')
    parser.add_argument('--analysis', choices=['iron', 'kidney'], 
                       help='Run preset analysis')
    
    args = parser.parse_args()
    
    if args.analysis == 'iron':
        example_iron_repletion()
    elif args.analysis == 'kidney':
        example_kidney_function()
    else:
        # Default: run iron analysis
        example_iron_repletion()
