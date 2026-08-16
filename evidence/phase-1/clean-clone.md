# Phase 1 Clean-Clone Evidence

## Status

PASS for final technical implementation commit `f4848cfe9dc738cc2b0d9787b1e33ffb6ff57efe`.

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
- `make validate`, `make validate-negative`, `make pre-commit`, and `make secret-scan`: PASS on
  immediate-parent implementation candidate `853beeb`.
- `make ci`: PASS on final implementation commit `f8364af`; this reran all four suites above.
- Reproduced image digest: `sha256:6d32d1047025bce8bc6b4f3e0aa926c458ebef55ac486434c8d874aa38462bb0`.

After the hosted runner exposed and Codex corrected Linux bind-mount ownership, a new clone was
created directly from the public remote at `f4848cf`. It began with no `.local/` directory, ran
`make bootstrap-tools` followed by `make ci`, scanned nine commits without a leak, and remained
clean after validation.

| Post-portability fresh-clone artifact | Bytes | SHA-256 |
|---|---:|---|
| `bootstrap-image.log` | 3,416 | `e1abce697d25f5d41b46e41c1201ebf4c4eda8a97b1b8a237f320234dc5b8aec` |
| `bootstrap-cache.log` | 1,912 | `e3caad9451be2483cc3180c9ceb071429fff244fb68a33646a4b732e62b1fa27` |
| `ci.log` | 9,950 | `66424cf258a1690fd8acdfff6ffcbf6b1797fce9d352135ff544d3533bcdef3a` |
| `tool-image.json` | 563 | `3aea022eaab64781d790c4c41d283f5022ce5c84861e878a37b0a3dd250feec6` |

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

The final `f8364af` clone produced these additional records:

| Local artifact | Bytes | SHA-256 |
|---|---:|---|
| `bootstrap-image.log` | 3,151 | `77d0970a903a12f9d7974945aba4a46d148ae04feffdddc597ae3127f3c50865` |
| `bootstrap-cache.log` | 1,912 | `e3caad9451be2483cc3180c9ceb071429fff244fb68a33646a4b732e62b1fa27` |
| `ci.log` | 10,122 | `325ed10b838b1099c4459b35d213a7295f11196872dea6d29e1ccb5af17d614a` |
| `tool-image.json` | 563 | `1a502c6cdd21637072fb7f2d9fad946270cd7b1fe624c0963890ec845e154e7e` |
