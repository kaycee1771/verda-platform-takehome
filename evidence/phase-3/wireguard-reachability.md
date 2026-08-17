# WireGuard and MTU Evidence

## Result

**PASS.** Each host generated and retained its private key locally; the controller retrieved only
public keys. The committed report contains no endpoint or private-key value.

| Check | Result |
|---|---|
| Underlay MTU | 1500 bytes on all three nodes |
| Management WireGuard MTU | 1420 bytes |
| Reserved future Cilium VXLAN MTU | 1370 bytes |
| Directed peer paths | 6 of 6 PASS |
| No-fragment payload test | 1392-byte payload PASS on every directed path |
| Future nested-overlay payload test | PASS on every directed path |
| Recent authenticated handshakes | PASS for every peer |
| Sustained traffic | 3-node ring, 5 seconds/path, all PASS; minimum observed receive rate 1529.02 Mbit/s |

The throughput measurement is a short acceptance signal, not a production performance SLO. The
MTU is an explicit architectural input: 1500 underlay minus a conservative 80-byte WireGuard
allowance yields 1420, and reserving another 50 bytes for future VXLAN yields 1370. Phase 4 must use
the reserved Cilium value and validate real pod-to-pod transfer before the cluster gate can pass.
