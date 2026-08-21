# FLOWSHIELD V2 — REST API Contract & Integration Specification

This document provides the complete API contract for the **FlowShield V2** backend, designed for consumption by the **Stitch** frontend and external emergency management systems.

---

## 1. Architectural Overview

```
EXTERNAL INPUT (Natural Language / JSON)
        ↓
GROK INPUT INTELLIGENCE GATEWAY (Server-Side)
        ↓
VALIDATION GATE (ACCEPT / CLARIFY / REJECT)
        ↓
FLOWSHIELD STATE CORE (Zone-Independent Incidents & Resources)
        ↓
LIFE-SAFETY PRIORITY ENGINE (Trapped Count + Critical Facilities + Risk)
        ↓
RESOURCE OPTIMIZER (Greedy Fit + Proximity Scoring)
        ↓
RESPONSE PLANNING AGENT (Policy Grounded + Citations + Actions)
        ↓
ACTION & OUTCOME DISPATCH
        ↓
SYNCHRONOUS REPLANNING
```

### Key Guarantees
- **Grok Security**: Grok API keys (`GROK_API_KEY`, `XAI_API_KEY`) remain strictly on the backend.
- **Fail-Safe Fallback**: If Grok is unavailable, times out, or returns invalid JSON, the deterministic fallback engine processes the input with zero disruption and marks `source: "fallback"`.
- **Validation Gate**: Unsupported or incomplete inputs never enter or corrupt the authoritative decision engine.
- **Simulation Safety**: What-if scenarios run on isolated deep snapshots — live operational state is never mutated by simulations.
- **Zone Independence**: Incidents possess unique identities and can have multiple incidents per zone, approximate locations, or multi-ward affected areas.

---

## 2. API Endpoints Summary

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/input/analyze` | Parse natural language, classify intent, extract facts, and evaluate gate status. |
| `POST` | `/api/input/execute` | Process and execute an accepted request through the decision engine and replan. |
| `GET`  | `/api/state` | Return complete operational snapshot (zones, incidents, resources, allocations, plan, why panel). |
| `GET`  | `/api/incidents` | Return list of active incidents with life-safety attributes. |
| `GET`  | `/api/resources` | Return deployable resource inventory with status. |
| `GET`  | `/api/decisions` | Return latest response plan, actions, and explainability records. |
| `GET`  | `/api/allocations` | Return resource allocations and unassigned gap incidents. |
| `POST` | `/api/state/update` | Apply direct state/resource updates and trigger synchronous replan. |
| `POST` | `/api/simulation` | Run what-if scenario on state snapshot without modifying live state. |
| `POST` | `/api/reset` | Reset simulation state to baseline scenario. |
| `POST` | `/api/ingest` | Legacy V1 citizen incident ingestion (backward compatibility). |

---

## 3. Endpoints Specification

### 3.1 `POST /api/input/analyze`
Analyzes arbitrary text through Grok (or deterministic fallback) without mutating live state.

#### Request Body
```json
{
  "text": "37 people are trapped near the civil hospital in W12-C",
  "zone_id_hint": "W12-C"
}
```

#### Response (200 OK — ACCEPT)
```json
{
  "status": "accept",
  "source": "grok",
  "confidence": 0.95,
  "envelope": {
    "id": "c1a9d0f4-...",
    "raw_input": "37 people are trapped near the civil hospital in W12-C",
    "intent": "incident",
    "domain": "flood_response",
    "status": "accept",
    "location": "civil hospital",
    "affected_areas": ["W12-C"],
    "requested_operation": "ingest_incident",
    "facts": {
      "people_at_risk": 37,
      "people_trapped": 37,
      "water_depth_m": null,
      "rainfall_mm_hr": null,
      "critical_facility": "Hospital",
      "road_blocked": null,
      "severity": "critical",
      "zone_id": "W12-C",
      "location_name": "civil hospital"
    },
    "missing_information": [],
    "rejection_reason": null,
    "clarification_prompt": null,
    "source": "grok",
    "processed_at": "2026-08-21T16:45:00Z"
  }
}
```

#### Response (200 OK — CLARIFY)
```json
{
  "status": "clarify",
  "source": "fallback",
  "confidence": 0.85,
  "envelope": {
    "raw_input": "Send help to the school",
    "intent": "clarification_required",
    "status": "clarify",
    "missing_information": ["specific_zone_or_school_name", "water_depth", "people_at_risk"],
    "clarification_prompt": "Please provide specific location/zone details, water level, and whether people are trapped or at risk."
  }
}
```

#### Response (200 OK — REJECT)
```json
{
  "status": "reject",
  "source": "fallback",
  "confidence": 0.95,
  "envelope": {
    "raw_input": "There was an earthquake in Ahmedabad",
    "intent": "unsupported",
    "status": "reject",
    "rejection_reason": "Input is outside the supported urban flood-response domain."
  }
}
```

---

### 3.2 `POST /api/input/execute`
Executes an accepted input, applies state changes, re-evaluates priorities, re-optimizes resources, and generates updated response plans.

#### Request Body
```json
{
  "text": "Rescue Crew Alpha is unavailable due to engine maintenance"
}
```

#### Response (200 OK — Resource Update Replan)
```json
{
  "status": "success",
  "intent": "resource_update",
  "resource_id": "crew-alpha",
  "previous_status": "available",
  "new_status": "unavailable",
  "allocations": {
    "assignments": [
      {
        "incident_id": "inc-hospital-01",
        "resource_id": "crew-beta",
        "fit_score": 0.82,
        "estimated_travel_minutes": 8.0,
        "reason_codes": ["OA_BEST_FIT"]
      }
    ],
    "unassigned_incidents": []
  },
  "response_plan": {
    "id": "plan-uuid",
    "requires_human_approval": true,
    "plan_actions": [...]
  },
  "source": "fallback",
  "timestamp": "2026-08-21T16:46:00Z"
}
```

---

### 3.3 `GET /api/state`
Returns the authoritative live operational state snapshot.

#### Response (200 OK)
```json
{
  "city": "Ahmedabad",
  "overall_severity": "critical",
  "zones": {
    "W12-C": {
      "zone_id": "W12-C",
      "severity": "critical",
      "latest_rainfall_mm_hr": 72.0,
      "latest_water_level_m": 2.1,
      "road_blocked": true,
      "affected_population": 2800
    }
  },
  "incidents": [...],
  "priority_results": [...],
  "resources": [...],
  "optimization_result": {...},
  "actions": [...],
  "outcomes": [...],
  "response_plan": {...},
  "why_panel": {
    "reasoning_situation": {...},
    "reasoning_priorities": {...},
    "reasoning_assignments": {...},
    "operator_response": {...}
  },
  "timeline": [...]
}
```

---

### 3.4 `POST /api/simulation`
Runs what-if simulation scenarios without modifying live state.

#### Request Body
```json
{
  "text": "What happens if Pump Unit A fails?",
  "resource_unavailable": "pump-A"
}
```

#### Response (200 OK)
```json
{
  "status": "success",
  "simulation": {
    "scenario": "What happens if Pump Unit A fails?",
    "simulated_at": "2026-08-21T16:47:00Z",
    "live_state_modified": false,
    "assignments": [...],
    "unassigned_gaps": [
      {
        "incident_id": "inc-south-drain",
        "priority_score": 0.62,
        "reason_codes": ["UA_NO_CAPABLE_RESOURCE"]
      }
    ],
    "gap_count": 1,
    "assigned_count": 2,
    "response_plan": {
      "gap_count": 1,
      "plan_actions": [
        {
          "action_description": "Escalate to municipal flood control: no capable resource available within travel limit",
          "approval_state": "required"
        }
      ]
    }
  }
}
```

---

## 4. Input Classification & Gate Reference

| Intent | Trigger Examples | Gate Status | Engine Action |
|---|---|---|---|
| `INCIDENT` | "37 people trapped near hospital" | `ACCEPT` | Ingest incident, update evidence, re-score priority, optimize, plan. |
| `RESOURCE_UPDATE` | "Crew 01 is unavailable" | `ACCEPT` | Update resource status, trigger re-allocation replan. |
| `STATE_UPDATE` | "Rainfall increased to 180 mm/hr in W12-C" | `ACCEPT` | Ingest weather/sensor event, update zone status, replan. |
| `SIMULATION` | "What happens if Pump 03 fails?" | `ACCEPT` | Run on state snapshot, return dry-run impact diff. |
| `QUERY` | "Which incident is most urgent?" | `ACCEPT` | Query state and return structured deterministic answer. |
| `CLARIFICATION_REQUIRED` | "Send help to the school" | `CLARIFY` | Prompt user for missing location/severity details. |
| `UNSUPPORTED` | "There was an earthquake in Ahmedabad" | `REJECT` | Reject safely with structured explanation. |

---

## 5. Structured Error Codes

| Error Code | HTTP Status | Meaning | Recommended UI Action |
|---|---|---|---|
| `MISSING_INPUT_TEXT` | 400 | Request body missing `text` or `report_text`. | Highlight input field. |
| `UNSUPPORTED_DOMAIN` | 200 / 400 | Topic outside flood response (e.g. earthquake). | Display warning badge with rejection reason. |
| `CLARIFICATION_REQUIRED` | 200 | Ambiguous input with missing fields. | Render clarification prompt dialog for user response. |
| `RESOURCE_NOT_FOUND` | 400 / 404 | Specified resource identifier does not exist. | Show available resource dropdown. |
| `NO_FEASIBLE_RESOURCE` | 200 | All matching resources are deployed or too far. | Display gap escalation action badge. |
| `EXECUTION_FAILURE` | 500 | Internal processing exception. | Display error notification and retry button. |

---

## 6. Frontend (Stitch) UI States Guide

1. **Loading State**: Show spinner while awaiting `/api/input/analyze` or `/api/input/execute`.
2. **Clarification State**: If `status === "clarify"`, display `missing_information` checklist and `clarification_prompt` textarea.
3. **Rejection State**: If `status === "rejected"`, display non-destructive dismissable alert with `reason`.
4. **Live Success State**:
   - Render `incidents` cards with life-safety badges (`people_trapped`, `people_at_risk`, `critical_facility`).
   - Render `priority_results` with drivers list (`"37 people trapped"`, `"Hospital at risk"`).
   - Render `allocations` table with resource, ETA, fit score, and reason codes.
   - Render `response_plan` with human approval toggles (`auto_dispatch` vs `approval_required`).
   - Render `why_panel` with transparent attribution (`source: "grok"` or `source: "fallback"`).
5. **Simulation State**: Render side-by-side comparison modal with badge `[SIMULATION DRY-RUN - LIVE STATE UNMODIFIED]`.
