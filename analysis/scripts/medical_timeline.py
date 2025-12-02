import duckdb
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import argparse
import sys

# --- CONFIG ---
DB_PATH = "Data/duck/health.duckdb"

# Temporary Fallback for markers missing from your normalization dictionary
MANUAL_REFS = {
    'Cystatin C': (0.52, 1.23),
    'eGFR': (60, 120),
    'Creatinine': (0.7, 1.3),
}

def get_data(markers, compounds):
    con = duckdb.connect(DB_PATH)
    
    # 1. Fetch Labs
    lab_data = pd.DataFrame()
    if markers:
        # Check DB columns
        try:
            cols = con.execute("DESCRIBE lake.labs").df()['column_name'].values
            has_refs = 'ref_low' in cols
        except:
            has_refs = False

        select_cols = "date, marker, value, unit"
        if has_refs:
            select_cols += ", ref_low, ref_high"
        else:
            select_cols += ", NULL as ref_low, NULL as ref_high"

        marker_list = "', '".join(markers)
        query = f"""
            SELECT {select_cols}
            FROM lake.labs 
            WHERE marker IN ('{marker_list}')
            ORDER BY date
        """
        lab_data = con.execute(query).fetchdf()

    # 2. Fetch Protocols
    prot_data = pd.DataFrame()
    if compounds:
        conditions = [f"compound_name ILIKE '%{c}%'" for c in compounds]
        where_clause = " OR ".join(conditions)
        
        # FIX: Handle NULL end_date as CURRENT_DATE so ongoing protocols show up!
        prot_data = con.execute(f"""
            SELECT 
                compound_name, 
                start_date, 
                COALESCE(end_date, CURRENT_DATE) as end_date,
                dosage,
                dosage_unit
            FROM lake.protocol_history
            WHERE {where_clause}
            ORDER BY start_date
        """).fetchdf()
        
    return lab_data, prot_data

def merge_intervals(df):
    """Merges adjacent intervals to prevent 'broken bar' look."""
    if df.empty: return df
    
    df['start_date'] = pd.to_datetime(df['start_date'])
    df['end_date'] = pd.to_datetime(df['end_date'])

    merged = []
    for name in df['compound_name'].unique():
        subset = df[df['compound_name'] == name].sort_values('start_date')
        if subset.empty: continue

        curr_start = subset.iloc[0]['start_date']
        curr_end = subset.iloc[0]['end_date']
        
        def fmt_dose(r):
            d = r['dosage'] if pd.notnull(r['dosage']) else "?"
            u = r['dosage_unit'] if pd.notnull(r['dosage_unit']) else ""
            return f"{d} {u}".strip()

        curr_doses = [fmt_dose(subset.iloc[0])]

        for i in range(1, len(subset)):
            row = subset.iloc[i]
            # Merge if gap <= 5 days (smoother look)
            if row['start_date'] <= (curr_end + timedelta(days=5)):
                curr_end = max(curr_end, row['end_date'])
                curr_doses.append(fmt_dose(row))
            else:
                # Seal block
                unique_doses = pd.Series(curr_doses).unique()
                merged.append({
                    'compound_name': name,
                    'start_date': curr_start,
                    'end_date': curr_end,
                    'details': " → ".join(unique_doses)
                })
                # Start new
                curr_start = row['start_date']
                curr_end = row['end_date']
                curr_doses = [fmt_dose(row)]
        
        # Seal final
        unique_doses = pd.Series(curr_doses).unique()
        merged.append({
            'compound_name': name,
            'start_date': curr_start,
            'end_date': curr_end,
            'details': " → ".join(unique_doses)
        })
    
    return pd.DataFrame(merged)

def create_chart(markers, compounds):
    df_labs, df_prot = get_data(markers, compounds)
    if not df_labs.empty:
        df_labs['date'] = pd.to_datetime(df_labs['date'])

    # Layout: Labs (80%), Protocols (20%)
    fig = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.02,
        row_heights=[0.80, 0.20],
        specs=[[{"secondary_y": True}], [{"type": "xy"}]]
    )

    # --- ROW 1: LABS ---
    if not df_labs.empty:
        # Determine Primary Axis (Right if > 20)
        primary_marker = markers[0]
        sub_prim = df_labs[df_labs['marker'] == primary_marker]
        
        # Default defaults
        low, high = 0, 0
        has_ref = False
        use_right_axis = False

        if not sub_prim.empty:
            avg_val = sub_prim['value'].mean()
            use_right_axis = avg_val > 20 and len(markers) > 1
            
            # Try getting ref from DB
            last = sub_prim.iloc[-1]
            if pd.notnull(last['ref_low']):
                low, high = last['ref_low'], last['ref_high']
                has_ref = True
            # Try manual fallback
            elif primary_marker in MANUAL_REFS:
                low, high = MANUAL_REFS[primary_marker]
                has_ref = True

        # Draw Green Band (On the correct axis!)
        if has_ref:
            fig.add_hrect(
                y0=low, y1=high,
                fillcolor="green", opacity=0.1, line_width=0,
                annotation_text=f"Normal ({low}-{high})", annotation_position="top left",
                row=1, col=1, 
                secondary_y=use_right_axis  # <--- CRITICAL FIX
            )

        # Plot Lines
        for m in markers:
            sub = df_labs[df_labs['marker'] == m].sort_values('date')
            if sub.empty: continue
            
            val_mean = sub['value'].mean()
            # Dynamic axis logic
            is_right = val_mean > 20 and len(markers) > 1
            
            fig.add_trace(go.Scatter(
                x=sub['date'], y=sub['value'],
                mode='lines+markers',
                name=m,
                line=dict(width=3),
                marker=dict(size=9, line=dict(width=2, color='white')),
                hovertemplate=f"<b>{m}</b><br>%{{y}} %{{text}}<br>%{{x|%b %d, %Y}}<extra></extra>",
                text=sub['unit']
            ), row=1, col=1, secondary_y=is_right)

    # --- ROW 2: PROTOCOLS (SWIMLANES) ---
    if not df_prot.empty:
        m_df = merge_intervals(df_prot)
        # Consistent colors
        colors = ['#EF553B', '#636EFA', '#00CC96', '#AB63FA', '#FFA15A']
        uniques = sorted(m_df['compound_name'].unique()) # Sort alphabetically
        
        for i, comp in enumerate(uniques):
            sub = m_df[m_df['compound_name'] == comp]
            
            # Using Scatter with None to create disconnected "thick lines" (Swimlanes)
            # This is robust for dates and prevents the "1 day bar is invisible" issue
            x_pts, y_pts, txt_pts = [], [], []
            
            for _, row in sub.iterrows():
                # Add Start, End, None (break)
                x_pts.extend([row['start_date'], row['end_date'], None])
                y_pts.extend([comp, comp, None])
                txt_pts.extend([row['details'], row['details'], None])

            fig.add_trace(go.Scatter(
                x=x_pts, y=y_pts,
                mode='lines',
                line=dict(color=colors[i % len(colors)], width=20), # Thick line
                name=comp,
                showlegend=False,
                hovertemplate=f"<b>{comp}</b><br>%{{x|%b %d, %Y}}<br>Dose: %{{text}}<extra></extra>",
                text=txt_pts,
                connectgaps=False 
            ), row=2, col=1)

    # --- STYLING ---
    fig.update_layout(
        title="Medical Timeline Analysis",
        template="plotly_white",
        height=800,
        hovermode="x unified",
        legend=dict(orientation="h", y=1.02, x=0)
    )
    
    # Axes
    fig.update_xaxes(
        type="date", 
        tickformat="%b %Y", 
        dtick="M3", 
        range=[df_labs['date'].min() - timedelta(days=30), datetime.now() + timedelta(days=30)] if not df_labs.empty else None,
        row=2, col=1
    )
    fig.update_xaxes(matches='x', row=1, col=1) # Lock zoom
    
    fig.update_yaxes(title="Primary", secondary_y=False, row=1, col=1, showgrid=True)
    fig.update_yaxes(title="Secondary", secondary_y=True, row=1, col=1, showgrid=False)
    fig.update_yaxes(categoryorder='category descending', row=2, col=1) # A-Z top down

    return fig

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--labs', required=True)
    parser.add_argument('--meds', required=True)
    args = parser.parse_args()
    
    l_list = [x.strip() for x in args.labs.split(',')]
    m_list = [x.strip() for x in args.meds.split(',')]
    
    fig = create_chart(l_list, m_list)
    
    out = f"analysis/outputs/timeline_{datetime.now().strftime('%Y%m%d')}.html"
    fig.write_html(out)
    print(f"✅ Saved to: {out}")