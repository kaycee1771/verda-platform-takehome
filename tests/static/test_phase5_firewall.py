import unittest
from pathlib import Path

import jinja2
import yaml


ROOT = Path(__file__).resolve().parents[2]


class Phase5FirewallTests(unittest.TestCase):
    @staticmethod
    def render(enabled: bool) -> str:
        template = (
            ROOT / "infra/ansible/roles/firewall/templates/90-verda-platform.nft.j2"
        ).read_text(encoding="utf-8")
        environment = jinja2.Environment(
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        environment.filters["bool"] = bool
        return environment.from_string(template).render(
            groups={
                "management_servers": [
                    "verda-mgmt-server-01",
                    "verda-mgmt-server-02",
                    "verda-mgmt-server-03",
                ]
            },
            inventory_hostname="verda-mgmt-server-01",
            hostvars={
                "verda-mgmt-server-01": {"ansible_host": "192.0.2.11"},
                "verda-mgmt-server-02": {"ansible_host": "192.0.2.12"},
                "verda-mgmt-server-03": {"ansible_host": "192.0.2.13"},
            },
            ansible_host="192.0.2.11",
            phase3_admin_cidrs_v4=["198.51.100.0/24"],
            phase3_wireguard_addresses={
                "verda-mgmt-server-01": "10.20.0.11",
                "verda-mgmt-server-02": "10.20.0.12",
                "verda-mgmt-server-03": "10.20.0.13",
            },
            phase3_wireguard_interface="wg-mgmt",
            phase3_wireguard_port=51820,
            phase4_cluster_firewall_enabled=True,
            phase4_management_pod_cidr="10.42.0.0/16",
            phase5_public_ingress_enabled=enabled,
        )

    def test_public_ingress_is_explicit_and_preserves_phase_four_fallback(self):
        variables = yaml.safe_load(
            (ROOT / "infra/ansible/inventories/group_vars/management_servers.yml").read_text(
                encoding="utf-8"
            )
        )
        self.assertIs(variables["phase5_public_ingress_enabled"], True)

        firewall = (
            ROOT / "infra/ansible/roles/firewall/templates/90-verda-platform.nft.j2"
        ).read_text(encoding="utf-8")
        selector = (
            'ct direction original iifname != "{{ phase3_wireguard_interface }}" '
            "meta l4proto tcp ct status dnat ct original ip daddr {{ ansible_host }} "
            "ct original proto-dst { 80, 443 }"
        )
        translated = (
            "ip daddr {{ phase4_management_pod_cidr }} "
            "tcp dport { 8000, 8443 }"
        )
        self.assertEqual(firewall.count(f"{selector} {translated} accept"), 1)
        self.assertEqual(firewall.count(f"{selector} drop"), 1)
        phase_five = firewall.split(
            "{% if phase5_public_ingress_enabled | default(false) | bool %}", 1
        )[1].split("{% endif %}", 1)[0]
        self.assertIn(f"{selector} {translated} accept", phase_five)
        self.assertIn("{% else %}", phase_five)
        self.assertIn(f"{selector} drop", phase_five)

    def test_port_matrix_opens_only_phase_five_web_ingress(self):
        matrix = yaml.safe_load(
            (ROOT / "config/firewall-port-matrix.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(matrix["active_phase"], 5)
        public = {entry["name"]: entry for entry in matrix["public_ingress"]}
        self.assertEqual(public["http-ingress"]["phase_5_action"], "allow")
        self.assertEqual(public["https-ingress"]["phase_5_action"], "allow")
        self.assertEqual(public["http-ingress"]["phase_3_action"], "deny")
        self.assertEqual(public["https-ingress"]["phase_3_action"], "deny")
        self.assertEqual(public["http-ingress"]["phase_5_purpose"], "acme-http01")
        self.assertEqual(public["ssh-administration"]["source"], "approved-admin-cidrs")
        self.assertNotIn("phase_5_action", public["kubernetes-api"])

    def test_rendered_branches_preserve_admin_rules_and_exact_translation(self):
        enabled = self.render(True)
        disabled = self.render(False)
        original = (
            "ct direction original iifname != \"wg-mgmt\" meta l4proto tcp "
            "ct status dnat ct original ip daddr 192.0.2.11 "
            "ct original proto-dst { 80, 443 }"
        )
        translated = "ip daddr 10.42.0.0/16 tcp dport { 8000, 8443 }"
        self.assertIn(f"{original} {translated} accept", enabled)
        self.assertNotIn(f"{original} drop", enabled)
        self.assertIn(f"{original} drop", disabled)
        self.assertNotIn(f"{translated} accept", disabled)
        for rendered in (enabled, disabled):
            self.assertIn("ip saddr @admin_ipv4 tcp dport 22", rendered)
            self.assertIn("ip saddr @admin_ipv4 tcp dport 6443", rendered)
            forward = rendered.split("chain forward", 1)[1]
            self.assertLess(
                forward.index("ct original proto-dst { 80, 443 }"),
                forward.index("ct state { established, related } accept"),
            )


if __name__ == "__main__":
    unittest.main()
