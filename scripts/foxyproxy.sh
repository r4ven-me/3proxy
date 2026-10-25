#!/bin/sh
set -eu

# Inside a container, use the read-only Compose source; no Docker socket needed.
if [ -f /etc/3proxy/compose.yaml ]; then
  exec interface-proxy foxyproxy --compose-file /etc/3proxy/compose.yaml
fi

# On the host, use resolved Compose data, including overrides and interpolation.
cd -- "$(dirname -- "$0")/.."
config=$(docker compose config --format json)
printf '%s\n' "$config" | python3 src/proxy.py foxyproxy --compose
