#!/usr/bin/env python3
"""
Interactive Health Metrics Correlation Explorer
Style: Semantic Zones (Piecewise Normalization)
Updates: 
  - Explicit 'Iron Intake' naming to avoid Lab confusion
  - X-Axis padding (7 days) for better readability
  - Robust query logic for missing columns
"""

import duckdb
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from pathlib import Path
import sys
import numpy as np

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from src.pipeline.common.config import get_config
from src.pipeline.common.labs_normalization import REFERENCE_RANGES

class HealthDashboard:
    def __init__(self, start_date=None, end_date=None):
        self.conn = duckdb.connect()
        config = get_config()
        self.data_root = config.get_data_dir('parquet')
        
        self.end_date = end_date or datetime.now()
        self.start_date = start_date or (self.end_date - timedelta(days=180))
        
        # --- DEFINED PHYSIOLOGICAL RANGES ---
        # Format: (Reasonable_Min, Ref_Low, Ref_High, Reasonable_Max)
        # Maps to: 0%, 20%, 80%, 100% on the chart
        self.metric_zones = {
            # Training
            'Total Meters':  (0, 5000, 15000, 25000),  
            'Total Volume':  (0, 5000, 25000, 50000), 
            'Max HR':        (40, 120, 175, 200),
            
            # Supplements (Target Doses)
            'Iron Intake':   (0, 50, 150, 300),        # Renamed for clarity
            'HGH':           (0, 1.0, 2.5, 6.0),
            'Creatine':      (0, 3000, 5500, 10000),
        }
        
        print(f"📊 Dashboard initialized ({self.start_date.date()} to {self.end_date.date()})")

    def query_metric(self, metric_name, category):
        """Query data with robust error handling"""
        try:
            if category == 'labs':
                # Map friendly name to query pattern if needed
                query_name = metric_name
                if metric_name == "Iron, Serum": query_name = "Iron" # Handle "Iron" vs "Ferritin"

                query = f"""
                SELECT date, value
                FROM read_parquet('{self.data_root}/labs/**/*.parquet')
                WHERE marker ILIKE '{query_name}'
                  AND date BETWEEN DATE '{self.start_date.date()}' AND DATE '{self.end_date.date()}'
                ORDER BY date
                """
            
            elif category == 'training':
                if 'Meters' in metric_name:
                    query = f"""
                    SELECT date, SUM(distance_m) as value
                    FROM read_parquet('{self.data_root}/workouts/**/*.parquet')
                    WHERE source = 'Concept2'
                      AND date BETWEEN DATE '{self.start_date.date()}' AND DATE '{self.end_date.date()}'
                    GROUP BY date ORDER BY date
                    """
                elif 'Volume' in metric_name:
                    query = f"""
                    SELECT date, SUM(total_volume_lbs) as value
                    FROM read_parquet('{self.data_root}/workouts/**/*.parquet')
                    WHERE source = 'JEFIT'
                      AND date BETWEEN DATE '{self.start_date.date()}' AND DATE '{self.end_date.date()}'
                    GROUP BY date ORDER BY date
                    """
                else: 
                     return pd.DataFrame()
            
            elif category == 'supplements':
                # Clean name for query (remove 'Intake' suffix to match DB)
                # "Iron Intake" -> "Iron"
                db_name = metric_name.replace(' Intake', '').replace(' Supplement', '')
                
                query = f"""
                WITH date_series AS (
                    SELECT UNNEST(generate_series(
                        DATE '{self.start_date.date()}',
                        DATE '{self.end_date.date()}',
                        INTERVAL 1 DAY
                    ))::DATE as date
                ),
                daily_doses AS (
                    SELECT d.date, COALESCE(SUM(p.dosage), 0) as value
                    FROM date_series d
                    LEFT JOIN read_parquet('{self.data_root}/protocol_history/**/*.parquet') p
                        ON d.date BETWEEN p.start_date AND COALESCE(p.end_date, CURRENT_DATE)
                        AND p.compound_name ILIKE '{db_name}%'
                    GROUP BY d.date
                )
                SELECT date, value FROM daily_doses WHERE value > 0 ORDER BY date
                """
            
            if 'query' in locals():
                return self.conn.execute(query).fetchdf()
            return pd.DataFrame()

        except Exception as e:
            # print(f"   ⚠️  Error querying {metric_name}: {e}")
            return pd.DataFrame()

    def get_zone_definition(self, metric_name, obs_min, obs_max):
        """Returns (Min_Reasonable, Ref_Low, Ref_High, Max_Reasonable)"""
        # 1. Manual Overrides
        if metric_name in self.metric_zones:
            return self.metric_zones[metric_name]
            
        # 2. Clinical Reference Ranges
        for ref_name, ranges in REFERENCE_RANGES.items():
            if ref_name.lower() in metric_name.lower():
                low = ranges.get('low', 0)
                high = ranges.get('high', obs_max)
                
                # Heuristic: Reasonable Range is 50% wider than Ref Range
                r_min = 0
                r_max = high * 2 if high else obs_max * 1.5
                
                if low is None: low = 0
                if high is None: high = obs_max
                
                return (r_min, low, high, r_max)

        # 3. Fallback (Data Driven)
        return (obs_min * 0.5, obs_min, obs_max, obs_max * 1.2)

    def normalize_piecewise(self, value, zones):
        """Maps value to chart % using 3 zones"""
        r_min, ref_low, ref_high, r_max = zones
        
        if value <= ref_low:
            # Zone 1 (Low): 0-20%
            denom = ref_low - r_min
            pct = (value - r_min) / denom if denom != 0 else 0
            return 0 + (pct * 20)
        elif value <= ref_high:
            # Zone 2 (Target): 20-80%
            denom = ref_high - ref_low
            pct = (value - ref_low) / denom if denom != 0 else 0.5
            return 20 + (pct * 60)
        else:
            # Zone 3 (High): 80-100%
            denom = r_max - ref_high
            pct = (value - ref_high) / denom if denom != 0 else 1
            return 80 + (pct * 20)

    def create_zone_chart(self, metrics_to_plot):
        print(f"\n📈 Creating Zone-Normalized chart...")
        
        fig = go.Figure()
        
        # Track global dates for X-axis padding
        all_dates = []
        
        for i, (metric_name, category) in enumerate(metrics_to_plot):
            df = self.query_metric(metric_name, category)
            
            if not df.empty and len(df) > 1:
                all_dates.extend(df['date'].tolist())
                
                # Get Zones
                zones = self.get_zone_definition(metric_name, df['value'].min(), df['value'].max())
                r_min, ref_low, ref_high, r_max = zones
                
                print(f"   ✓ {metric_name}: Ref [{ref_low}, {ref_high}]")

                # Normalize
                df['chart_y'] = df['value'].apply(lambda x: self.normalize_piecewise(x, zones))
                
                # Colors
                base_color = ['#636EFA', '#00CC96', '#AB63FA', '#EF553B', '#FFA15A'][i % 5]
                
                marker_colors = []
                for val in df['value']:
                    is_training = category == 'training'
                    
                    if val < ref_low:
                        marker_colors.append('#FFA15A') # Low (Orange)
                    elif val > ref_high:
                        # High Training = Gold, High Lab = Red
                        marker_colors.append('#FFD700' if is_training else '#EF553B')
                    else:
                        marker_colors.append(base_color) # OK

                # Plot
                mode = 'lines+markers'
                line_width = 3 if len(df) < 50 else 2
                marker_size = 8 if len(df) < 50 else 4
                shape = 'hv' if category == 'supplements' else 'linear'

                fig.add_trace(go.Scatter(
                    x=df['date'],
                    y=df['chart_y'],
                    name=metric_name,
                    mode=mode,
                    line=dict(width=line_width, color=base_color, shape=shape),
                    marker=dict(color=marker_colors, size=marker_size, line=dict(width=1, color='white')),
                    customdata=df['value'],
                    hovertemplate=(
                        f"<b>{metric_name}</b><br>" +
                        "Value: %{customdata:.1f}<br>" +
                        f"Ref: {ref_low}-{ref_high}<br>" +
                        "<extra></extra>"
                    )
                ))

        # --- LAYOUT ---
        if all_dates:
            # Calculate Padded Date Range
            min_date = min(all_dates)
            max_date = max(all_dates)
            # Add 5% padding to the right
            date_range = max_date - min_date
            pad_days = max(7, date_range.days * 0.05) 
            padded_max = max_date + timedelta(days=pad_days)
            
            fig.update_layout(xaxis=dict(range=[min_date, padded_max]))

        fig.update_layout(
            title='Normalized Health Trends (Zones)',
            template="plotly_white",
            hovermode="x unified",
            height=600,
            yaxis=dict(
                title="",
                range=[-5, 105],
                tickvals=[0, 20, 50, 80, 100],
                ticktext=['Min', 'Low Limit', 'Target', 'High Limit', 'Max'],
                showgrid=False
            ),
            shapes=[
                # Target Zone (Green Band)
                dict(type="rect", xref="paper", yref="y", x0=0, y0=20, x1=1, y1=80,
                     fillcolor="rgba(46, 204, 113, 0.1)", layer="below", line_width=0),
                # Reference Lines
                dict(type="line", xref="paper", yref="y", x0=0, y0=20, x1=1, y1=20,
                     line=dict(color="rgba(46, 204, 113, 0.3)", width=1, dash="dot")),
                dict(type="line", xref="paper", yref="y", x0=0, y0=80, x1=1, y1=80,
                     line=dict(color="rgba(46, 204, 113, 0.3)", width=1, dash="dot")),
            ]
        )
        
        output_path = Path('analysis/outputs/correlation_zones.html')
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(str(output_path))
        print(f"✅ Saved to: {output_path}")
        
        import webbrowser
        webbrowser.open(f'file://{output_path.absolute()}')

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--analysis', default='iron')
    args = parser.parse_args()

    presets = {
        "iron": [
            ('Ferritin', 'labs'),
            ('Iron Intake', 'supplements'), # Now explicit "Intake"
            ('Hemoglobin', 'labs'),
            ('Total Meters', 'training'),
            # Optional: Add this if you want to verify serum iron
            # ('Iron, Serum', 'labs'), 
        ],
        "kidney": [
            ('Creatinine', 'labs'),
            ('eGFR', 'labs'),
            ('HGH', 'supplements')
        ]
    }
    
    dash = HealthDashboard(start_date=datetime(2024, 1, 1))
    if args.analysis in presets:
        dash.create_zone_chart(presets[args.analysis])

if __name__ == "__main__":
    main()