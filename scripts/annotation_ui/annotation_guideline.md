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
- **Impact Analysis** — the AI's assessment of how this event affected the forecast outcome, showing direction (positive/negative/neutral/mixed) and reasoning. Some events have no impact analysis; the box will be muted in that case.
- **👍 / 👎 Reasoning Assessment buttons** — only visible when impact analysis is present

The sidebar also shows the **market window** (open → close date) and a link to the Polymarket market for in-context verification.

---

## 3. Decision Framework

For every event, make **two assessments** (in order):

### Step 1 — Event Validity (required for all events)

Ask: *Is this event real, specific, and causally relevant?*

| Decision | Condition |
|---|---|
| **Approve** | Event happened, dates are accurate, and it has a logical causal link to the forecast outcome |
| **Reject: Hallucination** | The agent fabricated the event, misrepresented dates, or confused a prediction/opinion article with a confirmed occurrence |
| **Reject: Noise** | Event is real but has no meaningful causal connection to the forecast outcome |
| **Reject: Duplicate** | Same occurrence already captured by another event — keep the one with richer detail |
| **Reject: Too Broad** | Describes a multi-month trend or category of events rather than a single, atomic occurrence |
| **Skip** | Cannot verify with available source material |

### Step 2 — Reasoning Quality (only when Impact Analysis is shown)

Ask: *Is the AI's impact analysis correct?*

| Assessment | Condition |
|---|---|
| 👍 **Accurate Reasoning** | The direction and causal chain correctly explain this event's role in the outcome |
| 👎 **Flawed Reasoning** | The AI's impact logic is wrong, reversed, or overstated — even if the event itself is real |

---

## 4. Using the Market Window as Evidence

### What "in market window" means
The market window is the period when Polymarket was actively tracking this question. Events are tagged "In Market Window" if their date falls between the market open and `resolution_date`.

- **Market open date**: shown when available (about 1/3 of questions). When absent, an estimated open date is shown — treat it as approximate.
- **Market close date**: always available (`resolution_date`).

### How to use it
For events **within the market window**, the UI shows a mini price chart (pre-fetched from Polymarket). Use it to verify the AI's claimed impact direction:

- A claimed **Towards outcome** impact (makes Yes more likely) should correspond to a **price increase** around that event date.
- A claimed **Against outcome** impact (makes Yes less likely) should correspond to a **price decrease**.
- If the claimed direction contradicts the price movement, mark reasoning as 👎 **Flawed**.
- If price barely moved, the impact may be **overstated** — mark reasoning as 👎 **Flawed** if magnitude is claimed to be high.

For events **before the market opened**, the chart will not cover that date. Judge the causal logic on its own merits.

For **non-Polymarket questions** (no market window or chart shown), assess impact validity based on general causal reasoning alone.

---

## 5. Annotation Criteria in Detail

### Factual Correctness
- The source article must confirm the event actually occurred.
- **Web Search is Encouraged**: If the source link is broken, missing, or behind a paywall, please perform a quick web search using the event title and date to verify if it happened.
- Dates should match the article's publication date or the event date reported within it.
- **Reject as Hallucination** if the article (or your web search) reveals it is about a *prediction*, *commentary*, or *hypothetical* — not a confirmed real-world occurrence.

### Impact Validity
- The event must have a plausible mechanism directly connecting it to the forecast question's outcome.
- Pure background/context events (e.g., "a facility was built in 2014") are not causally proximate unless the question directly depends on that specific historical fact.
- Intermediate causes are valid as long as the causal chain to the outcome is clear and traceable.

### Granularity
- The event must describe a **single, specific occurrence** with an identifiable date.
- **Reject as Too Broad** if it summarizes an ongoing process (e.g., "AI developed rapidly throughout 2023") rather than a discrete action (e.g., "OpenAI released GPT-4 on March 14, 2023").

---

## 6. Priority for Your Attention

Events are pre-sorted by importance. Spend the most effort on:

1. **Events with impact analysis that are inside the market window** — these are the most verifiable and the most consequential for evaluation quality
2. **Events with impact analysis outside the window** — impact can still be judged on causal logic
3. **Events without impact analysis** — assess validity only; skip the reasoning step entirely

---

## 7. Edge Cases

| Situation | Guidance |
|---|---|
| Event has no impact analysis | Assess validity only; do not mark reasoning |
| Two events describe the same news | Approve the one with more specific date/detail; Reject the other as **Duplicate** |
| Event date is years before the question's market window | Almost always background context — Reject as **Noise** unless the question outcome explicitly depends on that specific historical event |
| Source link is broken or missing | **Perform a quick web search** using the event details. Only skip if it remains completely unverifiable after a brief search. |
| Impact direction seems right but reasoning explanation is weak or superficial | Approve the event; mark reasoning as 👎 **Flawed** |
| Market open date shown as "estimated" | Treat the market window boundary as approximate ±2 weeks; don't reject events solely for falling slightly outside an estimated boundary |
