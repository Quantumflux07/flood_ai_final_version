# FLOWSHIELD V2 — System Architecture

This document describes the internal architecture, lifecycle flow, and data boundaries of the FLOWSHIELD V2 emergency decision-support platform.

---

## 1. High-Level System Flow

```
                      OPERATOR / FIELD INPUT
              (Natural Language / Radio / Dispatch)
                                │
                                ▼
            ┌────────────────────────────────────────┐
            │       Input Intelligence Gateway       │
            │   (Grok / Groq / Deterministic NLP)    │
            └───────────────────┬────────────────────┘
                                │
                                ▼
            ┌────────────────────────────────────────┐
            │            Validation Gate             │
            │       [ACCEPT / CLARIFY / REJECT]      │
            └───────────────────┬────────────────────┘
                                │ (Envelope)
                                ▼
            ┌────────────────────────────────────────┐
            │          Situation State Core          │
            │ (Zone Matrix, Independent Incidents)   │
            └───────────────────┬────────────────────┘
                                │
                                ▼
            ┌────────────────────────────────────────┐
            │        Life-Safety Priority Engine     │
            │  (Trapped / Vulnerable / Deadlines)    │
            └───────────────────┬────────────────────┘
                                │
                                ▼
            ┌────────────────────────────────────────┐
            │        Greedy Resource Optimizer       │
            │  (Proximity, Status, Resource Gaps)    │
            └───────────────────┬────────────────────┘
                                │
                                ▼
            ┌────────────────────────────────────────┐
            │         Response Planning Agent        │
            │    (SOP Grounding, Approval Policy)    │
            └───────────────────┬────────────────────┘
                                │
                                ▼
            ┌────────────────────────────────────────┐
            │     Operational Plan & Replan Loop     │
            │   (Actions, Live Diffs, What-If Sim)   │
            └────────────────────────────────────────┘
```

---

## 2. Core Architectural Principles

1. **Independent Incident Identity**: Incidents are first-class domain entities (`Incident`), decoupling incident tracking from static geographic zone boundaries.
2. **Deterministic Life-Safety Core**: Priority calculations, greedy matching, and response plans are computed by transparent, verifiable algorithms—never opaque LLM calculations.
3. **Dual-Layer Input Intelligence**: Grok / Groq parses unstructured free text into strict Pydantic envelopes. When offline or unconfigured, the deterministic regex/NLP fallback executes instantly with 0ms downtime.
4. **Isolated What-If Simulations**: Simulation requests clone deep state snapshots, execute hypothetical failures, and measure delta metrics without mutating authoritative live state.
5. **Human-in-the-Loop Governance**: High-risk actions (e.g. search and rescue deployment, multi-ward evacuations) require explicit operator confirmation before dispatch.

---

## 3. Module Boundaries

| Package | Purpose |
|---|---|
| `src.models` | Strict Pydantic v2 domain schemas (`Incident`, `Resource`, `Evidence`, `SituationState`, `ResponsePlan`) |
| `src.intelligence` | Grok gateway, intent classifier, entity extractor, and deterministic fallback parser |
| `src.engine` | `SituationEngine`, `IncidentPriorityEngine`, `GreedyResourceOptimizer`, and `FlowShieldV2Manager` |
| `src.reasoning` | IBM Granite text-generation client and explainability prompt templates |
| `src.knowledge` | BM25 SOP retrieval knowledge base and standard operating procedures |
| `src.api` | REST API endpoint handlers (`/api/input/execute`, `/api/simulation`, `/api/state`, etc.) |
| `src.dashboard` | Stitch-based dark mode command center frontend (HTML5/Tailwind/Vanilla JS) |
