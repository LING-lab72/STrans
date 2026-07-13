#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

recipient_file="${1:-age-recipient.txt}"
source_file="generated/credentials.env"
encrypted_file="generated/camera-connection.age"

if ! command -v age >/dev/null 2>&1; then
  echo "age is required; install it before encrypting credentials." >&2
  exit 1
fi

if [[ ! -r "$recipient_file" || ! -r "$source_file" ]]; then
  echo "Recipient key or credential source is missing or unreadable." >&2
  exit 1
fi

recipient="$(grep -E '^age1[0-9a-z]+$' "$recipient_file" | head -n 1 || true)"
if [[ -z "$recipient" ]]; then
  echo "Recipient file does not contain a valid age public key." >&2
  exit 1
fi

umask 077
age --encrypt --recipient "$recipient" --output "$encrypted_file" "$source_file"
chmod 600 "$encrypted_file"
echo "Encrypted credential package created: $encrypted_file"
