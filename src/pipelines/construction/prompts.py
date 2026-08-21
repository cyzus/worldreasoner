"""Prompt contracts for bounded benchmark-construction specialists."""

QUESTION_GENERATOR_INSTRUCTIONS = """You construct resolved real-world event
forecasting questions from supplied reporting. Return exactly one concrete
question. Prefer a binary question unless the reporting clearly supports a
different answer format. The outcome must already be objectively resolved, the
resolution date and forecast start must be timezone-aware, and the start must
precede resolution. Use only supplied source IDs in source_article_ids. Do not
invent outcomes, dates, or sources."""

SEARCH_PLANNER_INSTRUCTIONS = """You plan post-resolution research for a resolved
forecasting question. Produce focused web queries that recover the resolution,
major antecedent events, countervailing evidence, and dated reporting. Include
the relevant entities and bounded dates in each query. When market turning
points or lead changes are supplied, include targeted queries around those dates.
Do not answer the question and do not fabricate URLs."""

COVERAGE_ASSESSOR_INSTRUCTIONS = """You assess whether an approved evidence
dossier is sufficient to explain a resolved event. Mark ready only when it
contains source-backed reporting of the outcome and multiple dated developments
that can support a causal or influence chain. Identify concrete missing evidence
needs. The pipeline applies additional deterministic requirements."""

EXPLANATION_INSTRUCTIONS = """You synthesize a hindsight reference explanation
using only the approved evidence dossier. Every material claim must cite one or
more supplied article aliases. Return human-readable sections and an event
candidate inventory. Each event must be a concrete dated occurrence, use an E01
style alias, and include evidence_refs whose article alias and version ID exactly
match the dossier. Candidate events must occur no later than the question's
resolution calendar date; later reporting may support an earlier event but is
not itself a candidate event. Meet the supplied event-count requirement without
inventing, duplicating, or splitting events artificially. Distinguish direct
support from contextual support. Do not claim unique causal truth and do not use
outside knowledge."""

GRAPH_BUILDER_INSTRUCTIONS = """You convert a source-grounded explanation into a
complete directed event graph. Use only the supplied event candidates and
outcome aliases. Every non-outcome node must cite approved article aliases.
Edges represent proposed influence relationships and must form an acyclic path
toward an outcome. Meet the supplied event-count and graph-depth requirements.
Do not create outcome nodes: supplied O aliases may appear only as edge targets
and outcome-impact targets. Every event node must have a directed path to a
supplied outcome marked is_actual_outcome=true. Every event node must have one
event-to-outcome impact record for every supplied outcome scenario. For binary
questions, positive/negative directions must be complementary across YES and NO
outcomes. Edges must respect chronological order and no node may occur after the
question's resolution calendar date. Edge relation must be one of causes,
enables, prevents, inhibits, amplifies, triggers, correlates, or conditional.
Node event_type must be decision, outcome, indicator, milestone, or
external_shock. Include event-to-outcome impacts with direction positive,
negative, neutral, or mixed and calibrated magnitude and confidence. Return the
whole graph in one structured object."""

GRAPH_REPAIR_INSTRUCTIONS = """You repair a rejected graph revision. Use only the
approved evidence, explanation, supplied outcome aliases, and previous_graph in
the request. Return one complete replacement graph that addresses every typed
validation error. Do not emit supplied O aliases as graph nodes. Every event
node must have a directed path to a supplied outcome marked
is_actual_outcome=true. Every event must have one impact record for every supplied
outcome scenario; binary directions must be complementary. Remove nodes after
the resolution calendar date and ensure every edge respects chronological order.
Preserve valid parts of the previous graph while repairing invalid parts. You may
restructure nodes and edges, but may not invent evidence, events, dates, or
outcomes. If evidence cannot support a repair, preserve only supported nodes."""
