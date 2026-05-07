#!/usr/bin/env python3
"""
Genera ESTADO_ACTUAL.md con:
  - Header AUTO-GENERADO (estado git real + errores pendientes)
  - Sección MANUAL preservada entre runs (notas del equipo / pendientes)

Uso:
    py scripts/generar_estado_actual.py                       # muestra en stdout (dry-run)
    py scripts/generar_estado_actual.py --write               # escribe el archivo
    py scripts/generar_estado_actual.py --write --commit      # escribe + git commit
    py scripts/generar_estado_actual.py --write --commit --push  # + git push

Regla de CI: correr SIEMPRE al final de cada workflow con permisos contents:write.
Regla de sesión: correr con --write --commit --push como LAST ACTION de cada chat.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
ESTADO_PATH = REPO_ROOT / "ESTADO_ACTUAL.md"
ERRORES_PATH = REPO_ROOT / "logs" / "errores_criticos.json"

# Marcadores para la sección manual — NO cambiar, son parte del contrato
MANUAL_START = "<!-- MANUAL_NOTES_START -->"
MANUAL_END   = "<!-- MANUAL_NOTES_END -->"

MANUAL_DEFAULT = """
## Próximos pasos al reiniciar sesión

> Editar esta sección al final de cada sesión. Se preserva entre regeneraciones.

1. Leer errores pendientes (arriba en este archivo — auto-generado)
2. Verificar que el cron de 19:30 AR haya pasado con éxito
   → https://github.com/waltermosqueda/PythiaxEngine/actions → "Cloud Daily Operations"
3. Ver pendientes estructurales abajo.

---

## Pendientes estructurales

- **V94 migration** (2026-05-11): correr outcomes, luego bulk insert ARM + INTC en Supabase
- **Cloudflare Access**: pythiaxengine.pages.dev sigue público
  → Fail open → Fail closed en Workers & Pages → Settings → Runtime

---

## Decisiones importantes / reglas que NO hay que romper

- `_get_ultima_fecha_sentinel()` en `auto_actualizar.py` resuelve el problema de
  MTM intraday parcial que adelanta `MAX(date)`. **NO revertir.**
- En rebase, `--theirs` = nuestro commit local (semántica invertida vs merge).
  Para `preview_c1_pro.html` en rebase: `git checkout --theirs`.
- `ml_trading_v22.py` = archivo fuente **intocable**. Toda variante en archivo nuevo.
- Sync commit NO debe tener `[skip ci]` → Cloudflare lo ignoraría.
  `analisis/preview_c1_pro.html` está en `paths-ignore` del trigger para evitar loop.
"""


def run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(cwd or REPO_ROOT)
    )
    return result.stdout.strip()


def get_git_info() -> dict:
    return {
        "head":     run(["git", "log", "-1", "--format=%h"]),
        "head_msg": run(["git", "log", "-1", "--format=%s"]),
        "head_ts":  run(["git", "log", "-1", "--format=%ci"]),
        "log10":    run(["git", "log", "--oneline", "-10"]),
        "status":   run(["git", "status", "--short"]),
        "branch":   run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
    }


def get_errores() -> list[dict]:
    if not ERRORES_PATH.exists():
        return []
    with open(ERRORES_PATH, encoding="utf-8") as f:
        return json.load(f)


def extract_manual_notes(existing: str) -> str:
    """Extrae la sección manual del archivo existente, si existe."""
    if MANUAL_START in existing and MANUAL_END in existing:
        start = existing.index(MANUAL_START) + len(MANUAL_START)
        end   = existing.index(MANUAL_END)
        content = existing[start:end].strip()
        return content if content else MANUAL_DEFAULT.strip()
    # Primera vez: no hay marcadores → usar template default
    return MANUAL_DEFAULT.strip()


def build_estado(git: dict, errores: list[dict], manual_notes: str) -> str:
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    now_ar  = now_utc - timedelta(hours=3)
    dias_es = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]
    ar_str  = now_ar.strftime("%Y-%m-%d %H:%M") + " AR (" + dias_es[now_ar.weekday()] + ")"

    # Determinar estado de crons intraday
    crons_utc = [13, 14, 15, 16, 17, 18, 19, 20]
    cron_lines = []
    for h in crons_utc:
        pasado = now_utc.hour > h or (now_utc.hour == h and now_utc.minute >= 30)
        estado = "✅ PASADO" if pasado else "⏳ PENDIENTE"
        cron_lines.append(f"  {h:02d}:30 UTC = {h-3:02d}:30 AR  [{estado}]")
    crons_md = "\n".join(cron_lines)

    pipeline_pasado = now_utc.hour > 22 or (now_utc.hour == 22 and now_utc.minute >= 30)
    pipeline_estado = "✅ PASADO" if pipeline_pasado else "⏳ PENDIENTE"

    # ── Sección de errores ────────────────────────────────────────────────────
    pendientes = [e for e in errores if e.get("status") == "pendiente"]
    if pendientes:
        errores_lines = ["### ⚠️ Errores pendientes\n"]
        for e in pendientes:
            ts  = e.get("timestamp", "?")
            cat = e.get("category", "?")
            msg = e.get("line", "")
            errores_lines.append(f"- `{ts}` — **{cat}**")
            errores_lines.append(f"  > {msg}\n")
        errores_md = "\n".join(errores_lines)
    else:
        errores_md = "### ✅ Sin errores pendientes en `logs/errores_criticos.json`"

    # ── Working tree ──────────────────────────────────────────────────────────
    status_md = (
        f"```\n{git['status']}\n```"
        if git["status"]
        else "_Rama limpia — sin cambios sin commitear_"
    )

    return f"""\
<!-- AUTO-GENERADO por scripts/generar_estado_actual.py — NO editar esta sección -->
<!-- generated_at: {now_str} -->
<!-- git_head: {git['head']} -->
<!-- git_branch: {git['branch']} -->
<!--
  ⚠️  AVISO PARA AGENTES IA:
  Este header se auto-genera en cada CI run y al final de cada sesión.
  El git_head aquí puede ser VIEJO si el archivo no se regeneró.

  SIEMPRE ejecutar primero:
    1. py -c "from datetime import datetime,timezone,timedelta; u=datetime.now(timezone.utc); a=u-timedelta(hours=3); print('UTC:',u.strftime('%Y-%m-%d %H:%M'),'| AR:',a.strftime('%Y-%m-%d %H:%M'))"
    2. cd C:\\repos\\PythiaxEngine ; git log --oneline -3 ; git status --short

  Si el HEAD que ves en git ≠ {git['head']} → secciones de commits abajo DESACTUALIZADAS.
  Si la hora real AR difiere de {ar_str} → estado de crons abajo DESACTUALIZADO.
-->

# ESTADO ACTUAL — PythiaxEngine

*Auto-generado: {now_str} | `{ar_str}` | HEAD: `{git['head']}`*

---

## ⚡ VERIFICACIÓN OBLIGATORIA AL INICIAR SESIÓN

> Ejecutar en terminal ANTES de leer cualquier cosa:
>
> ```powershell
> # 1. Hora real
> py -c "from datetime import datetime,timezone,timedelta; u=datetime.now(timezone.utc); a=u-timedelta(hours=3); dias=['Lun','Mar','Mie','Jue','Vie','Sab','Dom']; print('UTC: '+u.strftime('%Y-%m-%d %H:%M')+' | AR: '+a.strftime('%Y-%m-%d %H:%M')+' ('+dias[a.weekday()]+')')"
> # 2. Git
> cd C:\\repos\\PythiaxEngine ; git log --oneline -5 ; git status --short
> ```
>
> - **Si HEAD ≠ `{git['head']}`** → sección de commits desactualizada, ignorar.
> - **Si hora AR ≠ `{ar_str}`** → estado de crons abajo desactualizado, recalcular.

---

## ⏰ Ancla temporal (al momento de generación)

| | Valor |
|---|---|
| Generado | `{now_str}` |
| Hora AR | `{ar_str}` |
| Argentina | UTC-3, **sin DST** (nunca cambia) |
| NYSE abre | 09:30 ET (EDT=UTC-4 verano) = **13:30 UTC = 10:30 AR** |

### Estado crons intraday al momento de generación
```
{crons_md}
```

**Pipeline diario** (19:30 AR = 22:30 UTC): `{pipeline_estado}`

---

## Estado git (al momento de generación)

**HEAD:** `{git['head']}` — {git['head_msg']}
**Timestamp commit:** {git['head_ts']}
**Branch:** {git['branch']}

### Últimos 10 commits
```
{git['log10']}
```

### Working tree
{status_md}

---

## Errores críticos

{errores_md}

---

{MANUAL_START}
{manual_notes}
{MANUAL_END}
"""


def main() -> None:
    write  = "--write"  in sys.argv
    commit = "--commit" in sys.argv
    push   = "--push"   in sys.argv

    git     = get_git_info()
    errores = get_errores()

    existing     = ESTADO_PATH.read_text(encoding="utf-8") if ESTADO_PATH.exists() else ""
    manual_notes = extract_manual_notes(existing)
    new_content  = build_estado(git, errores, manual_notes)

    if not write:
        print(new_content)
        return

    ESTADO_PATH.write_text(new_content, encoding="utf-8")
    print(f"[generar_estado_actual] ✓ Escrito: {ESTADO_PATH.name}  HEAD={git['head']}")

    if commit:
        run(["git", "add", str(ESTADO_PATH)])
        diff = run(["git", "diff", "--staged", "--stat"])
        if diff:
            run(["git", "commit", "-m",
                 f"chore(auto): update ESTADO_ACTUAL → {git['head']} [skip ci]"])
            print(f"[generar_estado_actual] ✓ Commit realizado")
        else:
            print("[generar_estado_actual] Sin cambios — commit omitido")

    if push:
        run(["git", "pull", "--rebase", "origin", git["branch"]])
        run(["git", "push", "origin", git["branch"]])
        print("[generar_estado_actual] ✓ Push realizado")


if __name__ == "__main__":
    main()
