# Roadmap — Three-Way Match Agent Lab

Living doc. Captures where the lab could go after Phase 1 ships. Not a commitment to build any of this. Exists so roadmap thinking has a home and Phase 2 does not start from a blank page months from now.

**Last updated:** 2026-04-16

---

## Rule

Do not touch any Phase 2 code until Phase 1 ships (scorecard published, LinkedIn post live, Loom recorded). Ideas live here. Implementations wait.

---

## Phase 1 (current, shipping)

Three-way match AP agent against Odoo with a labeled 300-bill playground and a six-pillar governance scorecard. Claude-only. RPST axes varied through YAML configs. Reproducible experiments, four runs planned (baseline, V1 tight_tolerance, V2 cfo_persona, V3 haiku_ap_persona control). Deliverable is a consulting-style scorecard, a LinkedIn post, a short Loom.

---

## Phase 2 possibilities — generalize the lab

If the lab becomes a tool other teams could use rather than a one-off portfolio piece, three abstractions would need to exist.

**Model abstraction layer.** Replace direct `anthropic` library calls with an interface that supports OpenAI, Gemini, Anthropic, and local models (Ollama, vLLM). Each model plugs in via a shared contract. Enables cross-vendor accuracy-versus-cost scorecards, which is exactly the comparison a mid-market CFO asks for when selecting a procurement agent.

**Workflow abstraction.** The matcher and the playbook are AP-specific today. A workflow abstraction would let someone swap in a different task (expense report approval, PO creation, vendor onboarding, inventory reconciliation) with a new matcher and a new playbook. The rest of the lab (manifest, runner, scorecard, governance scoring) stays shared.

**Dataset import path.** The playground is seeded from hardcoded vendors and products today. A dataset abstraction would let someone bring their own labeled manifest (CSV or JSON) and run the same scorecard against their own data. That is what turns the lab from "Brian's sandbox" into "our firm's evaluation harness for client work."

**UI for non-technical reviewers.** Static HTML viewer is already the Phase 1 plan. Phase 2 UI would add upload-your-own dataset, pick a model, pick a workflow, run, view scorecard. Keep it static where possible. No backend until one is truly needed.

---

## Phase 3 possibilities — beyond the lab

**Consulting firm methodology artifact.** Wipfli, West Monroe, or any mid-market ERP consulting practice adopts the lab as their standard evaluation harness. Before a client selects Stampli, AppZen, or an internal build, the firm runs the top three candidates through the lab and delivers a six-pillar scorecard. That reframes the lab from portfolio piece to practice-area tooling.

**Teaching material.** Workshop, course module, or bootcamp curriculum on "how to evaluate an enterprise AI agent before deployment." Audience: finance leadership, IT directors, consulting practitioners. Gartner's six pillars as the scaffolding, the lab as the hands-on example.

**Vertical expansion.** Move beyond procurement. Same methodology applied to other agentic-native domains: revenue cycle management in healthcare, claims processing in insurance, order-to-cash in distribution. Each vertical gets its own labeled sandbox and its own scorecard.

---

## When to revisit this file

After Phase 1 ships. Not before. If something from Phase 2 or 3 starts feeling like the right next move, reopen this file, pick one abstraction, and define it as Phase 2.1 with its own scope and deliverable. Do not generalize into all of Phase 2 at once.
