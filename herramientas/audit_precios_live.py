"""
Auditoría de integridad de precios y datos del dashboard.

Compara los valores embebidos en el snapshot (entry_close, latest_close,
actual_return) contra precios reales de Yahoo Finance para detectar:

  1. Staleness  — ¿cuántos días hábiles tiene de atraso la tabla prices?
  2. MTM abiertos — ¿los porcentajes de picks abiertos son correctos vs YF?
  3. Outcomes cerrados — ¿los retornos históricos coinciden con YF?
  4. Picks sin cerrar — posiciones con target_date pasado sin outcome
  5. Consistencia cross-modelo — mismo ticker/semana con precios distintos

Guarda el resultado en analisis/verify_payload.json que el dashboard embebe.

Uso:
    python herramientas/audit_precios_live.py
    python herramientas/audit_precios_live.py --dry-run
    python herramientas/audit_precios_live.py --output analisis/verify_payload.json
    python herramientas/audit_precios_live.py --max-open 30 --max-closed 15
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yfinance as yf

from infra.db.runtime import connect_runtime_db, RuntimeDB

# ── constantes ────────────────────────────────────────────────────────────────
DEFAULT_OUTPUT = ROOT / "analisis" / "verify_payload.json"
MTM_TOLERANCE_WARN = 0.5     # % — diferencia tolerable antes de WARN
MTM_TOLERANCE_CRIT = 3.0     # % — diferencia crítica
OUTCOME_TOLERANCE_WARN = 1.0  # % — para retornos históricos cerrados
OUTCOME_TOLERANCE_CRIT = 5.0
STALENESS_WARN_DAYS = 1       # días hábiles de atraso
STALENESS_CRIT_DAYS = 2
MAX_OPEN_TICKERS_DEFAULT = 40  # máximo de tickers abiertos a verificar con YF
MAX_CLOSED_DEFAULT = 12        # máximo de outcomes cerrados a verificar con YF
YF_FETCH_PERIOD = "30d"        # ventana de history a descargar por ticker
SCORE_W_FRESHNESS = 0.30
SCORE_W_MTM       = 0.40
SCORE_W_OUTCOMES  = 0.30


def _log(msg: str) -> None:
    print(f"[audit_precios] {msg}", flush=True)


def _biz_days_diff(date_a: str, date_b: str) -> int:
    """Diferencia aproximada en días hábiles entre dos fechas ISO YYYY-MM-DD."""
    try:
        d_a = datetime.date.fromisoformat(date_a)
        d_b = datetime.date.fromisoformat(date_b)
        if d_a > d_b:
            d_a, d_b = d_b, d_a
        total = 0
        cur = d_a
        while cur < d_b:
            cur += datetime.timedelta(days=1)
            if cur.weekday() < 5:  # lunes–viernes
                total += 1
        return total
    except (ValueError, TypeError):
        return 0


def _today_str() -> str:
    return datetime.datetime.now(datetime.UTC).date().isoformat()


# ── 1. Staleness de la tabla prices ──────────────────────────────────────────

def check_freshness(con: RuntimeDB) -> dict[str, Any]:
    """Verifica qué tan actualizada está la tabla prices en la DB."""
    try:
        row = con.execute(
            "SELECT MAX(date) AS mx FROM prices"
        ).fetchone()
        latest_date = str(row[0]) if row and row[0] else None
    except Exception as exc:
        return {
            "status": "error",
            "latest_price_date": None,
            "stale_biz_days": None,
            "error": str(exc),
        }

    today = _today_str()
    stale = _biz_days_diff(latest_date, today) if latest_date else 99

    if stale == 0:
        status = "ok"
    elif stale <= STALENESS_WARN_DAYS:
        status = "warn"
    else:
        status = "crit"

    return {
        "status": status,
        "latest_price_date": latest_date,
        "check_date": today,
        "stale_biz_days": stale,
    }


# ── 2. Picks sin cerrar ───────────────────────────────────────────────────────

def check_unclosed_picks(con: RuntimeDB) -> dict[str, Any]:
    """Busca predicciones con target_date < hoy sin outcome registrado."""
    today = _today_str()
    try:
        rows = con.execute(
            """
            SELECT p.model_name, p.ticker, p.prediction_date, p.target_date
            FROM predictions p
            LEFT JOIN outcomes o ON o.prediction_id = p.id
            WHERE o.id IS NULL
              AND p.target_date < ?
            ORDER BY p.target_date DESC
            LIMIT 50
            """,
            (today,),
        ).fetchall()
    except Exception as exc:
        return {"status": "error", "count": 0, "items": [], "error": str(exc)}

    items = [
        {
            "model_name": str(r[0]),
            "ticker": str(r[1]),
            "prediction_date": str(r[2]),
            "target_date": str(r[3]),
        }
        for r in rows
    ]
    count = len(items)
    status = "ok" if count == 0 else ("warn" if count <= 3 else "crit")
    return {"status": status, "count": count, "items": items}


# ── helpers de Yahoo Finance ──────────────────────────────────────────────────

def _fetch_yf_history(tickers: list[str], period: str = YF_FETCH_PERIOD) -> dict[str, Any]:
    """Descarga history para múltiples tickers en una sola llamada a YF.
    Retorna dict ticker → DataFrame con columna Close (indexed por Date).
    Maneja errores por ticker silenciosamente.
    """
    if not tickers:
        return {}
    try:
        raw = yf.download(
            tickers,
            period=period,
            auto_adjust=False,  # DB almacena precios sin ajustar (data_loader.py usa auto_adjust=False)
            progress=False,
            threads=True,
        )
    except Exception as exc:
        _log(f"ERROR yfinance download: {exc}")
        return {}

    result: dict[str, Any] = {}
    if raw.empty:
        return result

    # Con un solo ticker yf devuelve DataFrame plano; con múltiples devuelve MultiIndex
    if len(tickers) == 1:
        tk = tickers[0]
        if "Close" in raw.columns:
            result[tk] = raw[["Close"]].rename(columns={"Close": "close"})
    else:
        close_df = raw.get("Close") if "Close" in raw.columns else raw.xs("Close", axis=1, level=0, drop_level=True) if hasattr(raw.columns, "levels") else None
        if close_df is not None:
            for tk in tickers:
                if tk in close_df.columns:
                    s = close_df[[tk]].rename(columns={tk: "close"}).dropna()
                    if not s.empty:
                        result[tk] = s
    return result


def _yf_close_on_date(history: dict[str, Any], ticker: str, target_date: str) -> float | None:
    """Precio de cierre de un ticker en una fecha específica (o el más cercano anterior)."""
    df = history.get(ticker)
    if df is None or df.empty:
        return None
    try:
        td = datetime.date.fromisoformat(target_date)
    except ValueError:
        return None
    # Filtrar hasta target_date inclusive
    df_idx = df.copy()
    df_idx.index = df_idx.index.date  # type: ignore[assignment]
    filtered = df_idx[df_idx.index <= td]
    if filtered.empty:
        return None
    return float(filtered["close"].iloc[-1])


# ── 3. Verificación MTM picks abiertos ────────────────────────────────────────

def check_open_mtm(con: RuntimeDB, max_tickers: int = MAX_OPEN_TICKERS_DEFAULT) -> dict[str, Any]:
    """
    Compara MTM% del dashboard (calculado desde prices DB) contra YF real.
    Solo verifica tickers en picks abiertos (sin outcome aún).
    """
    today = _today_str()
    try:
        rows = con.execute(
            """
            SELECT
                p.ticker,
                p.prediction_date,
                p.target_date,
                p.model_name,
                p_entry.close AS entry_close,
                p_entry.date  AS entry_date,
                p_latest.close AS latest_close,
                lp.mx          AS latest_price_date
            FROM predictions p
            LEFT JOIN outcomes o ON o.prediction_id = p.id
            LEFT JOIN prices p_entry
                ON p_entry.ticker = p.ticker
                AND p_entry.date = (
                    SELECT MAX(pr2.date) FROM prices pr2
                    WHERE pr2.ticker = p.ticker AND pr2.date < p.prediction_date
                )
            LEFT JOIN (SELECT ticker, MAX(date) AS mx FROM prices GROUP BY ticker) lp
                ON lp.ticker = p.ticker
            LEFT JOIN prices p_latest
                ON p_latest.ticker = p.ticker AND p_latest.date = lp.mx
            WHERE o.id IS NULL
              AND p.target_date >= ?
            ORDER BY p.prediction_date DESC
            LIMIT ?
            """,
            (today, max_tickers * 3),  # traer más para dedup por ticker
        ).fetchall()
    except Exception as exc:
        return {"status": "error", "verified": 0, "items": [], "error": str(exc)}

    # Dedup: un ticker puede estar en varios modelos; tomamos la primera ocurrencia
    seen: set[str] = set()
    open_picks: list[dict[str, Any]] = []
    for r in rows:
        tk = str(r[0])
        if tk in seen:
            continue
        seen.add(tk)
        open_picks.append({
            "ticker": tk,
            "prediction_date": str(r[1]),
            "target_date": str(r[2]),
            "model_name": str(r[3]),
            "entry_close_db": float(r[4]) if r[4] is not None else None,
            "entry_date_db": str(r[5]) if r[5] else None,
            "latest_close_db": float(r[6]) if r[6] is not None else None,
            "latest_price_date_db": str(r[7]) if r[7] else None,
        })
        if len(open_picks) >= max_tickers:
            break

    if not open_picks:
        return {"status": "ok", "verified": 0, "items": [], "note": "no open picks"}

    tickers = [p["ticker"] for p in open_picks]
    _log(f"Descargando YF para {len(tickers)} tickers abiertos...")
    history = _fetch_yf_history(tickers, period="15d")

    items: list[dict[str, Any]] = []
    warn_count = 0
    crit_count = 0
    for pick in open_picks:
        tk = pick["ticker"]
        entry_close_db = pick["entry_close_db"]
        latest_close_db = pick["latest_close_db"]
        entry_date = pick["entry_date_db"]
        latest_price_date = pick["latest_price_date_db"]

        if entry_close_db is None or latest_close_db is None or entry_date is None:
            items.append({**pick, "status": "skip", "reason": "sin precios en DB"})
            continue

        # MTM según DB
        mtm_db = (latest_close_db - entry_close_db) / entry_close_db * 100.0

        # Precio de entrada según YF (día en que se tomó entrada = entry_date)
        yf_entry = _yf_close_on_date(history, tk, entry_date)
        # Precio actual según YF (último disponible)
        yf_latest = _yf_close_on_date(history, tk, latest_price_date or today)

        if yf_entry is None or yf_latest is None:
            items.append({
                **pick,
                "mtm_db_pct": round(mtm_db, 2),
                "status": "skip",
                "reason": "YF sin datos",
            })
            continue

        mtm_yf = (yf_latest - yf_entry) / yf_entry * 100.0
        diff = abs(mtm_db - mtm_yf)

        if diff >= MTM_TOLERANCE_CRIT:
            status = "crit"
            crit_count += 1
        elif diff >= MTM_TOLERANCE_WARN:
            status = "warn"
            warn_count += 1
        else:
            status = "ok"

        items.append({
            "ticker": tk,
            "model_name": pick["model_name"],
            "entry_date_db": entry_date,
            "entry_close_db": round(entry_close_db, 4),
            "entry_close_yf": round(yf_entry, 4),
            "latest_close_db": round(latest_close_db, 4),
            "latest_close_yf": round(yf_latest, 4),
            "mtm_db_pct": round(mtm_db, 2),
            "mtm_yf_pct": round(mtm_yf, 2),
            "diff_pct": round(diff, 2),
            "status": status,
        })

    verified = sum(1 for i in items if i.get("status") in ("ok", "warn", "crit"))
    if crit_count > 0:
        agg_status = "crit"
    elif warn_count > 0:
        agg_status = "warn"
    else:
        agg_status = "ok"

    return {
        "status": agg_status,
        "verified": verified,
        "ok_count": sum(1 for i in items if i.get("status") == "ok"),
        "warn_count": warn_count,
        "crit_count": crit_count,
        "items": items,
    }


# ── 4. Verificación outcomes cerrados ────────────────────────────────────────

def check_closed_outcomes(con: RuntimeDB, max_outcomes: int = MAX_CLOSED_DEFAULT) -> dict[str, Any]:
    """
    Compara actual_return en DB contra retorno calculado independientemente con YF.
    Verifica picks cerrados recientes para detectar bugs en el cálculo de outcomes.
    """
    try:
        rows = con.execute(
            """
            SELECT
                p.ticker,
                p.prediction_date,
                p.target_date,
                p.model_name,
                o.actual_return,
                p_entry.close AS entry_close,
                p_entry.date  AS entry_date,
                p_close.close AS target_close,
                p_close.date  AS target_close_date
            FROM predictions p
            JOIN outcomes o ON o.prediction_id = p.id
            LEFT JOIN prices p_entry
                ON p_entry.ticker = p.ticker
                AND p_entry.date = (
                    SELECT MAX(pr2.date) FROM prices pr2
                    WHERE pr2.ticker = p.ticker AND pr2.date < p.prediction_date
                )
            LEFT JOIN prices p_close
                ON p_close.ticker = p.ticker
                AND p_close.date = (
                    SELECT MAX(pr3.date) FROM prices pr3
                    WHERE pr3.ticker = p.ticker AND pr3.date <= p.target_date
                )
            WHERE o.actual_return IS NOT NULL
            ORDER BY p.target_date DESC, p.id DESC
            LIMIT ?
            """,
            (max_outcomes * 4,),
        ).fetchall()
    except Exception as exc:
        return {"status": "error", "verified": 0, "items": [], "error": str(exc)}

    # Dedup por ticker+target_date
    seen: set[tuple[str, str]] = set()
    closed: list[dict[str, Any]] = []
    for r in rows:
        key = (str(r[0]), str(r[2]))
        if key in seen:
            continue
        seen.add(key)
        if r[4] is None or r[5] is None:
            continue
        closed.append({
            "ticker": str(r[0]),
            "prediction_date": str(r[1]),
            "target_date": str(r[2]),
            "model_name": str(r[3]),
            "actual_return_db": float(r[4]),
            "entry_close_db": float(r[5]) if r[5] is not None else None,
            "entry_date_db": str(r[6]) if r[6] else None,
            "target_close_db": float(r[7]) if r[7] is not None else None,
            "target_close_date_db": str(r[8]) if r[8] else None,
        })
        if len(closed) >= max_outcomes:
            break

    if not closed:
        return {"status": "ok", "verified": 0, "items": [], "note": "no closed picks"}

    # Fetch YF para todos los tickers únicos en ventana amplia
    unique_tickers = list({c["ticker"] for c in closed})
    _log(f"Descargando YF para {len(unique_tickers)} tickers cerrados...")
    history = _fetch_yf_history(unique_tickers, period="60d")

    items: list[dict[str, Any]] = []
    warn_count = 0
    crit_count = 0

    for pick in closed:
        tk = pick["ticker"]
        actual_return_db = pick["actual_return_db"]
        entry_close_db = pick["entry_close_db"]
        entry_date = pick["entry_date_db"]
        target_date = pick["target_date"]

        if entry_close_db is None or entry_date is None:
            items.append({**pick, "status": "skip", "reason": "sin entry_close en DB"})
            continue

        # Retorno según YF
        yf_entry = _yf_close_on_date(history, tk, entry_date)
        yf_target = _yf_close_on_date(history, tk, target_date)

        if yf_entry is None or yf_target is None or yf_entry == 0:
            items.append({
                **pick,
                "actual_return_db_pct": round(actual_return_db * 100.0, 2),
                "status": "skip",
                "reason": "YF sin datos para entry/target",
            })
            continue

        # Verificar que los precios almacenados en DB coincidan con YF (misma fecha, tipo close).
        # El pipeline calcula actual_return con entry_open del día siguiente, pero aquí auditamos
        # la integridad de los precios almacenados comparando close vs close en la misma fecha.
        entry_price_diff = abs(entry_close_db - yf_entry) / yf_entry * 100.0 if yf_entry else 0.0
        target_close_db = pick.get("target_close_db") or 0.0
        target_price_diff = abs(target_close_db - yf_target) / yf_target * 100.0 if yf_target and target_close_db else 0.0
        price_diff = max(entry_price_diff, target_price_diff)

        if price_diff >= OUTCOME_TOLERANCE_CRIT:
            status = "crit"
            crit_count += 1
        elif price_diff >= OUTCOME_TOLERANCE_WARN:
            status = "warn"
            warn_count += 1
        else:
            status = "ok"

        # Retorno YF vs DB (solo informativo — el pipeline usa entry_open del día+1, no entry_close)
        actual_return_db_pct = actual_return_db * 100.0
        return_yf_pct = (yf_target - yf_entry) / yf_entry * 100.0

        items.append({
            "ticker": tk,
            "model_name": pick["model_name"],
            "prediction_date": pick["prediction_date"],
            "target_date": target_date,
            "entry_date_db": entry_date,
            "entry_close_db": round(entry_close_db, 4),
            "entry_close_yf": round(yf_entry, 4),
            "target_close_db": round(target_close_db, 4),
            "target_close_yf": round(yf_target, 4),
            "actual_return_db_pct": round(actual_return_db_pct, 2),
            "return_yf_pct": round(return_yf_pct, 2),
            "entry_price_diff_pct": round(entry_price_diff, 2),
            "target_price_diff_pct": round(target_price_diff, 2),
            "status": status,
        })

    verified = sum(1 for i in items if i.get("status") in ("ok", "warn", "crit"))
    if crit_count > 0:
        agg_status = "crit"
    elif warn_count > 0:
        agg_status = "warn"
    else:
        agg_status = "ok"

    return {
        "status": agg_status,
        "verified": verified,
        "ok_count": sum(1 for i in items if i.get("status") == "ok"),
        "warn_count": warn_count,
        "crit_count": crit_count,
        "items": items,
    }


# ── 5. Consistencia cross-modelo ──────────────────────────────────────────────

def check_cross_model_consistency(con: RuntimeDB) -> dict[str, Any]:
    """
    Detecta el mismo ticker con precios de entrada distintos en la misma fecha exacta
    en distintos modelos (señal de datos incoherentes en la tabla prices).
    Nota: dos modelos que entran el mismo ticker en días distintos de la misma semana
    tienen precios distintos por diseño; agrupar por semana generaba falsos positivos.
    """
    # Fecha límite hace 30 días
    thirty_days_ago = (datetime.datetime.now(datetime.UTC).date() - datetime.timedelta(days=30)).isoformat()
    try:
        rows = con.execute(
            """
            SELECT
                p.ticker,
                p.prediction_date,
                p.model_name,
                p_entry.close AS entry_close,
                p_entry.date  AS entry_date
            FROM predictions p
            LEFT JOIN prices p_entry
                ON p_entry.ticker = p.ticker
                AND p_entry.date = (
                    SELECT MAX(pr2.date) FROM prices pr2
                    WHERE pr2.ticker = p.ticker AND pr2.date < p.prediction_date
                )
            WHERE p_entry.close IS NOT NULL
              AND p.prediction_date >= ?
            ORDER BY p.ticker, p_entry.date
            """,
            (thirty_days_ago,),
        ).fetchall()
    except Exception as exc:
        return {"status": "error", "inconsistency_count": 0, "inconsistencies": [], "error": str(exc)}

    # Agrupar por ticker+entry_date exacto: mismo ticker+mismo día = mismo row en prices
    # → spread esperado = 0%. Cualquier spread > 0.1% indica corrupción de datos.
    from collections import defaultdict
    date_map: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        tk = str(r[0])
        model = str(r[2])
        price = float(r[3])
        entry_date = str(r[4]) if r[4] is not None else ""
        if not entry_date:
            continue
        date_map[(tk, entry_date)].append((model, price))

    inconsistencies: list[dict[str, Any]] = []
    for (tk, entry_date), entries in date_map.items():
        if len(entries) < 2:
            continue
        prices = [p for _, p in entries]
        min_p, max_p = min(prices), max(prices)
        if min_p <= 0:
            continue
        spread_pct = (max_p - min_p) / min_p * 100.0
        if spread_pct > 0.1:  # > 0.1% para mismo ticker+fecha exacta = incoherente
            inconsistencies.append({
                "ticker": tk,
                "entry_date": entry_date,
                "min_price": round(min_p, 4),
                "max_price": round(max_p, 4),
                "spread_pct": round(spread_pct, 2),
                "models": [m for m, _ in entries],
            })

    status = "ok" if not inconsistencies else ("warn" if len(inconsistencies) <= 2 else "crit")
    return {
        "status": status,
        "inconsistency_count": len(inconsistencies),
        "inconsistencies": inconsistencies[:10],
    }


# ── Score de confianza ─────────────────────────────────────────────────────────

def compute_confidence_score(
    freshness: dict[str, Any],
    mtm_check: dict[str, Any],
    outcomes_check: dict[str, Any],
    unclosed_check: dict[str, Any],
) -> float:
    """
    Score 0–100 ponderado:
      - Freshness (30%): 0 días stale = 100%, 1 día = 70%, 2+ = 30%
      - MTM abiertos (40%): ratio de picks OK vs total verificados
      - Outcomes cerrados (30%): ratio de histórico OK
    Penalización adicional por picks sin cerrar.
    """
    # Freshness score
    stale = freshness.get("stale_biz_days") or 0
    if stale == 0:
        fresh_score = 100.0
    elif stale == 1:
        fresh_score = 70.0
    elif stale == 2:
        fresh_score = 40.0
    else:
        fresh_score = 10.0

    # MTM score
    mtm_v = mtm_check.get("verified") or 0
    mtm_ok = mtm_check.get("ok_count") or 0
    if mtm_v > 0:
        mtm_score = (mtm_ok / mtm_v) * 100.0
        # Bajar proporcionalmente por críticos
        crit_w = (mtm_check.get("crit_count") or 0) * 15.0
        mtm_score = max(0.0, mtm_score - crit_w)
    elif mtm_check.get("status") == "error":
        mtm_score = 50.0  # penalización parcial, no total
    else:
        mtm_score = 95.0  # sin picks abiertos = no aplica, score neutro alto

    # Outcomes score
    out_v = outcomes_check.get("verified") or 0
    out_ok = outcomes_check.get("ok_count") or 0
    if out_v > 0:
        out_score = (out_ok / out_v) * 100.0
        crit_w = (outcomes_check.get("crit_count") or 0) * 20.0
        out_score = max(0.0, out_score - crit_w)
    elif outcomes_check.get("status") == "error":
        out_score = 50.0
    else:
        out_score = 95.0

    # Penalización por picks sin cerrar
    unclosed = unclosed_check.get("count") or 0
    unclosed_penalty = min(unclosed * 3.0, 20.0)

    score = (
        SCORE_W_FRESHNESS * fresh_score
        + SCORE_W_MTM * mtm_score
        + SCORE_W_OUTCOMES * out_score
    ) - unclosed_penalty

    return max(0.0, min(100.0, round(score, 1)))


def overall_status(score: float, checks: list[dict[str, Any]]) -> str:
    """Estado global: ok / warn / crit / error."""
    if any(c.get("status") == "crit" for c in checks):
        return "crit"
    if any(c.get("status") == "error" for c in checks):
        return "error"
    if score >= 85.0 and not any(c.get("status") == "warn" for c in checks):
        return "ok"
    if score >= 60.0:
        return "warn"
    return "crit"


# ── Runner principal ───────────────────────────────────────────────────────────

def run_audit(
    *,
    max_open: int = MAX_OPEN_TICKERS_DEFAULT,
    max_closed: int = MAX_CLOSED_DEFAULT,
    dry_run: bool = False,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    _log("Iniciando auditoría de integridad de precios...")

    # Conectar DB
    try:
        con = connect_runtime_db()
        _log(f"DB conectada: backend={con.backend.name}")
    except Exception as exc:
        _log(f"ERROR conectando DB: {exc}")
        payload = {
            "status": "error",
            "confidence_score": 0.0,
            "error": str(exc),
            "generated_at": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
            "checks": {},
        }
        if not dry_run:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    _log("Check 1/5: Staleness de prices table...")
    freshness = check_freshness(con)
    _log(f"  → {freshness['status']} | latest={freshness.get('latest_price_date')} | stale={freshness.get('stale_biz_days')}d")

    _log("Check 2/5: Picks sin cerrar...")
    unclosed = check_unclosed_picks(con)
    _log(f"  → {unclosed['status']} | count={unclosed.get('count', 0)}")

    _log(f"Check 3/5: MTM picks abiertos (max {max_open} tickers)...")
    mtm_check = check_open_mtm(con, max_tickers=max_open)
    _log(f"  → {mtm_check['status']} | verified={mtm_check.get('verified')} | warn={mtm_check.get('warn_count')} | crit={mtm_check.get('crit_count')}")

    _log(f"Check 4/5: Outcomes cerrados (max {max_closed} picks)...")
    outcomes_check = check_closed_outcomes(con, max_outcomes=max_closed)
    _log(f"  → {outcomes_check['status']} | verified={outcomes_check.get('verified')} | warn={outcomes_check.get('warn_count')} | crit={outcomes_check.get('crit_count')}")

    _log("Check 5/5: Consistencia cross-modelo...")
    cross_check = check_cross_model_consistency(con)
    _log(f"  → {cross_check['status']} | inconsistencies={cross_check.get('inconsistency_count', 0)}")

    score = compute_confidence_score(freshness, mtm_check, outcomes_check, unclosed)
    all_checks = [freshness, mtm_check, outcomes_check, unclosed, cross_check]
    status = overall_status(score, all_checks)

    _log(f"Score de confianza: {score:.1f}% | Estado global: {status}")

    # Payload minificado para el dashboard (evitar peso excesivo en HTML)
    # items de detalle: solo los que tienen estado != ok para ahorrar espacio
    def _trim_items(check: dict[str, Any], max_items: int = 8) -> dict[str, Any]:
        items = check.get("items") or []
        flagged = [i for i in items if i.get("status") in ("warn", "crit")]
        return {**check, "items": flagged[:max_items]}

    payload: dict[str, Any] = {
        "status": status,
        "confidence_score": score,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
        "checks": {
            "freshness": freshness,
            "unclosed_picks": unclosed,
            "open_mtm": _trim_items(mtm_check),
            "closed_outcomes": _trim_items(outcomes_check),
            "cross_model": cross_check,
        },
        "summary": {
            "freshness_status": freshness["status"],
            "freshness_latest_date": freshness.get("latest_price_date"),
            "freshness_stale_days": freshness.get("stale_biz_days"),
            "unclosed_count": unclosed.get("count", 0),
            "open_mtm_verified": mtm_check.get("verified", 0),
            "open_mtm_ok": mtm_check.get("ok_count", 0),
            "open_mtm_warn": mtm_check.get("warn_count", 0),
            "open_mtm_crit": mtm_check.get("crit_count", 0),
            "outcomes_verified": outcomes_check.get("verified", 0),
            "outcomes_ok": outcomes_check.get("ok_count", 0),
            "outcomes_warn": outcomes_check.get("warn_count", 0),
            "outcomes_crit": outcomes_check.get("crit_count", 0),
            "cross_inconsistencies": cross_check.get("inconsistency_count", 0),
        },
    }

    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        _log(f"Payload guardado en: {output_path}")

    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoría de integridad de precios del dashboard")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Ruta de salida del JSON")
    parser.add_argument("--dry-run", action="store_true", help="Solo imprimir resultado, no guardar")
    parser.add_argument("--max-open", type=int, default=MAX_OPEN_TICKERS_DEFAULT, help="Máximo tickers abiertos a verificar")
    parser.add_argument("--max-closed", type=int, default=MAX_CLOSED_DEFAULT, help="Máximo outcomes cerrados a verificar")
    args = parser.parse_args()

    payload = run_audit(
        max_open=args.max_open,
        max_closed=args.max_closed,
        dry_run=args.dry_run,
        output_path=args.output,
    )

    # Exit code según estado
    status = payload.get("status", "error")
    if status == "ok":
        _log("✅ Auditoría OK")
        return 0
    elif status == "warn":
        _log("⚠️  Auditoría con advertencias (no bloquea deploy)")
        return 0  # warnings no bloquean el pipeline
    elif status == "crit":
        _log("❌ Auditoría CRÍTICA — revisar datos antes de confiar en el dashboard")
        return 0  # tampoco bloquea; el dashboard muestra el semáforo rojo
    else:
        _log(f"ERROR en auditoría: {payload.get('error', 'desconocido')}")
        return 0  # nunca bloquear CI por este script — el dashboard lo muestra


if __name__ == "__main__":
    raise SystemExit(main())

# ci-trigger: semaforo 97% � 2026-05-06
