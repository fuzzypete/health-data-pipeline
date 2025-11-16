-- Lactate Tracking Query
-- Correlates lactate readings with workout metrics over time

WITH workout_watts AS (
    -- Calculate average watts per workout from strokes
    SELECT 
        workout_id,
        AVG(watts) as avg_watts,
        MAX(watts) as max_watts
    FROM lake.cardio_strokes
    WHERE watts > 0
    GROUP BY workout_id
)

SELECT 
    l.workout_id,
    l.lactate_mmol,
    l.measurement_time_utc,
    l.measurement_context,
    l.notes as lactate_notes,
    w.workout_type,
    w.start_time_utc::date as workout_date,
    ROUND(w.duration_s / 60.0, 1) as duration_min,
    ROUND(ww.avg_watts, 1) as average_watts,
    ROUND(ww.max_watts, 1) as max_watts,
    ROUND(w.avg_hr_bpm, 1) as avg_hr,
    ROUND(w.max_hr_bpm, 1) as max_hr,
    w.notes as workout_notes,
    
    -- Zone classification (approximate)
    CASE 
        WHEN w.avg_hr_bpm < 110 THEN 'Below Z2'
        WHEN w.avg_hr_bpm BETWEEN 110 AND 125 THEN 'Zone 2'
        WHEN w.avg_hr_bpm BETWEEN 126 AND 145 THEN 'Tempo/Threshold'
        ELSE 'Above Threshold'
    END as estimated_zone,
    
    -- Power-to-lactate ratio (higher = better aerobic efficiency)
    ROUND(ww.avg_watts / l.lactate_mmol, 1) as watts_per_lactate,
    
    -- Days since measurement
    DATEDIFF('day', l.measurement_time_utc, CURRENT_TIMESTAMP) as days_ago

FROM lake.lactate l
JOIN lake.workouts w ON l.workout_id = w.workout_id
LEFT JOIN workout_watts ww ON w.workout_id = ww.workout_id
WHERE w.source = 'Concept2'
ORDER BY l.measurement_time_utc DESC;

-- Run with: duckdb Data/duck/health.duckdb < lactate_tracking.sql
-- Or in Python for plotting:
-- df = duckdb.query("...").to_df()
-- df.plot(x='workout_date', y=['lactate_mmol', 'avg_hr', 'average_watts'])
