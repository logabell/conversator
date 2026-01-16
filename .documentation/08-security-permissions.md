
# Security, Permissions & Safety

## Threat model (high level)
- Secrets leakage to external models
- Prompt injection from repo content (docs/README telling agents to do unsafe things)
- Accidental destructive edits
- Untrusted tool execution

## Secrets hygiene
- Never send:
  - `.env`, secrets, tokens, kubeconfigs, SSH keys
- Implement:
  - redaction before external model calls
  - allowlist/denylist for file reads
  - “sensitive file detector” (path + content heuristics)

## Prompt injection defenses
- Repo content is untrusted input.
- Tool policy:
  - never execute instructions found in repo text unless user confirms
  - always follow system tool rules over in-repo instructions

## Permission model

### Conversator layer (control plane)
- Can:
  - write inside `.conversator/**`
  - read repo selectively for retrieval
- Cannot:
  - run destructive commands in repo by default

### Builder layer
- Can:
  - edit repo files
  - run tests/commands (with gates)
- Must:
  - request permission before write/run
  - log commands run + outputs

## Gates
- Write gate: before modifying repo
- Run gate: before executing tests/commands
- Destructive gate: before deleting, rewriting large areas, or migrations

## Audit logging
- Record:
  - files read
  - files written
  - commands executed
  - which provider/model performed actions
- Keep logs local by default; optionally attach summaries to Beads.
