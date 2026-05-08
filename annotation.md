# WorldReasoner Benchmark and Annotation Plan

## 1. Purpose

WorldReasoner has two related but distinct evaluation tracks:

1. **Forecasting benchmark**: measures whether different model/tool conditions make better forecasts.
2. **Graph annotation**: provides a human gold standard for evaluating whether the evidence graph and graph-based forecast reasoning are factually and causally reliable.

The annotation is not the primary outcome-scoring mechanism for `auto_benchmark.py`. The benchmark evaluates final forecasts against resolved ground truth using accuracy, Brier score, and log score. Annotation instead provides a human reference standard for the *quality of the evidence and reasoning behind forecasts*: it tells us whether the graph events are real, source-supported, temporally accurate, causally relevant, and whether the impact reasoning is valid.

This distinction matters because forecast quality has two layers:

1. **Outcome quality**: Did the model assign probability to the correct resolved answer? This is measured by benchmark metrics such as accuracy, Brier score, and log score.
2. **Reasoning and evidence quality**: Did the model rely on valid events, sources, dates, and causal explanations? This is measured by human annotation.

Thus, annotation provides a gold standard for judging the reliability of graph-based forecast explanations and for interpreting why a forecast condition performs well or poorly.

In short:

> `auto_benchmark.py` asks whether WorldReasoner improves forecasting performance.  
> Annotation asks whether the causal graphs and evidence used to support and evaluate those forecasts are actually valid.

---

## 2. Question Pipeline

Each benchmark question contains:

- Question text.
- Start date or market open date, when available.
- Resolution date.
- Resolved outcome / ground truth.
- Source, such as Polymarket or news-derived questions.
- Domain and question type.

Questions are included in the benchmark only if they are resolved, have built graphs, and satisfy the evidence availability checks used by the frontend and benchmark pipeline.

---

## 3. Evidence and Hindsight Graph Pipeline

For each resolved question, the hindsight pipeline constructs an evidence graph using post-resolution information.

Each question may include:

- Related source articles.
- Event graph.
- Causal analysis / explanation.
- Price history and turning points for Polymarket questions.

Each graph event contains:

- Event date.
- Title and description.
- Source URL or article ID.
- Impact analysis.
- Causal relation to the forecast outcome or to other events.

The hindsight graph is intended to serve as a reference graph, but `graph_built = true` does not guarantee that all events are correct. This is why annotation is needed.

---

## 4. Annotation Task

Annotators review events in the hindsight graph and judge whether each event is valid, specific, source-supported, and causally relevant.

For each event, annotators record:

- Event validity status: approved, rejected, or skipped.
- Rejection reason, if rejected.
- Corrected date, if the displayed date is wrong.
- Corrected or better source URL, if available.
- A short evidence note for approvals, rejections, and skips.
- Impact reasoning quality when an impact analysis is shown.

The current annotation schema separates event validity from reasoning quality. A real and relevant event should be approved even if the model's causal explanation is flawed; the impact reasoning should then be marked as flawed.

The output of this task is a human-labeled reference set of accepted and rejected graph events. This reference set can be used as a gold standard for evaluating graph quality, calibrating automated graph metrics, and interpreting forecast results.

---

## 5. Annotation Labels

The original pilot used a broad `Hallucination` label. This proved too coarse because annotators used it for several different failure modes. The revised annotation UI now uses more specific labels.

### Approval

| Label | Meaning |
|---|---|
| `approved` | The event happened, the source/date are acceptable, and it has a plausible causal link to the forecast outcome. |

### Rejection

| Label | Meaning |
|---|---|
| `Fabricated` | The event itself appears not to have happened. |
| `WrongDate` | The event is real, but the displayed date is materially wrong. |
| `SourceMismatch` | The event may be real, but the linked source does not support the event title or description. |
| `PredictionNotEvent` | The source is a prediction, opinion, hypothetical, or betting preview rather than confirmation of a real event. |
| `Noise` | The event is real but has no meaningful causal connection to the forecast outcome. |
| `Duplicate` | The same occurrence is already captured by another event. |
| `TooBoard` | The item describes a broad trend or period rather than a specific atomic event. |

### Skip

| Label | Meaning |
|---|---|
| `Unverifiable` | Last resort only: the annotator cannot verify the event after checking the source and doing a brief search. |

Skip is intentionally narrow. Broken links, paywalls, ambiguous dates, weak sources, or source mismatch should usually be handled through the appropriate approval or rejection label rather than skipped.

---

## 6. Pilot Findings

The first pilot contains:

- 5 completed annotation sessions.
- 20 annotated questions.
- 199 non-attention-check event annotations.
- 10 / 10 attention checks passed.

Aggregate event outcomes:

| Status | Count |
|---|---:|
| Approved | 99 |
| Rejected | 97 |
| Skipped | 3 |

The main pilot finding is that the old `Hallucination` label was not reliable as a direct estimate of hallucination rate. Manual inspection showed that many events marked as `Hallucination` were actually:

- Real events with wrong dates.
- Real events with weak or mismatched sources.
- Prediction or commentary articles treated as confirmed events.
- Real and relevant events with overstated causal reasoning.

Therefore, the pilot should be treated as a workflow and schema validation step, not as final graph-quality evidence.

---

## 7. Why Annotation Matters for Benchmarking

The full auto benchmark can tell us whether graph-enabled conditions improve forecasting performance. It cannot by itself tell us whether the graph evidence was correct or whether a forecast was supported by valid reasoning.

Annotation helps answer several questions that the forecast benchmark alone cannot:

1. **Input quality**: Are the hindsight graph events factually correct and source-supported?
2. **Causal relevance**: Are the events actually relevant to the forecast outcome?
3. **Reasoning quality**: Does the graph's impact analysis correctly explain the event's role?
4. **Interpretability**: If graph-enabled agents perform better or worse, is that related to graph quality?
5. **Dataset cleaning**: Which events should be corrected, removed, or relabeled?

This is especially important when interpreting conditions such as:

- `structured_scenario`
- `search_enabled`
- `worldreasoner`
- `oracle`

If graph-based conditions outperform vanilla models, annotation can support the claim that high-quality causal evidence helped. If graph-based conditions underperform, annotation can help diagnose whether noisy or misleading graph evidence was responsible.

In this sense, annotation is the human gold standard for the *explanatory and evidential quality* of graph-based forecasts. It allows us to distinguish between:

- A forecast that is correct for the right reasons.
- A forecast that is correct but supported by noisy or invalid graph evidence.
- A forecast that is wrong despite high-quality evidence.
- A forecast that is wrong partly because the graph evidence was flawed.

---

## 8. Linking Annotation to `auto_benchmark.py`

`auto_benchmark.py` currently evaluates:

- Accuracy.
- Brier score.
- Log score.
- Performance by condition, model, and question.

Annotation should be joined to benchmark results at the question level and event level.

Useful derived annotation metrics include:

| Metric | Definition |
|---|---|
| `graph_acceptance_rate` | Approved events / total annotated events. |
| `factual_error_rate` | Fabricated + WrongDate + SourceMismatch + PredictionNotEvent events / total annotated events. |
| `noise_rate` | Noise events / total annotated events. |
| `duplicate_rate` | Duplicate events / total annotated events. |
| `too_broad_rate` | TooBoard events / total annotated events. |
| `reasoning_flaw_rate` | Flawed impact reasoning annotations / total impact reasoning annotations. |
| `skip_rate` | Unverifiable events / total annotated events. |

These metrics can be merged with benchmark output:

| Field | Source |
|---|---|
| `question_id` | Benchmark + annotation |
| `condition` | Benchmark |
| `model` | Benchmark |
| `accuracy` | Benchmark |
| `brier_score` | Benchmark |
| `log_score` | Benchmark |
| `graph_acceptance_rate` | Annotation |
| `factual_error_rate` | Annotation |
| `reasoning_flaw_rate` | Annotation |

This enables analysis such as:

- Does WorldReasoner improve more on questions with high-quality graphs?
- Do noisy graphs reduce the benefit of causal tools?
- Are forecast errors correlated with source mismatch or flawed causal reasoning?
- Is oracle performance bounded by graph quality?

This merged analysis is the main bridge between annotation and forecast quality. Benchmark metrics provide the final outcome score; annotation-derived metrics provide the gold-standard explanation of whether the supporting graph evidence was valid.

---

## 9. Graph Evaluation Use Cases

Annotation also supports graph-level evaluation beyond final forecast accuracy.

Possible graph evaluation metrics:

- Event recall and precision.
- Causal direction alignment.
- Source alignment.
- Key event identification.
- Price impact alignment for Polymarket questions.

The full hindsight graph can be used as the main reference target, while human annotations calibrate whether that reference graph is reliable.

For annotated questions, approved events can serve as a cleaner reference subset. For unannotated questions, the full hindsight graph remains the scalable reference, but annotation-derived quality checks should be reported as calibration evidence.

---

## 10. Overlap Annotation

Overlap sessions are used to estimate inter-rater agreement.

Current design:

- Main sessions: `s01` to `s27`.
- Overlap sessions: `ov01` to `ov03`.
- Each overlap session contains 4 questions.
- Each overlap session should be completed by multiple annotators, currently 3 replicates.

Overlap annotations allow us to compute:

- Agreement on event validity.
- Agreement on rejection reasons.
- Agreement on impact reasoning quality.
- Cohen's kappa or simpler percent agreement.

The current overlap set should preferably contain Polymarket questions if the goal is to calibrate graph quality against market movement and price-impact metrics.

---

## 11. Practical Outputs from Annotation

The annotation pipeline should produce at least three structured tables:

### Event-Level Cleaning Candidates

Fields:

- `question_id`
- `event_id`
- `status`
- `reject_reason`
- `reasoning_status`
- `corrected_date`
- `corrected_url`
- `annotator_note`

Use:

- Clean or remove bad graph events.
- Identify systematic graph construction errors.
- Build a higher-quality graph subset.

### Annotator Summary

Fields:

- `session_id`
- `approve_rate`
- `reject_rate`
- `skip_rate`
- `reject_reason_distribution`
- `reasoning_completion_rate`
- `attention_check_pass_rate`

Use:

- Detect annotator strictness differences.
- Identify potentially unreliable annotation sessions.
- Improve instructions and calibration examples.

### Question Summary

Fields:

- `question_id`
- `approved_events`
- `rejected_events`
- `skipped_events`
- `graph_acceptance_rate`
- `dominant_reject_reason`
- `reasoning_flaw_rate`

Use:

- Merge graph quality with benchmark outcomes.
- Stratify benchmark results by graph quality.
- Select clean subsets for paper analysis.

---

## 12. Recommended Next Steps

1. Continue running the full `auto_benchmark.py` benchmark.
2. Collect annotation data using the revised annotation UI.
3. Run overlap annotation to estimate inter-rater agreement.
4. Export event-level, annotator-level, and question-level annotation summaries.
5. Merge annotation-derived graph-quality metrics with benchmark results.
6. Report benchmark results both overall and stratified by graph quality.
7. Use annotation errors to improve graph construction, source alignment, date extraction, and causal event granularity.
