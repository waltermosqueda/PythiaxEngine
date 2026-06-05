"""
PostgreSQL migration to fix broken sequences after Supabase migration.

This fixes the issue where pipeline_runs_id_seq was not reset correctly 
when data was migrated from old Supabase to new Supabase on 2026-06-03.

Root cause: The sequence ended up at value 12, but the table had records 
up to ID 210, causing all new INSERTs to fail with unique constraint violations.

Applied: 2026-06-05 (after deep analysis confirmed the issue)
"""

-- Fix pipeline_runs sequence (CRITICAL - already fixed via Python script)
SELECT setval('pipeline_runs_id_seq', (SELECT MAX(id) FROM pipeline_runs) + 1);

-- Verify other sequences are correct (for documentation)
SELECT 
    schemaname,
    sequencename,
    (SELECT MAX(id) FROM model_metrics) as max_id,
    CASE WHEN currval(sequencename||'::regclass') > (SELECT MAX(id) FROM model_metrics) THEN 'OK' ELSE 'BROKEN' END as status
FROM pg_sequences 
WHERE sequencename = 'model_metrics_id_seq';

SELECT 
    schemaname,
    sequencename,
    (SELECT MAX(id) FROM predictions) as max_id,
    CASE WHEN currval(sequencename||'::regclass') > (SELECT MAX(id) FROM predictions) THEN 'OK' ELSE 'BROKEN' END as status
FROM pg_sequences 
WHERE sequencename = 'predictions_id_seq';

SELECT 
    schemaname,
    sequencename,
    (SELECT MAX(id) FROM outcomes) as max_id,
    CASE WHEN currval(sequencename||'::regclass') > (SELECT MAX(id) FROM outcomes) THEN 'OK' ELSE 'BROKEN' END as status
FROM pg_sequences 
WHERE sequencename = 'outcomes_id_seq';

SELECT 
    schemaname,
    sequencename,
    (SELECT MAX(id) FROM model_run_snapshots) as max_id,
    CASE WHEN currval(sequencename||'::regclass') > (SELECT MAX(id) FROM model_run_snapshots) THEN 'OK' ELSE 'BROKEN' END as status
FROM pg_sequences 
WHERE sequencename = 'model_run_snapshots_id_seq';
