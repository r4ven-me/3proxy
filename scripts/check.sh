#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")/.."

python3 -B - <<'PY'
import json
import subprocess
import sys

sys.path.insert(0, 'src')
from proxy import compose_settings

# Cloudflare sees the external IP of each configured profile.
document = json.loads(subprocess.check_output(['docker', 'compose', 'config', '--format', 'json']))
for config in compose_settings(document):
    print(f"\n=== {config['title']} / {config['interface']} / SOCKS5 {config['port']} ===", flush=True)
    subprocess.run([
        'curl', '--noproxy', '', '--proxy', f"socks5h://127.0.0.1:{config['port']}",
        '--connect-timeout', '10', '--max-time', '25', '--fail', '--silent', '--show-error',
        'https://www.cloudflare.com/cdn-cgi/trace',
    ], check=True)
PY
