#!/usr/bin/env python3
"""Analysis script: snapshot state + yfinance backtest of stale picks."""
import json
import datetime
from pathlib import Path

sys_path = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(sys_path))

# ── 1. SNAPSHOT STATE ──────────────────────────────────────────────────────────
snap_path = Path("C:/repos/PythiaxEngine/dashboards/maquina_pensante/tablero_maquina_pensante_snapshot.json")
if snap_path.exists():
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    comp = snap.get("competition", [])
    today = datetime.date.today().isoformat()
    print(f"Snapshot generated: {snap.get('generated_at')}")
    print(f"Today: {today}")
    print()
    print(f"{'Model':<28} {'role':<20} {'latest_target_date':<22} {'picks':<7} {'tickers':<40} STATUS")
    print("-" * 130)
    for m in comp:
        ver = str(m.get("version", ""))
        role = str(m.get("role", ""))
        lt = str(m.get("latest_target_date") or "None")
        lp = str(m.get("latest_picks") or 0)
        tks = ", ".join(m.get("latest_tickers") or [])[:38]
        status = "OPEN" if lt != "None" and lt >= today else "CLOSED"
        print(f"{ver:<28} {role:<20} {lt:<22} {lp:<7} {tks:<40} {status}")
else:
    print("Snapshot not found - can't analyze")
    comp = []

# ── 2. YFINANCE BACKTEST ────────────────────────────────────────────────────────
try:
    import yfinance as yf
    print("\n\n" + "=" * 80)
    print("YFINANCE BACKTEST — Picks with target_date < today")
    print("=" * 80)

    # All stale picks from previous session analysis + any others
    STALE_TICKERS = {
        # V11 cycle closed May 12
        "LMT": {"model": "INVERTIR_V11", "entry_date": "2026-05-07", "target_date": "2026-05-12", "direction": "long"},
        "IP":  {"model": "INVERTIR_V11", "entry_date": "2026-05-07", "target_date": "2026-05-12", "direction": "long"},
        "SNOW":{"model": "INVERTIR_V11", "entry_date": "2026-05-07", "target_date": "2026-05-12", "direction": "long"},
        "NKE": {"model": "INVERTIR_V11", "entry_date": "2026-05-07", "target_date": "2026-05-12", "direction": "long"},
        "SYY": {"model": "INVERTIR_V11", "entry_date": "2026-05-07", "target_date": "2026-05-12", "direction": "long"},
        # ML_V97 cycle closed May 11-12
        "ARM": {"model": "ML_V97",       "entry_date": "2026-05-08", "target_date": "2026-05-12", "direction": "long"},
        "MUX": {"model": "ML_V97",       "entry_date": "2026-05-08", "target_date": "2026-05-12", "direction": "long"},
        "SWKS":{"model": "ML_V97",       "entry_date": "2026-05-07", "target_date": "2026-05-11", "direction": "long"},
        "NXE": {"model": "ML_V97",       "entry_date": "2026-05-07", "target_date": "2026-05-11", "direction": "long"},
        # Other potentially stale
        "GS":  {"model": "ML_V39",       "entry_date": "2026-05-19", "target_date": "2026-05-20", "direction": "long"},
        "GE":  {"model": "ML_V39",       "entry_date": "2026-05-19", "target_date": "2026-05-20", "direction": "long"},
        "QCOM":{"model": "ML_V94",       "entry_date": "2026-05-15", "target_date": "2026-05-21", "direction": "long"},
        "MRVL":{"model": "ML_V94",       "entry_date": "2026-05-15", "target_date": "2026-05-21", "direction": "long"},
        "UAL": {"model": "ML_V39FULL",   "entry_date": "2026-05-19", "target_date": "2026-05-20", "direction": "long"},
        "SE":  {"model": "ML_BRAIN_V11", "entry_date": "2026-05-14", "target_date": "2026-05-21", "direction": "long"},
        "PBR": {"model": "ML_BRAIN_V11_OPT", "entry_date": "2026-05-14", "target_date": "2026-05-21", "direction": "long"},
        "AMAT":{"model": "ML_BRAIN_V11_OPT", "entry_date": "2026-05-14", "target_date": "2026-05-21", "direction": "long"},
        "VIST":{"model": "ML_V37",       "entry_date": "2026-05-20", "target_date": "2026-05-21", "direction": "long"},
        "SCHW":{"model": "ML_BRAIN_V10", "entry_date": "2026-05-14", "target_date": "2026-05-21", "direction": "long"},
    }

    print(f"\n{'Ticker':<8} {'Model':<22} {'Entry':<12} {'Target':<12} {'Entry $':<10} {'Target $':<10} {'Curr $':<10} {'Return':<10} {'HIT?'}")
    print("-" * 110)

    for tk, info in STALE_TICKERS.items():
        try:
            ticker_obj = yf.Ticker(tk)
            # Get data from entry to today
            start = (datetime.date.fromisoformat(info["entry_date"]) - datetime.timedelta(days=2)).isoformat()
            hist = ticker_obj.history(start=start, end=datetime.date.today().isoformat(), interval="1d")
            if hist.empty:
                print(f"{tk:<8} {info['model']:<22} {info['entry_date']:<12} {info['target_date']:<12} NO DATA")
                continue

            # Entry price = OPEN on entry_date (day after signal)
            entry_rows = hist[hist.index.date == datetime.date.fromisoformat(info["entry_date"])]
            entry_price = float(entry_rows["Open"].iloc[0]) if not entry_rows.empty else None

            # Target price = CLOSE on target_date
            target_rows = hist[hist.index.date == datetime.date.fromisoformat(info["target_date"])]
            target_price = float(target_rows["Close"].iloc[0]) if not target_rows.empty else None

            # Current price = last close
            curr_price = float(hist["Close"].iloc[-1])

            if entry_price and target_price:
                ret = (target_price - entry_price) / entry_price * 100
                hit = "✓" if ret > 0 else "✗"
                ret_s = f"{ret:+.2f}%"
            else:
                ret_s = "—"
                hit = "?"

            entry_s = f"${entry_price:.2f}" if entry_price else "—"
            target_s = f"${target_price:.2f}" if target_price else "—"
            curr_s = f"${curr_price:.2f}"
            print(f"{tk:<8} {info['model']:<22} {info['entry_date']:<12} {info['target_date']:<12} {entry_s:<10} {target_s:<10} {curr_s:<10} {ret_s:<10} {hit}")

        except Exception as e:
            print(f"{tk:<8} ERROR: {e}")

    # Also show currently OPEN picks
    print("\n\nCURRENTLY OPEN PICKS (target >= today)")
    OPEN_TICKERS = {
        "YELP": {"model": "ML_V97", "entry_date": "2026-05-21", "target_date": "2026-05-25", "direction": "long"},
        "SPCE": {"model": "ML_V97", "entry_date": "2026-05-21", "target_date": "2026-05-25", "direction": "long"},
        "ERIC": {"model": "INVERTIR_V13", "entry_date": "2026-05-28", "target_date": "2026-06-03", "direction": "long"},
        "MUFG": {"model": "INVERTIR_V13", "entry_date": "2026-05-28", "target_date": "2026-06-03", "direction": "long"},
    }
    print(f"\n{'Ticker':<8} {'Model':<22} {'Target':<12} {'Curr $':<12} {'MTM vs signal'}")
    print("-" * 70)
    for tk, info in OPEN_TICKERS.items():
        try:
            ticker_obj = yf.Ticker(tk)
            hist = ticker_obj.history(period="5d", interval="1d")
            if not hist.empty:
                curr = float(hist["Close"].iloc[-1])
                print(f"{tk:<8} {info['model']:<22} {info['target_date']:<12} ${curr:.2f}")
        except Exception as e:
            print(f"{tk:<8} ERROR: {e}")

except ImportError:
    print("yfinance not installed — skipping market analysis")
    print("Install with: pip install yfinance")

print("\nDone.")
