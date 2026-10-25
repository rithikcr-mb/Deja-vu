---
doc: checklist
status: approved
---

# Build Checklist

Build mode: learn

## Slices

- [x] **1. Enter a topic and receive a validated lesson**
  Becomes usable: The local app starts, asks for and saves the display name once, accepts a topic, and shows either three validated lesson cards or the distinct recoverable unlearnable/provider error.
  Why now: This bootstraps the running app while delivering the first complete learning behavior. It resolves the Gemini response contract early, before battle logic depends on generated content.
  PRD ref: `prd.md > The Core Journey` (steps 1–3), `prd.md > Features and Behavior > Entering the Construct and Player Identity`, `prd.md > Features and Behavior > Requesting a Lesson`, `prd.md > Features and Behavior > AI-Generated Content Reliability`
  Spec ref: `spec.md > Stack`, `spec.md > Where It Runs and How Someone Tries It`, `spec.md > Components > Flask application and page routes`, `spec.md > Components > Identity and profile service`, `spec.md > Components > Lesson and question generation service`, `spec.md > Data Model`, `spec.md > AI Structured Schemas and Validation`, `spec.md > Important Failure Modes`, `spec.md > File Structure`
  Build: Create the Flask app and local setup files, shared Construct/identity/lesson templates and initial responsive theme; persist the single profile; implement the discriminated lesson response, Pydantic and semantic validation, and recoverable errors. Keep the topic editable on errors. A successful validated lesson creates its in-progress session; other outcomes create none. Use a controllable fake AI client for deterministic local verification, and keep live Gemini credentials server-side.
  Verify (mechanical): Install the declared dependencies and start Flask on `127.0.0.1`; use the app's deterministic fake client to verify first-use and returning identity, exactly three lesson cards and one session row for valid output, and preserved editable topic with no session row for unlearnable and malformed/provider-failure results. Confirm a missing key produces a safe setup error.
  Learner check: Open the local app, save a display name, request a topic, and inspect the lesson. Try an invalid topic response and check that the text stays editable and no battle starts.
  Commit: `Add local app and validated lessons`

- [x] **2. Fight the regular battle and save each mistake**
  Becomes usable: The learner can complete the three regular rounds, see correct/wrong feedback and fixed health effects, and retain each distinct wrong-answer event after a reload or defeat.
  Why now: This extends the lesson into an end-to-end playable loop and proves transactional event history before the mentor and boss rely on it. SQLite is introduced inside this working behavior rather than as a standalone layer.
  PRD ref: `prd.md > The Core Journey` (steps 4–5), `prd.md > Features and Behavior > The Battle — Three Regular Rounds`, `prd.md > Features and Behavior > Memory Integrity`, `prd.md > States and Boundaries`
  Spec ref: `spec.md > The Core Journey Through the System`, `spec.md > Components > Battle and boss rules service`, `spec.md > Components > SQLite repositories`, `spec.md > Data Model`, `spec.md > Data Model > Learning-session lifecycle`, `spec.md > AI Structured Schemas and Validation > Regular battle payload`, `spec.md > Important Failure Modes`
  Build: Add the validated 12-question set, encounter state and one-use run/page tickets, deterministic grading and PRD health rules, SQLite session/concept/event storage, and safe retry/idempotency handling. Keep run state in memory; persist a wrong-answer event and its concept update atomically before applying its health effect.
  Verify (mechanical): Run the battle flow using the fake AI client. Confirm all 12 questions validate before combat; check correct/wrong effects against the PRD values; submit the same action twice and confirm one effect and one event; miss the same concept twice and confirm two events linked to one concept; verify saved events remain after defeat/reload and an interrupted in-progress run becomes abandoned without deleting events.
  Learner check: Play through a round, deliberately miss one answer, and reload after leaving the encounter. Confirm the feedback is clear and that no interrupted battle resumes.
  Commit: `Add regular battle and persistent mistakes`

- [x] **3. Return to real memory and face the saved weaknesses**
  Becomes usable: A returning learner sees mentor context drawn from stored history and can face a boss whose weak-spot questions trace to actual mistake events, then reach the dedicated victory screen.
  Why now: This brings DEJAVU's unique kernel into the app early: saved mistakes shape the boss and real history shapes the return mentor. Seeded history exercises the same path without fabricated demo-only behavior.
  PRD ref: `prd.md > The Core Journey` (steps 6–9), `prd.md > Features and Behavior > The Final Boss`, `prd.md > Features and Behavior > After the Final Boss — Victory`, `prd.md > Features and Behavior > Returning-Player Mentor Screen`, `prd.md > Features and Behavior > Memory Integrity`
  Spec ref: `spec.md > Components > Approved mentor retrieval function: get_mentor_context`, `spec.md > Components > Seed-data command`, `spec.md > Components > Battle and boss rules service`, `spec.md > Data Model`, `spec.md > Data Model > Learning-session lifecycle`, `spec.md > AI Structured Schemas and Validation > Boss payload and trusted traceability`, `spec.md > Boss-Question Traceability`, `spec.md > Important Failure Modes`
  Build: Implement the bounded `get_mentor_context()` contract and idempotent marked seed command; use recent saved concepts and linked latest events to build and validate boss questions; tag lesson fillers in Python; implement boss retry, defeat, completion, victory, and invalid-ticket status handling. Keep events append-only and statuses terminal once completed, defeated, or abandoned.
  Verify (mechanical): Check empty/player/seeded mentor results; verify the seed command is idempotent and does not overwrite player history; check every weak-spot marker maps to its saved concept and source event. Replay/expire victory tickets for completed and defeated sessions and confirm statuses stay terminal; invalidate a ticket for an in-progress session and confirm it becomes abandoned while its events remain linked. Confirm victory requires the dedicated screen and its return action.
  Learner check: Use seeded history to return to the mentor, start the boss, and inspect a weak-spot marker against the earlier missed question. Complete a boss win and verify the victory screen and return action.
  Commit: Consolidated checkpoint `4a00047` — `Complete mentor, boss, and review flows` (slices 3 and 4 were already implemented together in the working tree when resumed).
  Evidence: built and mechanically verified. `get_mentor_context()` is the only mentor retrieval path, the seed command is idempotent and refuses a non-empty database, every boss weak-spot marker resolves to a saved concept and source event, and terminal session statuses survive ticket replay and expiry. Checked by the automated suite and by a real-Chrome run of the whole journey on a temporary database.

- [x] **4. Review a weakness and finish the local demo path**
  Becomes usable: The learner can generate and answer a two-question review without changing original mistake history, and the full demo can be run locally at phone and desktop widths.
  Why now: Review depends on the saved concept and retrieval work from the kernel slice; the final pass then checks the complete approved journey and responsive presentation.
  PRD ref: `prd.md > The Core Journey` (steps 9–10), `prd.md > Features and Behavior > Reviewing a Weakness`, `prd.md > States and Boundaries`, `prd.md > Look and Feel`
  Spec ref: `spec.md > Where It Runs and How Someone Tries It`, `spec.md > Components > Lesson and question generation service`, `spec.md > Components > SQLite repositories`, `spec.md > Components > Templates, styles, and browser behavior`, `spec.md > Data Model`, `spec.md > AI Structured Schemas and Validation > Review payload`, `spec.md > Important Failure Modes`, `spec.md > File Structure`
  Build: Add the selected-concept review flow, exactly two validated questions, separately persisted review outcomes, and remaining screen/style details needed by the approved journey. Update the README with local setup and seeded demo steps. Do not add deployment or features outside the approved boundary.
  Verify (mechanical): Start from an empty database, follow setup and seed commands, and run the approved topic-to-lesson, battle, boss/victory, return/mentor, and review paths using the fake AI client. Confirm two review outcomes are stored separately, original mistake rows are unchanged, and the app remains usable at phone and desktop viewport sizes.
  Learner check: Run the seeded return and review flow, then inspect the app at a phone-width and desktop-width window. Note anything broken, confusing, or worth changing.
  Commit: Consolidated checkpoint `4a00047` — `Complete mentor, boss, and review flows` (slices 3 and 4 were already implemented together in the working tree when resumed).
  Evidence: built and mechanically verified. The review generates exactly two validated questions for one trusted saved concept, writes one row per answer into the separate `review_outcomes` table, and leaves every `mistake_events` row and every `weak_concepts.last_missed_at` untouched. The schema was extended from `user_version` 2 to 3 with only the new table, so an existing database is upgraded in place on the next start. Checked by the automated suite and by a real-Chrome run at 390 px and 1280 px with no horizontal overflow.
  Note: the implementation adds one module, `dejavu/services/review.py`, for the review state machine, which the file structure in `spec.md` did not anticipate. `templates/review.html` matches the approved structure.

## Hands-on Checkpoints

- [x] Early usable behavior explored — after slice 2, so feedback on the lesson-to-battle loop can shape mentor and boss presentation.
  Evidence: learner manually ran the live lesson-to-battle flow, played through the battle, lost at Round 3, and individually tested both defeat actions. `RETRY ROUND` restarted Round 3, and `RETURN TO CONSTRUCT` returned to the Construct screen. The learner approved Slice 2. Reload/mistake persistence was not part of the manual confirmation reported here.
- [ ] Final kick-the-tires exploration and feedback completed — after slice 4.
  Evidence so far: all 196 automated tests pass. Final manual exploration and learner feedback are still needed; the fake-mode server will use a separate disposable review database.

## Final Review

- [ ] Final review complete — feedback resolved and learner confirms ready to ship.
  Mechanical verification: `python -m unittest discover -s tests -v` — 196 tests passed. The restricted runner could not create SQLite files in Python temporary directories, so the suite was rerun successfully with local filesystem permission. Live Gemini was not re-tested in this pass.
  Pending: learner explores the running app, reports anything broken/confusing/worth changing, and explicitly confirms the proof of concept is ready after any requested fixes.

## Code Tour and App Map

- [ ] Learning activity complete — guided route, focused alternative, prior practice connected, or brief recap
- [ ] Optional edit and transfer reflection addressed — offered/declined/already covered/not applicable as appropriate
- [x] `devpost/app-map.html` generated from commit `4a00047`; relative source links and script-free offline content checked. A browser surface was unavailable for visual preview; map path shared with learner.

Activity and evidence: App map generated at `devpost/app-map.html`; its action trace follows `answer_battle_question` through `grade_answer`, `record_mistake_in_transaction`, and the battle feedback. Evidence includes `tests/test_battle_routes.py` and a passing 196-test suite. Learner code-tour activity and optional reflection remain to be addressed.
Route and stops: Reference route prepared in the app map; learner has not yet toured the source interactively.
Edit outcome: Not applicable; no optional wrap-up edit made.
Reflection: Not yet offered; keep personal response in the ignored profile only if volunteered.
Activity mode: Static reference map checked offline; no browser preview available.

## Revisions

- Resumed with slices 3 and 4 implemented but uncommitted in the working tree. Saved them as one reviewed recovery checkpoint (`4a00047`) instead of claiming separate slice commits that were not present in history. All 196 tests pass.
- Final hands-on review, learner sign-off, and learning wrap-up reflection are still pending; do not mark the build complete until these are done.
