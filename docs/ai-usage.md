# AI Usage

| Task | Assistant used | Output used | Validation | Correction / rejection |
|---|---|---|---|---|
| Architecture and requirement decomposition | OpenAI Codex | ADRs, topology and acceptance criteria | provider schema, live inventory, human approval | optional second cluster and overengineered broker work removed |
| Terraform, Ansible and GitOps implementation | OpenAI Codex | code and tests | saved plans, syntax/static tests, live convergence | unsafe or unverified mutations rejected |
| Platform troubleshooting | OpenAI Codex | Harbor, Argo, monitoring and logging fixes | hosted CI and direct live checks | requests/replicas adjusted to measured capacity |
| Repository simplification | OpenAI Codex | dead-code removal, renames, evaluator docs | pre-commit, repository contract, link/term scans | historical evidence retained only for traceability |

Human authority remained with the user for credentials, billing, live mutation approval, architecture changes and final release. AI-generated changes were reviewed through tests and observed live outcomes; assistant claims are not treated as evidence by themselves.

The assignment suggested Claude as an AI assistant. I used ChatGPT and OpenAI Codex instead for architecture review, implementation, debugging and documentation. AI-generated output was treated as a proposal and validated against official documentation, automated tests and observed live behaviour.
