#!/bin/bash
# =============================================================================
# Quick Runner: Recovery Baseline HR Analysis
# =============================================================================
# Run this from your project root to execute the HR analysis query
# =============================================================================

set -e  # Exit on error

echo "=========================================="
echo "Recovery Baseline: Heart Rate Analysis"
echo "Period: Oct 4, 2025 → Present"
echo "=========================================="
echo ""

# Check if data directory exists
if [ ! -d "Data/Parquet/workouts" ]; then
    echo "❌ Error: Data/Parquet/workouts directory not found"
    echo "   Run this script from your project root"
    exit 1
fi

# Create temporary DuckDB script
cat > /tmp/run_hr_analysis.sql << 'EOF'
-- Attach Parquet data directly
CREATE VIEW workouts AS 
SELECT * FROM read_parquet('Data/Parquet/workouts/**/*.parquet');

-- Source the analysis queries
.read recovery_baseline_hr.sql

-- Optional: Export results to CSV for further analysis
-- COPY (SELECT * FROM ...) TO 'recovery_hr_results.csv' (HEADER, DELIMITER ',');
EOF

# Run DuckDB analysis
echo "🔍 Analyzing workout data..."
echo ""
duckdb < /tmp/run_hr_analysis.sql

# Cleanup
rm /tmp/run_hr_analysis.sql

echo ""
echo "=========================================="
echo "✅ Analysis complete!"
echo ""
echo "Next steps:"
echo "  1. Review the weekly trend (Part 2) - this is your primary feedback"
echo "  2. Check week-over-week changes (Part 4) - are you improving?"
echo "  3. Compare to May 2024 peak (Part 5) - sets context for recovery timeline"
echo ""
echo "Expected Week 6 targets:"
echo "  - Max HR: 122-125 bpm (currently ~120)"
echo "  - Should see +3-5 bpm improvement by Week 8"
echo "=========================================="
