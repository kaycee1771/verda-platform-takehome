# Management RKE2 CIS Assessment

Status: PASS for the focused Phase 4 self-assessment on all three servers. This is not a claim of
independent certification or complete CIS compliance.

| Server | Passed | Failed |
|---|---:|---:|
| `verda-mgmt-server-01` | 10 | 0 |
| `verda-mgmt-server-02` | 10 | 0 |
| `verda-mgmt-server-03` | 10 | 0 |

The checks cover CIS profile selection, the traditional `etcd` principal, pinned RKE2-generated
sysctls, restricted audit policy and administrator kubeconfig permissions, disabled anonymous API
access and profiling, active secrets encryption, an active nonempty audit log, and the RKE2 service.

Remaining manual identity boundary: Phase 4 retains break-glass client certificates. OIDC and
assessor identities belong to the later Rancher identity phase. The focused assessment supplements,
but does not replace, the SUSE RKE2 CIS 1.12 guide.
