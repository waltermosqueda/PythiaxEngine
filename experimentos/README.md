# LEDGER DE EXPERIMENTOS

Esta carpeta guarda el registro estructurado de decisiones sobre scanners y mejoras
del proyecto `Claude`.

Principio:
- `bitacora/BITACORA.md` cuenta la historia y el razonamiento
- `experimentos/scanner_ledger.json` guarda el veredicto canónico y estructurado

Uso:
- ver estado actual:
  - `python herramientas/ledger_experimentos.py status`
- listar entradas:
  - `python herramientas/ledger_experimentos.py list`
- inspeccionar una entrada:
  - `python herramientas/ledger_experimentos.py show --id SCN-V11-CAP-OPERATIVO`
- validar integridad del ledger:
  - `python herramientas/ledger_experimentos.py validate`

Reglas:
- el ledger no reemplaza a la bitácora; la complementa
- toda promoción, rechazo o mejora aplicada al scanner activo debe quedar en ambos
- `SCANNER/` sigue reservado solo para scanners canónicos `invertir_vN.py`
- variantes, investigaciones y experimentos siguen viviendo fuera de `SCANNER/`
