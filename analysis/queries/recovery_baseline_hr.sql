-- ============================================================================
-- RECOVERY BASELINE: Heart Rate Analysis (v2 - Schema Corrected)
-- ============================================================================
-- Period: Oct 4, 2025 (compound cessation) → Present
-- Goal: Establish current HR capacity and detect early improvement signals
-- ============================================================================

-- Part 1: Individual Workout Details
-- Shows every workout with HR metrics for granular inspection
SELECT 
    start_time_local::DATE as workout_date,
    workout_type,
    ROUND(duration_s / 60.0, 1) as duration_min,
    ROUND(distance_m, 0) as distance_m,
    avg_hr_bpm,
    max__hr_bpm,
    ROUND(avg_pace_sec_per_500m, 1) as avg_pace_sec_per_500m,
    CASE 
        WHEN max__hr_bpm >= 145 THEN '🟢 Target+'
        WHEN max__hr_bpm >= 130 THEN '🟡 Improving'
        WHEN max__hr_bpm >= 120 THEN '🟠 Low'
        ELSE '🔴 Very Low'
    END as hr_status,
    workout_id
FROM workouts
WHERE start_time_utc >= '2025-10-04'
    AND workout_type IN ('Rowing', 'Cycling', 'Skiing')
    AND duration_s >= 600  -- At least 10 min
ORDER BY workout_date DESC;

-- ============================================================================
-- Part 2: Weekly Trend Summary
-- Shows week-over-week progression (primary feedback metric)
-- ============================================================================
SELECT 
    strftime(date_trunc('week', start_time_utc), '%Y-%m-%d') as week_start,
    COUNT(workout_id) as workout_count,
    ROUND(AVG(avg_hr_bpm), 1) as avg_hr_mean,
    ROUND(AVG(max__hr_bpm), 1) as max_hr_mean,
    MIN(max__hr_bpm) as max_hr_min,
    MAX(max__hr_bpm) as max_hr_max,
    ROUND(AVG(avg_pace_sec_per_500m), 1) as avg_pace_mean,
    ROUND(SUM(distance_m) / 1000.0, 1) as total_km
FROM workouts
WHERE start_time_utc >= '2025-10-04'
    AND workout_type IN ('Rowing', 'Cycling', 'Skiing')
    AND duration_s >= 600
GROUP BY date_trunc('week', start_time_utc)
ORDER BY week_start;

-- ============================================================================
-- Part 3: Overall Period Summary
-- Aggregates the entire recovery period to date for a single baseline
-- ============================================================================
SELECT 
    'Recovery Baseline (Oct 4 - Present)' as period,
    COUNT(workout_id) as sessions,
    ROUND(AVG(avg_hr_bpm), 1) as avg_hr,
    ROUND(AVG(max__hr_bpm), 1) as max_hr,
    ROUND(AVG(avg_pace_sec_per_500m), 1) as avg_pace
FROM workouts
WHERE start_time_utc >= '2025-10-04'
    AND workout_type IN ('Rowing', 'Cycling', 'Skiing')
    AND duration_s >= 600;

-- ============================================================================
-- Part 4: Week-over-Week Change
-- Calculates the difference from the previous week
-- ============================================================================
WITH WeeklyStats AS (
    SELECT 
        date_trunc('week', start_time_utc) as week,
        AVG(max__hr_bpm) as max_hr_avg,
        AVG(avg_pace_sec_per_500m) as avg_pace
    FROM workouts
    WHERE start_time_utc >= '2025-10-04'
        AND workout_type IN ('Rowing', 'Cycling', 'Skiing')
        AND duration_s >= 600
    GROUP BY week
)
SELECT 
    strftime(week, '%Y-%m-%d') as week_start,
    ROUND(max_hr_avg, 1) as max_hr_avg,
    ROUND(max_hr_avg - LAG(max_hr_avg) OVER (ORDER BY week), 1) as max_hr_change,
    ROUND(avg_pace, 1) as avg_pace,
    ROUND(avg_pace - LAG(avg_pace) OVER (ORDER BY week), 1) as avg_pace_change
FROM WeeklyStats
ORDER BY week DESC;

-- ============================================================================
-- Part 5: Comparison to May 2024 Peak
-- Sets context for how far recovery has to go
-- ============================================================================
WITH recovery_period AS (
    SELECT 
        '1. Recovery Baseline (Oct 4 - Present)' as period,
        COUNT(workout_id) as sessions,
        ROUND(AVG(avg_hr_bpm), 1) as avg_hr,
        ROUND(AVG(max__hr_bpm), 1) as max_hr,
        ROUND(AVG(avg_pace_sec_per_500m), 1) as avg_pace
    FROM workouts
    WHERE start_time_utc >= '2025-10-04'
        AND workout_type IN ('Rowing', 'Cycling', 'Skiing')
        AND duration_s >= 600
),
peak_period AS (
    SELECT 
        '0. Pre-Depletion Peak (May 2024)' as period,
        COUNT(workout_id) as sessions,
        ROUND(AVG(avg_hr_bpm), 1) as avg_hr,
        ROUND(AVG(max__hr_bpm), 1) as max_hr,
        ROUND(AVG(avg_pace_sec_per_500m), 1) as avg_pace
    FROM workouts
    WHERE start_time_utc BETWEEN '2024-05-01' AND '2024-05-31'
        AND workout_type IN ('Rowing', 'Cycling', 'Skiing')
        AND duration_s >= 600
)
SELECT * FROM peak_period
UNION ALL
SELECT * FROM recovery_period
ORDER BY period;

-- ============================================================================
-- USAGE INSTRUCTIONS (Updated)
-- ============================================================================
-- 1. Run from your project root:
--    poetry run python analytics/run_hr_analysis.py
--
-- 2. Optional: Save weekly summary to CSV
--    poetry run python analytics/run_hr_analysis.py --output analytics/outputs/recovery_weekly.csv
--
-- 3. Interpret results:
--    - Part 1: Inspect individual workouts, look for outliers
--    - Part 2: Primary metric - are weeks trending up?
--    - Part 4: Week-over-week changes (🎯 KEY FEEDBACK)
--    - Part 5: Reality check vs peak capacity
-- ============================================================================