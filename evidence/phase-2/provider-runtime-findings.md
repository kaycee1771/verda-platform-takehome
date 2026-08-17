# Provider runtime findings

## Image canonicalization

The first apply created every planned resource, then provider 1.1.2 returned
`image=ubuntu-24.04` for instances planned with the immutable configuration UUID. Terraform marked
the three instance addresses tainted and emitted `Provider produced inconsistent result after
apply`. This is a provider representation defect, not an unplanned cloud action.

ADR 0012 documents the fail-closed correction: the root retains and publishes the immutable UUID;
the provider receives its official `image_type`; every plan/apply revalidates the exact live mapping.
No `ignore_changes`, provider fork, manual console resource, or floating `latest` value was accepted.

## Recovery outcome

The first post-apply plan proposed replacing all three instances solely because Terraform retained
the provider-error taint. The canonical assertion rejected it. After the user explicitly authorized
only server-02 replacement, the recovery target created verified encrypted backups, cleared the
provider-error taint only from healthy servers 01 and 03, and required exactly one `delete/create`
action at server-02's Terraform address.

The assertion also proved the replacement retained the accepted flavor, image mapping, location,
on-demand setting, 80 GiB OS size, and the identical existing data-volume attachment. The saved
recovery plan SHA-256 was `bbae1b085ac4f375db7677fe8f85fde1510ce613e497be652453775df042f42d`.
After apply and a state-only refreshed-output plan, the final plan contained zero resource actions;
its SHA-256 was `b8f563e99d2f1eff2dedd202b75cd2ddc9e12c71d844a9bb1cb3237d1617dc69`.
