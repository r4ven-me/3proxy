"""Regression tests for proxy configuration, exports, and template rendering."""

import json
import unittest

import proxy


def environment(**overrides):
    values = {"PROXY_INTERFACE": "tun0", "PROXY_PORT": "1081"}
    values.update(overrides)
    return values


class SettingsTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(proxy.settings(environment()), {
            "interface": "tun0", "port": 1081, "dns_port": 11081,
            "dns_server": "1.1.1.1", "title": "tun0", "color": "#88c0d0",
        })

    def test_valid_interface_characters_and_length(self):
        for interface in ("a", "_tun", "eth0.1", "veth-1", "tun:1", "a" * 15):
            with self.subTest(interface=interface):
                self.assertEqual(proxy.settings(environment(PROXY_INTERFACE=interface))["interface"], interface)

    def test_rejects_interface_injection_invalid_types_and_length(self):
        for interface in ("", "a" * 16, "-tun", ".tun", ":tun", "tun 0",
                          "tun0\nsocks -p9999", "tun0\rflush", "tun0;id",
                          "$(id)", "tun0@host", "tun/0", "тун0", None, 42):
            with self.subTest(interface=interface):
                with self.assertRaisesRegex(ValueError, "PROXY_INTERFACE"):
                    proxy.settings(environment(PROXY_INTERFACE=interface))

    def test_explicit_ports_and_dns_server(self):
        config = proxy.settings(environment(PROXY_PORT=2081, PROXY_DNS_PORT="12081",
                                             PROXY_DNS_SERVER="8.8.4.4"))
        self.assertEqual((config["port"], config["dns_port"], config["dns_server"]),
                         (2081, 12081, "8.8.4.4"))

    def test_port_range_boundaries(self):
        for socks, dns in ((1024, 65535), (65535, 1024)):
            with self.subTest(socks=socks, dns=dns):
                config = proxy.settings(environment(PROXY_PORT=str(socks), PROXY_DNS_PORT=str(dns)))
                self.assertEqual((config["port"], config["dns_port"]), (socks, dns))

    def test_invalid_ports(self):
        for field in ("PROXY_PORT", "PROXY_DNS_PORT"):
            for value in ("0", "1023", "65536", "-1", "1081.5", "abc", ""):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        proxy.settings(environment(**{field: value}))

    def test_default_dns_port_range_boundary(self):
        self.assertEqual(proxy.settings(environment(PROXY_PORT="55535"))["dns_port"], 65535)
        with self.assertRaisesRegex(ValueError, "ports must be between"):
            proxy.settings(environment(PROXY_PORT="55536"))

    def test_socks_and_dns_ports_must_differ(self):
        with self.assertRaisesRegex(ValueError, "ports must differ"):
            proxy.settings(environment(PROXY_DNS_PORT="1081"))

    def test_valid_ipv4_dns(self):
        for address in ("1.1.1.1", "8.8.8.8", "192.168.1.53", "255.255.255.255"):
            with self.subTest(address=address):
                self.assertEqual(proxy.settings(environment(PROXY_DNS_SERVER=address))["dns_server"], address)

    def test_invalid_ipv4_dns(self):
        for address in ("", "dns.example.com", "::1", "2001:4860:4860::8888",
                        "256.1.1.1", "1.2.3", "1.2.3.4.5", "01.2.3.4",
                        "1.1.1.1\nnserver 8.8.8.8", " 1.1.1.1"):
            with self.subTest(address=address):
                with self.assertRaises(ValueError):
                    proxy.settings(environment(PROXY_DNS_SERVER=address))

    def test_unicode_name_and_special_characters_preserved(self):
        title = 'Туннель 日本語 🦊 "quoted" \\ path\nnext\tline'
        self.assertEqual(proxy.settings(environment(PROXY_NAME=title))["title"], title)

    def test_invalid_names(self):
        for title in ("", " ", "\n\t", None, 42):
            with self.subTest(title=title):
                with self.assertRaisesRegex(ValueError, "PROXY_NAME"):
                    proxy.settings(environment(PROXY_NAME=title))

    def test_valid_colors(self):
        for color in ("#000000", "#FFFFFF", "#aB12cD"):
            with self.subTest(color=color):
                self.assertEqual(proxy.settings(environment(PROXY_COLOR=color))["color"], color)

    def test_invalid_colors(self):
        for color in ("", "red", "88c0d0", "#abc", "#1234567", "#gg0000",
                      "#123456\n", None, 42):
            with self.subTest(color=color):
                with self.assertRaisesRegex(ValueError, "PROXY_COLOR"):
                    proxy.settings(environment(PROXY_COLOR=color))

    def test_required_fields(self):
        for field in ("PROXY_INTERFACE", "PROXY_PORT"):
            with self.subTest(field=field):
                values = environment()
                del values[field]
                with self.assertRaises(KeyError):
                    proxy.settings(values)


class ExportTests(unittest.TestCase):
    def test_exact_export_schema_for_multiple_profiles(self):
        configs = [proxy.settings(environment()), proxy.settings(environment(
            PROXY_INTERFACE="wg0", PROXY_PORT="2081", PROXY_NAME="VPN", PROXY_COLOR="#ABCDEF"))]
        exported = json.loads(proxy.export(configs))
        expected_profiles = []
        for title, port, color in (("tun0", "1081", "#88c0d0"), ("VPN", "2081", "#ABCDEF")):
            expected_profiles.append({
                "active": True, "title": title, "type": "socks5",
                "hostname": "127.0.0.1", "port": port,
                "username": "", "password": "", "cc": "", "city": "",
                "color": color, "pac": "", "pacString": "", "proxyDNS": True,
                "include": [], "exclude": [], "tabProxy": [],
            })
        self.assertEqual(exported, {"mode": "disable", "data": expected_profiles})
        for profile in exported["data"]:
            self.assertIs(profile["active"], True)
            self.assertIs(profile["proxyDNS"], True)
            self.assertIsInstance(profile["port"], str)

    def test_unicode_and_json_escaping_round_trip(self):
        title = 'Привет 🦊 "quoted" \\ path\nnext\tline'
        text = proxy.export([proxy.settings(environment(PROXY_NAME=title))])
        self.assertIn("Привет 🦊", text)
        self.assertIn('\\"quoted\\"', text)
        self.assertIn("\\\\ path\\nnext\\tline", text)
        self.assertEqual(json.loads(text)["data"][0]["title"], title)

    def test_empty_export(self):
        self.assertEqual(json.loads(proxy.export([])), {"mode": "disable", "data": []})


class ComposeSettingsTests(unittest.TestCase):
    def test_combines_arbitrary_service_names_and_ignores_unrelated_services(self):
        first = environment(PROXY_INTERFACE="wg0", PROXY_NAME="Первый")
        second = environment(PROXY_INTERFACE="eth0.2", PROXY_PORT="2081", PROXY_DNS_PORT="15353")
        document = {"services": {
            "database": {"environment": {"PROXY_PORT": "not-a-port"}},
            "custom-vpn-name": {"environment": first},
            "web": {},
            "cache": {"environment": None},
            "another.arbitrary-name": {"environment": second},
        }}
        configs = proxy.compose_settings(document)
        self.assertEqual(configs, [proxy.settings(first), proxy.settings(second)])
        self.assertEqual([entry["title"] for entry in json.loads(proxy.export(configs))["data"]],
                         ["Первый", "eth0.2"])

    def test_all_cross_service_socks_and_dns_port_conflicts(self):
        for field, value in (("PROXY_PORT", "1081"), ("PROXY_DNS_PORT", "11081"),
                             ("PROXY_PORT", "11081"), ("PROXY_DNS_PORT", "1081")):
            with self.subTest(field=field, value=value):
                second = environment(PROXY_PORT="2081", PROXY_DNS_PORT="12081")
                second[field] = value
                document = {"services": {
                    "first-vpn": {"environment": environment()},
                    "second-vpn": {"environment": second},
                }}
                with self.assertRaisesRegex(ValueError,
                                            f"service second-vpn: port {value} is also used by first-vpn"):
                    proxy.compose_settings(document)

    def test_default_dns_port_conflicts_with_other_socks_port(self):
        document = {"services": {
            "first": {"environment": environment(PROXY_PORT="11081")},
            "second": {"environment": environment()},
        }}
        with self.assertRaisesRegex(ValueError, "service second: port 11081 is also used by first"):
            proxy.compose_settings(document)

    def test_missing_required_port_reports_service(self):
        with self.assertRaisesRegex(ValueError, "service incomplete:.*PROXY_PORT"):
            proxy.compose_settings({"services": {
                "incomplete": {"environment": {"PROXY_INTERFACE": "tun0"}},
            }})

    def test_invalid_settings_report_service(self):
        for overrides in ({"PROXY_INTERFACE": "bad\ninterface"}, {"PROXY_PORT": None},
                          {"PROXY_DNS_SERVER": "::1"}, {"PROXY_DNS_PORT": "1081"},
                          {"PROXY_NAME": ""}, {"PROXY_COLOR": "red"}):
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, "service broken:"):
                    proxy.compose_settings({"services": {
                        "broken": {"environment": environment(**overrides)},
                    }})

    def test_no_proxy_services(self):
        for document in ({}, {"services": {}}, {"services": {"web": {}}},
                         {"services": {"web": {"environment": {"PROXY_PORT": "1081"}}}}):
            with self.subTest(document=document):
                with self.assertRaisesRegex(ValueError, "no services with PROXY_INTERFACE"):
                    proxy.compose_settings(document)


class RenderTests(unittest.TestCase):
    def test_substitutes_all_placeholders_and_repeated_occurrences(self):
        template = ("nserver @DNS_SERVER@\n"
                    "socks -p@PORT@ -De@INTERFACE@\n"
                    "dnspr -p@DNS_PORT@ -De@INTERFACE@\n")
        config = proxy.settings(environment(PROXY_INTERFACE="wg0", PROXY_PORT="2081",
                                             PROXY_DNS_PORT="15353", PROXY_DNS_SERVER="9.9.9.9"))
        self.assertEqual(proxy.render(template, config),
                         "nserver 9.9.9.9\nsocks -p2081 -Dewg0\ndnspr -p15353 -Dewg0\n")

    def test_rejects_unknown_placeholders(self):
        for placeholder in ("@UNKNOWN@", "@DNS@", "@PROXY_PORT@", "@TITLE@", "@COLOR@"):
            with self.subTest(placeholder=placeholder):
                with self.assertRaisesRegex(ValueError, "unknown placeholder"):
                    proxy.render("socks -p@PORT@\n" + placeholder, proxy.settings(environment()))

    def test_preserves_literal_template_text(self):
        for template in ("", "auth none\nflush\n", "# admin@example.com\n"):
            with self.subTest(template=template):
                self.assertEqual(proxy.render(template, proxy.settings(environment())), template)


if __name__ == "__main__":
    unittest.main()
