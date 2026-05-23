#!/usr/bin/env python3
"""
FIX: Corrige precios open=close en Supabase (May 4-8, 2026)
y recalcula los outcomes con actual_return=0.0 afectados.

Causa raíz: pipeline corrió antes del cierre de mercado (19:51 UTC) y
Yahoo Finance devolvió barras incompletas donde open=high=low=close=precio_actual.
Los evaluadores D1/D3 calcularon (close - open)/open = 0.0 exacto.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, r"C:\repos\PythiaxEngine")

import yfinance as yf
from sqlalchemy import create_engine, text

URL = (
    "postgresql+psycopg://postgres.datdtnliztfzbmfbmobx:"
    "%40Supabase7786@aws-1-us-west-2.pooler.supabase.com:5432/postgres"
)
eng = create_engine(URL, connect_args={"connect_timeout": 30})

SEP = "─" * 72


def q(sql, **params):
    with eng.connect() as c:
        return c.execute(text(sql), params).fetchall()


# ── 1. Predicciones afectadas ────────────────────────────────────────────────
print(SEP)
print("PASO 1: Identificando predicciones afectadas (May 4-8, actual_return=0.0)")
affected = q("""
    SELECT
        o.id          AS outcome_id,
        p.id          AS pred_id,
        p.ticker,
        p.prediction_date::text,
        p.target_date::text,
        p.model_name,
        p.direction
    FROM outcomes o
    JOIN predictions p ON p.id = o.prediction_id
    WHERE o.actual_return = 0.0
      AND p.target_date BETWEEN '2026-05-04' AND '2026-05-08'
    ORDER BY p.target_date, p.ticker
""")
print(f"  {len(affected)} outcomes a corregir")

# ── 2. Calendario de trading (SPY dates) para calcular entry_date ─────────────
spy_dates_raw = q("""
    SELECT date::text FROM prices
    WHERE ticker = 'SPY' AND date BETWEEN '2026-04-28' AND '2026-05-12'
    ORDER BY date
""")
spy_dates = [r[0] for r in spy_dates_raw]
date_to_idx = {d: i for i, d in enumerate(spy_dates)}


def trading_day_offset(date_str, n):
    idx = date_to_idx.get(str(date_str))
    if idx is None:
        return None
    ti = idx + n
    return spy_dates[ti] if ti < len(spy_dates) else None


# ── 3. Descargar OHLCV correcto desde yfinance ───────────────────────────────
print(SEP)
print("PASO 2: Descargando OHLCV real desde yfinance (sin cache)...")
tickers_needed = sorted({r[2] for r in affected})
print(f"  Tickers: {tickers_needed}")

# Descarga fresca, sin cache de sesión compartida con intraday
real_ohlcv: dict[tuple[str, str], tuple[float, float, float, float]] = {}
for t in tickers_needed:
    try:
        # Usar cache limpio por símbolo para evitar contaminación
        df = yf.Ticker(t).history(start="2026-05-03", end="2026-05-10", auto_adjust=False)
        if not df.empty:
            for idx, row in df.iterrows():
                d = idx.date().isoformat()
                o = float(row["Open"])
                h = float(row["High"])
                lo = float(row["Low"])
                c = float(row["Close"])
                real_ohlcv[(t, d)] = (o, h, lo, c)
        print(f"  {t}: {sum(1 for k in real_ohlcv if k[0]==t)} filas")
    except Exception as e:
        print(f"  [WARN] {t}: {e}")

print(f"  Total (ticker,date) pares: {len(real_ohlcv)}")

# ── 4. Actualizar precios en Supabase ────────────────────────────────────────
print(SEP)
print("PASO 3: Actualizando precios en Supabase (solo rows con open≈close)...")
updated_prices = 0
skipped_ok = 0
skipped_still_bad = 0
price_updates: list[dict] = []

for (ticker, date_str), (o, h, lo, c) in real_ohlcv.items():
    if abs(o - c) < 0.01:
        skipped_still_bad += 1
        continue  # yfinance también devuelve dato sospechoso, no actualizar
    price_updates.append({"t": ticker, "d": date_str, "o": o, "h": h, "lo": lo, "c": c})

with eng.begin() as conn:
    for row in price_updates:
        result = conn.execute(text("""
            UPDATE prices
            SET open = :o, high = :h, low = :lo, close = :c
            WHERE ticker = :t AND date = :d
              AND ABS(open - close) < 0.01
        """), row)
        rc = result.rowcount
        updated_prices += rc
        if rc == 0:
            skipped_ok += 1

print(f"  Precios actualizados : {updated_prices}")
print(f"  Ya estaban correctos : {skipped_ok}")
print(f"  Aún sospechosos en YF: {skipped_still_bad}")

# ── 5. Recargar precios corregidos para recalcular outcomes ──────────────────
print(SEP)
print("PASO 4: Recargando precios corregidos desde Supabase...")
corrected: dict[tuple[str, str], tuple[float, float]] = {}
price_rows = q("""
    SELECT ticker, date::text, open, close
    FROM prices
    WHERE date BETWEEN '2026-05-03' AND '2026-05-10'
""")
for t, d, o, c in price_rows:
    if o is not None and c is not None:
        corrected[(t, d)] = (float(o), float(c))

# ── 6. Recalcular outcomes ────────────────────────────────────────────────────
print(SEP)
print("PASO 5: Recalculando outcomes...")

outcomes_to_update: list[dict] = []
skipped_reasons: list[str] = []

for outcome_id, pred_id, ticker, pred_date, target_date, model, direction in affected:
    entry_date = trading_day_offset(pred_date, 1)
    if entry_date is None:
        skipped_reasons.append(f"outcome={outcome_id} ticker={ticker}: no entry_date")
        continue

    # Standard tradeable return for all models:
    # return = (close(target_date) - open(entry_date)) / open(entry_date)
    entry_row = corrected.get((ticker, entry_date))
    target_row = corrected.get((ticker, target_date))
    if entry_row is None:
        skipped_reasons.append(f"outcome={outcome_id} {ticker}: sin precio entry {entry_date}")
        continue
    if target_row is None:
        skipped_reasons.append(f"outcome={outcome_id} {ticker}: sin precio target {target_date}")
        continue
    entry_open = entry_row[0]
    target_close = target_row[1]
    if entry_open in (None, 0):
        skipped_reasons.append(f"outcome={outcome_id} {ticker}: entry_open null/0")
        continue
    if target_close is None:
        skipped_reasons.append(f"outcome={outcome_id} {ticker}: target_close null")
        continue
    actual_return = (target_close - entry_open) / entry_open

    actual_direction = "UP" if actual_return >= 0 else "DOWN"
    hit = 1 if str(direction).upper() == actual_direction else 0
    outcomes_to_update.append({
        "ret": float(actual_return),
        "dir": actual_direction,
        "hit": hit,
        "oid": int(outcome_id),
        "_ticker": ticker,
        "_target": target_date,
        "_model": model[:35],
    })

print(f"  Outcomes a actualizar: {len(outcomes_to_update)}")
print(f"  Skipped              : {len(skipped_reasons)}")
for r in skipped_reasons:
    print(f"    {r}")

print(f"\n  Preview (primeros 15):")
print(f"  {'ticker':8}  {'target':12}  {'ret':>10}  {'dir':>6}  {'hit':>4}  modelo")
for row in outcomes_to_update[:15]:
    print(f"  {row['_ticker']:8}  {row['_target']:12}  {row['ret']:>10.4f}  {row['dir']:>6}  {row['hit']:>4}  {row['_model']}")

# ── 7. Aplicar UPDATEs a Supabase ─────────────────────────────────────────────
print(SEP)
print("PASO 6: Aplicando UPDATEs a Supabase...")
with eng.begin() as conn:
    for row in outcomes_to_update:
        conn.execute(text("""
            UPDATE outcomes
            SET actual_return = :ret,
                actual_direction = :dir,
                hit = :hit
            WHERE id = :oid
        """), {"ret": row["ret"], "dir": row["dir"], "hit": row["hit"], "oid": row["oid"]})

print(f"  ✓ {len(outcomes_to_update)} outcomes actualizados en Supabase")

# ── 8. Verificación final ─────────────────────────────────────────────────────
print(SEP)
print("PASO 7: Verificación final...")
remaining_zeros = q("""
    SELECT COUNT(*) FROM outcomes o
    JOIN predictions p ON p.id = o.prediction_id
    WHERE o.actual_return = 0.0 AND p.target_date BETWEEN '2026-05-04' AND '2026-05-08'
""")
print(f"  Zeros restantes en May 4-8: {remaining_zeros[0][0]}")

sample = q("""
    SELECT p.ticker, p.target_date::text, o.actual_return, o.hit, p.model_name
    FROM outcomes o JOIN predictions p ON p.id=o.prediction_id
    WHERE p.target_date BETWEEN '2026-05-04' AND '2026-05-08'
    ORDER BY p.target_date, p.ticker
    LIMIT 20
""")
print(f"\n  Muestra post-fix:")
print(f"  {'ticker':8}  {'target':12}  {'ret':>10}  {'hit':>4}  modelo")
for t, d, r, h, m in sample:
    print(f"  {t:8}  {d}  {r:>10.4f}  {h:>4}  {m[:35]}")

print(SEP)
print("FIX COMPLETADO")
print(SEP)
