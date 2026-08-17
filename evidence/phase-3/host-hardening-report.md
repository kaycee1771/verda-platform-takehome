# Host Hardening Report

## Result

**PASS on all three hosts.** The final diagnostic play reported zero failed and zero unreachable
hosts.

## Proven baseline

- Ubuntu 24.04 Minimal, x86_64, cgroup v2, 1500-byte public-interface MTU, shared root mount, and
  synchronized UTC time.
- Named `platform-admin` account with the external Ed25519 public key, passwordless sudo, and a
  successfully opened fresh strict-host-key session before access restriction.
- `PermitRootLogin no`, `PasswordAuthentication no`, public-key-only authentication,
  `AllowUsers platform-admin`, bounded attempts and grace time, and modern KEX/host/public-key
  algorithms. Independent probes proved administrator key login succeeds while direct root and
  password-only login fail.
- Swap disabled; bridge/forwarding, inotify, file, panic, conntrack, IPVS, overlay, iSCSI, and
  device-mapper prerequisites loaded or persisted for the later RKE2/Longhorn phases.
- Chrony, auditd, and iscsid enabled; bounded persistent journald and log rotation configured;
  diagnostic packages installed.
- Security-only unattended updates enabled with automatic reboot explicitly disabled. Reboots are
  controlled and serial.
- NetworkManager handling is conditional: the Cilium unmanaged-interface drop-in is installed only
  when NetworkManager is present and active. It was not fabricated on hosts where the service is
  absent.
- RKE2 binary, configuration, and data paths confirmed absent.

## Safe transition and recovery

Both SSH and firewall changes used a five-minute systemd recovery timer. The timer was cancelled
only after a second connection proved the named account, strict key, pinned host identity, sudo, and
the new firewall policy. Console access remains the documented out-of-band recovery path.
