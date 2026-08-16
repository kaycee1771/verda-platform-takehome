# Evidence: Seven-Day Stage A Cost Envelope

- Collected: 2026-08-16
- Balance authority: authenticated Verda project billing page
- Catalog authority: authenticated project deployment/volume dialogs, corroborated by current official Verda pricing
- Review window: 168 hours, supplied by the user
- Cloud resources created: 0

| Input | Value |
|---|---:|
| Project balance | $115.67 |
| Current run rate | $0.00/hour |
| Nodes | 3 |
| Compute per node | $0.02790/hour |
| Root per node | 80 GiB |
| Data per node | 100 GiB |
| NVMe | $0.20/GiB-month |
| Unquoted-services cap | $5.00 |
| Contingency | 15% |

```text
compute = 3 * 0.02790 * 168 = 14.0616
storage = 3 * (80 + 100) * 0.20 * 168 / 730 = 24.8548
known subtotal = 38.9164
with unquoted-services cap = 43.9164
with 15% contingency = 50.5039
rounded-up envelope = 50.51
remaining verified balance = 115.67 - 50.51 = 65.16
```

Result: **PASS.** The envelope uses 43.66% of the verified balance. The known compute-plus-NVMe rate is approximately $0.23165/hour ($5.56/day), and a 12-hour rate buffer is approximately $2.78.

The $5 amount is a stop-work cap for object/traffic/registry charges that are not currently quoted, not a claim about Verda pricing. Reconcile all rates and the balance before apply and at least daily thereafter.
