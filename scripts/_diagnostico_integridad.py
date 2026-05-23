#!/usr/bin/env python3
"""
Diagnóstico exhaustivo de integridad de datos.
Verifica outcomes en Supabase y cross-valida contra yfinance.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, r"C:\repos\PythiaxEngine")

import math
from datetime import date, timedelta
from collections import defaultdict

from sqlalchemy import create_engine, text

# ─── Conexión Supabase ────────────────────────────────────────────────────────
SUPABASE_URL = (
    "postgresql+psycopg://postgres.datdtnliztfzbmfbmobx:"
    "%40Supabase7786@aws-1-us-west-2.pooler.supabase.com:5432/postgres"
)
eng = create_engine(SUPABASE_URL, connect_args={"connect_timeout": 20})

SEP = "─" * 72

def q(sql, **params):
    with eng.connect() as c:
        return c.execute(text(sql), params).fetchall()

print(SEP)
print("DIAGNÓSTICO EXHAUSTIVO — Integridad de datos (Supabase)")
print(SEP)

# ─── 1. Resumen general ──────────────────────────────────────────────────────
print("\n[1] RESUMEN GENERAL")
rows = q("""
    SELECT
        COUNT(*) AS total_outcomes,
        COUNT(DISTINCT p.model_name) AS modelos,
        COUNT(DISTINCT p.target_date) AS fechas_distintas,
        MIN(p.target_date) AS primera_fecha,
        MAX(p.target_date) AS ultima_fecha
    FROM outcomes o
    JOIN predictions p ON p.id = o.prediction_id
""")
r = rows[0]
print(f"  Total outcomes  : {r[0]:,}")
print(f"  Modelos         : {r[1]}")
print(f"  Fechas distintas: {r[2]}")
print(f"  Rango           : {r[3]} → {r[4]}")

# ─── 2. Distribución de actual_return ────────────────────────────────────────
print("\n[2] DISTRIBUCIÓN DE actual_return")
dist = q("""
    SELECT
        ROUND(actual_return::numeric, 6) AS ret,
        COUNT(*) AS n
    FROM outcomes
    GROUP BY ROUND(actual_return::numeric, 6)
    ORDER BY n DESC
    LIMIT 30
""")
print(f"  {'actual_return':>14}  {'count':>8}  nota")
for ret, n in dist:
    nota = ""
    if ret == 0.0:
        nota = "  ← SOSPECHOSO si hay muchos"
    elif abs(ret) > 0.5:
        nota = "  ← RETORNO ENORME (>50%)"
    elif abs(ret) > 0.20:
        nota = "  ← grande (>20%)"
    print(f"  {ret:>14.6f}  {n:>8,}{nota}")

# ─── 3. Ceros exactos por modelo ─────────────────────────────────────────────
print("\n[3] CEROS EXACTOS (actual_return = 0.0) POR MODELO")
zeros_by_model = q("""
    SELECT
        p.model_name,
        COUNT(*) AS ceros,
        COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY p.model_name) AS pct_of_model
    FROM outcomes o
    JOIN predictions p ON p.id = o.prediction_id
    WHERE o.actual_return = 0.0
    GROUP BY p.model_name
    ORDER BY ceros DESC
""")
total_zeros = q("SELECT COUNT(*) FROM outcomes WHERE actual_return = 0.0")[0][0]
print(f"  Total ceros exactos: {total_zeros:,}")
print(f"\n  {'modelo':40}  {'ceros':>7}")
for model, ceros, pct in zeros_by_model:
    print(f"  {model:40}  {ceros:>7,}  ({pct:.1f}% del modelo)")

# ─── 4. Valores extremos / outliers ──────────────────────────────────────────
print("\n[4] OUTLIERS — retornos > 20% o < -20%")
outliers = q("""
    SELECT
        p.model_name,
        p.ticker,
        p.prediction_date,
        p.target_date,
        o.actual_return,
        o.hit
    FROM outcomes o
    JOIN predictions p ON p.id = o.prediction_id
    WHERE ABS(o.actual_return) > 0.20
    ORDER BY ABS(o.actual_return) DESC
    LIMIT 30
""")
print(f"  Casos con |ret| > 20%: {len(outliers)}")
for model, ticker, pred_date, tgt_date, ret, hit in outliers:
    print(f"  {ticker:6} {pred_date}→{tgt_date}  ret={ret:+.4f}  hit={hit}  [{model}]")

# ─── 5. Inconsistencias hit/direction ────────────────────────────────────────
print("\n[5] INCONSISTENCIAS HIT vs ACTUAL_RETURN")
# hit=1 (acertó UP) pero return < 0, o hit=0 (erró DOWN) pero return > 0
inconsistencies = q("""
    SELECT
        p.model_name,
        p.ticker,
        p.target_date,
        p.direction AS predicted,
        o.actual_direction,
        o.actual_return,
        o.hit
    FROM outcomes o
    JOIN predictions p ON p.id = o.prediction_id
    WHERE
        -- Predijo UP, acertó (hit=1) pero el retorno fue negativo
        (p.direction = 'UP' AND o.hit = 1 AND o.actual_return < -0.001)
        OR
        -- Predijo DOWN, acertó (hit=1) pero el retorno fue positivo
        (p.direction = 'DOWN' AND o.hit = 1 AND o.actual_return > 0.001)
        OR
        -- hit=1 pero actual_direction ≠ direction
        (o.hit = 1 AND p.direction != o.actual_direction)
        OR
        -- hit=0 pero actual_direction = direction
        (o.hit = 0 AND p.direction = o.actual_direction)
    LIMIT 40
""")
print(f"  Inconsistencias encontradas: {len(inconsistencies)}")
for model, ticker, tgt, pred_dir, act_dir, ret, hit in inconsistencies[:20]:
    print(f"  {ticker:6} {tgt}  pred={pred_dir} act={act_dir} ret={ret:+.4f} hit={hit}  [{model[:30]}]")

# ─── 6. Ceros por fecha — ¿dias enteros de 0.0? ──────────────────────────────
print("\n[6] FECHAS CON MUCHOS CEROS (posible problema de precios ese día)")
zero_dates = q("""
    SELECT
        p.target_date,
        COUNT(*) AS total,
        SUM(CASE WHEN o.actual_return = 0.0 THEN 1 ELSE 0 END) AS ceros,
        ROUND(SUM(CASE WHEN o.actual_return = 0.0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS pct_cero
    FROM outcomes o
    JOIN predictions p ON p.id = o.prediction_id
    GROUP BY p.target_date
    HAVING SUM(CASE WHEN o.actual_return = 0.0 THEN 1 ELSE 0 END) > 0
    ORDER BY pct_cero DESC, ceros DESC
    LIMIT 25
""")
print(f"  {'fecha':12}  {'total':>6}  {'ceros':>6}  {'%cero':>6}")
for d, total, ceros, pct in zero_dates:
    alerta = "  ← TODOS" if pct == 100.0 else ("  ← MAYORÍA" if pct > 50 else "")
    print(f"  {d}  {total:>6,}  {ceros:>6,}  {pct:>5.1f}%{alerta}")

# ─── 7. Ceros por ticker — ¿acciones con siempre 0.0? ────────────────────────
print("\n[7] TICKERS CON MÁS CEROS EXACTOS")
zero_tickers = q("""
    SELECT
        p.ticker,
        COUNT(*) AS total,
        SUM(CASE WHEN o.actual_return = 0.0 THEN 1 ELSE 0 END) AS ceros,
        ROUND(SUM(CASE WHEN o.actual_return = 0.0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS pct_cero
    FROM outcomes o
    JOIN predictions p ON p.id = o.prediction_id
    GROUP BY p.ticker
    HAVING SUM(CASE WHEN o.actual_return = 0.0 THEN 1 ELSE 0 END) > 0
    ORDER BY ceros DESC
    LIMIT 20
""")
print(f"  {'ticker':8}  {'total':>6}  {'ceros':>6}  {'%cero':>6}")
for ticker, total, ceros, pct in zero_tickers:
    alerta = "  ← SIEMPRE 0" if pct == 100.0 else ""
    print(f"  {ticker:8}  {total:>6,}  {ceros:>6,}  {pct:>5.1f}%{alerta}")

# ─── 8. Muestra de casos con 0.0 para cross-validate con yfinance ────────────
print("\n[8] MUESTRA PARA CROSS-VALIDACIÓN CON YFINANCE (primeros 20 ceros)")
sample_zeros = q("""
    SELECT
        p.ticker,
        p.prediction_date,
        p.target_date,
        p.model_name
    FROM outcomes o
    JOIN predictions p ON p.id = o.prediction_id
    WHERE o.actual_return = 0.0
    ORDER BY p.target_date DESC
    LIMIT 20
""")

# ─── Cross-validación con yfinance ────────────────────────────────────────────
print("\n[9] CROSS-VALIDACIÓN YFINANCE vs DB (verificando precios reales)")
try:
    import yfinance as yf
    
    # Agrupamos por ticker para descargar de a lotes
    check_cases = [(t, p, tgt, m) for t, p, tgt, m in sample_zeros]
    tickers_needed = list({t for t, _, _, _ in check_cases})
    
    # Rango de fechas
    all_dates = [tgt for _, _, tgt, _ in check_cases] + [p for _, p, _, _ in check_cases]
    date_min = min(all_dates)
    date_max = max(all_dates)
    # Extendemos el rango 3 días por cada lado para capturar fechas de mercado
    dmin = (date.fromisoformat(date_min) - timedelta(days=5)).isoformat()
    dmax = (date.fromisoformat(date_max) + timedelta(days=5)).isoformat()
    
    print(f"  Descargando {len(tickers_needed)} tickers desde {dmin} hasta {dmax}...")
    
    price_data = {}
    for ticker in tickers_needed:
        try:
            df = yf.download(ticker, start=dmin, end=dmax, auto_adjust=False, progress=False)
            if not df.empty:
                price_data[ticker] = {
                    str(idx.date()): float(row["Close"].iloc[0] if hasattr(row["Close"], "iloc") else row["Close"])
                    for idx, row in df.iterrows()
                    if not (isinstance(row["Close"], float) and math.isnan(row["Close"]))
                }
        except Exception as e:
            price_data[ticker] = {}
    
    print(f"\n  {'ticker':8}  {'pred_date':12}  {'tgt_date':12}  {'close_pred':>12}  {'close_tgt':>12}  {'ret_yf':>10}  {'ret_db':>10}  estado")
    print(f"  {'-'*8}  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*10}  {'-'*10}  ------")
    
    # También obtenemos los ret de DB para esta muestra
    for ticker, pred_date, tgt_date, model in check_cases[:20]:
        prices = price_data.get(ticker, {})
        
        # Buscamos precio más cercano a las fechas pedidas
        def closest_price(target_date_str):
            d = date.fromisoformat(target_date_str)
            for offset in range(0, 4):
                candidate = (d + timedelta(days=offset)).isoformat()
                if candidate in prices:
                    return prices[candidate], candidate
                candidate = (d - timedelta(days=offset)).isoformat()
                if candidate in prices:
                    return prices[candidate], candidate
            return None, None
        
        close_pred, actual_pred_date = closest_price(pred_date)
        close_tgt, actual_tgt_date = closest_price(tgt_date)
        
        if close_pred and close_tgt and close_pred != 0:
            ret_yf = (close_tgt - close_pred) / close_pred
            estado = "OK" if abs(ret_yf) < 0.001 else f"DISCREPANCIA ret_yf={ret_yf:+.4f}"
        else:
            ret_yf = None
            estado = "sin precio YF"
        
        ret_str = f"{ret_yf:+.4f}" if ret_yf is not None else "    -   "
        cp_str = f"{close_pred:.4f}" if close_pred else "     -   "
        ct_str = f"{close_tgt:.4f}" if close_tgt else "     -   "
        print(f"  {ticker:8}  {pred_date}  {tgt_date}  {cp_str:>12}  {ct_str:>12}  {ret_str:>10}  {0.0:>10.4f}  {estado}")

except ImportError:
    print("  yfinance no disponible")
except Exception as e:
    print(f"  Error yfinance: {e}")

# ─── 10. Verificar precios en DB local (precios stale) ────────────────────────
print("\n[10] PRECIOS EN DB — fechas duplicadas o congeladas (mismo close N días)")
stale_prices = q("""
    SELECT
        ticker,
        close,
        COUNT(*) AS dias_repetidos,
        MIN(date) AS desde,
        MAX(date) AS hasta
    FROM prices
    GROUP BY ticker, close
    HAVING COUNT(*) >= 5
    ORDER BY dias_repetidos DESC
    LIMIT 20
""")
print(f"  Casos con mismo close >= 5 días seguidos:")
if stale_prices:
    for ticker, close, dias, desde, hasta in stale_prices:
        print(f"  {ticker:8}  close={close:.4f}  {dias} días  ({desde} → {hasta})")
else:
    print("  Ninguno — precios no están congelados")

# ─── 11. Cobertura de precios para tickers con outcomes ──────────────────────
print("\n[11] TICKERS CON OUTCOMES SIN PRECIOS EN DB (data faltante)")
missing_prices = q("""
    SELECT DISTINCT p.ticker
    FROM predictions p
    JOIN outcomes o ON o.prediction_id = p.id
    WHERE p.ticker NOT IN (SELECT DISTINCT ticker FROM prices)
    LIMIT 20
""")
if missing_prices:
    print(f"  Tickers sin precios: {[r[0] for r in missing_prices]}")
else:
    print("  Todos los tickers con outcomes tienen precios en DB ✓")

# ─── 12. Predicciones sin outcomes (pendientes o abandonadas) ─────────────────
print("\n[12] PREDICCIONES SIN OUTCOMES POR MODELO")
no_outcomes = q("""
    SELECT
        model_name,
        COUNT(*) AS sin_outcome,
        MIN(target_date) AS primera,
        MAX(target_date) AS ultima
    FROM predictions p
    WHERE NOT EXISTS (SELECT 1 FROM outcomes o WHERE o.prediction_id = p.id)
      AND target_date < CURRENT_DATE::text
    GROUP BY model_name
    ORDER BY sin_outcome DESC
""")
if no_outcomes:
    for model, n, primera, ultima in no_outcomes:
        print(f"  {model:45}  {n:>6} sin outcome  ({primera} → {ultima})")
else:
    print("  Todas las predicciones vencidas tienen outcomes ✓")

# ─── 13. Doble-evaluación — mismo prediction_id con 2 outcomes ───────────────
print("\n[13] DOBLE-EVALUACIÓN (prediction_id con múltiples outcomes)")
dupes = q("""
    SELECT prediction_id, COUNT(*) AS n
    FROM outcomes
    GROUP BY prediction_id
    HAVING COUNT(*) > 1
    LIMIT 10
""")
if dupes:
    print(f"  ⚠ Hay {len(dupes)} predicciones con múltiples outcomes!")
    for pred_id, n in dupes:
        print(f"  prediction_id={pred_id}  n={n}")
else:
    print("  Sin doble-evaluaciones ✓")

# ─── 14. hit coherence: AVG(hit) por modelo ──────────────────────────────────
print("\n[14] SANITY CHECK — WIN RATE POR MODELO")
wr = q("""
    SELECT
        p.model_name,
        COUNT(*) AS total,
        ROUND(AVG(o.hit::float) * 100, 2) AS wr_pct,
        ROUND(AVG(o.actual_return) * 100, 4) AS avg_ret_pct,
        SUM(CASE WHEN o.actual_return = 0.0 THEN 1 ELSE 0 END) AS ceros,
        SUM(CASE WHEN ABS(o.actual_return) > 0.20 THEN 1 ELSE 0 END) AS extremos
    FROM outcomes o
    JOIN predictions p ON p.id = o.prediction_id
    GROUP BY p.model_name
    ORDER BY total DESC
""")
print(f"  {'modelo':45}  {'total':>7}  {'WR%':>7}  {'avgRet%':>8}  {'ceros':>6}  {'>20%':>5}")
for model, total, wr_pct, avg_ret, ceros, extremos in wr:
    flags = []
    if wr_pct is not None and (wr_pct > 90 or wr_pct < 10):
        flags.append("WR_EXTREMO")
    if avg_ret is not None and abs(avg_ret) > 5:
        flags.append("RET_GRANDE")
    if ceros > total * 0.3:
        flags.append("MUCHOS_CEROS")
    flag_str = "  ← " + ", ".join(flags) if flags else ""
    print(f"  {model:45}  {total:>7,}  {wr_pct:>7.2f}  {avg_ret:>8.4f}  {ceros:>6,}  {extremos:>5,}{flag_str}")

print(f"\n{SEP}")
print("FIN DEL DIAGNÓSTICO")
print(SEP)
