# WorldReasoner — Comprehensive Implementation Plan

**Date:** 2026-03-08
**Synthesises:** `WorldReasoner_v2_Roadmap.md` + `graph_builder_plan.md` + codebase analysis

---

## Guiding Principles

1. **Incremental over big-bang.** Each phase is independently shippable.
2. **NL explanation is the primary artifact.** The graph is derived from it.
3. **Agents do reasoning; tools do mechanics.** Remove mechanical overhead from agent
   step budgets.
4. **Don't replace what works.** `GenericDatabase` + pydantic models are sound; the
   repository pattern adds a thin layer, not a rewrite.
5. **Validate at commit time, not at tool-call time.** Agents should not be blocked
   mid-session by validation errors they cannot easily recover from.

---

## Current State (Codebase Baseline)

- **HindsightAgent**: manager + `evidence_collector` + `causal_analyzer` sub-agents.
  The causal_analyzer does graph work inline, blocking the pipeline.
- **ForecastAgent**: single agent connecting to an MCP server; causal tools optional.
- **GenericDatabase**: custom SQLite + pydantic models (not SQLAlchemy — the v2
  roadmap references SQLAlchemy but the real codebase does not use it).
- **Tool pain points**: event ID bootstrap problem, silent validation failures,
  JSON-in-a-string for outcome impacts, post-hoc graph feedback only.
- **Known bugs fixed**: `clear_evidence` now deletes `EventOutcomeImpact` records;
  `graph_inspector` no longer flags non-actual-outcome MCQ options as orphans.

---

## Phase 0 — Tool UX Fixes (Independent, Ship First)

**Goal:** Reduce the mechanical friction in graph building without changing architecture.
**Effort:** ~2 weeks. Zero risk — all additive or error-message improvements.

### 0.1 `causal_reasoner` — Three targeted fixes

**File:** `src/tools/reasoning/causal_reasoner.py`

**a) Validate event existence before linking**
```python
source_event = self.db.get(Event, source_event_id)
if not source_event:
    return self.error_response(
        f"source_event_id '{source_event_id}' not found. "
        "Create it first with event_identifier.",
        error="source_event_not_found",
    )
# same for target_event_id
```

**b) Explain chronology failures**
```python
# Replace silent HypothesisOutput(status="error") with:
return self.error_response(
    f"Chronology violation: source event occurred {source_date}, "
    f"target event occurred {target_date}. Cause must precede effect.",
    error="chronology_violation",
)
```

**c) Invalid `relation_type` → error, not silent CAUSES default**
```python
try:
    relation = CausalRelationType(relation_type.lower())
except ValueError:
    return self.error_response(
        f"Invalid relation_type '{relation_type}'. "
        f"Valid: {[r.value for r in CausalRelationType]}",
        error="invalid_relation_type",
    )
```

**d) Connectivity hint on success response**
After saving, check whether `target_event_id` is an actual outcome event for the
question. Include `"outcome_connected": true/false` in the response. Agents can skip
calling `graph_inspector` for a connectivity check after each link.

**e) Strict DAG Enforcement (Cycle checking)**
Explicitly verify that the new relation does not create a causal cycle (e.g. A → B → A).
Walk the existing graph upward from `source_event_id` and if `target_event_id` is encountered, return an error.

### 0.2 `event_identifier` — Two targeted fixes

**File:** `src/tools/reasoning/event_identifier.py`

**a) Soften date proximity warning**
Only warn when ALL source articles are published *before* the event date (genuinely
impossible and likely a date error). Remove the forward-looking ">30 days from
published_date" check — it fires legitimately when an article reports a past event.

**b) Always expose `actual_outcome_event_id` in response**
When `question_id` is set, include in the tool response:
```python
"actual_outcome_event_id": "<id of is_actual_outcome=True event>",
```
Agents always know their graph target without a separate `get_question_events` call.

### 0.3 New tool: `record_outcome_impact`

**File:** `src/tools/reasoning/record_outcome_impact.py`

Replace the `outcome_impacts` JSON-string parameter on `event_identifier` with a
dedicated tool that takes native typed inputs (one impact per call):

```
Inputs:
  event_id:         str
  outcome_event_id: str
  direction:        str   — "positive" | "negative" | "neutral"
  magnitude:        float
  confidence:       float
  reasoning:        str
```

Keep the deprecated `outcome_impacts` string on `event_identifier` for backward
compatibility, but new agents and prompts use `record_outcome_impact`.

### 0.4 `GraphInspectorTool` — Actionable orphan messages

**File:** `src/tools/inspectors/graph_inspector.py`

For each orphan event, append a suggested next action:
```
🔴 Iran's Supreme Leader Khamenei dies [ACTUAL OUTCOME]
   ID: evt_abc123
   → Fix: call causal_reasoner with target_event_id='evt_abc123' to connect
     your last intermediate event to this outcome.

🔴 US withdraws from region [non-ground-truth outcome]
   → No connection needed (not the actual outcome).
```

### 0.5 Update prompt field-name mismatch

**File:** `src/pipelines/prompts/hindsight_causal_analysis.py`

Replace every reference to `actual_outcome_event_id` (field does not exist in tool
outputs) with instructions to read the `actual_outcome_event_id` field now injected
by `event_identifier` (§0.2b above), or to look for `is_actual_outcome=True` in the
outcome events list.

### 0.6 Graph Modification Tools (Error Recovery)

**Files:** `src/tools/reasoning/delete_event.py`, `src/tools/reasoning/delete_hypothesis.py`

Agents often make minor errors but have no way to undo them. Instead of restarting the whole process, provide targeted tools to let them recover from their mistakes.
*   `delete_event`: Drops an event and its associated hypotheses. Fails with a friendly warning if the event is an Outcome event.
*   `delete_hypothesis`: Drops a causal link between two events if the agent realizes the relationship was incorrect.

---

## Phase 1 — NL Pipeline: HindsightAgent Decoupling

**Goal:** HindsightAgent produces a natural-language causal explanation and exits.
GraphBuilderAgent converts that into a structured graph asynchronously.
**Effort:** ~3–4 weeks. Medium risk on HindsightAgent prompt change.

### 1.1 Question model: two new fields

**File:** `src/domain/models/question.py`

```python
causal_explanation: Optional[str] = Field(
    None,
    description=(
        "NL causal explanation produced by HindsightAgent. "
        "Includes dated events, causal relationships, and article citations [art_id]. "
        "Input to GraphBuilderAgent."
    ),
)
graph_built: bool = Field(
    default=False,
    description="Set to True by GraphBuilderAgent after successfully building the causal graph.",
)
```

Add a DB migration for both columns. Update `clear_evidence` to reset both to
`None / False` when clearing a question for reprocessing.

### 1.2 New tool: `SaveExplanationTool`

**File:** `src/tools/generators/save_explanation.py`

```
Inputs:
  explanation: str   — full NL causal narrative (see §1.3 for format)

Behaviour:
  - Saves question.causal_explanation = explanation
  - Sets question.graph_built = False
  - Returns confirmation
```

Registered in `src/tools/__init__.py`. Question ID is injected at construction
(same pattern as `EventIdentifierTool`).

### 1.3 NL Explanation Format Contract

The explanation is the contract between stage 1 (HindsightAgent) and stage 2
(GraphBuilderAgent). The HindsightAgent prompt must instruct the agent to produce:

```
For each significant event:
  "[EventTitle] occurred on YYYY-MM-DD [art_id1, art_id2]. <description>"

For each causal link, use explicit language:
  "This caused / triggered / prevented / amplified [NextEvent]."

Outcome identification:
  "This resulted in [OutcomeEventTitle], which is the actual outcome (Option N)."

Impact on each possible outcome (MCQ):
  "Impact on Option 0: strongly positive — direct causal chain terminates here.
   Impact on Option 1: negative — escalation made ceasefire unlikely."
```

Article IDs must be real IDs from the DB — HindsightAgent reads them from
article_inspector output, not from memory.

### 1.4 Simplified HindsightAgent

**File:** `src/agents/hindsight_agent.py`

Remove `causal_agent` and all its tools. Managed agents become `[evidence_agent]` only.

Manager agent tools: `ArticleInspectorTool`, `QuestionArticlesTool`, `SaveExplanationTool`.

Manager agent prompt (replace `MANAGER_AGENT_DESCRIPTION`):

```
PROCESS:
1. COLLECT EVIDENCE
   Delegate to evidence_collector. Target: {min_evidence_articles}+ articles
   from {window_start} to {resolution_date}.
   Use article_inspector to verify coverage. Repeat if insufficient.

2. WRITE CAUSAL EXPLANATION
   With hindsight (ground truth: {ground_truth}), write a detailed NL explanation
   of HOW the outcome came about. Follow the explanation format exactly:
   - Each event: title, date, description, article IDs [art_id]
   - Explicit causal language between events
   - Outcome clearly identified
   - Impact on each possible outcome (for MCQ)

   Call save_explanation to store it.
```

### 1.5 GraphBuilderAgent

**File:** `src/agents/graph_builder_agent.py`

New agent. Does NOT do research. Reads stored NL + articles for citation verification.

Tools:
- `GetExplanationTool` — reads `question.causal_explanation`, outcome events, article list
- `ArticleRetrievalTool` — read-only, for citation verification only
- `EventIdentifierTool`
- `CausalReasonerTool`
- `record_outcome_impact`
- `GraphInspectorTool`
- `MarkGraphBuiltTool` — sets `question.graph_built = True`

Prompt (in `src/pipelines/prompts/graph_builder.py`):

```
You are converting a causal explanation into a structured event graph.
Do NOT research or invent — work only from the explanation below.

ACTUAL OUTCOME EVENT ID: {actual_outcome_event_id}

CAUSAL EXPLANATION:
{causal_explanation}

PROCESS:
1. For each event in the explanation:
   a. Fetch the cited article [art_id] with article_retrieval to confirm
      the event date and that the article supports the claim.
   b. Call event_identifier with the confirmed date and article IDs.
   c. Note the returned event ID.

2. For each causal relationship stated in the explanation:
   Call causal_reasoner with the source and target event IDs.
   Always end the chain with a link to the actual outcome event ID above.

3. For each significant event, call record_outcome_impact for each outcome.

4. Call graph_inspector to verify:
   - Max Depth >= 1
   - Actual outcome event is NOT listed as an orphan

5. Call mark_graph_built to complete.
```

**Article validation note:** Step 1a is the answer to the article validation concern.
The GraphBuilderAgent fetches each cited article once to confirm the date is consistent
before calling `event_identifier`. This keeps the validation that `event_identifier`
enforces while giving the agent the information it needs to pass it.

### 1.6 GraphBuilderPipeline

**File:** `src/pipelines/graph_builder/pipeline.py`

Polling-based. Mirrors `EvidencePipeline._process_single_question` pattern.

```python
def _load_pending_questions(self, db):
    # questions where causal_explanation IS NOT NULL AND graph_built = False
    all_questions = db.get_many(Question)
    return [
        q for q in all_questions
        if q.causal_explanation and not q.graph_built
    ]
```

Each question gets a fresh `GraphBuilderAgent`. Exposed as `wr graph-build` CLI.

---

## Phase 2 — Graph Simplification: Alias System + Batch Operations

**Goal:** Remove the UUID-tracking burden from agents. Let them work with semantic
labels; the system handles ID resolution.
**Effort:** ~3–4 weeks. This is the most impactful UX change from v2 §2.1.

### 2.1 Working Memory: Alias Registry

**File:** `src/core/alias_registry.py`

A session-local store mapping semantic aliases to event IDs:

```python
class AliasRegistry:
    def register(self, alias: str, event_id: str) -> None: ...
    def resolve(self, alias: str) -> Optional[str]: ...
    def list_aliases(self) -> Dict[str, str]: ...
```

Aliases are short semantic labels assigned at event creation:
`E1:KhameneiDeath`, `E2:IranStrikes`, `E3:DiplomaticCrisis`

The registry lives in memory for the agent session. It is injected into tools that
need to resolve IDs.

### 2.2 Update `event_identifier` to assign and return aliases

When an event is created or deduplicated, assign an alias `E{n}:{slug}` where `n`
is the creation order and `slug` is a camelCase truncation of the title. Return the
alias in the tool response alongside the ID:

```json
{
  "status": "created",
  "event_id": "evt_abc123",
  "alias": "E1:KhameneiDeath",
  "actual_outcome_event_id": "evt_outcome_0"
}
```

### 2.3 Update `causal_reasoner` to accept aliases

Allow both full IDs and aliases in `source_event_id` / `target_event_id`:

```python
# In forward():
source_id = self.alias_registry.resolve(source_event_id) or source_event_id
target_id = self.alias_registry.resolve(target_event_id) or target_event_id
```

Agents can write:
```
causal_reasoner(source_event_id="E1:KhameneiDeath", target_event_id="E2:Outcome")
```
instead of tracking raw UUIDs across tool calls.

### 2.4 New tool: `propose_subgraph`

**File:** `src/tools/reasoning/propose_subgraph.py`

Batch event + edge creation in a single call. Eliminates the N-call bootstrap problem. 
**Crucially, it leverages `smolagents` `Tool` structured output schemas (via Pydantic models)** instead of parsing JSON strings. This eliminates string-escaping and structural errors natively.

```
Input:
  subgraph: SubgraphModel  — Pydantic model describing events and edges

Schema:
class EventNode(BaseModel):
  alias: str
  title: str
  description: str
  occurred_date: str
  domain: str
  article_ids: List[str]

class CausalEdge(BaseModel):
  source: str
  target: str
  relation: str
  strength: float
  confidence: float
  reasoning: str

class SubgraphModel(BaseModel):
  events: List[EventNode]
  edges: List[CausalEdge]

Behaviour:
  - Validates DAG (no circular references) on the subgraph.
  - Creates each event via EventIdentifierTool logic (deduplication included)
  - Registers aliases
  - Creates each edge via CausalReasonerTool logic (validation included)
  - Returns summary: aliases → IDs, any failures per item

Failure handling:
  - Per-item errors (one bad edge doesn't abort the rest)
  - Returns which items succeeded and which failed with reasons
```

This collapses what currently takes 6–10 tool calls into 1. The GraphBuilderAgent
from Phase 1 can be simplified to use `propose_subgraph` as its primary tool.

### 2.5 Update GraphBuilderAgent prompt to use `propose_subgraph`

Replace the step-by-step event+edge creation in §1.5 with:

```
2. Read the full explanation. Identify all events and relationships.
   Build one subgraph_json covering all events and edges.
   Call propose_subgraph once. Review the response for any per-item failures.
   Retry only the failed items individually.
```

Total tool calls for a typical 5-event graph: ~3 (fetch explanation, propose_subgraph,
graph_inspector) vs the current ~15+.

---

## Phase 3 — Graph Quality: Staging + Audit Pipeline

**Goal:** Prevent bad data from reaching the main DB. Agents write to staging; an
audit step validates before committing. Directly addresses the article validation
concern and v2 §2.4 "Commit Protocol".
**Effort:** ~3 weeks.

### 3.1 Staging tables

Add `events_staging` and `causal_hypotheses_staging` tables (same schema as main
tables, plus `staging_session_id`, `staged_at`, `audit_status`).

`GraphBuilderAgent` (and optionally `causal_analyzer` if still used) writes to
staging by default. `event_identifier` and `causal_reasoner` get a `staging=True`
flag.

### 3.2 Audit pipeline

**File:** `src/pipelines/graph_builder/audit.py`

Runs after `GraphBuilderAgent` completes. Checks the staged subgraph:

| Check | Action on failure |
|---|---|
| All `article_ids` exist in `articles` table | Reject event, log missing IDs |
| No article published before its event's `occurred_date` | Reject event, log date conflict |
| No chronology violations in edges | Reject edge |
| Actual outcome event has at least one incoming edge | Warn (not reject) |
| No duplicate events vs main DB (embedding similarity) | Flag for review |

On pass: copy staging rows to main tables, set `question.graph_built = True`.
On partial failure: commit passing rows, log rejected rows, set
`graph_build_error` on the question.

### 3.3 Retry and debug support

Failed staging sessions are preserved (not deleted). The CLI exposes:

```
wr graph-audit --question-id Q_ID --show-failures
wr graph-build --question-id Q_ID --force   # re-runs even if graph_built=True
```

---

## Phase 4 — Infrastructure: Repository Pattern + Skills

**Goal:** Decouple business logic from the database layer. Replace MCP with an
internal Skills library for agent tool composition.
**Effort:** ~6–8 weeks. Largest phase. Does NOT block phases 0–3.

### 4.1 Repository layer

**File:** `src/data/repositories/`

Thin abstraction over `GenericDatabase`. Does not replace it — adds a typed interface:

```python
class EventRepository:
    def get_by_id(self, event_id: str) -> Optional[Event]: ...
    def save(self, event: Event) -> Event: ...
    def get_for_question(self, question_id: str) -> List[Event]: ...
    def search_similar(self, title: str, domain: Domain) -> List[Event]: ...

class HypothesisRepository:
    def get_for_question(self, question_id: str) -> List[CausalHypothesis]: ...
    def save(self, hyp: CausalHypothesis) -> CausalHypothesis: ...
```

Services (`QuestionService`, `OutcomeEventService`) depend on repositories, not on
`GenericDatabase` directly. Tools depend on services, not repositories.

This also fixes the full-table-scan problem from `improvement_plan.md` §2.1 — the
repository is the right place to put filtered queries.

### 4.2 Skills library

**File:** `src/skills/`

Convert the most-used agent tools into standalone Python functions, callable without
an agent framework. These become the backing implementation for both the CLI and the
MCP tools:

```python
# src/skills/graph_skill.py
def create_event(title, description, domain, occurred_date, article_ids, question_id, db) -> Event: ...
def link_events(source_id, target_id, relation, strength, confidence, reasoning, db) -> CausalHypothesis: ...
def propose_subgraph(subgraph_json, question_id, db) -> SubgraphResult: ...
```

MCP tools become thin wrappers over skills. CLI commands become thin wrappers over
skills. Agent tools (`EventIdentifierTool` etc.) become thin wrappers over skills.
One implementation, three surfaces.

### 4.3 ForecastAgent MCP simplification

Once skills exist, the MCP server's tool handlers are one-liners. The MCP layer stays
(it provides the temporal gateway and knowledge-cutoff enforcement) but the business
logic moves to skills where it is testable without an HTTP server.

---

## Phase 5 — Advanced Capabilities (Future)

These are from v2 Phase 3 and require phases 1–4 to be in place.

### 5.1 Zep-style entity resolution

Background service that merges duplicate event nodes using embedding similarity.
Runs asynchronously after graph commit. Produces merge proposals that require human
confirmation before executing. Resolves the deduplication opacity problem identified
in the earlier analysis.

### 5.2 Proposition extraction for Forecast Agent

```
Input:  "Oil might hit $100 if tensions rise"
Output: Proposition(subject="Oil Price", condition="Tensions rise", target="≥$100", deadline=...)
```

Lets the forecast agent crystallize vague beliefs into trackable graph nodes.

### 5.3 Counterfactual simulation

Graph traversal: disable a node, recalculate probability propagation.
"What if Khamenei had survived?" → re-weight the outcome distribution.

---

## Cross-Phase: Decisions and Constraints

### Article validation (the raised concern)

Handled at two levels:
- **Phase 1 (immediate):** GraphBuilderAgent fetches each cited article with
  `ArticleRetrievalTool` before calling `event_identifier` to confirm the date and
  existence.
- **Phase 3 (systematic):** Audit pipeline validates all article references before
  committing staged rows to the main DB.

### GenericDatabase vs SQLAlchemy

The v2 roadmap assumed SQLAlchemy. The actual codebase uses a custom
`GenericDatabase` with pydantic models. **Do not replace it.** The repository
pattern (Phase 4) adds a typed interface on top without changing the storage layer.

### LangGraph vs smolagents

The v2 roadmap proposes LangGraph for the graph state machine (§2.3). The current
codebase is entirely on smolagents. The validation logic from §2.3 is better
implemented as the audit pipeline (Phase 3) — a deterministic post-hoc check — rather
than a framework switch. This avoids a large dependency change while achieving the
same safety goal.

### MCP stays for forecast

The `ForecastAgent` is MCP-based for good reason: it enforces the temporal gateway
(knowledge cutoff, simulated date) at the HTTP layer. The skills library (Phase 4)
makes the MCP handlers thin without removing the layer.

---

## Phased Delivery Summary

| Phase | What ships | Effort | Unblocks |
|---|---|---|---|
| **0** | Tool UX fixes, DAG cycle checks, DAG modification tools (delete_event, delete_hypothesis), record_outcome_impact, inspector | 2 wks | — |
| **1** | NL pipeline: SaveExplanationTool, simplified HindsightAgent, GraphBuilderAgent, GraphBuilderPipeline | 3–4 wks | Phase 3 |
| **2** | Alias system, propose_subgraph batch tool, GraphBuilderAgent simplified prompt | 3–4 wks | Phase 3 |
| **3** | Staging tables, audit pipeline, wr graph-audit CLI | 3 wks | Phase 5 |
| **4** | Repository layer, Skills library, MCP handler simplification | 6–8 wks | Phase 5 |
| **5** | Entity resolution, proposition extraction, counterfactual simulation | TBD | — |

Phases 0, 1, and 2 are the highest ROI. They address the immediate pain (graph
building difficulty, blocking pipeline) with contained changes to existing files.
Phases 3 and 4 improve quality and maintainability but don't change agent behaviour
visibly. Phase 5 is new capability.
