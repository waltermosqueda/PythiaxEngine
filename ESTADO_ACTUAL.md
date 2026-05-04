# ESTADO ACTUAL — PythiaxEngine

*Archivo de handoff entre sesiones. Leer al inicio, actualizar al final.*

---

## LEER AL INICIO DE CADA SESION

1. Verificar Docker: `docker ps` → contenedor `pythiax_staging_postgres` debe estar UP en puerto 5433
2. Si acaba de reiniciar el PC: `docker start pythiax_staging_postgres`
3. Verificar backfill pendiente (ver seccion "Backfill en curso" abajo)

---

## Estado al 2026-05-03 (ultima sesion)

### Backfill en curso: ML_BRAIN_V10

**Terminal async ID:** `4a0cde5c-4936-41d9-97ee-ae60298110c4`  
**Ultimo checkpoint visto:** `2026-03-06`  
**Destino:** `2026-04-29` (igual que todos los Legacy ML)  
**Progreso estimado:** ~75% completo  
**Tasa:** 2 picks/dia, consistente

**Si el backfill se interrumpio:**
```powershell
python _check_backfill.py
# Toma nota del MAX(prediction_date)
python herramientas/aprendizaje_operativo_legacy_ml_brain_v10.py backfill --from-date <MAX+1dia>
```

**NUNCA iniciar desde la fecha tecnica minima (2025-05-15). Siempre usar 2025-12-18 o continuar desde el checkpoint.**

### Git status al cierre de sesion

- Commits en local (no pusheados aun): `f1a819a`, `256a0df`, `69caed6`, `6fbfe33`
- `analisis/preview_*.html` — PENDIENTE: refresh post-backfill, luego commit
- Comando para pushear cuando todo este listo: `git push origin main`

### DB state

- Total predictions antes del backfill v10: ~4218
- brain_v10 acumula 2 picks/dia desde 2025-12-18
- Sequence OK: fue reseteada a 4182 en esta sesion con `_fix_sequence.py`

---

## Proximos pasos al reiniciar sesion

1. Verificar backfill con `python _check_backfill.py`
2. Si MAX(prediction_date) = 2026-04-29 → backfill completo
3. `python herramientas/refrescar_datos_dashboard.py`
4. `git add analisis/preview_*.html ESTADO_ACTUAL.md`
5. `git commit -m "data: brain_v10 backfill complete + dashboard refresh"`
6. `git push origin main`

---

## Infraestructura

| Componente | Detalle |
|------------|---------|
| Python | C:\Users\wmx_7\AppData\Local\Programs\Python\Python314\python.exe |
| PostgreSQL | Docker local, puerto 5433, db=pythiax, user=postgres, pw=postgres_local |
| Container | pythiax_staging_postgres |
| DATABASE_URL | postgresql+psycopg://postgres:postgres_local@localhost:5433/pythiax |
| Repo | C:\Users\wmx_7\OneDrive\Escritorio\Inversiones\PythiaxEngine |
| Branch | main |

---

## Reglas criticas (ver AGENTS.md para lista completa)

- **BACKFILL FAIR-START:** Antes de cualquier backfill, consultar `SELECT MIN(prediction_date) FROM predictions WHERE model_name LIKE '<familia>%'` y usar esa fecha como `--from-date`
- **Sequence:** si hay UniqueViolation en PostgreSQL, correr `python _fix_sequence.py`
- **Docker:** siempre verificar que el contenedor esta UP antes de correr cualquier script que toque DB
