# Hosted CI

The latest protected platform change was [PR #41](https://github.com/kaycee1771/verda-platform-takehome/pull/41), `Add platform-demo availability alert`. It merged to `main` as commit `2ef36558a8070ffa0d620665eda70b71ce23d1dd`.

Its merge-candidate validation and the resulting protected-main revision both passed the required `Validate repository` workflow. The current recorded protected-main run is [32690306295](https://github.com/kaycee1771/verda-platform-takehome/actions/runs/32690306295), with successful job `Credential-free quality gates` ([97322653322](https://github.com/kaycee1771/verda-platform-takehome/actions/runs/32690306295/job/97322653322)). The workflow started at `2026-08-24T04:31:02Z`; the job ran from `2026-08-24T04:31:06Z` to `2026-08-24T04:34:08Z`, and the workflow completed at `2026-08-24T04:34:09Z` with conclusion `success`.

The job checked out complete history, verified host prerequisites, restored non-sensitive validator caches, bootstrapped the pinned tools and offline caches, ran the CI-equivalent positive and rejection suites, and uploaded non-sensitive validation reports. Those suites covered repository contracts, Terraform, application and static tests, rendered manifests, policy fixtures, Prometheus rules, Markdown, negative rejection cases, and working-tree plus full-history secret scanning. The full-history Gitleaks scan passed with no leaks found.

This record intentionally identifies the latest protected platform-change PR and its immutable successful run. Later documentation-only commits do not change that platform validation result.
