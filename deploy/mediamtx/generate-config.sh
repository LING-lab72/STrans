#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

usage() {
  cat <<'EOF'
Usage: ./generate-config.sh STREAM_DOMAIN [PUBLIC_HOST] [STREAM_PATH]

Examples:
  ./generate-config.sh stream.example.com
  ./generate-config.sh stream.example.com 203.0.113.10 mobile-camera

PUBLIC_HOST defaults to STREAM_DOMAIN. STREAM_PATH defaults to mobile-camera.
Generated plaintext credentials are written only to generated/credentials.env.
EOF
}

if [[ $# -lt 1 || $# -gt 3 ]]; then
  usage
  exit 2
fi

stream_domain="$1"
public_host="${2:-$stream_domain}"
stream_path="${3:-mobile-camera}"

if [[ ! "$stream_domain" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "STREAM_DOMAIN contains unsupported characters" >&2
  exit 2
fi

if [[ ! "$public_host" =~ ^[A-Za-z0-9.:-]+$ ]]; then
  echo "PUBLIC_HOST contains unsupported characters" >&2
  exit 2
fi

if [[ ! "$stream_path" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "STREAM_PATH must contain only letters, digits, underscore, or hyphen" >&2
  exit 2
fi

command -v openssl >/dev/null 2>&1 || {
  echo "openssl is required" >&2
  exit 1
}

umask 077
mkdir -p generated

publisher_user="publisher"
reader_user="viewer"
# Hex avoids reserved URL characters in RTSP/RTMP/SRT connection strings.
publisher_password="$(openssl rand -hex 24)"
reader_password="$(openssl rand -hex 24)"

sha256_base64() {
  printf '%s' "$1" | openssl dgst -binary -sha256 | openssl base64 -A
}

publisher_user_hash="$(sha256_base64 "$publisher_user")"
publisher_password_hash="$(sha256_base64 "$publisher_password")"
reader_user_hash="$(sha256_base64 "$reader_user")"
reader_password_hash="$(sha256_base64 "$reader_password")"

cat > generated/mediamtx.yml <<EOF
logLevel: info
logDestinations: [stdout]

authMethod: internal
authInternalUsers:
  - user: sha256:${publisher_user_hash}
    pass: sha256:${publisher_password_hash}
    ips: []
    permissions:
      - action: publish
        path: ${stream_path}
  - user: sha256:${reader_user_hash}
    pass: sha256:${reader_password_hash}
    ips: []
    permissions:
      - action: read
        path: ${stream_path}
      - action: playback
        path: ${stream_path}
  - user: any
    pass:
    ips: ["127.0.0.1", "::1"]
    permissions:
      - action: api
      - action: metrics
      - action: pprof

api: false
metrics: false
pprof: false

rtspTransports: [tcp]

webrtcAdditionalHosts: [${public_host}]
webrtcLocalUDPAddress: :8189
webrtcLocalTCPAddress: :8189

paths:
  ${stream_path}:
    source: publisher
EOF

cat > generated/credentials.env <<EOF
STREAM_DOMAIN=${stream_domain}
STREAM_PATH=${stream_path}
PUBLISH_USER=${publisher_user}
PUBLISH_PASSWORD=${publisher_password}
READ_USER=${reader_user}
READ_PASSWORD=${reader_password}

# Phone/browser WHIP publish endpoint (HTTPS, recommended)
WHIP_URL=https://${stream_domain}/${stream_path}/whip

# Browser WHEP endpoint
WHEP_URL=https://${stream_domain}/${stream_path}/whep

# Native-app alternatives
RTMP_URL=rtmp://${stream_domain}/${stream_path}?user=${publisher_user}&pass=${publisher_password}
SRT_URL=srt://${stream_domain}:8890?streamid=publish:${stream_path}:${publisher_user}:${publisher_password}&pkt_size=1316

# Backend/OpenCV analysis source
RTSP_URL=rtsp://${reader_user}:${reader_password}@${stream_domain}:8554/${stream_path}
EOF

cat > .env <<EOF
STREAM_DOMAIN=${stream_domain}
MEDIAMTX_IMAGE=bluenviron/mediamtx:1.19.2
EOF

chmod 600 generated/mediamtx.yml generated/credentials.env .env

echo "Configuration generated."
echo "Keep generated/credentials.env private; it contains plaintext client credentials."
echo "Next: docker compose config && docker compose up -d"
