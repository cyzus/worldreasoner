# WorldReasoner Hosted Platform Roadmap

## Objective

Build a hosted platform with three deliberately separated surfaces:

1. **Research Console** - private administration for question construction,
   evidence review, dataset releases, and evaluation jobs.
2. **Annotation Service** - anonymous, study-specific interfaces compatible with
   recruitment platforms such as Prolific.
3. **Benchmark Portal** - public question browsing, temporally controlled agent
   submissions, reproducible scoring, and versioned leaderboards.

The first implementation should remain a modular monolith: one FastAPI codebase,
one React application, shared domain schemas, PostgreSQL, object storage, and a
background worker. Separate deployments or microservices are unnecessary until
load or ownership boundaries justify them.

## Existing Foundations

WorldReasoner already provides:

- FastAPI and React/Vite applications;
- question collection and review interfaces;
- forecast, graph, evaluation, and benchmark models;
- a Temporal Gateway and MCP forecasting interface;
- versioned construction artifacts and validation services;
- local HTML annotation packets with stable item identifiers.

The current application is a trusted local research console. It exposes database
selection, local paths, mutation endpoints, and process controls, so it must not
be placed directly on the public internet.

## Target Architecture

```text
                         +----------------------+
 Prolific participant -> | Annotation Web/API   |
                         +----------+-----------+
                                    |
 Public user/agent ----> +----------v-----------+
                         | Public Portal/API     |
                         +----------+-----------+
                                    |
 Researcher -----------> +----------v-----------+
                         | Private Admin/API     |
                         +----------+-----------+
                                    |
             +----------------------+----------------------+
             | PostgreSQL | Object storage | Job queue     |
             +----------------------+----------------------+
                                    |
                         +----------v-----------+
                         | Construction and     |
                         | Evaluation Workers   |
                         +----------------------+
```

Use PostgreSQL for users, studies, assignments, questions, releases, runs, and
scores. Store article snapshots, cleaned Markdown, graph artifacts, and exported
dataset releases in versioned object storage. SQLite files may remain a portable
release format, but should not be the mutable production database.

## Annotation Service

### Task Contract and Interface

The canonical object of judgment is the **full event claim** (`event_description`).
The short event title is a secondary label and is not judged independently. Each
item should ask one repeated question:

> Does the cited article support the full event claim shown above?

Make **Event claim to validate** the most prominent text in the item. Label the
article panel **Cited article evidence** and explain once that this is the article
the hindsight graph cites as support for the event. Keep the question visible
above the response controls. The support, date, and entity judgments then refine
the answer into full, partial, unsupported, contradictory, date-valid, and
entity-valid decisions.

### Study Flow

1. **Introduction:** purpose, consent, expected duration, data use, withdrawal,
   and the distinction between the event claim and cited article.
2. **Tutorial:** one guided example with feedback showing how to judge the full
   claim, qualifiers, occurrence date, and entities.
3. **Comprehension check:** task-critical multiple-choice questions shown beside
   the instructions, with two attempts before asking the participant to return
   the study.
4. **Annotation:** autosaved event-source items with progress, resume, keyboard
   navigation, and server-side completeness checks.
5. **Completion:** freeze the submission transactionally, then redirect to
   Prolific or display the configured completion code.

### Prolific and Quality Controls

Accept `PROLIFIC_PID`, `STUDY_ID`, and `SESSION_ID` from the study URL. Show a
**Prolific ID** field prefilled and read-only so participants can verify it;
manual entry is only a fallback for preview/testing. Enforce one assignment per
participant and study, pseudonymize identifiers for analysis, and collect no
names or email addresses.

For a study longer than five minutes, include at least two clear
Prolific-compliant attention checks. They must not depend on prior knowledge,
memory, hidden text, completion speed, or ambiguous event interpretation. Keep
attention checks and tutorial comprehension checks separate from the 50-item
reliability sample and report their results separately from inter-annotator
agreement. Pilot all checks before using them for exclusion.

Persist immutable study/item versions, append-only response revisions, signed
assignment sessions, packet checksums, audit events, and a separate adjudication
record. API authorization must enforce blinding from model decisions and the
other annotator's labels.

### Annotation MVP Acceptance Test

Import the existing 50-pair overlap packet and test exact item parity,
introduction/tutorial completion, Prolific ID capture, interruption/resume,
duplicate-session rejection, attention checks, export parity, completion
redirect, and blinding. Complete a small paid Prolific pilot before launching the
formal reliability study.

## Benchmark Portal

### Public Dataset Catalog

Provide stable pages and APIs for benchmark releases, question metadata,
resolution state, answer type, domain, forecast window, and evaluation policy.
Every result must name an immutable `benchmark_version`; published questions and
evidence snapshots must never be edited in place.

### Question Update Workflow

Use an explicit lifecycle:

```text
candidate -> construction -> automated validation -> human review
          -> release candidate -> published -> resolved -> evaluated
```

Construction and validation run asynchronously. Researchers inspect typed
failures, approve repairs, and publish a signed release manifest. Refreshes create
new benchmark versions, allowing new questions for recently trained models while
preserving replayability of older versions.

### Forecast Sandbox and Submission

Each run receives a server-created sandbox bound to:

- benchmark version and track;
- question subset and simulated date policy;
- permitted tools and retrieval corpus;
- model/provider identity and declared knowledge cutoff;
- rate, token, time, and concurrency limits.

The Temporal Gateway must resolve all evidence access server-side. Public clients
must never provide database paths or select local databases. Every search,
article read, forecast update, citation, and graph mutation should be recorded in
an append-only run trace.

Support two submission paths:

1. REST/MCP sessions for interactive agents.
2. Batch uploads using a versioned JSON schema for externally run systems.

Submissions require idempotency keys, schema validation, citation integrity,
model metadata, and a finalization step. Finalized submissions become immutable.

### Evaluation and Leaderboard

Keep outcome, evidence, and reasoning metrics separate:

- resolved-outcome accuracy and proper scoring rules;
- source precision and temporal validity;
- key-event recovery under a named matcher version;
- coverage, abstention, latency, tokens, and estimated cost.

Leaderboard rows must display benchmark version, track, eligible question count,
model version, cutoff policy, tool configuration, submission date, and code or
artifact availability. Do not rank incomparable subsets as if they were the same
run. Keep unresolved or hidden-test scores private until the release policy
permits publication.

## Security Boundaries

Before any public deployment:

- remove database switching, arbitrary database headers, local paths, and process
  management from public routes;
- separate public, participant, submitter, and administrator authorization;
- use signed opaque aliases instead of internal article/event IDs in agent-facing
  prompts where practical;
- rate-limit study entry, autosave, retrieval, and submission endpoints;
- scan uploads and cap payload size;
- keep provider keys and completion URLs server-side;
- encrypt recruitment-platform identifiers and define retention periods;
- record release hashes, run manifests, and evaluation code versions;
- back up PostgreSQL and object storage and test restoration.

## Delivery Sequence

### Phase 0 - Contracts and Isolation

- Define API schemas and lifecycle state machines.
- Add PostgreSQL persistence alongside portable dataset exports.
- Split route registration into `admin`, `annotation`, and `public` applications.
- Add authentication, role checks, audit logs, and deployment configuration.
- Threat-model temporal leakage, identifier exposure, duplicate submissions, and
  unpublished benchmark access.

**Exit:** the private console still works, and public routes cannot reach local
database or process controls.

### Phase 1 - Hosted Annotation MVP

- Import an existing annotation packet as an immutable study.
- Implement assignment entry, autosave, resume, validation, finalization, export,
  and completion redirect.
- Add researcher study monitoring without exposing labels across annotators.
- Test concurrency and complete a small Prolific pilot.

**Exit:** the 50-pair overlap study can be completed end to end without local
HTML or CSV handling.

### Phase 2 - Versioned Question Operations

- Move construction jobs behind the worker queue.
- Add release-candidate review and immutable publication.
- Add public dataset catalog and release downloads.
- Preserve provenance from candidate source through released question.

**Exit:** researchers can add questions and publish a new replayable release
without manually editing a production database.

### Phase 3 - Agent Sandbox and Submission API

- Create run credentials and sealed run configurations.
- Expose Temporal Gateway tools through authenticated REST/MCP sessions.
- Record traces and accept structured forecast/graph submissions.
- Add quotas, timeouts, failure isolation, and reproducible run manifests.

**Exit:** an external agent can complete a benchmark run without direct dataset
or hindsight access.

### Phase 4 - Evaluation and Leaderboard

- Queue evaluation against frozen metric versions.
- Add private submission results and publication controls.
- Add versioned public leaderboard views and downloadable result artifacts.
- Add rerun and dispute workflows without mutating original submissions.

**Exit:** every displayed score is reproducible from a frozen submission,
benchmark release, and evaluator version.

### Phase 5 - Operations and Scale

- Load-test participant bursts and concurrent agent runs.
- Add monitoring for queue delay, error rate, cost, and temporal-gateway leakage.
- Add backups, restoration drills, retention jobs, and incident procedures.
- Automate Prolific study creation through its API only after the hosted study
  flow is stable.

## Immediate Tasks

- [x] Freeze the participant-facing labels and response schema for the current
  overlap packet.
- [x] Build an isolated hosted annotation MVP with assignments, autosave,
  resume, quality checks, and append-only response revisions.
- [x] Verify the participant flow against the real 50-pair packet on desktop
  and mobile.
- [ ] Pilot the hosted study with several internal participants and verify
  completion, resume, timing, attention-check, and export behavior.
- [ ] Add production settings, HTTPS deployment, managed persistence, backups,
  rate limiting, monitoring, and participant-identifier retention controls.
- [ ] Run a small paid Prolific pilot before launching the agreement study.
- [ ] Define benchmark release and run manifests.
- [ ] Design the public catalog, sandbox, submission, and leaderboard APIs
  against those manifests.

The local MVP is suitable for researcher and internal pilot validation. Public
hosting is blocked on the production controls above, not on annotation-page UX
or the response data model.

## External Integration References

- [Prolific software compatibility and URL parameters](https://researcher-help.prolific.com/en/articles/445178-what-survey-experimental-software-is-compatible-with-prolific)
- [Prolific attention and comprehension check policy](https://researcher-help.prolific.com/en/articles/445153-prolific-s-attention-and-comprehension-check-policy)
- [Prolific API overview](https://docs.prolific.com/documentation/get-started/overview)
- [Testing a Prolific study setup](https://docs.prolific.com/documentation/core-concepts/testing-study-set-up)
- [Managing high participant loads](https://docs.prolific.com/documentation/core-concepts/managing-high-loads)
