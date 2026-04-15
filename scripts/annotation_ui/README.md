# Hindsight Graph Annotation UI

Welcome to the Hindsight Causal Graph Annotation Tool. This tool is designed to review, verify, and filter timeline events used to build causal graphs.

## 🎯 Introduction

When constructing high-quality causal graph datasets, Large Language Models (LLMs) may generate events that contain hallucinations, redundancies, or irrelevant noise. As an expert annotator, your core objective is:
**To audit the generated timeline and ensure that every retained event is historically authentic and has a clear causal impact on the final outcome.**

The left panel provides the **Background**, **Outcome**, and **Resolution Criteria** for each question. Always use these as your reference ground truth when evaluating the events on the right timeline.

---

## 📋 Annotation Criteria & Decisions

For each event on the right timeline, you must make one of the following decisions:

### 1. ✅ Approve
Click "Approve" when the event meets **ALL** of the following conditions:
- **Authenticity**: The event actually occurred in reality, and the date is correct.
- **Causal Relevance**: The event has a substantial impact on or drives the narrative toward the listed Outcome.
- **Indispensable**: If this event were removed, the causal chain of the story would be broken or incomplete.

### 2. ❌ Reject
If the event is flawed, click "Reject" and select a specific reason:
- **Hallucination**: The event never happened, or the LLM fabricated fake news, incorrect dates, or mismatched entities.
- **Noise**: The event is authentic but trivial. It provides no causal drive toward the final Outcome (e.g., the CEO ate a hamburger the day before the company went bankrupt).
- **Duplicate**: The event expresses the exact same information as another event on the timeline, causing unnecessary redundancy.
- **Flawed Causal Impact**: The event is real, but the LLM's explanation of its impact (the causal link) is forced, nonsensical, or logically flawed, and cannot be easily corrected.

### 3. ⏭️ Skip
- Use this if you are unsure how to judge the event or need to consult additional sources/team members. Skipped events will remain marked as `skipped` in the final export.

---

## 💡 UI Features

- **Impact Editing**: If an event is valid but its Impact Analysis is slightly off, you can click the `✏️ Edit` button next to the impact text. Modify the reasoning directly and click Save. This directly improves the quality of the dataset.
- **Progress Indicators**: Click the dropdown in the top-left navigation bar to see the completion status of all questions at a glance:
  - 🟢 **Green Dot**: All events for this question are annotated.
  - 🟠 **Yellow Dot**: Annotation is in progress (partially completed).
  - ⚪ **Grey Dot**: Not started yet.
- **Fast Navigation**: Jump between questions instantly using the dropdown menu. Your progress is kept safe in your browser's memory.
- **One-Click Export**: Once all events are annotated, the top-right counter will max out, and the button will glow and change to **✨ Download Final Results**. Click it to download your `annotation_results.json` deliverable.

---

## 🚀 How to Run

1. Ensure your data has been exported as `annotation_data.js` via the Python prep script and placed in the same directory.
2. Simply double-click `index.html` to open it in any modern web browser. (No local server configuration is required; it runs entirely client-side, ensuring data privacy).
3. Complete your annotations and click the Export button to save the JSON file, then return it to the data processing pipeline.