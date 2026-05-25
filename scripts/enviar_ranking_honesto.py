"""Envia el ranking honesto al Telegram. Lee credenciales de env vars.

Uso (PowerShell):
    $env:TELEGRAM_BOT_TOKEN="<token>"
    $env:TELEGRAM_CHAT_ID="<chat_id>"
    py scripts/enviar_ranking_honesto.py
"""
from __future__ import annotations
import os
import sys
import urllib.parse
import urllib.request


MSG = """<b>RANKING HONESTO — 25-May-2026</b>
<i>Ajustado por d2t, upside_52w, MTM extendido y confirmacion multiple</i>

<b>Macro:</b> SPY +0.88% 5d | QQQ +1.21% | VIX 16.7 (-9.4%) → regimen constructivo

<b>TOP 5 — probabilidad real de suba (5-15 ruedas)</b>

1️⃣ <b>HAL</b> 65-68% — Mejor balance global
   Cons 0.74 (top), OBV+, EMA aligned, RSI 54.7, R:R 6.6, 11d margen
   ⚠️ MACD- aun no confirma

2️⃣ <b>GOLD</b> 62-65% — Mejor calidad fundamental
   Fund 0.90, Tec 0.75, MACD+ OBV+, R:R 9.84, upside 52.4%
   ⚠️ EMA20&lt;EMA50, d2t=0 (reset horizonte a 10d)

3️⃣ <b>PBR</b> 58-62% — Value defensivo
   P/E 4.84, beta -0.06 (descorrelacionado), RSI 44.7, target +13.8%
   ⚠️ Tec 0.51 floja, sin momentum aun

4️⃣ <b>PM</b> 58-60% — Unico con momentum 3/3
   EMA+MACD+OBV los 3 ON, Tec 0.74, defensivo
   ⚠️ RSI 68, upside_52w solo 2.1% (techo cerca)

5️⃣ <b>LAR</b> 55-58% — Value con upside grande
   Fund 0.85, upside 31.1%, RSI 45.1, R:R 8.5
   ⚠️ Tec 0.40, MACD- OBV-, d2t=2 corto

<b>CARTERA HONESTA — USD 10.000</b>
• HAL 30% (USD 3.000) — core probabilidad
• GOLD 20% (USD 2.000) — diversifica con refugio
• PBR 20% (USD 2.000) — descorrelaciona via beta negativo
• CASH 30% (USD 3.000) — reserva para LAR si rompe o agregar HAL si confirma MACD

<b>NO TOMAR</b>
• PM — techo a 2% upside
• QCOM — chasing, RSI 71.8, d2t=0
• UNH — R:R 2.94 mediocre
• INTC — fund 0.35 no compensa momentum
• CRM — earnings en 2d (binario)

<b>ESPERAR confirmacion</b>
• ASTS, PBI — prob limitrofe, ver una rueda mas de fuerza

<b>Vs ranking del bot</b>
Bot: GOLD &gt; HAL &gt; PBR (por composite_prob crudo)
Honesto: HAL &gt; GOLD &gt; PBR (HAL tiene trifecta consenso+OBV+horizonte; GOLD tiene EMA mixto)
"""


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("ERROR: faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en env", file=sys.stderr)
        return 2

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": MSG,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", "replace")
            print(f"HTTP {resp.status} | {body[:300]}")
            return 0 if resp.status == 200 else 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
