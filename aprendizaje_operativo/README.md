# APRENDIZAJE OPERATIVO

Esta carpeta guarda la memoria operativa de la base historica util, la referencia inmediata y el scanner activo.

Nota de foco:
- Estos artefactos locales son apoyo y trazabilidad del repo `PythiaxEngine`.
- La fuente de verdad operativa para mejoras y auditorias es la arquitectura cloud-first (`GitHub + Neon + GitHub Pages`), no una rama local separada llamada `Claude`.

Reglas:
- `SCANNER/` sigue reservado solo para scanners productivos canonicos `invertir_vN.py` o `invertir_vN_M.py`
- los artefactos diarios, snapshots y rastros de aprendizaje viven aca
- un scanner nuevo no queda realmente promovido si no trae su `aprendizaje_operativo_vN.py`
- las herramientas actuales son:
  - `herramientas/aprendizaje_operativo_v11.py`
  - `herramientas/aprendizaje_operativo_v12.py`
  - `herramientas/aprendizaje_operativo_v13.py`
  - `herramientas/scanner_operativo_context.py`

Contenido esperado:
- `v11_runs/YYYY-MM-DD.json` -> snapshot diario de V11 con contexto y senales
- `v12_runs/YYYY-MM-DD.json` -> snapshot diario de V12 con contexto y senales
- `v13_runs/YYYY-MM-DD.json` -> snapshot diario de V13 con contexto, senales D/E y memoria propia
- `v11_reports/YYYY-MM-DD_aprendizaje.txt` -> salida del paso de aprendizaje V11 dentro del pipeline
- `v11_reports/YYYY-MM-DD_aprendizaje_v12.txt` -> salida del paso de aprendizaje V12 dentro del pipeline
- `v11_reports/YYYY-MM-DD_aprendizaje_v13.txt` -> salida del paso de aprendizaje V13 dentro del pipeline
- `v11_reports/YYYY-MM-DD_scanner.txt` -> salida del scanner diario activo
- `v11_reports/YYYY-MM-DD_gestor.txt` -> captura del paso gestor dentro del pipeline
- `v11_reports/YYYY-MM-DD_gestor_operativo.txt` -> reporte vivo del gestor sized V15
- `v11_reports/YYYY-MM-DD_resumen.txt` -> resumen final diario del loop V11
- `v11_reports/YYYY-MM-DD_resumen_v12.txt` -> resumen final diario del loop V12 disparado por pipeline
- `v11_reports/YYYY-MM-DD_resumen_v13.txt` -> resumen final diario del loop V13 disparado por pipeline
- `v11_reports/YYYY-MM-DD_auditoria_centinela.txt` -> cierre automatico del pipeline con auditoria fast
- `v12_reports/YYYY-MM-DD_resumen.txt` -> resumen propio de memoria operativa V12
- `v13_reports/YYYY-MM-DD_resumen.txt` -> resumen propio de memoria operativa V13

Convencion de medicion:
- los outcomes de V11, V12 y V13 se miden de forma operable:
  - entrada = `open` de la rueda siguiente a la prediccion
  - salida = `close` de la fecha objetivo
- si hace falta reconciliar historia tras un cambio metodologico:
  - `python herramientas/aprendizaje_operativo_v11.py recompute-outcomes`
  - `python herramientas/aprendizaje_operativo_v12.py recompute-outcomes`
  - `python herramientas/aprendizaje_operativo_v13.py recompute-outcomes`

Objetivo:
- recordar que predijo cada scanner importante del stack operativo cada dia
- medir resultados cuando la fecha objetivo ya existe en `titan.db`
- construir memoria cuantitativa real para evolucionar el proyecto
- refrescar `model_metrics` para que la DB no arrastre infraestructura sin uso
- dejar trazabilidad diaria del portfolio sized real sugerido/ejecutado por el gestor V15
- cerrar cada pipeline diario con un auditor centinela reproducible
- mantener continuidad de aprendizaje cuando se promueva un nuevo champion
