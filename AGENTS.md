# PythiaxEngine Agent Policy

- The only active project is `PythiaxEngine` at `https://github.com/waltermosqueda/PythiaxEngine`.
- This working copy may still live inside a local folder named `Claude/`, but that path is historical only and must not be treated as a separate project.
- All analysis, fixes, predictions, audits, automation, and dashboard work must target the cloud-first stack: `GitHub + GitHub Actions + Neon Postgres + GitHub Pages`.
- Local sibling projects, snapshots, or legacy folders may be inspected only when a critical migration issue blocks the cloud pipeline or published dashboard.
- Prefer DB-driven and reproducible workflows. Avoid manual hardcoding or one-off local-only fixes.
- Process scanner models one at a time, end to end: analyze, validate, backtest, integrate or discard, then move to the next model without leaving partial work pending.
- Promote a model only when it is not a clone, adds decision value, and passes honest, auditable validation on the cloud-first stack. Rejected models must be cleaned out of DB artifacts, run artifacts, and working-tree changes in the same session.
- Timebox expensive tasks. If a backtest, audit, build, or migration shows no meaningful progress within roughly 10-15 minutes, stop or kill the process, inspect the failure mode, and retry once with a tighter scope or better instrumentation.
- If the second attempt also stalls or behaves like a loop, pivot to another approach and report progress instead of letting the session sit silently for hours.
