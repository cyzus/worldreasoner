# Event & Graph Annotation Guideline

## 1. Objective

Verify the factual correctness and causal validity of events in the Hindsight Graph. The graph serves as ground truth for evaluating LLM forecasting — its quality must be rigorously validated.

Up to 10 events per question.

---

## 2. What You See Per Event

Each event card shows:

- **Date** — color-coded blue if within the Polymarket market window, gray if before it opened
- **In Market Window / Pre-Market badge** — quick visual indicator
- **Title & Description** — the event as extracted by the Hindsight Agent
- **Source** — link to the original article (if available)
- **Final outcome** — the actual resolved answer for the question. This is shown in the sidebar and again in the expected-impact section.
- **Your Expected Impact** — after approving an event, judge whether it should move probability towards the final resolved outcome, away from the final resolved outcome, or not meaningfully at all. The AI's impact analysis is hidden behind an expandable section and should not be treated as the answer.

The sidebar also shows the **market window** (open → close date) and a link to the Polymarket market for in-context verification.

Before annotating events for a question, review the hindsight explanation popup for at least 20 seconds. Events are then shown one at a time. For each event, first open the source or acknowledge that no source URL is available. Only then will the event-validity decision appear. If the event is valid, the expected-impact section appears under the event.

---

## 3. Decision Framework

For every event, follow this order:

1. Open the source, or acknowledge that no source URL is available.
2. Decide whether the event is valid using the source. Use **Event is valid**, **Event is invalid**, or **Cannot verify**.
3. If the event is valid, choose the expected impact direction. Optional reasoning can be added, but it is not required.

### Step 1 — Event Validity (required for all events)

Ask: *Is this specific event card valid, based on the source and event details?*

This step is **not** asking whether the forecast question resolved correctly. It is asking whether the displayed event is real, specific, dated correctly, supported by the source, and relevant enough to evaluate. Only after an event is valid do you judge its impact on the final outcome.

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

Ask: *Based on the event and source, how should this event affect the probability of the final resolved outcome?*

| Assessment | Condition |
|---|---|
| **Towards final outcome** | The event should move probability toward the final resolved outcome. |
| **Away from final outcome** | The event should move probability away from the final resolved outcome. |
| **No meaningful impact** | The event is valid but should not meaningfully move the outcome probability. |

Validity notes and expected-impact reasoning are optional. Invalid-event and cannot-verify notes remain required so factual, source, date, and unverifiable cases can be audited later.

---

## 4. Using the Market Window as Evidence

### What "in market window" means
The market window is the period when Polymarket was actively tracking this question. Events are tagged "In Market Window" if their date falls between the market open and `resolution_date`.

- **Market open date**: shown when available (about 1/3 of questions). When absent, an estimated open date is shown — treat it as approximate.
- **Market close date**: always available (`resolution_date`).

### How to use it
For events **within the market window**, the UI provides a collapsed mini price chart under **Market movement**. Use it only as supporting context when judging your expected impact direction:

- If the event coincides with movement toward the final outcome, **Towards final outcome** may be appropriate.
- If the event coincides with movement away from the final outcome, **Away from final outcome** may be appropriate.
- If price barely moved or the event is only background context, **No meaningful impact** may be appropriate.

Do not treat the price chart as the answer. Market movement may reflect several simultaneous signals, liquidity, or trader expectations unrelated to the specific event being annotated. The event source and final outcome should remain the primary evidence.

For events **before the market opened**, the chart will not cover that date. Judge the causal logic on its own merits.

For **non-Polymarket questions** (no market window or chart shown), assess impact validity based on general causal reasoning alone.

---

## 5. Annotation Criteria in Detail

### Factual Correctness and Source Quality
- The source article should confirm the event actually occurred.
- **Web Search is Encouraged**: If the source link is broken, missing, weak, or behind a paywall, please perform a quick web search using the event title and date to verify if it happened.
- Dates should match the article's publication date or the event date reported within it.
- If the event is real but the date is wrong, reject as **Wrong Date** and enter the corrected date if available.
- If the event is real but the linked URL does not support it, reject as **Source Mismatch** and enter a better URL if available.
- If the article or your search shows only a *prediction*, *commentary*, *hypothetical*, betting preview, or analyst opinion, reject as **Prediction / Opinion**.
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
| Valid event has no AI impact analysis | Still choose your own expected impact direction; use the event, source, final outcome, and market movement if available |
| Two events describe the same news | Mark the one with more specific date/detail as **Event is valid**; mark the other as **Invalid event: Duplicate** |
| Event date is years before the question's market window | Almost always background context — mark **Invalid event: Noise** unless the question outcome explicitly depends on that specific historical event |
| Source link is broken or missing | **Perform a quick web search** using the event details. If you find a better source, use **Event is valid** if the event is relevant or **Invalid event: Source Mismatch** if the original URL is misleading. Only use cannot-verify if it remains completely unverifiable after a brief search. |
| Source is paywalled | Search for another source or article title first. Use **Invalid event: Source Mismatch** if the visible article metadata does not support the event; use **Cannot verify** only if no verification is possible. |
| Event is true but the source only supports part of it | Mark **Invalid event: Source Mismatch** if the unsupported part is central; otherwise use **Event is valid** and provide the better source URL. |
| Event is true but the AI's causal explanation is overstated | Mark the event as valid if relevant, then choose your own expected impact direction. Do not mark a real relevant event as invalid solely because the AI's reasoning is weak. |
| Market open date shown as "estimated" | Treat the market window boundary as approximate ±2 weeks; don't reject events solely for falling slightly outside an estimated boundary |
