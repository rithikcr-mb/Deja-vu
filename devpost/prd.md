---
doc: prd
status: approved
---

# DEJAVU — Product Requirements

DEJAVU is a locally runnable, Matrix-inspired AI learning game for short technical revision sessions: a student enters a topic, reads a short AI-generated lesson, fights turn-based battles, and faces a final boss built from their own saved mistakes.
Source: `scope.md > The Unique Kernel`, `scope.md > The Core Loop`.

This document defines what the player sees, does, and gets back. It stays inside the approved POC boundary; it does not describe stack, storage, or architecture.

## The Core Journey

1. **Enter the Construct.** The app opens on a dark, Matrix-inspired initialization screen: subtle green digital rain, terminal text, and a short loading sequence. The sequence is short and skippable or time-limited — the effects are enhancements, never a prerequisite.
2. **First visit only — identity.** No saved display name is found, so the screen shows `IDENTITY NOT FOUND` followed by `What should I call you?`. The player types a name and confirms. It is saved locally to SQLite (no account, password, or cloud step). A brief welcome uses the supplied name, then the app moves to the main Construct screen.
3. **Request a lesson.** On the main Construct screen the player types a topic and presses `Download`. Input is validated before any AI call (see *Requesting a Lesson*).
4. **Read the lesson.** The topic becomes the lesson heading and all three cards are shown at once — core idea, how it works, practical example — in clear, student-friendly language. The player reads at their own pace; no card-by-card advancing.
5. **Start the fight.** A prominent `INITIATE COMBAT` button begins the turn-based battle using questions generated for that lesson. It is enabled only once all three cards have passed validation.
6. **Fight three rounds.** Four-option multiple-choice questions, one at a time. Correct answers damage the enemy; wrong answers cost health, reveal the correct answer with a concise explanation, and a distinct mistake event is saved immediately and associated with its weak concept in SQLite.
7. **Face the final boss.** A separate encounter that attacks with harder variations of the player's own saved weak concepts, visibly marked as their weak spots. If nothing was missed, all boss questions come from the current lesson and none is labelled a personal weakness.
8. **Victory.** Defeating the boss shows a dedicated, concise win screen that makes beating the player's own weaknesses feel earned, optionally summarising the weak spots overcome from actual session data, and offering `RETURN TO CONSTRUCT`.
9. **Return later.** On reload or reopen, the mentor greets the player by name and names a real weak concept from saved history through the approved retrieval tool. The player can `REVISIT WEAKNESS` or `DOWNLOAD A NEW TOPIC` — continuing a journey rather than restarting.

## Screens and Layout

- **Construct initialization** — full-screen dark overlay: green digital rain, terminal text, short loading sequence. Skippable or time-limited.
- **Identity prompt** (first visit) — `IDENTITY NOT FOUND`, then `What should I call you?` with a text input and confirm action. Single-purpose screen.
- **First-visit welcome** — brief message using the supplied name, then transition to the main Construct screen.
- **Main Construct screen** — the topic input, the `Download` button, and space for inline validation/error messages directly beneath the input.
- **Lesson screen** — topic as heading, all three lesson cards visible together, `INITIATE COMBAT` at the bottom. Desktop: three-card layout when readable. Phone-sized: cards stack vertically.
- **Battle screen** — the question, four options, player health, enemy health, and current round/round progress. `LOCK ANSWER` submits; `NEXT QUESTION` continues after a result is shown.
- **Round result** — brief summary with `CONTINUE` to the next round.
- **Defeat screen** — `RETRY ROUND` (or `RETRY BOSS`) and `RETURN TO CONSTRUCT`.
- **Final boss screen** — same battle layout, plus the weak-spot marker area above the question.
- **Victory screen** — shown after the boss is defeated: a clear victory message, an optional summary of weak spots overcome drawn from actual session data, and a `RETURN TO CONSTRUCT` action.
- **Returning-player mentor screen** — the mentor character, greeting using the saved name, the signature line, one primary weakness (plus at most one secondary), last session topic and date/time when they exist, and the actions `REVISIT WEAKNESS` and `DOWNLOAD A NEW TOPIC`. Not a statistics dashboard.
- **Review screen** — the selected saved weak concept, a concise explanation, the original missed-question context when available, two fresh practice questions, and closing actions `REVIEW ANOTHER WEAKNESS` and `DOWNLOAD A NEW TOPIC`.
- **Mentor, corner presence** — the same mentor character appears consistently across the first-visit, returning-player, and review screens.

The layout is responsive and remains usable at desktop and phone-sized widths.

## Look and Feel

Direction established with the learner; `4-spec` converts this into implementable styling and should not need to ask again.

- **Palette:** black / dark background, terminal green as the primary interface colour, restrained red reserved for weak-spot warnings. High contrast and readable.
- **Mentor character:** an original, recognizable stylized human-like Construct guide — dark futuristic outfit, restrained green digital accents, calm, intelligent, slightly mysterious. It should feel native to DEJAVU's Matrix-inspired world, not a copy of a film character, and it must not be an abstract terminal avatar or a generic chatbot icon. Same character across first-visit, returning-player, and review screens.
- **Mentor animation:** start with two lightweight states — idle and speaking — using subtle blinking, expression changes, or glow. A thinking state is deferred. Elaborate animation or custom sprite production must not block the core learning and memory features.
- **Typography, three roles:**
  1. A distinctive futuristic **display font** for major headings and the signature line `You have been here before.`
  2. A clean **monospace** for terminal messages, system status, health bars, round indicators, and diagnostic labels.
  3. A readable **sans-serif** for lesson cards, quiz questions, explanations, and longer mentor messages.
- **Priority:** readability and mobile responsiveness over decorative effects. Visual effects are progressive enhancements, never blockers.

## Features and Behavior

### Entering the Construct and Player Identity

Develops `scope.md > The Core Loop` (steps 1–2) and `scope.md > Player Identity`.

- First visit: after the initialization sequence, show `IDENTITY NOT FOUND` and `What should I call you?`. The player enters a display name and confirms; it is saved to local SQLite. No account, password, cloud sync, or multi-device support.
- Show a brief welcome using the supplied name, then move to the main Construct screen.
- The first visit must not pretend to remember prior learning. Returning-player greetings use only real persisted history through the approved retrieval tool.
- The stored name is cosmetic only. It is never used to fabricate or infer learning history.
- The opening sequence stays short and skippable or time-limited so it never obstructs the learning loop.

- [ ] A first-time player can complete name entry and reach the main Construct screen.
- [ ] Reloading after first use does not re-prompt for identity.

### Requesting a Lesson

Develops `scope.md > The Core Loop` (step 3) and `scope.md > The POC Boundary` (topic input, structured output, error state).

- The player types a topic and presses `Download`.
- **Empty input** (empty or whitespace only): do not call the AI. Stay on the topic screen, focus the input, and show inline: `Enter a topic to begin your download.`
- **Clearly invalid or unlearnable input:** show a recoverable inline error saying the Construct couldn't identify a learnable topic, with examples such as Process Scheduling and DBMS Normalization. Keep the entered text editable and retryable. Do not navigate away or start a battle.
- **Valid but unfamiliar or specific topics:** do not reject a topic merely for being narrow or unfamiliar. Attempt generation when reasonable.
- **Generation failure or invalid structured output:** show a distinct retryable error — `Download failed. Your lesson wasn't created. Try again.` — and preserve the entered topic.
- Lesson content is never fabricated to conceal a generation or validation failure.

### AI-Generated Content Reliability

- Every AI-generated lesson, battle question and explanation, boss question and explanation, and review question and explanation must use structured output that is validated before it is shown or used for gameplay. Validation covers the required fields, types, answer options, and answer reference needed by that content.
- If generation fails or its output fails validation, show a clear, recoverable error with an action to retry generation. Do not show partial or fabricated content, apply gameplay effects, or lose the player's current context.
- For a lesson, preserve the entered topic and use the `Download failed` message above. For regular battle questions, do not start combat until the required questions are valid; allow retry from the lesson. For boss questions, keep the player at the boss encounter and allow retry without changing health or saved mistakes. For review questions, keep the selected weakness and allow retry without changing review outcomes or mistake history.
- A failed explanation generation must leave the answer result recoverable and must not silently advance or apply the same answer again.

- [ ] Pressing `Download` with an empty box performs no AI call and shows the empty-input message.
- [ ] A failed generation shows the retry message with the topic text still present.
- [ ] The lesson screen and `INITIATE COMBAT` appear only after all three cards pass validation.

### Reading the Lesson

Develops `scope.md > The Core Loop` (step 3) and `scope.md > The POC Boundary`.

- The topic is the lesson heading. All three cards are shown together, each covering a core idea, how something works, or a practical example, in clear student-friendly language.
- No card-by-card advancing and no extra quiz, tutorial, or navigation step.
- `INITIATE COMBAT` sits at the bottom and starts the battle using questions generated for this lesson.
- Desktop shows a three-card layout when it stays readable; phone-sized screens stack the cards vertically.

- [ ] All three cards are visible at once after a successful generation.
- [ ] Clicking `INITIATE COMBAT` starts a battle with questions drawn from this lesson.
- [ ] The lesson screen remains readable and correctly stacked at phone width.

### The Battle — Three Regular Rounds

Develops `scope.md > The Core Loop` (steps 4–5) and `scope.md > What "Working" Looks Like`.

Rules are fixed and simple enough to understand and test:

- Three regular rounds, **four questions per round** (up to 12 questions per battle).
- Player starts at **100 HP**, carried across all regular rounds (not reset between rounds).
- Each round's enemy starts at **75 HP**, resetting each round.
- **Correct answer:** 25 damage to the enemy. Four options, one question at a time, submit with `LOCK ANSWER`; a submitted answer cannot be changed.
- **Incorrect answer:** 20 damage to the player, reveal the correct answer with a concise explanation, immediately record this individual mistake event in SQLite, and associate it with the relevant weak concept.
- A round **ends early** when enemy HP reaches zero — no further questions and no further damage are applied. Otherwise the round resolves after the fourth question.
- After a round, show a brief round result and a `CONTINUE` action, unless the player has already won or lost.
- The screen shows the question, four options, player health, enemy health, and round progress.
- After each answer, a `NEXT QUESTION` action lets the player read the explanation before continuing — the app never auto-advances past an explanation.
- **Defeat** occurs when player HP reaches zero: stop the battle and show a defeat screen with `RETRY ROUND` and `RETURN TO CONSTRUCT`.
- Retrying restarts the current round with the enemy at 75 HP and restores the player's health to what it was at the beginning of that round. It must not delete or duplicate individual mistake events already saved.
- Question **difficulty escalates across rounds** through the generated questions (round 3 is harder than round 1). The regular-round damage and health values stay fixed.
- Completing all three regular rounds leads to the final boss.

- [ ] Each wrong answer produces a distinct, traceable mistake event in SQLite, associated with its weak concept; repeated mistakes may contribute to the same concept without overwriting or merging their event records.
- [ ] A wrong answer shows the correct answer and an explanation before `NEXT QUESTION` appears.
- [ ] Correct answers reduce enemy HP by 25; wrong answers reduce player HP by 20.
- [ ] A round ends immediately when enemy HP reaches zero.
- [ ] Reaching 0 player HP shows the defeat screen, and `RETRY ROUND` restores round-start health without deleting saved mistakes.

### The Final Boss

Develops `scope.md > The Unique Kernel`, `scope.md > The Core Loop` (step 6), and `scope.md > What "Working" Looks Like` (the boss beat).

- **Boss health: 100.** Correct answer deals 25 damage (four correct answers can win).
- **Up to five questions.** The boss is defeated as soon as its HP reaches zero.
- Questions prioritise harder variations of concepts the player actually missed, derived from saved weak-concept records.
- If fewer than five suitable weak concepts exist, remaining slots are filled with harder questions from the current lesson. Weaknesses are never invented.
- If no weak concepts exist, all boss questions come from the current lesson and none is labelled a weak spot.
- **Player health restores to 100** at the start of the boss encounter (a clean final encounter).
- Wrong answers cost 20 player HP, show the correct answer with an explanation, and immediately record a distinct mistake event associated with the relevant weak concept.
- **Defeat** shows `RETRY BOSS` and `RETURN TO CONSTRUCT`. Retrying restores player and boss HP to 100 without deleting saved mistakes.
- **Weak-spot marker:** questions derived from a saved weakness display a clear Matrix-style warning — `WEAK SPOT DETECTED` — followed by `PREVIOUSLY MISSED: [original saved concept]` and a short line explaining that this question targets that concept. Use restrained red against the green interface.
- Questions derived from the current lesson instead of a saved weakness display a neutral `ADAPTIVE TEST` label and are never labelled personal weaknesses.
- The marker is grounded in the actual saved weak-concept record used to generate the question. The original concept stays linked to its harder variation, and the link is preserved through answer resolution and retries. The AI never invents the player's past mistakes.

- [ ] The final boss uses a harder variation of a saved missed concept and identifies it as a weak spot.
- [ ] With no saved mistakes, boss questions carry `ADAPTIVE TEST` and no weak-spot label.
- [ ] Boss defeat shows `RETRY BOSS`, and retrying restores both HP pools without deleting saved mistakes.

### After the Final Boss — Victory

Develops `scope.md > The Unique Kernel` and `scope.md > The Core Loop` (winning feels earned because you beat your own weaknesses).

- Defeating the boss leads to a dedicated, concise win screen rather than returning straight to the Construct.
- Show a clear victory message that makes overcoming the player's weaknesses feel earned.
- Optionally summarise the weak spots overcome, using actual session data only.
- The win screen must not fabricate progress or claim a weakness was overcome unless the saved session data supports it.
- Provide a clear `RETURN TO CONSTRUCT` action.
- All learning history and review outcomes are preserved across victory.

- [ ] Defeating the boss shows the victory screen with a `RETURN TO CONSTRUCT` action.
- [ ] Any weak spots listed as overcome correspond to real saved session data; with no supported data, no claim is shown.
- [ ] Returning to the Construct after victory leaves all learning history and review outcomes intact.

### Returning-Player Mentor Screen

Develops `scope.md > The Core Loop` (why Arjun returns) and `scope.md > What "Working" Looks Like` (the return beat).

- Greet the player using the locally saved display name, and show the signature line `You have been here before.`
- Retrieve the player's actual weak concepts through the approved retrieval tool. Feature **one primary weakness** prominently with a concise explanation grounded in the saved concept and mistake context; optionally show **one secondary** weakness. No long list.
- Show the last session's topic and its saved date/time when that information exists.
- Offer two main actions: `REVISIT WEAKNESS` and `DOWNLOAD A NEW TOPIC`.
- If no weak concepts exist, say so honestly and offer a new topic. If there is no session history, use the first-time welcome instead.
- Never fabricate a memory or a session date.

- [ ] After reloading or reopening, the mentor retrieves accurate learning context through the approved tool and names a real weak concept.
- [ ] The mentor never shows a weak concept or date that is not in the database.

### Reviewing a Weakness

Develops `scope.md > The Core Loop` (why Arjun returns) and `scope.md > What "Working" Looks Like`.

- `REVISIT WEAKNESS` opens a focused revision screen for the selected saved weak concept: the concept, a concise explanation, and the original missed-question context when available.
- Present **two fresh four-option multiple-choice practice questions** targeting that concept. After each answer, show whether it was correct with a concise explanation.
- At completion, offer `REVIEW ANOTHER WEAKNESS` and `DOWNLOAD A NEW TOPIC`.
- Review stays separate from the full battle and the final boss.
- Reviewing a concept must not erase its original mistake history. Review outcomes are persisted separately so every original mistake event and later improvement remain distinguishable.

- [ ] `REVISIT WEAKNESS` shows the saved concept with two fresh practice questions.
- [ ] Completing a review leaves the original weak-concept record intact and records a distinguishable review outcome.

### Memory Integrity

Develops `scope.md > The POC Boundary` (memory-integrity and seeded-history requirements).

- Every weak concept is traceable to one or more individual incorrect-answer events or clearly identified seeded demo records. Repeated events remain individually distinguishable even when grouped under one weak concept.
- Boss questions derive from those saved weak concepts. Mentor context comes through the same approved retrieval tool used in normal operation.
- No hardcoded personalised greetings, no fabricated memory, no demo-only retrieval path.
- Seeded demo records are clearly identifiable as seeded data, while flowing through the same normal retrieval, boss-generation, and gameplay code paths as genuine history. Seeding prepares data only; it never bypasses the code that reads it.

- [ ] Every displayed weakness can be traced to a stored record and its source (answered or seeded).
- [ ] Demo seeding uses the same code path a normal player hits.

## States and Boundaries

- **First use** — no identity and no history: initialization sequence → `IDENTITY NOT FOUND` → name entry → welcome → main Construct screen. Nothing is claimed about prior learning.
- **Empty topic input** — no AI call; input refocused, inline message `Enter a topic to begin your download.`
- **Invalid / unlearnable topic** — recoverable inline error with examples; text preserved for editing; no navigation, no battle.
- **Generation or validation failure** — show a recoverable retry error appropriate to the content being generated; preserve the topic, selected weakness, or encounter context; do not show partial or fabricated content, apply gameplay effects, or discard saved history. For lessons, use `Download failed. Your lesson wasn't created. Try again.` and keep `INITIATE COMBAT` disabled until valid lesson content exists.
- **Round lost / battle defeat** — battle stops, defeat screen with `RETRY ROUND` / `RETURN TO CONSTRUCT`. Retry restores round-start health and never deletes saved mistakes.
- **Boss defeat** — defeat screen with `RETRY BOSS` / `RETURN TO CONSTRUCT`; retry restores both HP pools and keeps saved mistakes.
- **Boss victory** — a dedicated win screen with a victory message and optional, data-backed summary of weak spots overcome; `RETURN TO CONSTRUCT` leaves all learning history and review outcomes intact.
- **No saved weak concepts on return** — mentor says so honestly and offers a new topic; no weakness is invented.
- **No session history** — first-time welcome is used instead of a returning-player greeting.
- **No saved mistakes before the boss** — boss draws all questions from the current lesson and labels none as a personal weak spot.
- **Persistence** — the display name, individual mistake events and their associated weak concepts, the last session's topic and timestamp, and review outcomes persist in local SQLite across reloads and visits on the same machine.
- **Not persisted between sessions** — an in-progress battle or boss sequence is not resumed after closing the app; the player starts a fresh topic or a review on their next visit.
- **Duplicate-safety** — completing, losing, or retrying a battle or boss encounter must not duplicate or lose individual mistake events; each submitted wrong answer is recorded once, and concept-level summaries may aggregate related events without replacing them.
- **Boundaries** — one local player per machine; no accounts, cloud sync, or multi-device view. Seeded demo data is identifiable and never bypasses normal retrieval.

## Product Decisions

- Construct-first, name-before-topic on first visit — identity is established once, cheaply, and never faked.
- Lesson shown as three cards at once with a single `INITIATE COMBAT` action — the learner wants reading at their own pace, with no extra tutorial or navigation step.
- Four-option multiple-choice with `LOCK ANSWER` then `NEXT QUESTION` — keeps grading unambiguous and gives time to read explanations; the app never auto-advances past an explanation.
- Fixed battle numbers (3 rounds × 4 questions, 100 player HP carried, 75 enemy HP per round, 25/−20 damage) with escalation in the generated questions — simple to understand, simple to test.
- Each individual wrong-answer event is saved immediately and associated with a weak concept; concept-level summaries can aggregate related events while preserving the event history.
- Retry restores health without deleting saved mistakes — repetition should not erase learning history.
- Final boss is a separate encounter with restored player HP and a 100 HP pool — a clean, winnable final test built from the player's own weaknesses.
- Weak-spot marker (`WEAK SPOT DETECTED` + `PREVIOUSLY MISSED: [concept]`) in restrained red, with a neutral `ADAPTIVE TEST` label for lesson-derived questions — makes the core kernel visible without ever inventing a weakness.
- Mentor screen is a focused relationship moment (one primary weakness, optional secondary, last topic and date), not a statistics dashboard.
- Review is a separate, two-question focused screen — reinforces a concept without duplicating the battle, and keeps original mistakes distinguishable from later improvement.
- Original 2D mentor character with idle and speaking states — recognisable and native to the world, but animation is never a blocker.
- Three-role typography (display / monospace / sans-serif) on the established dark-green palette — atmosphere with readability first.
- Topic validation is cheap and honest: no AI call for empty input, recoverable errors for invalid topics, and no fabricated lesson content to hide a failure.
- All AI-generated lesson, battle, boss, and review content, including explanations, is validated structured output with recoverable generation and validation errors.

## What We're Building

- Construct initialization screen with skippable or time-limited loading
- First-visit identity prompt and welcome, name persisted locally
- Main Construct screen with topic input, validation, and recoverable error states
- AI-generated three-card lesson with structured-output validation and a retryable failure state
- Three-round turn-based battle with the fixed numbers above, explanations, and `LOCK ANSWER` / `NEXT QUESTION`
- Immediate, distinct mistake-event persistence on wrong answers, associated with aggregatable weak concepts and duplicate-safe across retries and defeats
- Final boss encounter with weak-spot and `ADAPTIVE TEST` markers, linked to real saved records
- Returning-player mentor screen driven by real history through the approved retrieval tool
- Focused review screen with two practice questions per weakness and distinguishable review outcomes
- Persistent learning history in local SQLite, surviving reloads and visits on the same machine
- Seeded prior session for demo preparation, flowing through normal code paths
- Original 2D mentor character with idle and speaking states
- Matrix-inspired visual identity with the three-role typography
- Responsive layout for desktop and phone-sized screens

## Deferred From the POC

- **Thinking mentor state and full animation set** (idle/thinking/speaking) — the build starts with idle and speaking only; a thinking state is nice but not required to prove the kernel.
- **Sophisticated adaptive difficulty** — regular rounds use a small, fixed escalation in the generated questions instead.
- **Multiple enemy types and elaborate boss variations** — one enemy per round plus the final boss is enough for the demo.
- **Optional HTML visual companion for planning review** — Markdown stays canonical; not needed to prove the product.
- **Accounts, cloud sync, multi-device** — local SQLite only; not needed to prove mistake-memory.

## Possible Later Enhancements

- A thinking/animation state and richer mentor expression driven by the player's actual history.
- Adaptive difficulty that reacts to the player's recent accuracy rather than a fixed escalation curve.
- A wider set of enemy types and boss patterns built on the same weak-concept data.
- Study summaries or progress views once the core loop is proven.

## Non-Goals

- Accounts, passwords, cloud sync, or multi-device support — local, single-player only.
- Leaderboards, XP, streaks, or progression systems — extra systems that don't touch the kernel.
- Sound, music, sprite artwork, or cinematics — cost without proof value.
- Teaching a full syllabus or many topics in one session — one topic per session keeps the lesson short and the demo tight.
- An abstract terminal avatar or generic chatbot icon in place of the original mentor character.
- Hardcoded personalised greetings, fabricated memory, or a demo-only retrieval path.

## Open Questions

- **Retrieval tool shape, its input/output contract, and the exact database structure** — *deliberately left to `4-spec`.*
- **Seeding mechanism for demo history** (how seeded records are marked and prepared) — *left to `4-spec`*, provided it never bypasses normal code paths.
- **Mentor asset approach** (how the 2D character and its two states are produced without blocking the core loop) — *left to `4-spec`.*
