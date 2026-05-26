# Cómo añadir GitHub Secrets (automático)

Este repositorio incluye scripts para añadir secrets de forma segura al repo `waltermosqueda/PythiaxEngine` usando la GitHub CLI (`gh`).

Archivos:
- `scripts/set_github_secrets.ps1` — PowerShell interactivo (Windows / pwsh).
- `scripts/set_github_secrets.sh` — Shell script interactivo (Linux / macOS / Git Bash / WSL).

Requisitos:
- `gh` instalado y autenticado: `gh auth login` (usa tu cuenta con permisos de admin en el repo).

Ejemplo (PowerShell):
```powershell
# Opcional: exportar variables de entorno para evitar prompts
$env:SMTP_HOST='smtp.sendgrid.net'
$env:SMTP_PORT='587'
$env:SMTP_USER='apikey'
$env:SMTP_PASS='<SENDGRID_API_KEY>'
$env:MAIL_FROM='noreply@tu.dom'
$env:MAIL_TO='xeneize7786@gmail.com'

pwsh .\scripts\set_github_secrets.ps1
```

Ejemplo (Bash):
```bash
export SMTP_HOST='smtp.sendgrid.net'
export SMTP_PORT='587'
export SMTP_USER='apikey'
export SMTP_PASS='<SENDGRID_API_KEY>'
export MAIL_FROM='noreply@tu.dom'
export MAIL_TO='xeneize7786@gmail.com'

./scripts/set_github_secrets.sh
```

Notas:
- Si no quieres exportar variables, el script pedirá cada valor de forma interactiva.
- `gh` debe estar autenticado con una cuenta que tenga permisos para administrar secrets del repositorio.
- Tras ejecutar, puedes verificar en: https://github.com/waltermosqueda/PythiaxEngine/settings/secrets/actions
