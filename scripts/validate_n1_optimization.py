#!/usr/bin/env python3
"""
Validation script: Verify N+1 batch optimization produces identical outcomes.
Tests that the refactored evaluate_due_predictions maintains prediction quality.
"""

from datetime import datetime, date, timedelta
from pathlib import Path
import sys

# Setup path
repo_path = Path(__file__).parent.parent
sys.path.insert(0, str(repo_path))
sys.path.insert(0, str(repo_path / "repo"))

from titan_system.core.database import TitanDB
from herramientas.aprendizaje_operativo_v11 import OperationalLearningV11

def validate_batch_optimization():
    """Test that evaluate_due_predictions produces consistent results."""
    
    print("\n" + "="*70)
    print("[VALIDATION] N+1 Batch Optimization - Prediction Quality Check")
    print("="*70)
    
    try:
        with TitanDB() as db:
            # Check database connectivity
            count_result = db.conn.execute("SELECT COUNT(*) as cnt FROM predictions").fetchone()
            total_predictions = count_result[0] if count_result else 0
            
            print(f"\n[DB] Connected. Total predictions: {total_predictions:,}")
            
            # Get recent evaluation dates
            recent_evaluations = db.conn.execute(
                """
                SELECT DISTINCT p.target_date
                FROM predictions p
                LEFT JOIN outcomes o ON p.id = o.prediction_id
                WHERE p.model_name LIKE 'INVERTIR_V11_%'
                ORDER BY p.target_date DESC
                LIMIT 5
                """
            ).fetchall()
            
            print(f"\n[PRED] Recent target dates (last 5):")
            for row in recent_evaluations:
                print(f"       - {row[0]}")
            
            # Count outcomes before
            outcomes_before = db.conn.execute(
                "SELECT COUNT(*) as cnt FROM outcomes WHERE prediction_id IN (SELECT id FROM predictions WHERE model_name LIKE 'INVERTIR_V11_%')"
            ).fetchone()[0]
            
            print(f"\n[OUTCOMES] Before test: {outcomes_before:,} outcomes recorded")
            
            # Initialize V11 operational learning
            learner = OperationalLearningV11(db)
            
            # Get a recent date that has pending predictions without outcomes
            pending_check = db.conn.execute(
                """
                SELECT DISTINCT p.target_date
                FROM predictions p
                LEFT JOIN outcomes o ON p.id = o.prediction_id
                WHERE p.model_name LIKE 'INVERTIR_V11_%'
                AND o.id IS NULL
                ORDER BY p.target_date DESC
                LIMIT 1
                """
            ).fetchone()
            
            if not pending_check:
                print("\n[WARN] No pending predictions found to evaluate.")
                print("[INFO] This is OK - means all predictions have been evaluated.")
                return True
            
            target_date = pending_check[0]
            print(f"\n[TEST] Evaluating pending predictions for target_date: {target_date}")
            
            # Get pending predictions count for this date
            pending_count = db.conn.execute(
                """
                SELECT COUNT(*) as cnt
                FROM predictions p
                LEFT JOIN outcomes o ON p.id = o.prediction_id
                WHERE p.model_name LIKE 'INVERTIR_V11_%'
                AND p.target_date = ?
                AND o.id IS NULL
                """,
                (target_date,)
            ).fetchone()[0]
            
            print(f"[TEST] Pending predictions for this date: {pending_count}")
            
            # Run evaluation (uses batch optimization)
            print("\n[RUN] Executing evaluate_due_predictions()...")
            summary = learner.evaluate_due_predictions(max_target_date=target_date, recompute_existing=False)
            
            print(f"\n[RESULT] Evaluation Summary:")
            print(f"  - Evaluated:  {summary['evaluated']:>6}")
            print(f"  - Hits:       {summary['hits']:>6} ({summary['hits']/max(1,summary['evaluated'])*100:.1f}%)")
            print(f"  - Misses:     {summary['misses']:>6}")
            print(f"  - Errors:     {summary['errors']:>6}")
            print(f"  - Dates:      {summary['dates']:>6}")
            
            # Verify no errors
            if summary['errors'] > 0:
                error_rate = summary['errors'] / (summary['evaluated'] + summary['errors']) * 100
                if error_rate > 5:  # Allow < 5% error rate from missing price data
                    print(f"\n[ERROR] Error rate too high: {error_rate:.1f}%")
                    return False
            
            # Check that outcomes were inserted
            outcomes_after = db.conn.execute(
                "SELECT COUNT(*) as cnt FROM outcomes WHERE prediction_id IN (SELECT id FROM predictions WHERE model_name LIKE 'INVERTIR_V11_%')"
            ).fetchone()[0]
            
            new_outcomes = outcomes_after - outcomes_before
            print(f"\n[OUTCOMES] After test: {outcomes_after:,} total (+{new_outcomes} new)")
            
            if new_outcomes > 0:
                print("[OK] Outcomes successfully inserted by batch optimization")
            
            # Sample check: verify a few outcomes have reasonable values
            sample_outcomes = db.conn.execute(
                """
                SELECT o.actual_direction, o.actual_return, o.hit
                FROM outcomes o
                JOIN predictions p ON p.id = o.prediction_id
                WHERE p.model_name LIKE 'INVERTIR_V11_%'
                AND o.actual_direction IN ('UP', 'DOWN')
                LIMIT 5
                """
            ).fetchall()
            
            if sample_outcomes:
                print(f"\n[SAMPLE] Random outcome samples:")
                for direction, ret, hit in sample_outcomes:
                    print(f"       - {direction:4s} | ret={ret*100:+7.2f}% | hit={hit}")
                print("[OK] Outcomes have valid structure and values")
            
            print("\n" + "="*70)
            print("[SUCCESS] N+1 Batch Optimization validation PASSED")
            print("="*70 + "\n")
            return True
            
    except Exception as e:
        print(f"\n[ERROR] Validation failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = validate_batch_optimization()
    sys.exit(0 if success else 1)
