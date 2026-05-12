# Event & Graph Annotation Guideline

## 1. Objective

You are helping build a dataset of causal event timelines for real forecasting questions. Each question has already been resolved, and a hindsight system has generated events that may explain why the resolved answer occurred.

Verify the factual correctness and causal validity of those events in the Hindsight Graph. The graph serves as ground truth for evaluating forecasting systems, so its quality must be rigorously validated.

Up to 10 events per question.

### Per-question causal analysis

Before each question, you will see a causal analysis explaining why the resolved outcome may have occurred. Spend 1 minute reviewing that analysis before annotating events. The resolved option and original question are shown as context, but the causal analysis is the main summary to read.

Each forecast question in this study has already been resolved. You are not being asked to predict the answer. You are being asked to check whether the displayed events are valid parts of a hindsight timeline for the resolved question.

For each event:

1. Read the resolved option and original forecast question.
2. Open the source, or acknowledge that no source URL is available.
3. Decide whether the event is valid, invalid, or cannot be verified.
4. If the event is valid, choose whether it should move probability towards the resolved option, away from the resolved option, or have no meaningful impact.

The event card is what you are validating. Do not reject an event just because the forecast question is already resolved; all questions shown here are already resolved by design.

---

## 2. What You See Per Event

Each event card shows:

- **Date** — color-coded blue if within the Polymarket market window, gray if before it opened
- **In Market Window / Pre-Market badge** — quick visual indicator
- **Title & Description** — the event as extracted by the Hindsight Agent
- **Source** — link to the original article (if available)
- **Resolved option** — the actual answer for the already-resolved forecast question. This is shown before the question text.
- **Your Expected Impact** — after approving an event, judge whether it should move probability towards the resolved option, away from the resolved option, or not meaningfully at all.

The sidebar also shows the **market window** (open → close date) and a link to the Polymarket market for in-context verification.

Before annotating events for a question, review the causal analysis for at least 1 minute. Events are then shown one at a time. For each event, first open the source or acknowledge that no source URL is available. Only then will the event-validity decision appear. If the event is valid, the expected-impact section appears under the event.

### Quick tutorial

1. Start with the causal analysis, resolved option, and question. This tells you what actually happened and why the timeline claims it happened.
2. Read the event card. Treat the title, date, and description as the claim to verify.
3. Check the source. If the source is missing, broken, weak, or paywalled, do a brief web search.
4. Choose **Event is valid** only when the event happened, the date/source are acceptable, and the event is specific enough to evaluate.
5. Choose an invalid-event reason when the event is false, dated incorrectly, unsupported by the source, speculative, irrelevant, duplicated, or too broad.
6. Use **Cannot verify** only as a last resort after checking the source and doing a brief search.
7. If the event is valid, choose the expected impact relative to the resolved option.

---

## 3. Decision Framework

For every event, follow this order:

1. Open the source, or acknowledge that no source URL is available.
2. Decide whether the event is valid using the source. Use **Event is valid**, **Event is invalid**, or **Cannot verify**.
3. If the event is valid, choose the expected impact direction. Optional reasoning can be added, but it is not required.

### Step 1 — Event Validity (required for all events)

Ask: *Is this specific event card valid, based on the source and event details?*

This step is **not** asking whether the forecast question resolved correctly. The questions shown here are already resolved. This step asks whether the displayed event is real, specific, dated correctly, supported by the source, and relevant enough to evaluate. Only after an event is valid do you judge its impact on the resolved option.

For every rejection, add a short evidence note in the inline form. One concise
sentence is enough. For factual/source problems, also enter the corrected date
or a better source URL if you know one. This keeps approval and rejection effort
balanced and helps distinguish a truly fabricated event from a real event with
a bad link, wrong date, weak causal connection, duplicate coverage, or overly
broad framing.

| Decision | Condition |
|---|---|
| **Event is valid** | The event happened, the source/date are acceptable, and the event is specific enough to evaluate |
| **Invalid event: Fabricated Event** | The event itself appears not to have happened |
| **Invalid event: Wrong Date** | The event is real, but the displayed date is materially wrong |
| **Invalid event: Source Mismatch** | The event may be real, but the linked source does not support this title/description |
| **Invalid event: Prediction / Opinion** | The source is only predicting, speculating, or commenting — not reporting a confirmed occurrence |
| **Invalid event: Noise** | Event is real but has no meaningful causal connection to the forecast outcome |
| **Invalid event: Duplicate** | Same occurrence already captured by another event — keep the one with richer detail |
| **Invalid event: Too Broad** | Describes a multi-month trend or category of events rather than a single, atomic occurrence |
| **Cannot verify** | Last resort only: cannot verify after checking the source and doing a brief search |

### Step 2 — Expected Impact Direction (required after approving any event)

Ask: *Based on the event and source, how should this event affect the probability of the resolved option?*

| Assessment | Condition |
|---|---|
| **Towards option** | The event should move probability toward the resolved option. |
| **Away from option** | The event should move probability away from the resolved option. |
| **No meaningful impact** | The event is valid but should not meaningfully move the outcome probability. |

Validity notes and expected-impact reasoning are optional. Invalid-event and cannot-verify notes remain required so factual, source, date, and unverifiable cases can be audited later.

---

## 4. Using the Market Window as Context

### What "in market window" means
The market window is the period when Polymarket was actively tracking this question. Events are tagged "In Market Window" if their date falls between the market open and `resolution_date`.

- **Market open date**: shown when available (about 1/3 of questions). When absent, an estimated open date is shown — treat it as approximate.
- **Market close date**: always available (`resolution_date`).

### How to use it
Use the market window only as date context. Events inside the market window are usually the most relevant to the forecasting setup, while events before the market opened may still matter if they have a clear causal link to the resolved question.

For events **before the market opened**, judge the causal logic on its own merits.

For **non-Polymarket questions** (no market window shown), assess impact validity based on the event, source, resolved option, and general causal reasoning.

---

## 5. Annotation Criteria in Detail

### Factual Correctness and Source Quality
- The source article should confirm the event actually occurred.
- **Web Search is Encouraged**: If the source link is broken, missing, weak, or behind a paywall, please perform a quick web search using the event title and date to verify if it happened.
- Dates should match the article's publication date or the event date reported within it.
- If the event is real but the date is wrong, reject as **Wrong Date** and enter the corrected date if available.
- If the event is real but the linked URL does not support it, reject as **Source Mismatch** and enter a better URL if available.
- If the article or your search shows only a *prediction*, *commentary*, *hypothetical*, betting preview, or analyst opinion, reject as **Prediction / Opinion**.
- Opinion-related news is not automatically invalid. If the source merely comments on what might happen, mark **Prediction / Opinion**. If the source reports that a specific actor publicly said, released, announced, ruled, voted, filed, or published something, that can be a valid event if it is dated, sourced, and causally relevant.
- Use **Fabricated Event** only when the event itself appears false or you cannot find evidence that it happened after a reasonable check.
- Use **Cannot verify** sparingly. A broken link, paywall, weak source, or ambiguous date is usually not enough by itself to mark cannot-verify. If you can determine the event is false, source-mismatched, date-mismatched, irrelevant, duplicated, or too broad, use the corresponding invalid-event label instead.

### Impact Validity
- The event must have a plausible mechanism directly connecting it to the forecast question's outcome.
- Pure background/context events (e.g., "a facility was built in 2014") are not causally proximate unless the question directly depends on that specific historical fact.
- Intermediate causes are valid as long as the causal chain to the outcome is clear and traceable.

### Granularity
- The event must describe a **single, specific occurrence** with an identifiable date.
- Mark **Invalid event: Too Broad** if it summarizes an ongoing process (e.g., "AI developed rapidly throughout 2023") rather than a discrete action (e.g., "OpenAI released GPT-4 on March 14, 2023").

---

## 6. Priority for Your Attention

Events are pre-sorted by importance. Spend the most effort on:

1. **Valid events inside the market window** — these are the most verifiable and the most consequential for evaluation quality
2. **Valid events outside the window** — impact can still be judged on causal logic
3. **Events marked invalid or cannot-verify** — do not mark expected impact

---

## 7. Edge Cases

| Situation | Guidance |
|---|---|
| Two events describe the same news | Mark the one with more specific date/detail as **Event is valid**; mark the other as **Invalid event: Duplicate** |
| Event date is years before the question's market window | Almost always background context — mark **Invalid event: Noise** unless the question outcome explicitly depends on that specific historical event |
| Source link is broken or missing | **Perform a quick web search** using the event details. If you find a better source, use **Event is valid** if the event is relevant or **Invalid event: Source Mismatch** if the original URL is misleading. Only use cannot-verify if it remains completely unverifiable after a brief search. |
| Source is paywalled | Search for another source or article title first. Use **Invalid event: Source Mismatch** if the visible article metadata does not support the event; use **Cannot verify** only if no verification is possible. |
| Event is true but the source only supports part of it | Mark **Invalid event: Source Mismatch** if the unsupported part is central; otherwise use **Event is valid** and provide the better source URL. |
| Source is an opinion or analysis article | Mark **Prediction / Opinion** if the card is only a forecast or commentary. But if the article reports a concrete statement, filing, vote, ruling, poll release, or official announcement, judge that reported occurrence as the event. |
| Market open date shown as "estimated" | Treat the market window boundary as approximate ±2 weeks; don't reject events solely for falling slightly outside an estimated boundary |
