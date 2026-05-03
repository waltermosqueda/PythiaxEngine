# PythiaxEngine Agent Policy

## FIRST ACTION — Read ESTADO_ACTUAL.md
At the start of every session, ALWAYS read `ESTADO_ACTUAL.md` in the repo root before doing anything else. It contains: what's in progress, pending tasks, DB state, and key decisions from the last session.

## LAST ACTION — Update ESTADO_ACTUAL.md
At the end of every session, update `ESTADO_ACTUAL.md` with what was done, what's still running, and what's pending. This is the only way to preserve context across conversations. Then commit it.

---

- The only active project is `PythiaxEngine` at `https://github.com/waltermosqueda/PythiaxEngine`.
- This working copy may still live inside a local folder named `Claude/`, but that path is historical only and must not be treated as a separate project.
- All analysis, fixes, predictions, audits, automation, and dashboard work must target the cloud-first stack: `GitHub + GitHub Actions + Neon Postgres + GitHub Pages`.
- Local sibling projects, snapshots, or legacy folders may be inspected only when a critical migration issue blocks the cloud pipeline or published dashboard.
- Prefer DB-driven and reproducible workflows. Avoid manual hardcoding or one-off local-only fixes.
- Process scanner models one at a time, end to end: analyze, validate, backtest, integrate or discard, then move to the next model without leaving partial work pending.
- **BACKFILL FAIR-START — MANDATORY**: Before running any backfill for a new model, query `SELECT MIN(prediction_date) FROM predictions WHERE model_name LIKE '<family_prefix>%'` and use that date as `--from-date`. NEVER use the technical minimum date (`min_rows` reached) as the backfill start. All models in the same competition family must share the same start date. Extra history = unfair advantage = corrupted rankings.
- Promote a model only when it is not a clone, adds decision value, and passes honest, auditable validation on the cloud-first stack. Rejected models must be cleaned out of DB artifacts, run artifacts, and working-tree changes in the same session.
- Timebox expensive tasks. If a backtest, audit, build, or migration shows no meaningful progress within roughly 10-15 minutes, stop or kill the process, inspect the failure mode, and retry once with a tighter scope or better instrumentation.
- If the second attempt also stalls or behaves like a loop, pivot to another approach and report progress instead of letting the session sit silently for hours.
