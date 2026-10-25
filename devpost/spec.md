---
doc: spec
status: approved
---

# DEJAVU — Technical Spec

This is the draft technical blueprint for the approved product requirements. Product behavior and battle numbers remain defined by `prd.md`; this document proposes how to implement them. Recommendations that need the learner's agreement are called out in **Decisions and Open Issues**.

## How This Works, In Plain Language

DEJAVU runs on one computer. Flask is the Python web server: it shows the pages, receives button presses, checks answers, and saves learning history in a SQLite file. The browser handles the Matrix-inspired look and small interactions. Gemini generates the lesson and question content; it never decides whether an answer is correct, how much health changes, or what the player previously missed.

When an answer is wrong, the app writes one permanent mistake event with the question and answer context. A separate weak-concept row groups events that have the same normalized concept label. Grouping makes it easy to choose boss topics, while keeping every original event available for review. The mentor asks one approved database-retrieval function for a small, factual summary; it does not search the database on its own or ask Gemini to invent memories.

Battle progress and generated questions live only in the running Flask process while an encounter is active. A short-lived signed browser-session cookie carries only an opaque run ID so ordinary answer and navigation requests can reach that in-memory encounter. One-use page tickets support POST/redirect/GET without allowing a fresh page load to restore an encounter. The cookie is not an account, identity system, cloud sync, or durable resume mechanism. The profile, session history, mistakes, concepts, and review outcomes live in SQLite and remain after an encounter is abandoned.

## The Core Journey Through the System

```text
Browser page
  → Flask route checks the action and calls an app service
  → service calls Gemini when new content is needed, then validates it
  → valid content is rendered; trusted answer grading and fixed HP rules run in Python
  → SQLite stores the profile, session history, mistake events, concepts, and review outcomes
  → mentor page receives its history only from get_mentor_context()
```

1. Flask checks whether the one local profile has a display name. If not, it shows the first-use prompt and saves the supplied name.
2. The player submits a topic. Flask rejects empty input locally; otherwise the content service asks Gemini for a typed lesson result. It distinguishes a valid lesson, a valid `unlearnable_topic` result, a provider failure, and malformed/invalid output. Only a valid three-card lesson is shown and creates an in-progress learning-session row.
3. `INITIATE COMBAT` asks for the full regular battle question set. The battle starts only after all 12 questions pass validation. If generation fails, the player stays on the lesson and can retry.
4. The browser submits one selected option at a time through a one-use action ID. Flask grades against the validated correct option. For a wrong answer it first commits an individual event and the exact-label concept update, linked to the active session, then applies the fixed PRD health effect once and advances. A failed commit leaves the question pending without applying the effect.
5. After the three regular rounds, the boss service gives Gemini eligible saved concepts plus current-lesson fallback material. Each returned weak-concept reference must match a supplied reference. Python attaches the trusted database IDs and original event reference; the model cannot author its own history or weak-spot marker.
6. Boss victory opens the dedicated victory screen. The `RETURN TO CONSTRUCT` action then returns to the Construct/mentor flow.
7. On return, the mentor screen calls `get_mentor_context()` once. It renders the saved name, last session, and up to two actual concepts with saved context. Review questions are generated for the selected concept, validated, and their outcomes are stored separately from mistake events.

## Stack

| Area | Draft recommendation | Why / trade-off |
|---|---|---|
| Language and runtime | Python 3.12 or newer supported by the selected packages | Matches the learner's Flask experience. Pin the exact version used when the build environment is checked. |
| Web app | Flask 3.1.x with Jinja HTML templates | One familiar Python app serves pages and handles form submissions. Server-rendered pages avoid a separate frontend framework and build step. |
| Browser behavior | HTML, CSS, and small vanilla JavaScript modules | Keeps the existing target stack and provides enough interaction for `LOCK ANSWER`, health updates, and animation. No client framework. |
| Database | Python's built-in `sqlite3`; one local SQLite file | No database server or ORM setup. A little SQL is explicit and appropriate for this small, single-player POC. |
| AI API | Google's supported `google-genai` Python SDK | Official Google SDK; use the current stable package and verify the installed API surface in the first AI slice. |
| Structured validation | Pydantic 2.x models, plus explicit semantic checks | One readable model per generated payload. Pydantic checks fields and types; custom checks cover counts, answer indexes, references, and business rules. |
| Secrets | `.env` read by `python-dotenv`, with `.env` ignored by Git | Easier local setup on Windows. Keep the Gemini key on the Flask server; never send it to the browser. The repository already ignores `.env`. |
| Verification | `pytest` for unit and route tests; a manual browser pass for layout and the full flow | Gives each implementation slice a small check. Test files are planned; none are created or run during this spec stage. |

The official Gemini Python SDK is currently documented as `google-genai`; Google's structured-output guide demonstrates JSON Schema and Pydantic validation. Pin exact compatible versions in `requirements.txt` during the build after checking the live package versions and SDK examples. Avoid pinning to a model alias or API shape without that check.

## Where It Runs and How Someone Tries It

- **Runtime:** local Flask development server listening only on `127.0.0.1`; one player and one local SQLite database. No deployment is selected or required.
- **Requirements:** supported Python installation, package installation from `requirements.txt`, and a Gemini API key in `.env` for live generation.
- **Planned first-run commands (PowerShell):**

  ```powershell
  py -3.12 -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install -r requirements.txt
  Copy-Item .env.example .env
  # Add GEMINI_API_KEY to .env using a local editor.
  python -m flask --app app init-db
  python -m flask --app app run --host 127.0.0.1
  ```

- Open `http://127.0.0.1:5000/` in a browser. Do not bind to `0.0.0.0` or expose the development server to a network.
- For the repeatable return demo, run `python -m flask --app app seed-demo` before starting the app on an otherwise empty database. The command is idempotent, labels its records as seeded, does not alter existing player history, and uses the ordinary mentor and boss code paths. It is not shown in the player UI.
- Submission later requires a short demo video and a public GitHub repository; a local recording is sufficient. Deployment remains optional.

## Look and Feel

Implement `prd.md > Look and Feel` and `scope.md > Inspiration & Identity` as a restrained dark Construct: near-black surfaces, terminal green for primary status and actions, and red only for the weak-spot warning. Use a display face for major headings and the signature line, a monospace face for terminal and status details, and a readable sans-serif for lessons and questions. Keep body text high-contrast and controls usable at phone widths.

Use a shared Jinja layout and CSS variables so each screen keeps the same visual language. Digital rain and glitch details are lightweight progressive enhancements and must not obscure or delay content. **Asset recommendation:** create one original, simple human-like mentor illustration as local SVG and use two subtle CSS states for idle and speaking. This avoids a sprite pipeline or image service; the trade-off is that a custom vector may be less polished than commissioned art. The mentor remains static enough to avoid blocking functionality.

## Components

### Flask application and page routes

Owns page navigation and form handling for identity, Construct, lesson, regular battle, boss, victory, return mentor, and review. It passes data to templates and never trusts a browser-supplied correct answer or HP value. Use POST/redirect/GET for state-changing actions. A local-secret signed, browser-session cookie carries only an opaque active run ID; it contains no display name, learning history, API key, or encounter state. It is cleared after the terminal page ticket is consumed or the run is abandoned. This cookie is a request-correlation mechanism only: it creates no account or identity system, provides no cloud sync, and cannot restore a run after process loss or a consumed page ticket.

Implements `prd.md > The Core Journey`, `prd.md > Screens and Layout`, and `prd.md > States and Boundaries`.

### Identity and profile service

Reads and updates the single `player_profile` row. The name is cosmetic and is not passed to Gemini. First-use and returning-player screens are chosen from profile and actual session-history results, not a hardcoded greeting.

Implements `prd.md > Entering the Construct and Player Identity` and `prd.md > Returning-Player Mentor Screen`.

### Lesson and question generation service

Wraps all Gemini calls behind one server-side client. It builds prompts from the current topic, lesson, or selected saved concept; requests JSON structured output; parses with Pydantic; and runs semantic validation before returning content to a route. It maps provider, timeout, parsing, and validation failures to a small internal error type. It does not write directly to SQLite.

Implements `prd.md > Requesting a Lesson`, `prd.md > Reading the Lesson`, `prd.md > The Battle — Three Regular Rounds`, `prd.md > The Final Boss`, and `prd.md > Reviewing a Weakness`.

### Battle and boss rules service

Owns encounter state in process memory while the Flask app is running, grades selected options, applies the fixed PRD values, and decides round, defeat, boss, and victory transitions. Question content may come from Gemini, but health changes and answer correctness are deterministic Python rules. It never writes question sets, HP, or encounter progress to durable storage.

**Active encounter request lifecycle:**

1. A successful `POST` action (show lesson, start battle, answer, next question, continue, retry, enter boss, or return to Construct) changes the in-memory run once and creates a one-use page ticket. The ticket is a signed token containing only the learning-session ID, a random nonce, and a five-minute expiry; the server's in-memory ticket ledger records whether its nonce has been consumed and which run it belongs to. It returns a `303` redirect carrying the ticket. It contains no encounter state and cannot restore a run.
2. The redirected `GET` must present the matching run cookie and an unused ticket. Flask consumes the ticket and renders that state. This is the normal POST/redirect/GET path; the encounter remains active in process memory across these ordinary actions. A defeat screen is still an active choice point because retry is available. After boss victory, clear the cookie only after the victory page is rendered; after a player chooses to leave a defeat/unfinished run, clear it only after the Construct page is rendered.
3. Reloading the rendered URL reuses a consumed ticket. A page load with no matching in-memory run, no matching run cookie, a consumed ticket, or an expired ticket does not restore encounter state. For a verifiable ticket, read the linked session's persisted status: change it to `abandoned` only if it is still `in_progress`, using a conditional update; leave `completed`, `defeated`, or already `abandoned` unchanged. If the ticket is unverifiable, do not use it to select a database row. In either case clear stale in-memory run/cookie state and redirect safely to Construct. A new topic or explicit `RETURN TO CONSTRUCT` also ends the run. A server restart loses the run map; startup marks all persisted `in_progress` sessions abandoned, without changing terminal statuses. No durable battle resume is introduced.
4. If an answer POST is repeated with the same action ID, return its cached result/ticket if still pending; otherwise show a safe already-submitted/Construct response. Never re-grade, apply HP, or insert an event a second time. A retry action starts a new attempt ID for each question it presents, so an intentional wrong answer during a later retry remains a distinct event.

The valid lesson response uses this same one-use ticket flow: successful lesson generation creates the `in_progress` session and its in-memory run before redirecting to render the lesson. Unlearnable/provider/validation outcomes do not create the run cookie, page ticket, or session row.

Normal in-app actions use POST forms that issue fresh one-use tickets; ordinary navigation between the battle, boss, defeat, and victory states therefore preserves the active run. A genuine reload, abandoned browser run, or process restart cannot restore it. On defeat, `RETRY ROUND` / `RETRY BOSS` keeps the session in progress and resets only the PRD-specified HP. Choosing `RETURN TO CONSTRUCT` from a defeat screen finalizes the session as defeated, then clears its cookie after the Construct redirect renders. Boss victory marks it completed before the victory screen is shown, then clears its cookie after that page renders.

An answer submission is applied at most once per question-attempt ID. A transaction and a unique `(session_id, question_instance_id)` constraint protect wrong-answer writes. For a wrong answer, commit the event and concept update before changing in-memory HP or advancing; on a database failure keep the question pending and allow the same action ID to retry. In-memory action IDs protect correct-answer damage, wrong-answer damage, and page transitions from repeated POSTs. After a process restart, no encounter exists to apply an old action to.

Implements `prd.md > The Battle — Three Regular Rounds`, `prd.md > The Final Boss`, and `prd.md > After the Final Boss — Victory`.

### SQLite repositories

Own profile, session, concept, mistake-event, and review-outcome reads/writes. Each mistake write and concept upsert is one transaction. Foreign keys are enabled. Query results are parameterized; template output is escaped by Jinja.

Implements `prd.md > Memory Integrity`, `prd.md > Reviewing a Weakness`, and `prd.md > States and Boundaries`.

### Approved mentor retrieval function: `get_mentor_context`

This is the sole approved database retrieval function for assembling mentor context. It is a normal Python function, not a Gemini function-calling feature. The returning-player route calls it; the route and template do not run their own mentor-history queries. Other application features still use their repositories for their own required storage and gameplay operations.

**Input:** `get_mentor_context(*, max_weak_concepts: int = 2)`; accept only `1` or `2`. There is one local player, so the function takes no user-controlled player ID. It reads the profile, most recent real-or-seeded session, and the most recently missed concepts with their latest event context.

**Output:** a typed object with:

```text
MentorContext
  display_name: string | null
  has_session_history: boolean
  last_session: null | { topic: string, occurred_at_utc: ISO-8601 string, origin: player | seeded_demo }
  weak_concepts: list[0..2] of {
    concept_id: integer
    label: string
    explanation: string
    mistake_event_count: integer
    latest_mistake: {
      question: string
      chosen_answer: string
      correct_answer: string
      explanation: string
      occurred_at_utc: ISO-8601 string
      origin: player | seeded_demo
    }
  }
```

An empty history returns `has_session_history = false`, `last_session = null`, and an empty list. The output is bounded and contains only facts stored in SQLite. The UI builds the greeting from the saved display name and this result; a concept not in the result cannot appear as a personalized memory. No name or direct identifier is sent to Gemini.

Implements `prd.md > Returning-Player Mentor Screen` and `prd.md > Memory Integrity`.

### Seed-data command

Provides a Flask CLI command that inserts one clearly marked prior session, a small set of weak concepts, and their associated mistake events only when the database is empty. It is idempotent and refuses to overwrite player history. The seed data then flows through the same mentor retrieval function, candidate selection, boss generation, answer handling, and UI as normal data; there is no demo-only retrieval or gameplay branch.

Implements `prd.md > Memory Integrity` and `prd.md > States and Boundaries`.

### Templates, styles, and browser behavior

Jinja templates provide one page per PRD screen and a shared layout. CSS provides responsive desktop and phone layouts, the palette, health bars, and two mentor states. Small JavaScript handles visual-only animation and selection feedback. Flask remains authoritative for answer correctness, health, and persistence.

Implements `prd.md > Screens and Layout` and `prd.md > Look and Feel`.

## Data Model

One SQLite database at `instance/dejavu.sqlite3`; it is local and must be ignored by Git. Store timestamps as UTC ISO-8601 text. Use parameterized SQL, foreign keys, and small schema migrations via `PRAGMA user_version` plus checked-in `schema.sql`; avoid adding an ORM or migration framework for this POC.

| Table | Important fields | Purpose and update rule |
|---|---|---|
| `player_profile` | `id` fixed to `1`; `display_name`; `created_at` | Exactly one local profile. The display name is set on first use and may be changed only if the PRD later allows it; for this POC the first supplied name is retained. |
| `learning_sessions` | `id` UUID; `topic`; `started_at`; `ended_at`; `status`; `origin` (`player` or `seeded_demo`) | One row is created only after a lesson has passed validation and is ready to display. Stores the topic and provenance. Status is `in_progress`, `completed`, `defeated`, or `abandoned`; it does not contain resumable battle state. Boss victory sets `completed`; leaving a defeat screen for Construct sets `defeated`; choosing a new topic before victory/defeat, or invalidating a ticket for a session still `in_progress`, sets `abandoned` by conditional update. Process startup abandons only old `in_progress` rows. Retrying after defeat keeps it `in_progress`; terminal statuses are never overwritten. |
| `weak_concepts` | `id`; `normalized_label` unique; `label`; `explanation`; `first_missed_at`; `last_missed_at` | Aggregated concept-level index. Exact normalized label matching (trim, lowercase, collapse whitespace and punctuation) groups obvious repeats. It never stores or replaces the underlying mistake history. |
| `mistake_events` | `id`; `session_id`; `question_instance_id`; `weak_concept_id`; `origin` (`player` or `seeded_demo`); `question_kind` (`regular` or `boss`); `question_text`; `chosen_answer`; `correct_answer`; `explanation`; `occurred_at` | Append-only record for every distinct wrong answer, including repeated misses of the same concept. `question_instance_id` is new for each intentional attempt, including a round/boss retry; a repeated POST for the same attempt reuses its ID. Unique `(session_id, question_instance_id)` prevents duplicate writes. Events remain linked to their session if it later becomes defeated or abandoned. Boss events link to the target weak concept. `origin` distinguishes player activity from seeded demo records. |
| `review_outcomes` | `id`; `review_id` UUID grouping the two questions; `question_instance_id`; `weak_concept_id`; `question_text`; `chosen_answer`; `correct_answer`; `is_correct`; `explanation`; `occurred_at` | One row per answered review question. Unique `(review_id, question_instance_id)` prevents duplicate POSTs. Separate from mistakes, so later improvement never edits or erases original events. |

### Learning-session lifecycle

Create a `learning_sessions` row only after a lesson response has the valid `lesson` outcome, all three lesson cards pass checks, and the lesson is ready to show. A blank, unlearnable, provider-failed, or malformed lesson request creates no session row. At this point the row is `in_progress`; a later failure generating the 12 battle questions leaves it in progress so the player can retry from the lesson.

| Event | Session transition | Durable record effect |
|---|---|---|
| Valid lesson is ready | Create as `in_progress` | Save topic, start time, and origin. Keep lesson and run state in process memory. |
| Regular/boss wrong answer | Remain `in_progress` | In one transaction, upsert the concept and insert the event with the same `session_id`. The event is durable before the HP change/result transition. |
| Retry round or boss | Remain `in_progress` | Reset only the health/progress required by the approved PRD; allocate new question-attempt IDs. Existing mistake rows remain untouched. |
| Boss defeated | Set `completed` | Write `ended_at` before rendering the dedicated victory screen. |
| Player chooses `RETURN TO CONSTRUCT` on a defeat screen | Set `defeated` | Write `ended_at`; retain every event. |
| Player leaves an unfinished session for a new topic/Construct, a page ticket expires/is replayed, or the run is interrupted | If status is `in_progress`, set `abandoned`; otherwise leave status unchanged | Use a conditional update `WHERE status = 'in_progress'`; set `ended_at` only when that update succeeds. Retain every event. |
| Flask process starts and finds old `in_progress` rows | Set those rows `abandoned` | Update only rows still `in_progress`; encounter state is gone, and terminal statuses are unchanged. Do not recreate state from SQLite. |

Terminal statuses (`completed`, `defeated`, `abandoned`) never transition back to `in_progress`. A session row remains the parent of its mistake events after any terminal transition; no cleanup path deletes or reassigns events. If event persistence fails, roll back both the event insert and concept update, keep the same question and action ID pending, and do not apply the answer's health effect until a retry commits successfully.

Every `mistake_events` row points to one `weak_concepts` row; several events can point to the same concept. Mentor counts are derived from events rather than kept as a second mutable counter. Boss candidates are selected from these concept rows, and each selected concept is linked to its latest actual event for traceability. Exact-label grouping intentionally avoids embedding search or AI-based merging; differently worded labels may remain separate concepts.

## AI Structured Schemas and Validation

All provider calls run in Python on the server through the Google GenAI SDK. Use a Pydantic model to supply the JSON response schema to Gemini and parse the returned text back into the same model. Structured output reduces malformed responses; it does **not** replace local validation. Do not stream partial content into the interface. Do not render any content until the complete payload passes both structural and semantic checks.

### Lesson generation result

The lesson call returns one structurally valid result with an explicit outcome. This lets the app tell a valid product decision (topic is not reasonably teachable) from a failed provider call or broken payload.

```text
LessonGenerationResult {
  outcome: lesson | unlearnable_topic
  title: non-empty string | null
  cards: LessonCard list, length 0..3
  reason_code: no_teachable_subject | null
}
```

Semantic combination rules:

- `outcome = lesson` requires a non-empty title, exactly 3 cards with the roles below, and `reason_code = null`.
- `outcome = unlearnable_topic` requires `title = null`, no cards, and `reason_code = no_teachable_subject`.
- Any other combination is invalid structured output, not an unlearnable-topic result.

The prompt permits `unlearnable_topic` only when the input is nonsensical or no teachable subject can reasonably be identified. Do not use it just because a topic is narrow, advanced, or unfamiliar; for a specific but interpretable topic, attempt a lesson and note uncertainty in its teaching content where needed. This is model classification, so implementation verification must include nonsense input and narrow-but-learnable topics.

### Lesson payload

```text
Lesson {
  title: non-empty string
  cards: exactly 3 LessonCard values
}
LessonCard {
  role: one of core_idea | how_it_works | practical_example
  heading: non-empty string
  body: non-empty student-friendly string
  concept_label: non-empty string
  concept_explanation: non-empty concise string
}
```

For `outcome = lesson`, require each role exactly once. Reject empty or repeated headings, blank bodies, and an incomplete card set. The requested topic is kept by the app and used as the screen heading; Gemini does not get to replace it with a different topic.

If `outcome = unlearnable_topic` passes its branch checks, show the recoverable inline message: `The Construct couldn't identify a learnable topic. Try Process Scheduling or DBMS Normalization, or edit your topic.` Preserve the entered topic, keep it editable, and allow the player to retry or revise it. Do not create a learning-session row or start a battle for this outcome. Empty input is rejected before Gemini is called.

### Regular battle payload

```text
BattleSet {
  rounds: exactly 3 Round values
}
Round {
  round_number: integer 1..3
  questions: exactly 4 Question values
}
Question {
  question: non-empty string
  options: exactly 4 distinct non-empty strings
  correct_option_index: integer 0..3
  explanation: non-empty string
  concept_label: non-empty string
  concept_explanation: non-empty string
}
```

The prompt requests introductory, application, then more challenging questions across rounds. The validator checks round ordering, exact counts, distinct options, and valid answer indexes; a human acceptance pass checks that the actual difficulty escalates. The app keeps this generated set in encounter memory, not durable storage.

### Boss payload and trusted traceability

```text
BossSet {
  questions: 1..5 BossQuestion values
}
BossQuestion {
  target_ref: string
  question: non-empty string
  options: exactly 4 distinct non-empty strings
  correct_option_index: integer 0..3
  explanation: non-empty string
}
```

Python supplies candidate references such as `C1` along with saved concept text and a bounded example of actual missed-question context. For weak-concept questions, validate that each `target_ref` exactly matches a supplied candidate and is not duplicated. Python—not Gemini—maps that reference to `weak_concept_id`, `mistake_event_id`, and the saved label used by `WEAK SPOT DETECTED` / `PREVIOUSLY MISSED`. For current-lesson fillers, request a separate adaptive set and mark it `ADAPTIVE TEST` in Python. Fallback questions never receive a weak-concept ID or personal weak-spot label. Reject unknown references and regenerate the full invalid set before the encounter begins.

Select up to five distinct weak concepts, most recently missed first. When fewer than five suitable saved concepts exist, fill the remaining slots from the current lesson as required by `prd.md > The Final Boss`. If none exist, all questions are adaptive tests. Boss question order preserves the mapped reference and event link through answer resolution and a boss retry. Four correct answers can defeat the boss at its existing 100 HP; the fifth slot is only used if needed.

### Review payload

```text
ReviewSet {
  questions: exactly 2 ReviewQuestion values
}
ReviewQuestion {
  question: non-empty string
  options: exactly 4 distinct non-empty strings
  correct_option_index: integer 0..3
  explanation: non-empty string
  target_concept_label: non-empty string
}
```

The server supplies one selected saved concept and validates that both questions target it. Store outcomes in `review_outcomes`, never in `mistake_events`.

### Shared semantic checks

- Reject missing, extra, wrong-type, empty, truncated, or unparsable fields; reject options that are not exactly four distinct choices; reject an answer index outside `0..3`.
- Apply exact count/role checks for each payload, reference checks for boss questions, and target-concept checks for review questions.
- Bound string lengths and question counts before rendering; do not use provider HTML or mark generated strings as safe HTML.
- Do not infer a personal history, concept ID, correct answer, or source event from model prose.
- If a set fails validation, discard it and show a recoverable error. Do not silently fill missing content with invented defaults.

## Gemini Service Contract

**Recommended call path:** `google-genai` Python client, configured with a server-side `GEMINI_API_KEY` and an environment-selected `GEMINI_MODEL`. Use a stable Flash-class model that supports the needed structured output, selected and pinned during implementation after checking current official model availability. A stable model is less likely to change under the project than a `latest`, preview, or experimental alias.

For each call, the service sends the task prompt, the minimum topic/lesson/concept material needed, and the Pydantic JSON schema through the SDK's structured-output configuration. It receives a response object and parses its text as the expected Pydantic model. The exact SDK method and response field must be checked against the installed `google-genai` version in the first AI slice, because Google evolves the API surface. Do not send player names, database IDs, timestamps, or whole history. Boss generation necessarily sends the concept and limited missed-question content needed to make a harder variation; review generation sends the selected concept.

Key official references:

- [Google GenAI SDK libraries and support status](https://ai.google.dev/gemini-api/docs/libraries)
- [Gemini structured outputs and Python/Pydantic examples](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini API getting started and API-key setup](https://ai.google.dev/gemini-api/docs/get-started)
- [Gemini model availability and model-name guidance](https://ai.google.dev/gemini-api/docs/models)
- [Gemini API pricing and data-use notes](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Flask quickstart](https://flask.palletsprojects.com/en/stable/quickstart/)
- [Python `sqlite3` documentation](https://docs.python.org/3/library/sqlite3.html)
- [Pydantic documentation](https://docs.pydantic.dev/latest/)

Gemini rate limits vary by project, model, and account tier; confirm the active limits in AI Studio during setup. Cost depends on the chosen model and token volume; keep prompts and outputs short and check current pricing before use. Google's current pricing page says free-tier content may be used to improve products, while paid-tier content handling differs. The player must understand this before sending real learning content. No paid plan or hosting is assumed.

## Important Failure Modes

- **Gemini slow, unavailable, or rate-limited** → show a content-specific retry message, preserve the topic/selected concept/encounter context, and keep the player out of a half-started encounter. Do not automatically repeat an answer or apply HP changes again.
- **Malformed or semantically invalid structured output** → discard it, log a concise server-side diagnostic without the API key, show a retry action, and do not reveal partial questions or fabricate content.
- **Valid unlearnable-topic result** → show the distinct recoverable topic-validation message from `prd.md > Requesting a Lesson`; keep the input editable and retryable. Do not create a session or show a lesson/battle.
- **Provider failure or malformed lesson result** → preserve topic and show the PRD's `Download failed. Your lesson wasn't created. Try again.`. Do not show the lesson or enable combat until it validates. A timeout, HTTP/API error, missing response, JSON/Pydantic failure, or invalid outcome-field combination always follows this failure path, never the unlearnable-topic path.
- **Battle question-set failure** → stay on the lesson, show a retry for combat setup, and start no round until all 12 questions validate.
- **Boss generation failure** → stay at boss setup with unchanged player/boss HP and saved mistakes; retry generation without advancing the encounter.
- **Review generation failure** → preserve the selected weakness and original history; retry without writing review outcomes.
- Explanations are generated with their question set and validated before combat/review begins. A provider failure therefore follows that content type's retry path; the app never enters a state where an answer has been graded but its generated explanation is unavailable.
- **SQLite write failure** → roll back concept and event writes together, keep the same question/action pending, and do not apply the answer's HP effect. Show a clear save error and retry safely with the same action ID.
- **No history** → show first-time welcome if no session exists; if sessions exist but no misses, say no weak concepts were saved and offer a new topic. Never fabricate a mentor memory.
- **Server restarts during battle** → discard the in-memory encounter and conditionally mark its session abandoned only if it is still `in_progress`; completed, defeated, and already abandoned statuses remain unchanged. Persistent mistake events and review outcomes remain intact.
- **Missing API key** → allow the application shell and local pages to open, but show a setup-specific generation error when AI content is requested; never expose a traceback or key.

## Boss-Question Traceability

For every weak-spot boss question, keep this server-owned link in active encounter memory:

```text
boss question instance
  → supplied target_ref (temporary model-facing label)
  → weak_concept_id (saved aggregate)
  → mistake_event_id (a real event in that concept's history)
  → original question/answer context shown by the marker
```

The model receives only the minimum text needed to make a harder variation. Its returned `target_ref` is checked against the supplied references. The application attaches trusted IDs after validation and renders the weak-spot marker from the saved label and event. A bad or missing reference invalidates that generated set. Adaptive fillers are tagged by Python and have no event link. Thus an LLM cannot create a player's history by returning an invented concept name or database ID.

## File Structure

```text
DEJA VU/
├── app.py                         # Flask entry point and CLI registration
├── requirements.txt               # Flask, google-genai, Pydantic, python-dotenv; pytest for verification
├── .env.example                   # Variable names only; no credentials
├── .gitignore                     # Add instance/ and test/cache artifacts; .env is already ignored
├── README.md                      # Windows setup, local run, demo seed, recording path
├── instance/                      # Local-only, ignored runtime data
│   └── dejavu.sqlite3             # Persistent profile and learning records
├── dejavu/
│   ├── __init__.py                # App factory, config, startup checks
│   ├── routes.py                  # Page routes and form handling
│   ├── settings.py                # Environment configuration
│   ├── db/
│   │   ├── connection.py          # SQLite connection and transaction helpers
│   │   ├── schema.sql             # Tables, indexes, constraints
│   │   └── repository.py          # Profile/session/concept/mistake/review storage
│   ├── services/
│   │   ├── ai_client.py           # Gemini client and provider error mapping
│   │   ├── ai_schemas.py          # Pydantic content schemas
│   │   ├── content.py             # Prompts, structured generation, semantic validation
│   │   ├── battle.py              # Encounter memory, answer grading, fixed game rules
│   │   ├── mentor_context.py      # The sole approved mentor retrieval function
│   │   └── demo_seed.py           # Idempotent, explicitly marked demo seed operation
│   ├── templates/
│   │   ├── base.html              # Shared shell and navigation-free frame
│   │   ├── identity.html          # First-use display-name prompt
│   │   ├── construct.html         # Topic entry and recoverable errors
│   │   ├── lesson.html            # Three validated lesson cards
│   │   ├── battle.html            # Regular battle and question feedback
│   │   ├── boss.html              # Weak-spot/adaptive boss encounter
│   │   ├── victory.html           # Dedicated post-boss victory
│   │   ├── mentor.html            # Returning-player screen from retrieval contract
│   │   └── review.html            # Two-question focused review
│   └── static/
│       ├── css/app.css            # Theme, responsive layout, health bars, states
│       ├── js/app.js              # Small visual interactions only
│       └── img/mentor.svg         # Original local vector mentor illustration
├── tests/
│   ├── test_ai_schemas.py         # Structural and semantic validation
│   ├── test_repository.py         # Persistence, append-only events, aggregation, seed safety
│   ├── test_mentor_context.py     # Contract output and no-history behavior
│   ├── test_battle_rules.py       # Fixed values, transitions, idempotent submissions, traceability
│   └── test_routes.py             # Recoverable errors and screen flow
└── devpost/
    ├── learner-profile.md         # Existing learning context; excluded from Git by current ignore rule
    ├── scope.md                   # Approved product scope
    ├── prd.md                     # Approved product requirements
    └── spec.md                    # This canonical specification
```

## Testable Implementation Slices

Each slice should be built and checked before the next. The checks below are plans for `5-build`; they have not been run in this specification stage.

1. **Local Flask shell, identity, and visual frame** — create the app factory, shared template, first-use name prompt, responsive theme, and local startup. Check that it opens at `127.0.0.1:5000`, saves the name, and does not ask again after reload.
2. **SQLite schema and memory integrity** — add profile/session/concept/mistake/review tables, transaction helpers, exact-label aggregation, and append-only event writes. Check two identical concept misses create two event rows but one concept row; a simulated duplicate submission does not double-write.
3. **Mentor retrieval and seeded history** — implement `get_mentor_context()` and the idempotent seed command. Check its empty, player-history, and seeded-history outputs; verify seed data is marked and existing player data is not overwritten.
4. **Gemini lesson integration** — add server-side key loading, the discriminated lesson result, schema validation, and recoverable lesson errors. Check valid output shows exactly three cards; nonsense returns the distinct unlearnable message without creating a session; a narrow but learnable topic is attempted; malformed output, missing key, timeout, and provider failure preserve the topic and show the generation error without a stack trace.
5. **Regular battle generation and fixed rules** — generate/validate all 12 questions before combat, implement the three rounds and values from `prd.md > The Battle — Three Regular Rounds`. Check correct/wrong damage, early round end, explanation pause, retry behavior, and no changed PRD numbers.
6. **Mistake event history and recovery** — persist each wrong answer once, link it to a concept, retain question context, and handle retry/duplicate POST safely. Check repeated misses remain distinct and survive defeat/retry/reload.
7. **Boss traceability and victory** — select saved concepts, generate linked weak variations and adaptive fillers, implement boss rules and the dedicated victory screen. Check each weak marker maps to a saved concept and event; no-history questions show `ADAPTIVE TEST`; boss failure preserves HP and data; victory returns only through the required action. Replay/expire the victory ticket and verify `completed` remains unchanged; do the same for a `defeated` session. Replay/expire a ticket for an `in_progress` session and verify it becomes `abandoned` while all mistake events remain linked.
8. **Returning mentor and review** — use only `get_mentor_context()` for the returning screen, generate two validated review questions, and persist review outcomes separately. Check no false memories/dates, original events remain unchanged, and both review actions work.
9. **Seeded end-to-end demo and responsive pass** — run the return and boss beats using marked seed data through ordinary code paths; inspect phone and desktop widths and complete local recording steps. Fix visual polish only after the kernel passes.

## What Was Simplified and Why

- One local player and one SQLite file instead of accounts, hosted storage, and sync — this preserves return memory on the same machine without authentication or infrastructure.
- Server-rendered Jinja pages with small JavaScript instead of a separate frontend framework — one app and no frontend build step.
- Standard-library SQLite access instead of an ORM — fewer abstractions and dependencies for five small tables. The trade-off is that SQL and transactions must be written carefully and tested.
- In-memory encounter state and one-use page tickets instead of durable battle checkpoints — normal PRG transitions keep the active encounter, while reloads, expired/replayed tickets, and server restarts abandon only an `in_progress` session. Terminal statuses remain unchanged, and already-saved mistakes remain. The trade-off is that an interrupted run must start from a fresh topic or review.
- Deterministic mentor copy from database facts instead of an extra AI-personalized greeting — fewer API calls and stronger memory integrity; the prose is less conversational.
- Exact normalized-label aggregation instead of semantic concept matching — predictable and cheap, but labels that mean the same thing and differ in wording may remain separate.
- One local SVG mentor illustration and lightweight CSS states instead of a sprite system or custom animation pipeline — keeps the requested character without making animation a blocker.
- No deployment requirement — local running and recording prove the approved POC; hosting would add cost and setup without strengthening the kernel.

## Decisions and Open Issues

### Recommendations in this draft

- **Architecture recommendation:** Flask + Jinja + small vanilla JavaScript; SQLite through `sqlite3`; official `google-genai` SDK; Pydantic structured schemas. These choices align with the learner profile and avoid extra services. The trade-off is that answer handling, database transactions, and validation stay in this one Python app and must be tested carefully.
- **Concept grouping recommendation:** group by exact normalized label; preserve every event row. This keeps boss/retrieval queries understandable and avoids hidden AI merging. The limitation is that semantic duplicates with different wording remain separate.
- **Mentor recommendation:** deterministic template copy fed only by `get_mentor_context()`, not a second AI call. This reduces cost and makes memory claims auditable, at the cost of less varied prose.
- **Run recommendation:** local loopback only and no deployment for the POC. The trade-off is that reviewers need the demo video to see the app.
- **Mentor asset recommendation:** hand-authored SVG with CSS idle/speaking states. This needs a brief visual pass during implementation but no new image service or sprite tooling.

### Genuine uncertainty to clarify during the build

The learner profile says Gemini API key availability and account willingness are not established, and SQLite/API-key setup are not established technical areas. The spec makes the planned key location and data path explicit. Before the first live call, confirm key availability and review Google's current data-use terms for the chosen tier. The build can start with schema and mocked-client tests, but live Gemini verification depends on that confirmation.

### Open questions carried from `prd.md > Open Questions`

- Confirm API-key availability and acceptable Gemini data-use tier before sending real topic or weakness content. Recommendation: minimize what is sent (no display name, local IDs, dates, or full history); a boss call still sends the saved concept and limited missed-question context needed for the requested harder variation. The free-tier versus paid-tier data-use and cost trade-off must be understood before live use.
- Verify the precise supported `google-genai` structured-output call, installed package version, and stable model name during the first AI slice; current official references are linked above, but model availability and limits can change.
- Choose the final 2D mentor SVG asset approach in build; this spec recommends a small hand-authored local vector and does not prescribe detailed art.
- Confirm Python/package versions against the available local environment and pin them in `requirements.txt` during setup.
