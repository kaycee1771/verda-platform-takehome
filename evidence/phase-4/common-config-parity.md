# Management Common-Configuration Parity

Status: PASS on 2026-08-19.

| Assertion | Result |
|---|---|
| Server count | 3 |
| Unique common-configuration hashes | 1 |
| Sanitized SHA-256 | Retained in ignored runtime report; omitted from final curated evidence |
| Secret values included in the hash | No |

The parity hash covers the source-controlled common RKE2 configuration shared by all servers. Node
names and node-specific addresses remain outside that common file. The definitive bootstrap proved
one unique hash across all three nodes, and the corrected current-tree independent verification
reproved the same parity assertion. The digest is deliberately omitted; this report records neither
raw configuration nor endpoint values.
