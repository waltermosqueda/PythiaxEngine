#!/usr/bin/env bash
# set_github_secrets.sh
# Usage:
#   Ensure gh is installed and authenticated (`gh auth login`).
#   Run: ./scripts/set_github_secrets.sh [owner/repo]

repo=${1:-waltermosqueda/PythiaxEngine}

command -v gh >/dev/null 2>&1 || { echo "gh CLI not found. Install and 'gh auth login' first." >&2; exit 2; }

read_or_env() {
  name=$1
  val=$(printenv "$name")
  if [ -z "$val" ]; then
    read -rp "$name: " val
  fi
  echo "$val"
}

for s in SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASS MAIL_FROM MAIL_TO SENDGRID_API_KEY COPILOT_GH_TOKEN; do
  val=$(read_or_env "$s")
  if [ -z "$val" ]; then
    echo "Skipping $s (empty)"
    continue
  fi
  echo -n "$val" | gh secret set "$s" --repo "$repo"
  echo "Set $s"
done

echo "All done. Verify at: https://github.com/waltermosqueda/PythiaxEngine/settings/secrets/actions" > /dev/stderr
