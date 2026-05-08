"""
Genera _staging_prod_preview.html desde preview_c1_pro.html
inyectando el bloque JS de precios en tiempo real via Supabase.
Uso: py scripts/_inject_live_prices.py
"""
from pathlib import Path

SRC = Path(r'C:\repos\PythiaxEngine\analisis\preview_c1_pro.html')
DST = Path(r'C:\repos\PythiaxEngine\analisis\_staging_prod_preview.html')

LIVE_PRICES_JS = r"""<script id="live-prices-v1">
/* ─── Precios Live via Supabase ─────────────────────────────────────────────
   Corre en el browser al cargar la página.
   Obtiene el cierre más reciente de la tabla `prices` (RLS SELECT abierto
   para anon) y actualiza todas las celdas de precio en el panel de señales
   y en las hero cards. No modifica innerHTML (sin riesgo XSS).
   ────────────────────────────────────────────────────────────────────────── */
(function () {
  'use strict';
  var SB_URL = 'https://datdtnliztfzbmfbmobx.supabase.co';
  var SB_KEY = 'sb_publishable_xDQ6rIZG5PjG45VTAbJnyg_c97mWXGx';

  /* Recolecta tickers únicos del panel de señales (.svb-tk-name) */
  function collectTickers() {
    var s = new Set();
    document.querySelectorAll('.svb-tk-name').forEach(function (el) {
      var t = el.textContent.trim();
      if (/^[A-Z]{1,6}$/.test(t)) s.add(t);
    });
    return Array.from(s);
  }

  /* Fetch a Supabase: último close por ticker */
  function fetchPrices(tickers) {
    var list = tickers.join(',');
    var url = SB_URL + '/rest/v1/prices?select=ticker,date,close,fetched_at'
            + '&ticker=in.(' + list + ')'
            + '&order=date.desc&limit=300';
    return fetch(url, {
      headers: { 'apikey': SB_KEY, 'Authorization': 'Bearer ' + SB_KEY }
    }).then(function (r) {
      if (!r.ok) throw new Error('Supabase HTTP ' + r.status);
      return r.json();
    }).then(function (rows) {
      var map = {};
      rows.forEach(function (row) {
        if (!map[row.ticker]) map[row.ticker] = row;  // primera fila = más reciente
      });
      return map;
    });
  }

  /* Actualiza precios en la tabla de señales (.svb-tickers-table) */
  function updateSvbTable(map) {
    document.querySelectorAll('.svb-tickers-table tr').forEach(function (tr) {
      var nm = tr.querySelector('.svb-tk-name');
      var pr = tr.querySelector('.svb-tk-price');
      if (nm && pr) {
        var t = nm.textContent.trim();
        if (map[t]) {
          pr.textContent = '$' + parseFloat(map[t].close).toFixed(2);
          pr.title = 'live · cierre ' + map[t].date;
          pr.style.color = '#44e890';
          pr.style.fontWeight = '700';
        }
      }
    });
  }

  /* Actualiza precios en las hero cards (.hc-picks-live)
     Estructura: TICKER_TEXNODE <small.hc-tk-price> <small.hc-tk-pct> <small.hc-tk-date> · TICKER ...
     Los text nodes contienen "TICKER" o " · TICKER" — extraemos el ticker con regex. */
  function updateHeroCards(map) {
    document.querySelectorAll('.hc-picks-live').forEach(function (container) {
      var curTk = null;
      container.childNodes.forEach(function (n) {
        if (n.nodeType === 3) {
          // Extraer último token que sea ticker válido (ignorar " · ")
          var parts = n.textContent.split('\u00b7')   // ·
            .map(function (s) { return s.trim(); })
            .filter(function (s) { return /^[A-Z]{1,6}$/.test(s); });
          if (parts.length) curTk = parts[parts.length - 1];
        } else if (n.nodeType === 1
                   && n.classList.contains('hc-tk-price')
                   && curTk && map[curTk]) {
          n.textContent = ' $' + parseFloat(map[curTk].close).toFixed(2);
          n.title = 'live · cierre ' + map[curTk].date;
          n.style.color = '#44e890';
          n.style.fontWeight = '700';
        }
      });
    });
  }

  /* Agrega badge "precios live · FECHA · HH:MM AR / HH:MM UTC" con hora real del sync */
  function addLiveBadge(maxDate, fetchedAt) {
    if (!maxDate) return;
    var sub = document.getElementById('kpi-fresh-sub');
    if (!sub || document.getElementById('kpi-live-badge')) return;
    var d = document.createElement('div');
    d.id = 'kpi-live-badge';
    d.style.cssText = 'color:#44e890;font-size:10px;margin-top:4px;'
                    + 'font-weight:700;letter-spacing:.05em';
    var label = '\u26a1 precios live \u00b7 ' + maxDate;
    if (fetchedAt) {
      try {
        var ts = new Date(fetchedAt);
        var pad = function(n) { return ('0' + n).slice(-2); };
        var utcH = pad(ts.getUTCHours());
        var utcM = pad(ts.getUTCMinutes());
        var arD  = new Date(ts.getTime() - 3 * 3600000);
        var arH  = pad(arD.getUTCHours());
        var arM  = pad(arD.getUTCMinutes());
        label += ' \u00b7 ' + arH + ':' + arM + ' AR / ' + utcH + ':' + utcM + ' UTC';
      } catch(e) { /* si falla el parse, queda solo la fecha */ }
    }
    d.textContent = label;
    sub.parentNode.insertBefore(d, sub.nextSibling);
  }

  /* Entry point */
  function run() {
    var tickers = collectTickers();
    if (!tickers.length) return;
    fetchPrices(tickers).then(function (map) {
      updateSvbTable(map);
      updateHeroCards(map);
      var entries = Object.values(map).filter(function(r) { return r.date; });
      entries.sort(function(a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : 0; });
      var latest = entries.length ? entries[entries.length - 1] : null;
      addLiveBadge(
        latest ? latest.date : null,
        latest ? latest.fetched_at : null
      );
    }).catch(function (e) {
      console.warn('[live-prices]', e);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }
})();
</script>
"""

def main():
    import re as _re
    html = SRC.read_text(encoding='utf-8')

    if 'live-prices-v1' in html:
        # Reemplazar script existente con la versión actualizada
        _new_js = LIVE_PRICES_JS.strip()
        html_new = _re.sub(
            r'<script id="live-prices-v1">.*?</script>',
            lambda _m: _new_js,
            html,
            flags=_re.DOTALL,
            count=1
        )
        if html_new == html:
            print('ERROR: no se pudo reemplazar el script existente')
            return
        print('Script existente reemplazado con version actualizada')
    else:
        # Primera inyección: insertar antes de </body>
        if '</body>' not in html:
            print('ERROR: no se encontro </body> en el HTML')
            return
        html_new = html.replace('</body>', LIVE_PRICES_JS + '\n</body>', 1)
        print('Script inyectado por primera vez')

    DST.write_text(html_new, encoding='utf-8')

    # Verificación
    staging = DST.read_text(encoding='utf-8')
    ok = 'live-prices-v1' in staging and 'supabase.co' in staging
    print(f'Staging generado: {DST}')
    print(f'Tamaño fuente: {len(html):,} chars | staging: {len(html_new):,} chars')
    print(f'Verificación JS: {"OK" if ok else "FALLO"}')

if __name__ == '__main__':
    main()
