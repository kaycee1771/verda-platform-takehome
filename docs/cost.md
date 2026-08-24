# Cost and Review Window

| Resource | Quantity | Cost contribution |
|---|---:|---:|
| Verda CPU instances | 3 | included in live rate |
| OS volumes | 3 x 80 GiB | included in live rate |
| Longhorn data volumes | 3 x 100 GiB | included in live rate |
| Total provider rate | | **$0.231645/hour** |
| Daily rate | | **$5.559/day** |
| Seven-day review estimate | | **$38.92** |
| Ten-day evaluator-window estimate | | **$55.59** |

The authenticated read-only reconciliation on 2026-08-24 showed **$77.64** credit,
or roughly **13.9 days** at the current rate. A ten-day evaluator window costs
**$55.59** and leaves **$22.05** credit. The repository's 15% contingency for
that window is **$8.34**, leaving a further **$13.71** beyond contingency.
Small certificate, registry-transfer and object/request charges are not
separately quoted and remain within that reserve.

All three instances and all six volumes are currently `PAY_AS_YOU_GO`. The
official resource responses expose no provider contract-end or rental-expiry
field; the timestamp in each instance description is operator-owned metadata,
not a Verda-enforced expiry. Consequently no provider extension is required
and no resource identity, address, attachment, Terraform configuration, or
Kubernetes membership is changed for the evaluator window.

The submission commit was created on 2026-08-24. The minimum ten-calendar-day
review date is 2026-09-03, and the planned operator teardown is
**2026-09-04T00:00:00Z**, after the full review date. Reconfirm the account
balance daily. From the 2026-08-24 reconciliation time, keeping the platform
through that teardown is projected to cost **$60.42** and leave **$17.22**
credit. Stop early only if the documented 15% contingency would be consumed.
No second cluster or GPU capacity is included.
