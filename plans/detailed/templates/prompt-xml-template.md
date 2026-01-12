
# Prompt Template (XML-like)

Use this structure for `handoff.md` and (optionally) `working.md`.

```xml
<task>
  <title>...</title>
  <goal>
    ...
  </goal>

  <definition_of_done>
    <item>...</item>
    <item>...</item>
  </definition_of_done>

  <constraints>
    <item>Respect existing style and architecture.</item>
    <item>Do not modify secrets (.env, tokens). Redact if encountered.</item>
    <item>Ask before running commands or making destructive changes.</item>
  </constraints>

  <repo_targets>
    <file path="path/to/file.ts">
      <intent>What should change here</intent>
    </file>
  </repo_targets>

  <expected_artifacts>
    <item>diff summary</item>
    <item>test output</item>
    <item>rollback plan</item>
  </expected_artifacts>

  <gates>
    <write_gate>true</write_gate>
    <run_gate>true</run_gate>
    <destructive_gate>true</destructive_gate>
  </gates>

  <context_pointers>
    <beads_id>bd-xxxx</beads_id>
    <artifact path=".conversator/prompts/.../handoff.json"/>
  </context_pointers>
</task>
```
