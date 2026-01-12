
# Open Questions

1. Which primary implementation runtime (TS vs Python vs Rust)?
2. How strict should default file read allowlists be (per repo vs global)?
3. How should Beads tasks be “claimed” by builders (single worker vs multi)?
4. How do we represent complex approvals (approve once vs approve always)?
5. How aggressive should memory compaction be (timed vs on completion)?
6. How should we structure cross-repo workspaces (multi-project support)?
7. How should we handle long-running builder sessions across network drops?
