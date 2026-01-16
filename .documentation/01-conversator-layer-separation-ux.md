# Conversator: Layer Separation & User Experience Guide

## Executive Summary

Conversator operates as **two completely separate agent environments** that communicate through well-defined interfaces. This separation is critical for understanding the system:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   CONVERSATOR LAYER                          BUILDER LAYER                  │
│   (Voice + Planning)                         (Execution)                    │
│                                                                             │
│   ┌─────────────────────┐                   ┌─────────────────────┐         │
│   │                     │                   │                     │         │
│   │  OpenCode Session   │  ═══ FILES ═══►   │  OpenCode Session   │         │
│   │  (or custom agent)  │  ◄═══ STATUS ═══  │  (or Claude Code)   │         │
│   │                     │                   │                     │         │
│   │  • Voice interface  │                   │  • Code execution   │         │
│   │  • Subagents        │                   │  • File editing     │         │
│   │  • Memory bank      │                   │  • Bash commands    │         │
│   │  • Plan drafting    │                   │  • Testing          │         │
│   │                     │                   │                     │         │
│   │  CANNOT modify      │                   │  CANNOT speak       │         │
│   │  source code        │                   │  to user            │         │
│   │                     │                   │                     │         │
│   └─────────────────────┘                   └─────────────────────┘         │
│                                                                             │
│   Models: Gemini Flash                      Models: Opus 4.5, Sonnet 4.5    │
│   Cost: Cheap                               Cost: Expensive                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Principle:** The Conversator layer NEVER modifies source code. The Builder layer NEVER speaks to the user. They communicate through files and status updates.

---

## Part 1: The Two Environments

### Conversator Layer (OpenCode Session #1)

**Purpose:** Voice conversation, prompt refinement, memory management, coordination

**What it CAN do:**
- ✅ Speak to user via Gemini Live API
- ✅ Read source code files (for understanding)
- ✅ Write to `.conversator/**` workspace only
- ✅ Spawn subagents for planning, summarizing, context retrieval
- ✅ Query memory index
- ✅ Create Beads tasks
- ✅ Monitor builder status

**What it CANNOT do:**
- ❌ Modify source code (`src/**`, `lib/**`, etc.)
- ❌ Execute bash commands (except safe reads)
- ❌ Run tests
- ❌ Install packages
- ❌ Make git commits

**Runtime:**
- Always running during voice session
- Gemini Live maintains voice connection
- OpenCode HTTP API handles subagent orchestration
- Multiple subagents can run in parallel

### Builder Layer (OpenCode Session #2 or Claude Code)

**Purpose:** Code implementation, testing, execution

**What it CAN do:**
- ✅ Read and write ANY file
- ✅ Execute bash commands
- ✅ Run tests
- ✅ Install packages
- ✅ Make git commits
- ✅ Full codebase access

**What it CANNOT do:**
- ❌ Speak to user directly
- ❌ Ask questions interactively
- ❌ Access voice interface

**Runtime:**
- Spawned on-demand when tasks are ready
- Multiple instances can run in parallel
- Managed by Beads task queue
- Reports status back to Conversator layer

---

## Part 2: Communication Between Layers

### Conversator → Builder (Dispatch)

```
METHOD 1: File-Based Dispatch
─────────────────────────────
Conversator writes:  .conversator/plans/active/jwt-fix.md
Beads creates task:  bd create "JWT Fix" --file .conversator/plans/active/jwt-fix.md
Builder reads:       .conversator/plans/active/jwt-fix.md
Builder executes:    Implements the plan

METHOD 2: Direct CLI Dispatch
─────────────────────────────
Conversator runs:    claude -p "Execute plan in .conversator/plans/active/jwt-fix.md"
                     (or opencode with specific session)

METHOD 3: Beads Queue
─────────────────────────────
Conversator:         bd create "Task Name" --file plan.md --deps "other-task"
Beads:               Manages queue, dependencies
Builder:             bd ready | xargs -I{} claude -p "Execute task {}"
```

### Builder → Conversator (Status & Completion)

```
METHOD 1: Status File Updates
─────────────────────────────
Builder writes:      .conversator/cache/agent-status.json
                     {
                       "builder_1": {
                         "state": "building",
                         "task": "jwt-fix",
                         "progress": 70,
                         "started": "2026-01-12T14:30:00"
                       }
                     }
Conversator reads:   Polls or watches file for changes

METHOD 2: Completion Markers
─────────────────────────────
Builder writes:      .conversator/plans/completed/jwt-fix.md
                     (moves from active/ to completed/)
Builder writes:      .conversator/cache/completions/jwt-fix.json
                     {
                       "task": "jwt-fix",
                       "status": "success",
                       "files_changed": ["src/auth/middleware.ts"],
                       "summary": "Added mutex lock to prevent race condition"
                     }
Conversator reads:   Detects new file, triggers notification

METHOD 3: Stdout Capture (Direct Dispatch)
─────────────────────────────
Builder outputs:     Streams to stdout
Conversator:         Captures, summarizes, queues notification
```

### Communication Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   CONVERSATOR LAYER                                                         │
│                                                                             │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│   │    Voice     │    │   Planner    │    │   Status     │                  │
│   │   (Gemini)   │◄──►│   Subagent   │    │   Monitor    │                  │
│   └──────────────┘    └──────────────┘    └──────┬───────┘                  │
│          │                   │                   │                          │
│          │                   ▼                   │ polls                    │
│          │           ┌──────────────┐            │                          │
│          │           │    Plans     │            │                          │
│          │           │   (.md)      │            │                          │
│          │           └──────┬───────┘            │                          │
│          │                  │                    │                          │
└──────────┼──────────────────┼────────────────────┼──────────────────────────┘
           │                  │                    │
           │                  │ write              │ read
           │                  ▼                    │
     ══════╪══════════════════════════════════════╪════════════════════════════
           │                  │                    │
           │      .conversator/plans/active/       │
           │      .conversator/cache/status.json   │
           │                  │                    │
     ══════╪══════════════════════════════════════╪════════════════════════════
           │                  │                    │
           │                  │ read               │ write
           │                  ▼                    ▲
┌──────────┼──────────────────┼────────────────────┼──────────────────────────┐
│          │                  │                    │                          │
│          │           ┌──────┴───────┐    ┌──────┴───────┐                   │
│          │           │    Beads     │    │   Builder    │                   │
│          │           │    Queue     │───►│    Agent     │                   │
│          │           └──────────────┘    └──────────────┘                   │
│          │                                      │                           │
│          ▼                                      ▼                           │
│   [No voice access]                      [Full code access]                 │
│                                                                             │
│   BUILDER LAYER                                                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Part 3: Conversator Layer Subagents

### Subagent Registry

| Subagent | Model | Trigger | Output | Permissions |
|----------|-------|---------|--------|-------------|
| **Planner** | Gemini 3 Flash | `start_planning()` | Draft .md + questions | read, write(.conversator/) |
| **Summarizer** | Gemini Flash-Lite | Agent completion | 2-3 sentence summary | read only |
| **Context Reader** | Gemini 3 Flash | `lookup_context()` | Relevant context | read only |
| **Status Monitor** | None (code) | Polling/events | Status JSON | read(.conversator/cache/) |
| **Scratchpad Manager** | Gemini Flash-Lite | Dead time / capture | Checklist updates | write(.conversator/scratchpad/) |

### Subagent: Planner

**Role:** Transform vague user requests into detailed, actionable prompts through iterative conversation.

**Behavior:**
1. Receives initial request from voice layer
2. Reads relevant source files to understand context
3. Generates 2-3 clarifying questions per turn
4. Updates draft plan after each user response
5. Signals `READY_FOR_DEEP_PLANNING` when complete

**Expected Interaction Pattern:**
```
Input:  "auth is broken, token thing"
Action: Read src/auth/*.ts, identify JWT-related files
Output: "Is this the JWT refresh issue in middleware.ts, 
         or something with session tokens?"

Input:  "JWT, stops after 15 minutes"
Action: Read refresh logic, identify timing issues
Output: "Is it failing to trigger refresh, or refreshing 
         but not using the new token?"

Input:  "not refreshing when active"
Action: Finalize understanding, write draft plan
Output: "READY_FOR_DEEP_PLANNING: jwt-refresh-fix.md"
```

**Configuration:**
```yaml
# .conversator/agents/planner.yaml
name: conversator-planner
model: google/gemini-3-flash
max_questions_per_turn: 3
max_turns: 10

tools:
  read: true
  glob: true
  grep: true
  write:
    allow: [".conversator/plans/**", ".conversator/drafts/**"]
    deny: ["src/**", "lib/**", "**/*.ts", "**/*.js"]

permissions:
  bash:
    deny: ["*"]
```

### Subagent: Summarizer

**Role:** Condense long outputs into voice-appropriate summaries.

**Behavior:**
1. Receives content (plan, builder output, error message)
2. Extracts key information: what happened, result, next steps
3. Produces 2-3 sentence summary suitable for speaking

**Expected Output Examples:**
```
Input:  [2000 token plan with technical details]
Output: "The plan adds a mutex lock to the JWT refresh and 
         implements retry logic. Three files will change."

Input:  [500 token error stack trace]
Output: "The build failed. There's a type error in 
         middleware.ts on line 45. Missing property 'expiresAt'."

Input:  [Builder completion with diff]
Output: "Done. Fixed the race condition by adding a mutex. 
         Changed middleware.ts and added a new lock utility."
```

**Configuration:**
```yaml
# .conversator/agents/summarizer.yaml
name: conversator-summarizer
model: google/gemini-2.5-flash-lite
max_output_tokens: 150

system_prompt: |
  Summarize for voice output. Be concise (2-3 sentences).
  Focus on: what happened, the result, and any needed action.
  Never use code blocks or technical formatting.
```

### Subagent: Context Reader

**Role:** Retrieve relevant context from codebase and memory when asked.

**Behavior:**
1. Receives query (e.g., "why did we use mutex?")
2. Checks memory index for keyword matches
3. Retrieves summaries for relevant files
4. If needed, reads full content
5. Returns synthesized answer

**Expected Interaction Pattern:**
```
Query:  "why did we decide on mutex instead of semaphore?"
Action: 
  1. Check index: "mutex" → [jwt-fix.md, decisions-log.md]
  2. Read summaries
  3. Find: decisions-log.md mentions "Jan 10 discussion"
  4. Read full section
Output: "On January 10th, you discussed this. The reasoning was 
         single-resource locking, and mutex is simpler for that case."

Query:  "what files handle authentication?"
Action:
  1. Check index: "auth" → [middleware.ts, useAuth.ts, token.ts]
  2. Read summaries
Output: "There are three main files: middleware.ts handles JWT 
         validation, useAuth.ts is the React hook, and token.ts 
         manages refresh logic."
```

**Configuration:**
```yaml
# .conversator/agents/context-reader.yaml
name: conversator-context-reader
model: google/gemini-3-flash

tools:
  read: true
  glob: true
  grep: true

permissions:
  write:
    deny: ["**"]
  bash:
    deny: ["*"]
```

### Subagent: Status Monitor

**Role:** Track all running agents and provide instant status.

**Behavior:**
1. Polls `.conversator/cache/agent-status.json` regularly
2. Watches for completion files in `.conversator/cache/completions/`
3. Maintains in-memory registry of all agent states
4. Returns instant status (no LLM call needed)

**Implementation:**
```python
class StatusMonitor:
    def __init__(self):
        self.agents = {}
        self.pending_completions = []
    
    async def poll(self):
        """Called every 1-2 seconds"""
        # Check status file
        status = read_json(".conversator/cache/agent-status.json")
        self.agents = status.get("agents", {})
        
        # Check for new completions
        for f in glob(".conversator/cache/completions/*.json"):
            if f not in self.processed:
                self.pending_completions.append(read_json(f))
                self.processed.add(f)
    
    def get_instant_status(self) -> str:
        """No LLM call - pure data lookup"""
        if not self.agents:
            return "Nothing running. Ready for new tasks."
        
        lines = []
        for agent_id, state in self.agents.items():
            elapsed = time_since(state["started"])
            lines.append(f"{state['task']}: {state['state']} ({elapsed})")
        
        return "; ".join(lines)
```

### Subagent: Scratchpad Manager

**Role:** Capture ideas, manage checklist, fill dead time.

**Behavior:**
1. When agent is thinking (2+ min), suggest productive activities
2. Capture fleeting thoughts user mentions
3. Maintain todo checklist
4. Track blockers

**Expected Interactions:**
```
Trigger: Deep planner has been thinking for 30 seconds
Output:  "That'll take a couple minutes. We have rate limiting 
          on the list. Want to start drafting that?"

Trigger: User says "oh also remind me about the caching thing"
Action:  Append to ideas.md: "- [14:32] caching thing - user mentioned"
Output:  "Noted."

Trigger: User asks "what's on my list?"
Output:  "You have: JWT fix running, rate limiting ready to start, 
          and three ideas captured including the caching thing."
```

---

## Part 4: Builder Layer Agents

### Builder Layer Agent Registry

| Agent | Model | Trigger | Input | Output |
|-------|-------|---------|-------|--------|
| **Deep Planner** | Opus 4.5 | `dispatch_to_deep_planner()` | Refined prompt | Detailed plan + questions |
| **Builder** | Sonnet 4.5 | Beads task or direct dispatch | Finalized plan | Code changes + status |
| **Test Runner** | Haiku/Flash | Builder completion | Changed files | Test results |

### Agent: Deep Planner

**Role:** Produce comprehensive, implementation-ready plans from refined prompts.

**Behavior:**
1. Receives refined prompt from Conversator layer
2. Analyzes full codebase context
3. Produces detailed plan with:
   - Step-by-step implementation
   - File-by-file changes
   - Potential risks
   - Follow-up questions
4. Writes plan to `.conversator/plans/active/`

**Expected Output Structure:**
```markdown
# Plan: JWT Refresh Fix

## Summary
Fix race condition in JWT refresh by adding mutex lock.

## Analysis
The issue is in `src/auth/middleware.ts` lines 45-67. When multiple 
requests arrive simultaneously during token expiry, each triggers 
a refresh, causing race condition.

## Implementation Steps
1. Create mutex utility in `src/utils/mutex.ts`
2. Modify `refreshToken()` to acquire lock before refresh
3. Add retry logic with exponential backoff
4. Update tests

## Files to Modify
- src/auth/middleware.ts (lines 45-67)
- src/utils/mutex.ts (new file)
- tests/auth.test.ts

## Risks
- Lock timeout could cause request failures
- Need to handle lock acquisition errors

## Follow-up Questions
1. What should the lock timeout be? (default: 5000ms)
2. How many retry attempts? (default: 3)
3. Should failed refresh throw or return null?
```

### Agent: Builder

**Role:** Implement code changes based on finalized plans.

**Behavior:**
1. Receives task from Beads queue
2. Reads plan from `.conversator/plans/active/`
3. Implements changes step by step
4. Runs relevant tests
5. Reports status to `.conversator/cache/agent-status.json`
6. On completion, writes to `.conversator/cache/completions/`

**Status Reporting:**
```json
// .conversator/cache/agent-status.json
{
  "agents": {
    "builder_jwt_fix": {
      "state": "building",
      "task": "jwt-fix",
      "progress": 70,
      "current_step": "Modifying middleware.ts",
      "started": "2026-01-12T14:30:00",
      "files_touched": ["src/utils/mutex.ts", "src/auth/middleware.ts"]
    }
  }
}

// .conversator/cache/completions/jwt-fix.json (on completion)
{
  "task": "jwt-fix",
  "status": "success",
  "duration_seconds": 145,
  "files_changed": [
    "src/utils/mutex.ts",
    "src/auth/middleware.ts",
    "tests/auth.test.ts"
  ],
  "summary": "Added mutex lock to JWT refresh. All tests passing.",
  "warnings": []
}
```

---

## Part 5: User Experience Examples

### Example A: Simple Conversation (Conversator Layer Only)

**Scenario:** User wants to discuss approach, no code changes needed.

```
USER: "hey, thinking about how we should handle rate limiting"

CONVERSATOR: "Sure. What's driving this—seeing abuse, or proactive protection?"

USER: "proactive, we're launching soon and want to be ready"

CONVERSATOR: "Makes sense. Are you thinking per-user limits, per-IP, 
              or something more granular like per-endpoint?"

USER: "probably per-IP for now, but maybe layered later"

CONVERSATOR: "Per-IP is a good start. Redis with sliding window is the 
              usual approach. Want me to draft a plan for that, or just 
              capture this as notes for later?"

USER: "just notes for now, we'll come back to it"

CONVERSATOR: "Got it. Added to your ideas list: 'Rate limiting - per-IP 
              first, Redis sliding window, consider layered approach later.'"
```

**What Happened:**
- Voice layer handled entire conversation
- Scratchpad Manager captured the idea
- No subagents spawned (simple discussion)
- No Builder layer involvement
- Zero code access needed

**Layers Involved:**
```
[Voice Layer] ──► [Scratchpad Manager] ──► ideas.md
```

---

### Example B: Memory/Context Query (Conversator Layer Only)

**Scenario:** User wants to recall past decision.

```
USER: "wait, why did we go with mutex for the JWT thing?"

CONVERSATOR: [calls lookup_context("mutex JWT decision")]

         ┌─────────────────────────────────────────────┐
         │  Context Reader Subagent                    │
         │                                             │
         │  1. Index lookup: "mutex" "jwt"             │
         │     → [jwt-fix.md, decisions-log.md]        │
         │                                             │
         │  2. Read decisions-log.md summary           │
         │     → "Jan 10: mutex vs semaphore..."       │
         │                                             │
         │  3. Read full section                       │
         │     → "Single-resource locking, mutex       │
         │        is simpler, semaphore overkill"      │
         └─────────────────────────────────────────────┘

CONVERSATOR: "We discussed that on January 10th. You said the use case 
              is single-resource locking, and mutex is simpler than 
              semaphore for that. Want me to pull up the full context?"

USER: "no that's good, I remember now"
```

**What Happened:**
- Voice layer triggered context lookup
- Context Reader subagent queried memory index
- Retrieved and synthesized relevant context
- No Builder layer involvement
- Read-only codebase access

**Layers Involved:**
```
[Voice Layer] ──► [Context Reader] ──► [Memory Index] ──► [decisions-log.md]
```

---

### Example C: Codebase Query (Conversator Layer Only)

**Scenario:** User wants to understand code structure.

```
USER: "what handles authentication in this project?"

CONVERSATOR: [calls lookup_context("authentication handlers")]

         ┌─────────────────────────────────────────────┐
         │  Context Reader Subagent                    │
         │                                             │
         │  1. Index lookup: "auth" "authentication"   │
         │     → [middleware.ts, useAuth.ts, token.ts] │
         │                                             │
         │  2. Read file summaries                     │
         │     → middleware.ts: "JWT validation"       │
         │     → useAuth.ts: "React auth hook"         │
         │     → token.ts: "Token refresh logic"       │
         │                                             │
         │  3. Glob for related: src/auth/*            │
         │     → Also found: types.ts, constants.ts    │
         └─────────────────────────────────────────────┘

CONVERSATOR: "Authentication is handled in the src/auth folder. The main 
              files are: middleware.ts for JWT validation on requests, 
              useAuth.ts is the React hook for auth state, and token.ts 
              manages refresh logic. There's also types and constants 
              files. Want me to dig into any of these?"

USER: "what does the middleware do exactly?"

CONVERSATOR: [Context Reader reads middleware.ts]
              "The middleware checks the Authorization header on each 
              request, validates the JWT signature, checks expiry, and 
              if expired, triggers a refresh. It attaches the user object 
              to the request context. About 80 lines of code."
```

**What Happened:**
- Voice layer triggered context lookup
- Context Reader used glob + file reading
- Synthesized structural understanding
- No code modifications
- No Builder layer involvement

**Layers Involved:**
```
[Voice Layer] ──► [Context Reader] ──► [Codebase Files (read-only)]
```

---

### Example D: Planning & Building (Both Layers)

**Scenario:** User wants to fix a bug.

```
USER: "the JWT refresh is broken, fix it"

CONVERSATOR: [calls start_planning("JWT refresh", "broken")]

         ┌─────────────────────────────────────────────┐
         │  Planner Subagent                           │
         │                                             │
         │  1. Read src/auth/middleware.ts             │
         │  2. Read src/auth/token.ts                  │
         │  3. Identify JWT refresh logic              │
         └─────────────────────────────────────────────┘

CONVERSATOR: "I see the refresh logic in token.ts. What's happening—
              is it not refreshing at all, or refreshing but something 
              else is wrong?"

USER: "it stops refreshing after about 15 minutes of inactivity"

         ┌─────────────────────────────────────────────┐
         │  Planner Subagent                           │
         │                                             │
         │  1. Analyze timing logic                    │
         │  2. Check token expiry settings             │
         │  3. Look for inactivity handling            │
         └─────────────────────────────────────────────┘

CONVERSATOR: "The tokens expire after 15 minutes, and I see the refresh 
              is tied to user activity. Is it supposed to refresh even 
              when inactive, or only when the user comes back?"

USER: "should refresh when they come back"

         ┌─────────────────────────────────────────────┐
         │  Planner Subagent                           │
         │                                             │
         │  1. Identify the bug                        │
         │  2. Write draft plan                        │
         │  → .conversator/plans/drafts/jwt-fix.md    │
         └─────────────────────────────────────────────┘

CONVERSATOR: "Got it. The issue is the refresh doesn't trigger on 
              return from inactivity. I've drafted a plan. Ready to 
              send to deep planner for full analysis?"

USER: "yeah send it"

CONVERSATOR: [calls dispatch_to_deep_planner("jwt-fix.md")]
              "Sent to Opus for deep planning. That'll take 2-3 minutes. 
              Want to work on something else while it runs?"

USER: "what else is on my list?"

CONVERSATOR: [instant status from Scratchpad Manager]
              "You have: rate limiting ideas from earlier, and a note 
              about caching. The rate limiting is more fleshed out."

USER: "let's sketch out rate limiting then"

CONVERSATOR: [calls start_planning("rate limiting", "per-IP, Redis")]
              ... [planning conversation continues] ...

═══════════ 2 MINUTES LATER ═══════════

         ┌─────────────────────────────────────────────┐
         │  Deep Planner (Opus 4.5) COMPLETES          │
         │                                             │
         │  Output: jwt-fix-plan.md                    │
         │  - Detailed implementation steps            │
         │  - 3 follow-up questions                    │
         │                                             │
         │  Writes: .conversator/plans/active/         │
         └─────────────────────────────────────────────┘

         ┌─────────────────────────────────────────────┐
         │  Summarizer Subagent                        │
         │                                             │
         │  Condenses plan to voice summary            │
         └─────────────────────────────────────────────┘

         ┌─────────────────────────────────────────────┐
         │  Notification Manager                       │
         │                                             │
         │  Queues notification (priority: normal)     │
         │  Waits for natural pause...                 │
         └─────────────────────────────────────────────┘

[User finishes sentence about rate limiting]

CONVERSATOR: "Quick update—the JWT deep plan is ready. It's proposing 
              to add an activity timestamp check and trigger refresh 
              on return from idle. Has three questions: Should stale 
              tokens auto-refresh or require re-auth? What's the max 
              idle time? And should we log refresh events? Want to 
              answer those now or finish rate limiting first?"

USER: "let's answer those—auto-refresh, 30 minutes max, and yes log them"

CONVERSATOR: [updates jwt-fix-plan.md with answers]
              "Updated. The plan is complete. Want me to execute it?"

USER: "yes"

CONVERSATOR: [calls execute_plan("jwt-fix-plan.md")]

         ┌─────────────────────────────────────────────┐
         │  Beads Task Created                         │
         │                                             │
         │  bd create "JWT Refresh Fix"                │
         │     --file .conversator/plans/active/...    │
         └─────────────────────────────────────────────┘

         ┌─────────────────────────────────────────────┐
         │  Builder Agent (Sonnet 4.5) SPAWNS          │
         │                                             │
         │  Runs in SEPARATE OpenCode session          │
         │  Full codebase access                       │
         │  Reports status to cache/agent-status.json  │
         └─────────────────────────────────────────────┘

CONVERSATOR: "Building now. Estimated 2-3 minutes. The rate limiting 
              draft is about half done—want to finish that?"

USER: "yeah"

... [conversation continues] ...

═══════════ 3 MINUTES LATER ═══════════

         ┌─────────────────────────────────────────────┐
         │  Builder Agent COMPLETES                    │
         │                                             │
         │  Writes: cache/completions/jwt-fix.json     │
         │  Status: success                            │
         │  Files: middleware.ts, token.ts, tests      │
         └─────────────────────────────────────────────┘

         ┌─────────────────────────────────────────────┐
         │  Status Monitor detects completion          │
         │  Summarizer condenses                       │
         │  Notification queued                        │
         └─────────────────────────────────────────────┘

[Natural pause in conversation]

CONVERSATOR: "JWT fix is done. Added activity timestamp check, 
              30-minute idle threshold, and refresh logging. 
              Three files changed, all tests passing. Want details?"

USER: "nice, no I'm good"
```

**What Happened:**
- Conversator layer: Voice, Planner, Summarizer, Status Monitor, Scratchpad
- Builder layer: Deep Planner (Opus), Builder (Sonnet)
- Communication: Files in `.conversator/`, status JSON, Beads task
- Parallel work: Rate limiting planning while JWT building

**Layers Involved:**
```
[Voice Layer]
      │
      ▼
[Planner Subagent] ──► draft.md
      │
      ▼
[Deep Planner (Opus)] ◄─── .conversator/plans/drafts/
      │
      ▼
.conversator/plans/active/jwt-fix.md
      │
      ▼
[Beads Task Queue]
      │
      ▼
[Builder (Sonnet)] ──► src/auth/middleware.ts (MODIFIES)
      │                src/auth/token.ts (MODIFIES)
      │
      ▼
.conversator/cache/completions/jwt-fix.json
      │
      ▼
[Status Monitor] ──► [Summarizer] ──► [Voice Layer]
```

---

### Example E: Status Check (Cross-Layer Query)

**Scenario:** User wants to know what's happening.

```
USER: "what's the status of everything?"

CONVERSATOR: [calls get_status() - INSTANT, no LLM]

         ┌─────────────────────────────────────────────┐
         │  Status Monitor (in-memory lookup)          │
         │                                             │
         │  Reads: cache/agent-status.json             │
         │                                             │
         │  builder_jwt: building, 70%, 2min elapsed   │
         │  planner_rate: drafting, 50%                │
         │  deep_planner: idle                         │
         └─────────────────────────────────────────────┘

CONVERSATOR: "JWT fix is building, about 70% done, been running 2 minutes. 
              Rate limiting plan is half drafted. Deep planner is free."

USER: "any errors?"

CONVERSATOR: [checks cache/errors/]
              "No errors. Everything running smooth."

USER: "ETA on the JWT fix?"

CONVERSATOR: "Based on progress, probably another minute or so."
```

**What Happened:**
- Status Monitor reads from cache (no LLM call)
- Instant response from in-memory registry
- Cross-layer visibility via status files
- No subagent spawning needed

---

## Part 6: Permission Model Summary

### Conversator Layer Permissions

```yaml
# Global permissions for all Conversator subagents
conversator_permissions:
  read:
    allow: ["**"]  # Can read everything
  
  write:
    allow:
      - ".conversator/**"
      - ".beads/**"
    deny:
      - "src/**"
      - "lib/**"
      - "tests/**"
      - "*.ts"
      - "*.js"
      - "*.py"
      - "package.json"
      - "Cargo.toml"
  
  bash:
    allow:
      - "cat *"
      - "ls *"
      - "find *"
      - "grep *"
      - "bd create *"
      - "bd ready"
      - "bd list"
    deny:
      - "rm *"
      - "mv *"
      - "cp *"
      - "npm *"
      - "pip *"
      - "cargo *"
      - "git commit *"
      - "git push *"
```

### Builder Layer Permissions

```yaml
# Permissions for Builder agents
builder_permissions:
  read:
    allow: ["**"]
  
  write:
    allow: ["**"]  # Full access
  
  bash:
    allow: ["**"]  # Full access
    
  # Additional capabilities
  capabilities:
    - execute_tests
    - install_packages
    - git_operations
    - modify_config
```

---

## Summary: Layer Separation

| Aspect | Conversator Layer | Builder Layer |
|--------|-------------------|---------------|
| **Primary Purpose** | Voice conversation, planning | Code implementation |
| **Voice Access** | ✅ Full | ❌ None |
| **Code Modification** | ❌ Cannot | ✅ Full |
| **Bash Execution** | ❌ Read-only | ✅ Full |
| **Models** | Cheap (Gemini Flash) | Expensive (Opus, Sonnet) |
| **Runtime** | Always on | On-demand |
| **Parallelism** | Multiple subagents | Multiple builders |
| **Communication** | Function calls, files | Status files, completions |

**The Golden Rule:** Conversator talks, Builder builds. They never cross roles.
