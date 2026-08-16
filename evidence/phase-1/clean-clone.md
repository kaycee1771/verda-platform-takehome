# Phase 1 Clean-Clone Evidence

## Status

PASS for implementation candidate `853beeba81aa85c9453b37f7a18223f1c46fba2f`.

## Required proof

From an isolated local clone with no copied `.local/` directory:

```powershell
make bootstrap-tools
make validate
make validate-negative
make pre-commit
make secret-scan
make ci
```

## Result

- Source `.local/` copied into clone: No.
- Clone working tree before and after validation: Clean.
- `make bootstrap-tools`: PASS; all checksummed schemas and provider cache created from zero.
- `make validate`: PASS.
- `make validate-negative`: PASS; five invalid inputs rejected.
- `make pre-commit`: PASS; all hooks over all tracked files.
- `make secret-scan`: PASS; working tree and complete history clean.
- `make ci`: PASS.

The first candidate clean-clone test rejected the repository because a broad `generated/` ignore
pattern omitted the generated-inventory sentinel. The pattern was narrowed, the sentinel was added
to the machine contract, a new commit and clone were created, and the entire sequence above passed.

| Local artifact | Bytes | SHA-256 |
|---|---:|---|
| `bootstrap-image.log` | 3,569 | `62921eadcb3eb2e1b93a0e91dde0f235db47953d25d8095081f9052317f2cded` |
| `bootstrap-cache.log` | 1,912 | `e3caad9451be2483cc3180c9ceb071429fff244fb68a33646a4b732e62b1fa27` |
| `validate.log` | 8,432 | `391f3405ecfc9a07c759b2c217691683c1f69980a7801d40b98a63129624c54d` |
| `negative.log` | 414 | `a6f1352dfe6418c64e76e2772fa50f4c9fa1cc52413fab9d2f7c65884c222673` |
| `pre-commit.log` | 749 | `d77f875df541be36359b3862071895f3feae2a704adccbb4eaef50b8de37aab5` |
| `secret-scan.log` | 407 | `8c5416ddd427dce41c2173396abcfbedece9b0e7b91ba309e422c2856c2aef78` |
| `ci.log` | 10,122 | `32482bf0955aeea9f7e9b4f6a496535189d9940368953927d017d5ca2a2788cc` |
