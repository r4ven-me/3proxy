"""Tests for reading the read-only Compose source inside a container."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

from proxy import compose_settings, load_compose_file


@unittest.skipUnless(importlib.util.find_spec("yaml"), "PyYAML is installed in the container")
class ComposeSourceTests(unittest.TestCase):
    def load(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compose.yaml"
            path.write_text(content)
            return load_compose_file(path)

    def test_anchors_and_multiple_services(self):
        document = self.load('''
x-env: &env
  PROXY_INTERFACE: enp5s0
  PROXY_PORT: "1081"
services:
  first:
    environment: *env
  second:
    environment:
      <<: *env
      PROXY_INTERFACE: tun0
      PROXY_PORT: "1082"
''')
        configs = compose_settings(document)
        self.assertEqual([config["interface"] for config in configs], ["enp5s0", "tun0"])
        self.assertEqual([config["dns_port"] for config in configs], [11081, 11082])

    def test_invalid_yaml_and_non_mapping(self):
        for text in ("[", "- item", "", "!!python/object/apply:os.system ['false']"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.load(text)

    def test_rejects_interpolation(self):
        with self.assertRaisesRegex(ValueError, "interpolation"):
            self.load('services: {vpn: {environment: {PROXY_INTERFACE: "${IFACE}"}}}')

    def test_rejects_unresolved_compose_features(self):
        for text in (
            'include: other.yaml',
            'services: {vpn: {extends: other}}',
            'services: {vpn: {env_file: .env}}',
            'services: {vpn: {environment: [PROXY_INTERFACE=tun0]}}',
        ):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "resolved JSON"):
                self.load(text)
