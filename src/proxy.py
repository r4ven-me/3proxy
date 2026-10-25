#!/usr/bin/env python3
"""Render device-bound 3proxy configuration and FoxyProxy import JSON."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import tempfile


def port(value):
    number = int(value)
    if not 1024 <= number <= 65535:
        raise ValueError("ports must be between 1024 and 65535")
    return number


def settings(environment):
    interface = environment["PROXY_INTERFACE"]
    if not isinstance(interface, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,14}", interface):
        raise ValueError("invalid PROXY_INTERFACE")
    socks_port = port(environment["PROXY_PORT"])
    dns_port = port(environment.get("PROXY_DNS_PORT", socks_port + 10000))
    if socks_port == dns_port:
        raise ValueError("SOCKS and DNS relay ports must differ")
    dns_server = str(ipaddress.IPv4Address(environment.get("PROXY_DNS_SERVER", "1.1.1.1")))
    color = environment.get("PROXY_COLOR", "#88c0d0")
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("PROXY_COLOR must be a #RRGGBB color")
    title = environment.get("PROXY_NAME", interface)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("PROXY_NAME must be non-empty")
    return dict(interface=interface, port=socks_port, dns_port=dns_port,
                dns_server=dns_server, title=title, color=color)


def profile(config):
    return {
        "active": True, "title": config["title"], "type": "socks5",
        "hostname": "127.0.0.1", "port": str(config["port"]),
        "username": "", "password": "", "cc": "", "city": "",
        "color": config["color"], "pac": "", "pacString": "",
        "proxyDNS": True, "include": [], "exclude": [], "tabProxy": [],
    }


def compose_settings(document):
    result = []
    occupied = {}
    for name, service in document.get("services", {}).items():
        environment = service.get("environment") or {}
        if "PROXY_INTERFACE" not in environment:
            continue
        try:
            config = settings(environment)
            for field in ("port", "dns_port"):
                number = config[field]
                if number in occupied:
                    raise ValueError(f"port {number} is also used by {occupied[number]}")
                occupied[number] = name
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"service {name}: {error}") from error
        result.append(config)
    if not result:
        raise ValueError("no services with PROXY_INTERFACE found")
    return result


def export(configs):
    return json.dumps({"mode": "disable", "data": [profile(config) for config in configs]},
                      ensure_ascii=False, indent=2)


def render(template, config):
    for key in ("interface", "port", "dns_port", "dns_server"):
        template = template.replace("@" + key.upper() + "@", str(config[key]))
    if re.search(r"@[A-Z_]+@", template):
        raise ValueError("unknown placeholder in 3proxy template")
    return template


def load_compose_file(path):
    # Only the container needs YAML; the host path uses resolved Compose JSON.
    import yaml

    try:
        document = yaml.safe_load(Path(path).read_text())
    except yaml.YAMLError as error:
        raise ValueError(f"invalid Compose YAML: {error}") from error
    if not isinstance(document, dict):
        raise ValueError("Compose source must be a mapping")
    if document.get("include"):
        raise ValueError("Compose include requires resolved JSON via --compose")
    for name, service in document.get("services", {}).items():
        if service.get("extends") or service.get("env_file"):
            raise ValueError(f"service {name}: extends/env_file requires resolved JSON via --compose")
        environment = service.get("environment") or {}
        if not isinstance(environment, dict):
            raise ValueError(f"service {name}: use environment mapping or resolved JSON via --compose")
        for key, value in environment.items():
            if key.startswith("PROXY_") and isinstance(value, str) and "$" in value:
                raise ValueError(f"service {name}: Compose interpolation requires resolved JSON via --compose")
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("serve", "foxyproxy"))
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--compose", action="store_true",
                        help="read resolved docker compose JSON from stdin")
    source.add_argument("--compose-file", type=Path,
                        help="read a self-contained Compose YAML file (no interpolation or overrides)")
    args = parser.parse_args()
    try:
        if args.compose or args.compose_file:
            if args.command != "foxyproxy":
                raise ValueError("Compose sources are only supported for foxyproxy")
            document = load_compose_file(args.compose_file) if args.compose_file else json.load(sys.stdin)
            print(export(compose_settings(document)))
            return
        config = settings(os.environ)
        if args.command == "foxyproxy":
            print(export([config]))
            return
        template = Path("/etc/3proxy/3proxy.cfg.tmpl").read_text()
        content = render(template, config)
        fd, path = tempfile.mkstemp(prefix="3proxy-", suffix=".cfg")
        with os.fdopen(fd, "w") as target:
            target.write(content)
        print("--- FoxyProxy import: this container only ---", flush=True)
        print(export([config]), flush=True)
        print("--- End FoxyProxy import ---", flush=True)
        os.execv("/usr/local/bin/3proxy", ["3proxy", path])
    except (KeyError, ValueError, TypeError, OSError) as error:
        parser.exit(1, f"interface-proxy: {error}\n")


if __name__ == "__main__":
    main()
