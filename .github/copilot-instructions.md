## Instrucciones permanentes para GitHub Copilot — PythiaxEngine

### INICIO DE SESIÓN OBLIGATORIO

Al comenzar CUALQUIER sesión de trabajo en este repositorio, ejecutar estos pasos ANTES de atender el pedido del usuario:

1. **Chequear errores críticos pendientes**
   - Leer `logs/errores_criticos.json`
   - Si existen entradas con `"status": "pendiente"`, reportar al usuario cuántos hay y de qué tipo
   - Proponer o iniciar la corrección sin esperar que el usuario lo pida
   - Al resolver un error, actualizar su entrada: `"status": "resuelto"`, `"resolved_at": <timestamp>`, `"resolution": <descripcion breve>`

2. **Chequear salud del dashboard**
   - Leer `dashboards/maquina_pensante/tablero_maquina_pensante_snapshot.json`
   - Verificar que `generated_at` sea del día actual (Argentina UTC-3) si es día hábil y pasaron las 21:00 local
   - Si está desactualizado, investigar el log de pipeline y reportar la causa

### REGLAS PERMANENTES DEL PROYECTO

- **"dashboard"** = SIEMPRE `analisis/preview_c1_pro.html` → `https://waltermosqueda.github.io/PythiaxEngine/`
- `tablero_maquina_pensante.html` está DEPRECADO — NUNCA mencionar ni modificar
- `actual_return` en DB = ratio (0.05 = 5%). El dashboard multiplica ×100 para mostrar
- Comando Python: usar `py` (no `python`) — Python 3.14.3
- DB producción: Supabase (URL en `.env` línea comentada `# DATABASE_URL=...supabase...`)
- DB local staging: Docker en `localhost:5433` (`.env` línea activa)
- Log de pipeline `logs/pipeline_run.log`: encoding **UTF-16 LE** (PowerShell Tee-Object) — leer con `read_bytes()` + detección BOM `\xff\xfe`
- CI workflow `ci.yml` siempre falla — es pre-existente, ignorar

### TAREAS PROGRAMADAS (referencia)

| Tarea | Horario | Descripción |
|-------|---------|-------------|
| `TITAN_AutoActualizar_Diario` | L-V 19:15 | Pipeline producción → Supabase → genera picks provisorios |
| `TITAN_UpdateLocalStaging` | L-V 20:00 | Pipeline staging → Docker local |
| `TITAN_DashboardHealthCheck` | L-V 20:45 | Health check dashboard → `logs/dashboard_health.log` |

### FLUJO DE CORRECCIÓN DE ERRORES

Cuando se detecta un error en `logs/errores_criticos.json`:
1. Identificar el archivo fuente (columna `source`) y la línea del error (`line`)
2. Buscar la causa raíz en el código
3. Aplicar el fix directamente (no solo sugerir)
4. Marcar el error como resuelto en el JSON
5. Hacer commit del fix con mensaje descriptivo

### CONFLICTOS DE GIT FRECUENTES

`analisis/preview_c1_pro.html` siempre tiene conflicto en rebase (GitHub Actions lo auto-commitea):
```
git checkout --theirs analisis/preview_c1_pro.html
git add analisis/preview_c1_pro.html
git rebase --continue
```
