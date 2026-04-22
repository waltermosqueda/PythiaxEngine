"""
GESTOR DE POSICIONES V11
========================

Herramienta operativa para V11/V15:
  - registra posiciones abiertas tomadas manualmente
  - persiste sizing real de V15 por posicion
  - mide PnL sized abierto/cerrado, no solo retorno crudo
  - muestra la accion recomendada hoy para cada posicion
  - revisa slots libres vs nuevas senales del scanner activo
  - genera un reporte diario integrable al pipeline
"""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from SCANNER.invertir_v11 import (
    A_HOLDING_DAYS,
    C_EARLY_TP_DAYS,
    C_EARLY_TP_PCT,
    C_HOLDING_DAYS,
)
from SCANNER import invertir_v11 as v11
from titan_system.core.database import TitanDB


STATE_VERSION = 2
DEFAULT_STATE_PATH = ROOT / "herramientas" / "v11_open_positions.json"
LEGACY_STATE_PATH = ROOT / "herramientas" / "v10_open_positions.json"
REPORTS_DIR = ROOT / "aprendizaje_operativo" / "v11_reports"
OPS_C_SCORE_MAX = 85.0
OPS_C_VOL_MAX = 4.0
MAX_SLOTS = 3

ATR_SIZING_ENABLED = True
ATR_SIZING_TARGET_PCT = 4.0
ATR_SIZING_MIN_FACTOR = 0.3
ATR_SIZING_MAX_FACTOR = 2.0


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_money(value: float | None) -> str:
    if value is None:
        return ""
    return f"${float(value):,.2f}"


def _fmt_pct(value: float | None, signed: bool = True) -> str:
    if value is None:
        return ""
    if signed:
        return f"{float(value):+.2f}%"
    return f"{float(value):.2f}%"


def _fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"


def _fmt_shares(value: float | None) -> str:
    if value is None:
        return ""
    return f"{float(value):.4f}"


def _timestamp_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def default_account() -> dict[str, Any]:
    return {
        "equity_base": None,
        "currency": "USD",
        "max_slots": MAX_SLOTS,
        "updated_at": None,
    }


def default_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "policy": "SCORE85_VOL4_ATR4",
        "account": default_account(),
        "positions": [],
    }


def calc_slot_base(equity_base: float | None, max_slots: int = MAX_SLOTS) -> float | None:
    if equity_base is None or equity_base <= 0 or max_slots <= 0:
        return None
    return float(equity_base) / float(max_slots)


def calc_suggested_shares(entry_price: float | None, notional_suggested: float | None) -> float | None:
    if entry_price is None or entry_price <= 0 or notional_suggested is None or notional_suggested <= 0:
        return None
    return round(float(notional_suggested) / float(entry_price), 4)


def calc_atr_size_factor(atr_pct: float | None) -> tuple[float, str]:
    if not ATR_SIZING_ENABLED or atr_pct is None or atr_pct <= 0:
        return 1.0, "equal_weight"

    raw_factor = ATR_SIZING_TARGET_PCT / max(float(atr_pct), 0.5)
    factor = max(ATR_SIZING_MIN_FACTOR, min(ATR_SIZING_MAX_FACTOR, raw_factor))
    return round(factor, 2), f"ATR {float(atr_pct):.1f}% -> {factor:.2f}x slot"


def build_sizing_snapshot(
    *,
    entry_price: float,
    atr_pct: float | None,
    equity_base: float | None,
    shares_real: float | None = None,
    size_factor: float | None = None,
    size_note: str | None = None,
) -> dict[str, Any]:
    factor, factor_note = calc_atr_size_factor(atr_pct) if size_factor is None else (
        round(float(size_factor), 2),
        size_note or "",
    )
    slot_base = calc_slot_base(equity_base, MAX_SLOTS)
    notional_suggested = round(slot_base * factor, 2) if slot_base is not None else None
    shares_suggested = calc_suggested_shares(entry_price, notional_suggested)
    shares_effective = float(shares_real) if shares_real is not None else shares_suggested
    entry_notional_effective = (
        round(float(shares_effective) * float(entry_price), 2) if shares_effective is not None else None
    )

    return {
        "equity_base": None if equity_base is None else round(float(equity_base), 2),
        "slot_base": None if slot_base is None else round(float(slot_base), 2),
        "size_factor": round(float(factor), 2),
        "size_note": size_note or factor_note,
        "notional_suggested": notional_suggested,
        "shares_suggested": shares_suggested,
        "shares_real": None if shares_real is None else round(float(shares_real), 4),
        "shares_effective": shares_effective,
        "entry_notional_effective": entry_notional_effective,
    }


def migrate_position(position: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(position)
    migrated.setdefault("status", "OPEN")
    migrated.setdefault("validated", False)
    migrated.setdefault("validation_error", None)
    migrated.setdefault("notes", "")

    meta = dict(migrated.get("meta", {}))
    sizing = dict(migrated.get("sizing", {}))

    entry_price = _to_float(migrated.get("entry_price"))
    atr_pct = _to_float(sizing.get("atr_pct"))
    if atr_pct is None:
        atr_pct = _to_float(meta.get("atr_pct"))

    size_factor = _to_float(sizing.get("size_factor"))
    if size_factor is None:
        size_factor = _to_float(meta.get("size_factor"))

    size_note = sizing.get("size_note") or meta.get("size_note")
    equity_base = _to_float(sizing.get("equity_base"))
    if equity_base is None:
        equity_base = _to_float(account.get("equity_base"))

    shares_real = _to_float(sizing.get("shares_real"))
    if shares_real is None:
        shares_real = _to_float(migrated.get("shares_real"))

    if entry_price is not None:
        normalized_sizing = build_sizing_snapshot(
            entry_price=entry_price,
            atr_pct=atr_pct,
            equity_base=equity_base,
            shares_real=shares_real,
            size_factor=size_factor,
            size_note=size_note,
        )
        for field in (
            "notional_suggested",
            "shares_suggested",
            "shares_effective",
            "entry_notional_effective",
            "slot_base",
        ):
            if field in sizing and sizing[field] is not None:
                normalized_sizing[field] = round(float(sizing[field]), 4 if "shares" in field else 2)
        if sizing.get("size_note"):
            normalized_sizing["size_note"] = sizing["size_note"]
    else:
        normalized_sizing = {
            "equity_base": equity_base,
            "slot_base": None,
            "size_factor": size_factor or 1.0,
            "size_note": size_note or "",
            "notional_suggested": None,
            "shares_suggested": None,
            "shares_real": shares_real,
            "shares_effective": shares_real,
            "entry_notional_effective": None,
        }

    migrated["meta"] = meta
    migrated["sizing"] = normalized_sizing
    return migrated


def migrate_state(raw: dict[str, Any]) -> dict[str, Any]:
    state = default_state()
    raw_policy = raw.get("policy", state["policy"])
    if raw_policy in {"SCORE85_VOL4", "SCORE85_VOL4_V11"}:
        raw_policy = "SCORE85_VOL4_ATR4"
    state["policy"] = raw_policy

    account = default_account()
    account_raw = raw.get("account", {})
    account["currency"] = account_raw.get("currency", account["currency"])
    account["max_slots"] = int(account_raw.get("max_slots", MAX_SLOTS) or MAX_SLOTS)
    account["equity_base"] = _to_float(account_raw.get("equity_base"))
    account["updated_at"] = account_raw.get("updated_at")

    if account["equity_base"] is None:
        legacy_equity = _to_float(raw.get("equity_base"))
        if legacy_equity is not None:
            account["equity_base"] = legacy_equity
            account["updated_at"] = account["updated_at"] or _timestamp_now()

    state["account"] = account
    state["positions"] = [migrate_position(position, account) for position in raw.get("positions", [])]
    return state


def load_state(path: Path) -> dict[str, Any]:
    if path == DEFAULT_STATE_PATH and not path.exists() and LEGACY_STATE_PATH.exists():
        raw = json.loads(LEGACY_STATE_PATH.read_text(encoding="utf-8"))
        return migrate_state(raw)
    if not path.exists():
        return default_state()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return migrate_state(raw)


def save_state(path: Path, state: dict[str, Any]) -> None:
    normalized = migrate_state(state)
    normalized["version"] = STATE_VERSION
    path.write_text(json.dumps(normalized, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def normalize_signal(signal: str) -> str:
    value = signal.strip().upper()
    if value in {"A", "A (MEANREV)", "MEANREV", "MEAN_REVERSION"}:
        return "A"
    if value in {"C", "C4", "C5", "C4 (CRASH+REBOUND)", "C5 (CRASHCAP)", "CRASH", "CRASH+REBOUND"}:
        return "C5"
    raise ValueError(f"Signal no reconocido: {signal}")


def prev_trading_day(df: pd.DataFrame, trading_date: str) -> str | None:
    ts = pd.Timestamp(trading_date)
    earlier = df.index[df.index < ts]
    if len(earlier) == 0:
        return None
    return earlier[-1].date().isoformat()


def resolve_close_price(df: pd.DataFrame, trading_date: str) -> float | None:
    ts = pd.Timestamp(trading_date)
    if ts not in df.index:
        return None
    price = df.loc[ts, "Close"]
    if pd.isna(price):
        return None
    return float(price)


def infer_signal_result(
    ticker: str,
    signal: str,
    signal_date: str,
    prepared: dict[str, pd.DataFrame],
) -> tuple[v11.ScanResult | None, str | None]:
    if ticker not in prepared:
        return None, "ticker ausente en titan.db"

    df = prepared[ticker]
    ts = pd.Timestamp(signal_date)
    if ts not in df.index:
        return None, "signal_date no esta en titan.db"

    work = df.loc[:ts].copy()
    if signal == "A":
        result = v11.signal_a_mean_reversion(ticker, work)
    else:
        result = v11.build_c5_candidate(ticker, work)

    if result is None:
        return None, "la logica del scanner no valida ese setup en signal_date"
    return result, None


def classify_c4_priority(score: float | None, vol_ratio: float | None) -> str:
    if score is None or vol_ratio is None:
        return "UNKNOWN"
    if score < OPS_C_SCORE_MAX and vol_ratio < OPS_C_VOL_MAX:
        return "PREFERRED"
    return "EXTREME"


def result_to_meta(result: v11.ScanResult, signal: str) -> dict[str, Any]:
    meta = {
        "score": round(float(result.score), 2),
        "rsi": None if result.rsi is None else round(float(result.rsi), 2),
        "vol_ratio": None if result.vol_ratio is None else round(float(result.vol_ratio), 2),
        "roc10": None if result.roc10 is None else round(float(result.roc10), 2),
        "atr_pct": None if result.atr_pct is None else round(float(result.atr_pct), 2),
        "note": result.note,
    }
    if signal == "C5":
        meta["priority"] = classify_c4_priority(meta["score"], meta["vol_ratio"])
    else:
        meta["priority"] = "STANDARD"

    size_factor, size_note = calc_atr_size_factor(meta["atr_pct"])
    meta["size_factor"] = size_factor
    meta["size_note"] = size_note
    return meta


def format_signal_rows(results: list[v11.ScanResult], equity_base: float | None = None) -> pd.DataFrame:
    rows = []
    for result in results:
        size_factor, _ = calc_atr_size_factor(result.atr_pct)
        slot_base = calc_slot_base(equity_base, MAX_SLOTS)
        notional_suggested = round(slot_base * size_factor, 2) if slot_base is not None else None
        shares_suggested = calc_suggested_shares(float(result.price), notional_suggested)
        rows.append(
            {
                "Ticker": result.ticker,
                "Signal": result.signal,
                "Sector": result.sector,
                "Precio": round(float(result.price), 2),
                "RSI": "" if result.rsi is None else round(float(result.rsi), 1),
                "vs SMA50": "" if result.dist_sma50 is None else f"{float(result.dist_sma50):.1f}%",
                "ROC 10d": "" if result.roc10 is None else f"{float(result.roc10):.1f}%",
                "Vol": "" if result.vol_ratio is None else f"{float(result.vol_ratio):.2f}x",
                "ATR%": "" if result.atr_pct is None else f"{float(result.atr_pct):.1f}%",
                "Sizing": f"{size_factor:.1f}x",
                "Notional": _fmt_money(notional_suggested),
                "Sh sug": _fmt_shares(shares_suggested),
                "Score": round(float(result.score), 1),
                "Nota": result.note,
            }
        )
    return pd.DataFrame(rows)


def load_market_context() -> dict[str, Any]:
    today = date.today()
    with TitanDB() as db:
        universe_data, missing = v11.load_universe_data(db, v11.UNIVERSE)
        prepared = v11.precompute_indicators(universe_data)
        if "SPY" not in prepared:
            raise RuntimeError("SPY no esta disponible en titan.db")

        latest_date_str = db.get_latest_date("SPY")
        latest_dt = datetime.strptime(latest_date_str, "%Y-%m-%d").date() if latest_date_str else None
        staleness = v11.business_days_between(latest_dt, today) if latest_dt else None
        regime_safe, regime_info = v11.check_regime(prepared["SPY"])
        breadth = v11.compute_breadth(universe_data)
        quality_alerts = v11.recent_quality_alerts(prepared)

    return {
        "prepared": prepared,
        "latest_date_str": latest_date_str,
        "staleness": staleness,
        "regime_safe": regime_safe,
        "regime_info": regime_info,
        "breadth": breadth,
        "quality_alerts": quality_alerts,
        "missing": missing,
    }


def build_latest_signals(prepared: dict[str, pd.DataFrame], regime_safe: bool) -> list[v11.ScanResult]:
    results_a: list[v11.ScanResult] = []
    results_c5: list[v11.ScanResult] = []

    for ticker in sorted(t for t in prepared.keys() if t != "SPY"):
        df = prepared[ticker]
        if regime_safe:
            sig_a = v11.signal_a_mean_reversion(ticker, df)
            if sig_a is not None:
                results_a.append(sig_a)

        sig_c5 = v11.build_c5_candidate(ticker, df)
        if sig_c5 is not None and not any(existing.ticker == ticker for existing in results_a):
            results_c5.append(sig_c5)

    all_results = results_a + results_c5
    all_results.sort(key=lambda item: item.score, reverse=True)
    return all_results


def effective_shares(position: dict[str, Any]) -> float | None:
    sizing = position.get("sizing", {})
    shares_real = _to_float(sizing.get("shares_real"))
    if shares_real is not None:
        return shares_real
    shares_effective = _to_float(sizing.get("shares_effective"))
    if shares_effective is not None:
        return shares_effective
    return _to_float(sizing.get("shares_suggested"))


def entry_notional_effective(position: dict[str, Any]) -> float | None:
    sizing = position.get("sizing", {})
    entry_notional = _to_float(sizing.get("entry_notional_effective"))
    if entry_notional is not None:
        return entry_notional
    shares = effective_shares(position)
    entry_price = _to_float(position.get("entry_price"))
    if shares is None or entry_price is None:
        return None
    return round(shares * entry_price, 2)


def enrich_open_position(position: dict[str, Any], prepared: dict[str, pd.DataFrame], latest_date: str) -> dict[str, Any]:
    ticker = position["ticker"]
    signal = position["signal"]
    df = prepared.get(ticker)

    if df is None:
        return {**position, "action": "ERROR", "action_note": "ticker ausente", "current_return_pct": None}

    entry_ts = pd.Timestamp(position["entry_date"])
    latest_ts = pd.Timestamp(latest_date)
    if entry_ts not in df.index or latest_ts not in df.index:
        return {**position, "action": "ERROR", "action_note": "entry_date o latest_date no estan en la DB"}

    entry_loc = df.index.get_loc(entry_ts)
    latest_loc = df.index.get_loc(latest_ts)
    current_close = float(df["Close"].iloc[latest_loc])
    entry_price = float(position["entry_price"])
    current_return_pct = (current_close / entry_price - 1.0) * 100.0
    trading_days = latest_loc - entry_loc
    tp_price = entry_price * (1.0 + C_EARLY_TP_PCT / 100.0)

    shares_used = effective_shares(position)
    entry_notional = entry_notional_effective(position)
    current_notional = round(shares_used * current_close, 2) if shares_used is not None else None
    pnl_amount = None
    if current_notional is not None and entry_notional is not None:
        pnl_amount = round(current_notional - entry_notional, 2)

    sizing = position.get("sizing", {})
    equity_base = _to_float(sizing.get("equity_base"))
    pnl_equity_pct = None
    if pnl_amount is not None and equity_base not in (None, 0):
        pnl_equity_pct = round((pnl_amount / equity_base) * 100.0, 3)

    action = "HOLD"
    action_note = ""

    if signal == "A":
        due_loc = entry_loc + A_HOLDING_DAYS
        if latest_loc == due_loc:
            action = "CLOSE_TODAY"
            action_note = f"hold cumplido ({A_HOLDING_DAYS}d)"
        elif latest_loc > due_loc:
            action = "PAST_DUE_CLOSE"
            action_note = f"debio cerrarse hace {latest_loc - due_loc} rueda(s)"
        else:
            action_note = f"dia {trading_days}/{A_HOLDING_DAYS}"
    else:
        tp_hit_loc = None
        tp_window_end = min(entry_loc + C_EARLY_TP_DAYS, latest_loc)
        for idx in range(entry_loc + 1, tp_window_end + 1):
            close_px = float(df["Close"].iloc[idx])
            if close_px >= tp_price:
                tp_hit_loc = idx
                break

        due_loc = entry_loc + C_HOLDING_DAYS
        if tp_hit_loc is not None:
            hit_date = df.index[tp_hit_loc].date().isoformat()
            if latest_loc == tp_hit_loc:
                action = "TAKE_PROFIT_TODAY"
                action_note = f"activo TP temprano (+{C_EARLY_TP_PCT:.0f}%)"
            else:
                action = "MISSED_TP_REVIEW"
                action_note = f"el TP ya se activo el {hit_date}"
        elif latest_loc == due_loc:
            action = "CLOSE_TODAY"
            action_note = f"day {C_HOLDING_DAYS} alcanzado"
        elif latest_loc > due_loc:
            action = "PAST_DUE_CLOSE"
            action_note = f"debio cerrarse hace {latest_loc - due_loc} rueda(s)"
        else:
            action_note = f"dia {trading_days}/{C_HOLDING_DAYS} | TP @ ${tp_price:.2f}"

    return {
        **position,
        "current_close": round(current_close, 2),
        "current_return_pct": round(current_return_pct, 2),
        "trading_days": int(trading_days),
        "shares_effective": shares_used,
        "entry_notional_effective": entry_notional,
        "current_notional_effective": current_notional,
        "unrealized_pnl_amount": pnl_amount,
        "unrealized_pnl_equity_pct": pnl_equity_pct,
        "action": action,
        "action_note": action_note,
    }


def priority_bucket(result: v11.ScanResult) -> str:
    signal_name = result.signal.upper()
    if signal_name.startswith("A"):
        return "STANDARD"
    if signal_name.startswith("C5"):
        return classify_c4_priority(float(result.score), float(result.vol_ratio or 0.0))
    return "UNKNOWN"


def portfolio_summary(state: dict[str, Any], enriched_open: list[dict[str, Any]]) -> dict[str, Any]:
    positions = state.get("positions", [])
    open_positions = [position for position in positions if position.get("status", "OPEN") == "OPEN"]
    closed_positions = [position for position in positions if position.get("status") == "CLOSED"]

    account = state.get("account", {})
    equity_base = _to_float(account.get("equity_base"))
    realized_pnl = 0.0
    realized_known = 0
    for position in closed_positions:
        pnl_amount = _to_float(position.get("realized_pnl_amount"))
        if pnl_amount is not None:
            realized_pnl += pnl_amount
            realized_known += 1

    unrealized_pnl = 0.0
    unrealized_known = 0
    open_notional = 0.0
    open_notional_known = 0
    for position in enriched_open:
        pnl_amount = _to_float(position.get("unrealized_pnl_amount"))
        if pnl_amount is not None:
            unrealized_pnl += pnl_amount
            unrealized_known += 1
        notional = _to_float(position.get("current_notional_effective"))
        if notional is not None:
            open_notional += notional
            open_notional_known += 1

    marked_equity = None
    if equity_base is not None:
        marked_equity = round(equity_base + realized_pnl + unrealized_pnl, 2)

    return {
        "equity_base": equity_base,
        "open_positions": len(open_positions),
        "closed_positions": len(closed_positions),
        "realized_pnl_amount": round(realized_pnl, 2) if realized_known else None,
        "unrealized_pnl_amount": round(unrealized_pnl, 2) if unrealized_known else None,
        "open_notional_amount": round(open_notional, 2) if open_notional_known else None,
        "marked_equity": marked_equity,
    }


def build_status_text(state_path: Path, report_mode: bool = False) -> str:
    state = load_state(state_path)
    market = load_market_context()
    prepared = market["prepared"]
    latest_date_str = market["latest_date_str"]
    regime_safe = market["regime_safe"]

    open_positions = [position for position in state["positions"] if position.get("status", "OPEN") == "OPEN"]
    enriched = [enrich_open_position(position, prepared, latest_date_str) for position in open_positions]
    summary = portfolio_summary(state, enriched)

    output = io.StringIO()
    with redirect_stdout(output):
        print("=" * 110)
        title = "REPORTE DIARIO GESTOR V11" if report_mode else f"GESTOR POSICIONES V11 - {date.today().isoformat()}"
        print(f"  {title}")
        print("=" * 110)
        print(f"  Archivo estado   : {state_path}")
        print(f"  Politica slots   : {state.get('policy', 'SCORE85_VOL4_ATR4')}")
        print(f"  Ultima fecha DB  : {latest_date_str}")
        if market["staleness"] is not None:
            freshness = "AL DIA" if market["staleness"] <= 1 else f"STALE ({market['staleness']} dias habiles)"
            print(f"  Frescura DB      : {freshness}")
        if "safe" in market["regime_info"]:
            label = "SEGURO" if market["regime_info"]["safe"] else "PELIGRO"
            print(
                f"  Regimen          : {label} | SPY dist {market['regime_info']['spy_dist']:+.2f}% | "
                f"vol20 {market['regime_info']['spy_vol20d']:.2f}%"
            )
        print(f"  Breadth > SMA50  : {market['breadth']['pct_above_sma50']:.1f}%")

        print("\n" + "=" * 110)
        print("  CUENTA Y SIZING V15")
        print("=" * 110)
        print(f"  Equity base      : {_fmt_money(summary['equity_base']) or 'NO CONFIGURADA'}")
        print(f"  Slot base        : {_fmt_money(calc_slot_base(summary['equity_base'], MAX_SLOTS))}")
        print(f"  Slots maximos    : {MAX_SLOTS}")
        print(f"  PnL realizado    : {_fmt_money(summary['realized_pnl_amount'])}")
        print(f"  PnL abierto      : {_fmt_money(summary['unrealized_pnl_amount'])}")
        print(f"  Exposicion open  : {_fmt_money(summary['open_notional_amount'])}")
        print(f"  Equity marcada   : {_fmt_money(summary['marked_equity'])}")

        print("\n" + "=" * 110)
        print("  POSICIONES ABIERTAS")
        print("=" * 110)
        if enriched:
            rows = []
            for pos in enriched:
                meta = pos.get("meta", {})
                sizing = pos.get("sizing", {})
                rows.append(
                    {
                        "Ticker": pos["ticker"],
                        "Signal": pos["signal"],
                        "Entry": pos["entry_date"],
                        "Px in": round(float(pos["entry_price"]), 2),
                        "Px now": pos.get("current_close", ""),
                        "Ret": "" if pos.get("current_return_pct") is None else f"{pos['current_return_pct']:+.2f}%",
                        "PnL$": _fmt_money(pos.get("unrealized_pnl_amount")),
                        "Eq%": _fmt_pct(pos.get("unrealized_pnl_equity_pct")),
                        "Sh sug": _fmt_shares(sizing.get("shares_suggested")),
                        "Sh real": _fmt_shares(sizing.get("shares_real")),
                        "Not sug": _fmt_money(sizing.get("notional_suggested")),
                        "Not eff": _fmt_money(pos.get("current_notional_effective")),
                        "ATRx": _fmt_num(sizing.get("size_factor"), 2),
                        "Tier": meta.get("priority", ""),
                        "Accion": pos.get("action", ""),
                        "Nota": pos.get("action_note", ""),
                    }
                )
            df_show = pd.DataFrame(rows)
            print(df_show.to_string(index=False))
        else:
            print("  Sin posiciones abiertas registradas.")

        free_slots = max(0, MAX_SLOTS - len(enriched))
        print("\n" + "=" * 110)
        print("  NUEVAS SENALES Y SLOTS")
        print("=" * 110)
        print(f"  Slots ocupados   : {len(enriched)}/{MAX_SLOTS}")
        print(f"  Slots libres     : {free_slots}")

        latest_signals = build_latest_signals(prepared, regime_safe)
        preferred = [signal for signal in latest_signals if priority_bucket(signal) in {"STANDARD", "PREFERRED"}]
        extreme = [signal for signal in latest_signals if priority_bucket(signal) == "EXTREME"]

        if preferred:
            print("\n  Senales preferidas para consumir slot:")
            df_show = format_signal_rows(preferred[: max(5, free_slots)], summary["equity_base"])
            df_show["Tier"] = [priority_bucket(signal) for signal in preferred[: len(df_show)]]
            print(df_show.to_string(index=False))
        else:
            print("\n  No hay senales preferidas hoy.")

        if extreme:
            print("\n  Senales C5 extremas (solo modo agresivo):")
            df_show = format_signal_rows(extreme[:5], summary["equity_base"])
            df_show["Tier"] = [priority_bucket(signal) for signal in extreme[: len(df_show)]]
            print(df_show.to_string(index=False))

        if market["quality_alerts"]:
            print("\n  Alertas de calidad recientes:")
            for alert in market["quality_alerts"][:5]:
                print(
                    f"  - {alert['ticker']} {alert['date']} | ret1 {alert['ret1']:+.1f}% | "
                    f"intraday {alert['intraday']:+.1f}% | rango {alert['range_pct']:.1f}%"
                )

        recent_closed = [p for p in state["positions"] if p.get("status") == "CLOSED"][-5:]
        if recent_closed:
            print("\n" + "=" * 110)
            print("  CIERRES RECIENTES")
            print("=" * 110)
            rows = []
            for pos in recent_closed:
                rows.append(
                    {
                        "Ticker": pos["ticker"],
                        "Entry": pos.get("entry_date", ""),
                        "Exit": pos.get("exit_date", ""),
                        "Ret": _fmt_pct(_to_float(pos.get("realized_return_pct"))),
                        "PnL$": _fmt_money(_to_float(pos.get("realized_pnl_amount"))),
                        "Eq%": _fmt_pct(_to_float(pos.get("realized_pnl_equity_pct"))),
                        "Sh used": _fmt_shares(_to_float(pos.get("shares_used"))),
                    }
                )
            print(pd.DataFrame(rows).to_string(index=False))

        print("\n" + "=" * 110)
        print("  GUIA OPERATIVA")
        print("=" * 110)
        print("  - A y C5 preferred pueden consumir slot.")
        print(f"  - C5 preferred = score < {OPS_C_SCORE_MAX:.0f} y vol_ratio < {OPS_C_VOL_MAX:.1f}.")
        print("  - C5 extreme queda para modo agresivo o slots totalmente vacios.")
        print("  - El gestor no cierra posiciones solo: marca la accion recomendada.")
        print("  - V15 sized PnL usa shares reales si existen; si no, usa shares sugeridas.")
        if summary["equity_base"] is None:
            print("  - Falta configurar equity_base para que el loop V15 mida sizing y PnL en serio.")
        if ATR_SIZING_ENABLED:
            print()
            print("  ATR SIZING ACTIVO (V15 validated):")
            print(f"  - Target: {ATR_SIZING_TARGET_PCT:.0f}% ATR diario por posicion")
            print(f"  - Slot base = equity / {MAX_SLOTS}. Sizing = slot_base * factor.")
            print(f"  - Factor = target / ATR%. Clamp [{ATR_SIZING_MIN_FACTOR:.1f}x, {ATR_SIZING_MAX_FACTOR:.1f}x].")
            print("  - shares_sugeridas = notional_sugerido / precio de entrada")
            print("  - shares_reales pueden diferir; el gestor prioriza lo realmente ejecutado")

    return output.getvalue().rstrip() + "\n"


def render_status(state_path: Path) -> None:
    print(build_status_text(state_path), end="")


def write_daily_report(state_path: Path) -> Path:
    market = load_market_context()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "" if state_path == DEFAULT_STATE_PATH else f"_{state_path.stem}"
    path = REPORTS_DIR / f"{market['latest_date_str']}_gestor_operativo{suffix}.txt"
    path.write_text(build_status_text(state_path, report_mode=True), encoding="utf-8")
    return path


def ensure_account_equity(state: dict[str, Any], override_equity: float | None = None) -> float:
    if override_equity is not None:
        equity_base = float(override_equity)
        state["account"]["equity_base"] = round(equity_base, 2)
        state["account"]["updated_at"] = _timestamp_now()
        return equity_base

    equity_base = _to_float(state.get("account", {}).get("equity_base"))
    if equity_base is None or equity_base <= 0:
        raise ValueError(
            "No hay equity_base configurada. Usa 'config --equity-base ...' o pasa --equity-base al agregar."
        )
    return equity_base


def add_position(args: argparse.Namespace, state_path: Path) -> None:
    state = load_state(state_path)
    market = load_market_context()
    prepared = market["prepared"]
    ticker = args.ticker.upper().strip()
    signal = normalize_signal(args.signal)

    if ticker not in prepared:
        raise ValueError(f"{ticker} no existe en titan.db")

    df = prepared[ticker]
    if pd.Timestamp(args.entry_date) not in df.index:
        raise ValueError(f"entry_date {args.entry_date} no existe para {ticker} en titan.db")

    signal_date = args.signal_date or prev_trading_day(df, args.entry_date)
    if signal_date is None:
        raise ValueError("No pude inferir signal_date. Pasala manualmente con --signal-date")

    result, error = infer_signal_result(ticker, signal, signal_date, prepared)
    validated = result is not None
    meta = result_to_meta(result, signal) if result is not None else {"priority": "UNKNOWN"}

    position_id = f"{ticker}-{args.entry_date}-{signal}"
    existing_open = [
        position
        for position in state["positions"]
        if position.get("status", "OPEN") == "OPEN" and position.get("id") == position_id
    ]
    if existing_open:
        raise ValueError(f"Ya existe una posicion abierta con id {position_id}")

    equity_base = ensure_account_equity(state, args.equity_base)
    atr_pct = _to_float(meta.get("atr_pct"))
    shares_real = _to_float(args.shares_real)
    sizing = build_sizing_snapshot(
        entry_price=float(args.entry_price),
        atr_pct=atr_pct,
        equity_base=equity_base,
        shares_real=shares_real,
        size_factor=_to_float(meta.get("size_factor")),
        size_note=str(meta.get("size_note", "")),
    )

    position = {
        "id": position_id,
        "ticker": ticker,
        "signal": signal,
        "signal_date": signal_date,
        "entry_date": args.entry_date,
        "entry_price": float(args.entry_price),
        "status": "OPEN",
        "validated": validated,
        "validation_error": error,
        "meta": meta,
        "sizing": sizing,
        "notes": args.notes or "",
    }
    state["positions"].append(position)
    save_state(state_path, state)

    print("=" * 110)
    print("  POSICION AGREGADA")
    print("=" * 110)
    print(f"  ID              : {position_id}")
    print(f"  Ticker          : {ticker}")
    print(f"  Signal          : {signal}")
    print(f"  Signal date     : {signal_date}")
    print(f"  Entry date      : {args.entry_date}")
    print(f"  Entry price     : ${float(args.entry_price):.2f}")
    print(f"  Validada        : {'SI' if validated else 'NO'}")
    if error:
        print(f"  Aviso           : {error}")
    print(f"  Equity base     : {_fmt_money(sizing['equity_base'])}")
    print(f"  Slot base       : {_fmt_money(sizing['slot_base'])}")
    print(f"  Size factor     : {sizing['size_factor']:.2f}x")
    print(f"  Notional sug    : {_fmt_money(sizing['notional_suggested'])}")
    print(f"  Shares sug      : {_fmt_shares(sizing['shares_suggested'])}")
    print(f"  Shares real     : {_fmt_shares(sizing['shares_real'])}")
    print(f"  Notional eff    : {_fmt_money(sizing['entry_notional_effective'])}")
    if meta:
        print(f"  Tier            : {meta.get('priority', 'UNKNOWN')}")
        if meta.get("score") is not None:
            print(f"  Score           : {meta['score']}")
        if meta.get("vol_ratio") is not None:
            print(f"  Vol ratio       : {meta['vol_ratio']}")
        if meta.get("atr_pct") is not None:
            print(f"  ATR%            : {meta['atr_pct']:.1f}%")
        print(f"  Sizing note     : {sizing.get('size_note', '')}")


def close_position(args: argparse.Namespace, state_path: Path) -> None:
    state = load_state(state_path)
    market = load_market_context()
    prepared = market["prepared"]
    ticker = args.ticker.upper().strip()
    exit_date = args.exit_date or market["latest_date_str"]

    matches = [
        position
        for position in state["positions"]
        if position.get("status", "OPEN") == "OPEN"
        and position.get("ticker") == ticker
        and (args.entry_date is None or position.get("entry_date") == args.entry_date)
    ]
    if not matches:
        raise ValueError("No encontre una posicion abierta que coincida")
    if len(matches) > 1:
        raise ValueError("Hay multiples posiciones abiertas para ese ticker. Pasar tambien --entry-date")

    position = matches[0]
    df = prepared.get(ticker)
    if df is None:
        raise ValueError(f"{ticker} no existe en titan.db")

    exit_price = args.exit_price
    if exit_price is None:
        resolved = resolve_close_price(df, exit_date)
        if resolved is None:
            raise ValueError("No pude inferir exit_price desde titan.db. Pasalo manualmente con --exit-price")
        exit_price = resolved

    if args.shares_real is not None:
        position["sizing"]["shares_real"] = round(float(args.shares_real), 4)
        position["sizing"]["shares_effective"] = round(float(args.shares_real), 4)
        position["sizing"]["entry_notional_effective"] = round(
            float(args.shares_real) * float(position["entry_price"]),
            2,
        )

    shares_used = effective_shares(position)
    entry_notional = entry_notional_effective(position)
    exit_notional = round(float(shares_used) * float(exit_price), 2) if shares_used is not None else None
    realized_pnl_amount = None
    if entry_notional is not None and exit_notional is not None:
        realized_pnl_amount = round(exit_notional - entry_notional, 2)

    equity_base = _to_float(position.get("sizing", {}).get("equity_base"))
    realized_pnl_equity_pct = None
    if realized_pnl_amount is not None and equity_base not in (None, 0):
        realized_pnl_equity_pct = round((realized_pnl_amount / equity_base) * 100.0, 3)

    position["status"] = "CLOSED"
    position["exit_date"] = exit_date
    position["exit_price"] = float(exit_price)
    position["shares_used"] = shares_used
    position["exit_notional_effective"] = exit_notional
    position["realized_return_pct"] = round((float(exit_price) / float(position["entry_price"]) - 1.0) * 100.0, 2)
    position["realized_pnl_amount"] = realized_pnl_amount
    position["realized_pnl_equity_pct"] = realized_pnl_equity_pct
    save_state(state_path, state)

    print("=" * 110)
    print("  POSICION CERRADA")
    print("=" * 110)
    print(f"  ID              : {position['id']}")
    print(f"  Exit date       : {exit_date}")
    print(f"  Exit price      : ${float(exit_price):.2f}")
    print(f"  Shares usadas   : {_fmt_shares(shares_used)}")
    print(f"  Exit notional   : {_fmt_money(exit_notional)}")
    print(f"  Retorno real    : {position['realized_return_pct']:+.2f}%")
    print(f"  PnL sized       : {_fmt_money(realized_pnl_amount)}")
    print(f"  Impacto equity  : {_fmt_pct(realized_pnl_equity_pct)}")


def configure_account(args: argparse.Namespace, state_path: Path) -> None:
    state = load_state(state_path)
    account = state["account"]

    changed = False
    if args.equity_base is not None:
        account["equity_base"] = round(float(args.equity_base), 2)
        changed = True
    if args.currency:
        account["currency"] = args.currency.upper().strip()
        changed = True
    if changed:
        account["updated_at"] = _timestamp_now()
        save_state(state_path, state)

    print("=" * 110)
    print("  CONFIGURACION DE CUENTA V15")
    print("=" * 110)
    print(f"  Equity base     : {_fmt_money(_to_float(account.get('equity_base')))}")
    print(f"  Currency        : {account.get('currency', 'USD')}")
    print(f"  Slot base       : {_fmt_money(calc_slot_base(_to_float(account.get('equity_base')), MAX_SLOTS))}")
    print(f"  Updated at      : {account.get('updated_at') or '-'}")


def daily_report(state_path: Path) -> None:
    path = write_daily_report(state_path)
    print(build_status_text(state_path, report_mode=True), end="")
    print("-" * 110)
    print(f"  Reporte gestor guardado en: {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gestor operativo de posiciones V11/V15")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="Path al archivo JSON de estado")

    subparsers = parser.add_subparsers(dest="command")

    config_parser = subparsers.add_parser("config", help="Configurar equity base y moneda de referencia")
    config_parser.add_argument("--equity-base", type=float, help="Equity base en USD")
    config_parser.add_argument("--currency", help="Moneda de referencia. Default: USD")

    add_parser = subparsers.add_parser("add", help="Agregar una posicion abierta")
    add_parser.add_argument("--ticker", required=True)
    add_parser.add_argument("--signal", required=True, help="A o C5")
    add_parser.add_argument("--entry-date", required=True, help="YYYY-MM-DD")
    add_parser.add_argument("--entry-price", required=True, type=float)
    add_parser.add_argument("--signal-date", help="YYYY-MM-DD. Si no, usa la rueda previa al entry-date")
    add_parser.add_argument("--equity-base", type=float, help="Override de equity base para esta alta")
    add_parser.add_argument("--shares-real", type=float, help="Shares realmente ejecutadas")
    add_parser.add_argument("--notes", help="Nota libre")

    close_parser = subparsers.add_parser("close", help="Cerrar una posicion abierta")
    close_parser.add_argument("--ticker", required=True)
    close_parser.add_argument("--entry-date", help="Recomendado si puede haber mas de una posicion")
    close_parser.add_argument("--exit-date", help="YYYY-MM-DD. Default: ultima fecha de la DB")
    close_parser.add_argument("--exit-price", type=float, help="Si no, usa el close de la DB")
    close_parser.add_argument("--shares-real", type=float, help="Permite reconciliar shares reales al cierre")

    subparsers.add_parser("daily-report", help="Generar reporte diario del gestor operativo")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    state_path = Path(args.state).resolve()

    state = load_state(state_path)
    save_state(state_path, state)

    if args.command == "config":
        configure_account(args, state_path)
    elif args.command == "add":
        add_position(args, state_path)
    elif args.command == "close":
        close_position(args, state_path)
    elif args.command == "daily-report":
        daily_report(state_path)
    else:
        render_status(state_path)


if __name__ == "__main__":
    main()
