# CLAUDE.md — Phase 1 Three-Way Match Agent

Operating rules for any Claude session (Cowork or Claude Code) working in this project. Read before starting work.

---

## Cost Control

This is a learning lab, not a production system. API spend should reflect that.

- **Default model for variants: Haiku 4.5.** Reserve Sonnet 4.6 for the baseline run and for experiments where reasoning depth is the variable under test. Opus is off the table unless Brian specifically requests it.
- **Sample size discipline.** The 30-bill labeled sample is the default for variants. The full 300-bill set runs only when a variant's headline number will be published (scorecard, LinkedIn post, portfolio site). No speculative 300-bill runs.
- **Rerun discipline.** Don't rerun baseline unless the code under test has changed. `experiments/baseline/runs.jsonl` is the frozen reference.
- **Token hygiene.** Trim system prompts, playbooks, and tool descriptions before adding. Every variant's prompt should be shorter or the same length as baseline unless verbosity is the variable.
- **Budget checkpoint.** At $25 cumulative API spend on this project, stop and check with Brian before the next variant.

---

## Cowork ↔ Claude Code Handoff

Brian works in two modes: Cowork for framing/writing/strategy, Claude Code for execution. Sessions hand off explicitly.

**Stop and send Brian back to Cowork when:**
- A framing question appears (what should the policy be? which Gartner pillar does this target? how do we present the result?)
- A writing or content decision is on deck (post draft, SESSION_STATE narrative, scorecard prose)
- Two or more technically-valid paths exist and the choice is strategic, not technical
- The data turned up something surprising that deserves interpretation before the next step
- Scope starts expanding past the current variant's hypothesis

**Handoff message format:**
- One-sentence statement of the open question
- The 2–3 valid options
- A recommendation with one line of reasoning
- Close with: "Go work this out in Cowork, then come back with the answer."

**Resume Claude Code when:**
- Cowork has returned a one-sentence decision or hypothesis
- Ready to execute, not deliberate further

**Don't:**
- Silently pick a framing and run with it
- Keep iterating in Claude Code when the real blocker is strategic
- Assume the Cowork session will read the diff — summarize the decision in plain English

---

## Standing decisions (as of 2026-04-15)

- **Policy default for the three-way match:** AND logic (baseline, 96.7%) is the lab's recommended default for mid-market AP. OR logic (V1, 90.0%) is the strict audit-grade mode for regulated industries or high-fraud-risk contexts. Both should appear in the scorecard as a policy knob, not as "winner/loser."
- **Architecture discipline:** Math in code, narration in model. The deterministic matcher computes; the agent narrates and decides from a bounded output space.
- **Quality bar:** Ship at 85%, iterate in public.
- **Audience priority:** Consulting-credible primary, engineering-respectable secondary.
