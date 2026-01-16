<task>
  <title>Kids' Bubblegum Calculator App Brainstorm</title>

  <goal>
    Brainstorm a simple calculator app for kids with a specific theme.
  </goal>

  <definition_of_done>
    <item>Simple calculator for kids</item>
    <item>Bubblegum front-end theme</item>
    <item>Bubblegum machine as the calculator interface</item>
  </definition_of_done>

  <constraints>
    <item>Respect existing style and architecture.</item>
    <item>Do not modify secrets (.env, tokens). Redact if encountered.</item>
    <item>Ask before running commands or making destructive changes.</item>
  </constraints>

  <expected_artifacts>
    <item>diff summary</item>
    <item>test output</item>
  </expected_artifacts>

  <gates>
    <write_gate>true</write_gate>
    <run_gate>true</run_gate>
    <destructive_gate>true</destructive_gate>
  </gates>

  <context_pointers>
    <artifact path=".conversator/prompts/3bc3070d/handoff.json"/>
  </context_pointers>
</task>