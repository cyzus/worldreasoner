# Hosted Annotation Setup

This service hosts an immutable event-validation packet with participant
assignment, autosave, resume, quality checks, and final submission. It is
separate from the researcher review artifacts and from the public benchmark
interface.

## Local Pilot

```powershell
uv run worldreasoner-annotation `
  --packet-dir /path/to/annotation-packet `
  --db tmp/hosted_annotation.db `
  --host 127.0.0.1 `
  --port 8011
```

Open:

```text
http://127.0.0.1:8011/?PROLIFIC_PID=preview&STUDY_ID=preview&SESSION_ID=preview
```

Use a fresh `SESSION_ID` for each pilot participant. Responses are stored in
the dedicated SQLite database passed through `--db`; the source packet remains
unchanged.

## Prolific Configuration

The study URL must include Prolific's participant, study, and session query
parameters. Supply `--completion-url` with the Prolific completion URL so a
successful final submission can return the participant automatically.

The workflow includes an introduction, tutorial, two comprehension checks, two
attention checks, autosave, and resumable assignments. Attention checks are
stored separately from research labels and must not enter agreement analysis.

The participant information page also states the research purpose, procedure,
recorded fields, pseudonymized research use, autosave behavior, voluntary
participation, withdrawal route, compensation context, sensitive-content
notice, researcher contact, and prohibition on AI-assisted annotation. Consent
is versioned and its acceptance time is stored with the assignment.

The following deployment settings can override the participant-facing research
identity:

```text
ANNOTATION_RESEARCH_ORGANISATION
ANNOTATION_RESEARCH_CONTACT
PROLIFIC_COMPLETION_URL
```

This interface does not itself constitute institutional ethics approval. Before
launch, reconcile the wording with the approved protocol and Prolific listing,
including the exact duration, reward, retention period, withdrawal deadline,
principal investigator details, and ethics reference where required.

## UX Decisions From The Pilot

The completed 50-item researcher pilot had no missing required labels, but all
50 items also contained a separate date-evidence passage. Those passages
averaged about 105 characters and frequently repeated the claimed date,
publication date, or nearby article text already visible in the interface. In
contrast, the generic notes field was unused for 36 of 50 items. This indicates
duplicated transcription effort rather than missing annotator diligence.

- The full event description is the canonical claim; the short title is only
  an orientation label.
- Annotators answer whether the cited article supports that full claim.
- Claimed and publication dates are displayed as metadata and never need to be
  copied into a response.
- Date support is a categorical judgment plus a structured basis: explicit
  occurrence date, contextual or relative date, publication date only, or no
  date evidence.
- One exact excerpt anchors the judgment. One reason is required only when the
  source, date, or entity judgment is not fully supported.
- The header item selector labels every item as `Saved`, `Draft`, or `Missing`.
  Navigation never requires an incomplete current item to pass validation, and
  final submission returns the participant to the first missing item.

## Staging Deployment

The files in `deploy/annotation/` provide a staging template for a dedicated
Ubuntu host. Uvicorn binds only to `127.0.0.1:8011`; Caddy handles HTTPS and is
the only public application entry point. The service runs as the non-login
`wr-annotation` user with a read-only packet and a separate writable state
directory.

Server paths:

```text
/srv/worldreasoner-annotation/app       application code
/srv/worldreasoner-annotation/private  immutable annotation packet
/srv/worldreasoner-annotation/state    live SQLite database
/srv/worldreasoner-annotation/backups  daily 14-day local backups
```

Copy `worldreasoner-annotation.env.example` to the host environment file and set
the research identity and Prolific completion URL there. Set `ANNOTATION_HOST`
for Caddy or replace the example hostname before loading the configuration.

Do not recruit an annotation cohort until the final study packet, Prolific
completion URL, compensation, retention wording, and ethics text have been
installed and an internal multi-participant test has passed.

Operational checks:

```bash
ssh annotation-host 'systemctl status worldreasoner-annotation caddy'
ssh annotation-host 'curl -fsS http://127.0.0.1:8011/health'
ssh annotation-host 'systemctl list-timers worldreasoner-annotation-backup.timer'
```

After origin HTTPS has been verified, the Cloudflare record may be proxied with
SSL/TLS mode set to Full (strict).

## Production Gate

Do not expose the local SQLite service directly to the public internet. Before
a paid external study, deploy behind HTTPS, use a managed database with backups,
set retention and access rules for participant identifiers, add rate limiting
and monitoring, and run a small end-to-end Prolific pilot including completion
redirect and duplicate-session tests.
