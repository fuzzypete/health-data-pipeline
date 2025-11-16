-- Historical Iron Depletion Timeline Analysis
-- Shows ferritin, performance metrics, and protocol changes over time
-- Focus: Oct 2024 - Nov 2025 (depletion period)

WITH -- <-- FIX 1: Added the missing WITH keyword

-- Part 1: Labs timeline (ferritin, HDL, key biomarkers)
labs_timeline AS (
    SELECT 
        date,
        MAX(CASE WHEN marker = 'Ferritin' THEN value END) as ferritin,
        MAX(CASE WHEN marker = 'HDL' THEN value END) as hdl,
        MAX(CASE WHEN marker = 'Hemoglobin' THEN value END) as hemoglobin,
        MAX(CASE WHEN marker = 'MCHC' THEN value END) as mchc,
        MAX(CASE WHEN marker = 'eGFR' THEN value END) as egfr
    FROM lake.labs
    WHERE date >= '2024-01-01'
    GROUP BY date
),

-- Part 2: Monthly workout performance with watts from cardio_strokes
monthly_performance AS (
    SELECT 
        DATE_TRUNC('month', w.start_time_utc) as month,
        w.workout_type,
        COUNT(DISTINCT w.workout_id) as workout_count,
        ROUND(AVG(s.avg_watts), 1) as avg_watts,
        ROUND(AVG(w.max_hr_bpm), 1) as avg_max_hr,
        ROUND(AVG(w.avg_hr_bpm), 1) as avg_hr,
        ROUND(AVG(CASE WHEN w.avg_hr_bpm BETWEEN 105 AND 125 THEN s.avg_watts END), 1) as zone2_watts
    FROM lake.workouts w
    LEFT JOIN (
        -- Calculate average watts per workout from strokes
        SELECT 
            workout_id,
            AVG(watts) as avg_watts
        FROM lake.cardio_strokes
        WHERE watts > 0
        GROUP BY workout_id
    ) s ON w.workout_id = s.workout_id
    WHERE w.start_time_utc >= '2024-01-01'
        AND w.source = 'Concept2'
        AND w.workout_type IN ('Rowing', 'Cycling')
    GROUP BY DATE_TRUNC('month', w.start_time_utc), w.workout_type
),

-- Part 3: Protocol events (TRT start, compounds, blood donations)
protocol_events AS (
    SELECT 
        start_date as event_date,
        'Protocol: ' || compound_name as event_description,
        notes
    FROM lake.protocol_history
    WHERE start_date >= '2024-01-01'
    -- Removed unnecessary ORDER BY from inside the CTE
)

-- Combine all data sources for timeline view
SELECT 
    l.date as date, -- <-- FIX 2: Removed COALESCE to out-of-scope mp and pe aliases
    'Lab' as data_type,
    l.ferritin,
    l.hdl,
    l.hemoglobin,
    l.mchc,
    NULL as avg_watts,
    NULL as avg_max_hr,
    NULL as event_description
FROM labs_timeline l

UNION ALL

SELECT 
    mp.month::date as date,
    'Performance: ' || mp.workout_type as data_type,
    NULL as ferritin,
    NULL as hdl,
    NULL as hemoglobin,
    NULL as mchc,
    mp.zone2_watts as avg_watts,
    mp.avg_max_hr,
    NULL as event_description
FROM monthly_performance mp

UNION ALL

SELECT 
    pe.event_date as date,
    'Event' as data_type,
    NULL, NULL, NULL, NULL, NULL, NULL,
    pe.event_description || COALESCE(' - ' || pe.notes, '') as event_description
FROM protocol_events pe

ORDER BY date;