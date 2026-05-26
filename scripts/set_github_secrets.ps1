<#
set_github_secrets.ps1

Usage:
  - Install GitHub CLI and authenticate: `gh auth login`
  - Provide secrets via environment variables or interactively when prompted.
  - Run in PowerShell (from repo root):
      pwsh .\scripts\set_github_secrets.ps1

This script sets repository secrets using `gh secret set` for the repo `waltermosqueda/PythiaxEngine`.
#>

param(
  [string]$Repo = "waltermosqueda/PythiaxEngine"
)

function ReadOrEnv([string]$Name) {
  $val = $null
  try {
    $val = (Get-Item -Path Env:$Name -ErrorAction SilentlyContinue).Value
  } catch {
    $val = $null
  }
  if ([string]::IsNullOrEmpty($val)) {
    Write-Host "Enter value for $Name (leave empty to skip):"
    if ($Host.Name -eq 'ConsoleHost') {
      $val = Read-Host
    } else {
      $secure = Read-Host -AsSecureString "Enter $Name"
      $val = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    }
  }
  return $val
}

$secrets = @(
  'SMTP_HOST',
  'SMTP_PORT',
  'SMTP_USER',
  'SMTP_PASS',
  'MAIL_FROM',
  'MAIL_TO',
  'SENDGRID_API_KEY',
  'COPILOT_GH_TOKEN'
)

Write-Host "Setting secrets for repo: $Repo"

# Ensure gh is available
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  Write-Error "GitHub CLI 'gh' is not installed or not in PATH. Install and authenticate with 'gh auth login' first."
  exit 2
}

foreach ($s in $secrets) {
  $value = ReadOrEnv $s
  if ([string]::IsNullOrEmpty($value)) {
    Write-Host "Skipping $s (no value provided)"
    continue
  }
  try {
    # Try using --body first (supported in newer gh versions)
    gh secret set $s --repo $Repo --body $value 2>$null
    if ($LASTEXITCODE -ne 0) {
      # Fallback to piping
      $bytes = [System.Text.Encoding]::UTF8.GetBytes($value)
      $tmp = [System.IO.Path]::GetTempFileName()
      [System.IO.File]::WriteAllBytes($tmp, $bytes)
      Get-Content $tmp -Raw | gh secret set $s --repo $Repo
      Remove-Item $tmp -Force
    }
    Write-Host "Set secret: $s"
  } catch {
    Write-Warning "Failed to set $s: $_"
  }
}

Write-Host "Done. Verify secrets in GitHub: https://github.com/waltermosqueda/PythiaxEngine/settings/secrets/actions"
