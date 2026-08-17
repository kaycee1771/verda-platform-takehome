#!/usr/bin/env python3
"""Fail-closed static checks for the Phase 3 implementation boundary."""

from __future__ import annotations

import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]


class Phase3ContractTests(unittest.TestCase):
    def test_public_port_matrix_is_fail_closed(self) -> None:
        matrix = yaml.safe_load((ROOT / "config" / "firewall-port-matrix.yaml").read_text())
        actions = {row["ports"]: row["phase_3_action"] for row in matrix["public_ingress"]}
        self.assertEqual(actions["22"], "allow")
        self.assertEqual(actions["51820"], "allow")
        for port in ("80", "443", "6443"):
            self.assertEqual(actions[port], "deny")
        self.assertEqual(matrix["phase_3_public_default"], "drop")

    def test_wireguard_private_key_is_never_slurped(self) -> None:
        tasks = (ROOT / "infra" / "ansible" / "roles" / "wireguard" / "tasks" / "main.yml").read_text()
        self.assertIn(".pub", tasks)
        slurp_blocks = tasks.split("ansible.builtin.slurp:")[1:]
        self.assertTrue(slurp_blocks)
        for block in slurp_blocks:
            public_read = block.split("register:", 1)[0]
            self.assertIn(".pub", public_read)
            self.assertNotIn(".key", public_read)

    def test_storage_format_is_guarded_by_identity_and_empty_media_checks(self) -> None:
        tasks = (ROOT / "infra" / "ansible" / "roles" / "storage_device" / "tasks" / "main.yml").read_text()
        for contract in (
            "phase3_virtio_serial_suffix_length",
            "phase3_data_size_bytes",
            "wipefs",
            "blockdev --getsize64",
            'cmp --bytes="${size_bytes}"',
            "mkfs.ext4",
            "phase3_min_data_free_bytes",
            "--mountpoint",
            "UUID=",
        ):
            self.assertIn(contract, tasks)

    def test_phase3_orchestrator_never_invokes_cloud_apply(self) -> None:
        script = (ROOT / "scripts" / "host" / "phase3.ps1").read_text()
        self.assertIn("@('plan', 'state-audit', 'cost-report', 'inventory')", script)
        self.assertNotIn("-Target apply", script)
        self.assertNotIn("repair-node-02", script)
        self.assertNotIn("-Target destroy", script)
        self.assertIn("$runtimePreparationOutput = @(& python", script)
        self.assertIn("--extra-vars '@$groupVarsContainer' --extra-vars '@$varsContainer'", script)
        self.assertIn("$adminAccessible -and -not $rootAccessible", script)
        self.assertNotIn("ANSIBLE_REMOTE_TEMP", script)

    def test_removed_timesyncd_unit_is_guarded_by_live_load_state(self) -> None:
        tasks = (ROOT / "infra" / "ansible" / "roles" / "common" / "tasks" / "main.yml").read_text()
        self.assertIn("--property=LoadState", tasks)
        self.assertIn("!= 'not-found'", tasks)
        self.assertNotIn("'systemd-timesyncd.service' in ansible_facts['services']", tasks)

    def test_firewall_uses_the_nftables_syslog_level_keyword(self) -> None:
        template = (ROOT / "infra" / "ansible" / "roles" / "firewall" / "templates" / "90-verda-platform.nft.j2").read_text()
        self.assertIn("level warn", template)
        self.assertNotIn("level warning", template)

    def test_controlled_reboot_requires_a_new_kernel_boot_identity(self) -> None:
        script = (ROOT / "scripts" / "host" / "phase3.ps1").read_text()
        self.assertGreaterEqual(script.count("/proc/sys/kernel/random/boot_id"), 2)
        self.assertIn("$bootAfter.Output.Trim() -ne $bootBefore.Output.Trim()", script)
        self.assertIn("--on-active=2s", script)
        self.assertIn("ServerAliveInterval=5", script)
        self.assertIn("cloud-init status --wait --long", script)
        self.assertIn("post-reboot-prepare-hosts.log", script)
        self.assertIn("Post-reboot convergence", script)
        self.assertNotIn("never entered the reboot boundary", script)

    def test_image_managed_locale_and_hosts_are_not_fought_on_reboot(self) -> None:
        common = (ROOT / "infra" / "ansible" / "roles" / "common" / "tasks" / "main.yml").read_text()
        wireguard = (ROOT / "infra" / "ansible" / "roles" / "wireguard" / "tasks" / "main.yml").read_text()
        diagnostics = (ROOT / "infra" / "ansible" / "roles" / "diagnostics" / "tasks" / "main.yml").read_text()
        self.assertNotIn("LC_ALL=", common)
        self.assertNotIn("/etc/default/locale", common)
        self.assertIn("'System Locale: LANG=C.UTF-8' in diagnostics_system_locale.stdout", diagnostics)
        self.assertNotIn("path: /etc/hosts", wireguard)

    def test_secure_launcher_keeps_credentials_process_only(self) -> None:
        launcher = (ROOT / "scripts" / "host" / "invoke-phase3-secure.ps1").read_text()
        self.assertEqual(launcher.count("-AsSecureString"), 1)
        self.assertIn("ZeroFreeBSTR", launcher)
        self.assertIn("'Process'", launcher)
        self.assertIn("SetEnvironmentVariable($name, $null, 'Process')", launcher)
        for persistence_command in ("setx", "Out-File", "Set-Content"):
            self.assertNotIn(persistence_command, launcher)

    def test_rke2_install_remains_a_failing_phase_four_gate(self) -> None:
        playbook = (ROOT / "infra" / "ansible" / "playbooks" / "install-rke2.yml").read_text()
        self.assertIn("Phase 4 gate", playbook)
        self.assertIn("ansible.builtin.fail", playbook)


if __name__ == "__main__":
    unittest.main()
