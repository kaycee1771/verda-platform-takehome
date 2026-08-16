# Verda Provider Discovery

This configuration declares no resource and no data source. It exists only to download a pinned provider family and export the exact local schema before production modules are written.

Run it through `scripts/phase0/export-provider-schema.ps1`. Provider download requires an explicit switch; schema output is local and ignored.

Authentication values are read from supported environment variables when required. They are never declared in HCL.
