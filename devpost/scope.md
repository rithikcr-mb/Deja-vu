---
doc: scope
status: approved
---

# DEJAVU

A Matrix-inspired AI learning game: short AI-generated lessons, turn-based battles, and a mentor that remembers what you got wrong.

## The Unique Kernel

**Mistakes aren't just points lost — they become the boss's ammunition.** A wrong answer is saved as a *weak concept*, and the final boss attacks you with harder variations of the concepts you personally missed, visibly marked as your weak spots. On your return, the mentor names a real weakness from your history.

Remove that and DEJAVU is just another quiz app. Everything else is atmosphere in service of it.

## Who It's For

**Arjun** — a final-year BCA student with an exam coming up and ten minutes between classes. He needs to revise something technical: process scheduling, DBMS normalization, AI concepts.

What he does today: rereads class notes and PDFs (passive), hunts for YouTube videos (slow to find), or uses ordinary quiz apps (tells him right/wrong, then stops — he can repeat the same mistake with no path back to it). He doesn't want another full course or a study planner. He wants to understand a topic quickly, test himself, and *find out what he hasn't understood*.

Arjun is a representative user, not a claim that everyone studies the same way — he's grounded in the learner's own experience of this problem.

## The Core Loop

1. **Enter the Construct.** Black screen, green digital rain, terminal text, a short loading sequence.
2. **Type a topic** and press Download.
3. **Read a short lesson** — three cards, each teaching a core idea, how it works, or a practical example.
4. **Fight.** A turn-based battle where questions come from the lesson and difficulty escalates across rounds. Correct → damage the enemy. Wrong → lose health, and see an explanation of the correct answer.
5. **The mistake is banked as a concept**, not merely a lost point.
6. **Face the final boss** — harder variations of your own missed concepts. If you missed nothing, the boss gives a **harder test drawn from the current lesson** instead; no previous weakness is invented. Winning feels earned because you beat your own weaknesses.

Why Arjun comes back: the system remembers him. Tomorrow the mentor greets him by name and points at a concept he actually struggled with, and he can review it or start another session. It continues a journey rather than restarting.

## Player Identity

**A display name, asked once and persisted locally in SQLite.** That is the whole identity system.

- No accounts, passwords, cloud sync, or multi-device support.
- On return, the mentor may use the locally stored name for the greeting.
- The name is **cosmetic only**: all learning context must still come from the approved database-retrieval tool, and the name must never be used to fabricate or infer learning history.

## Inspiration & Identity

The Matrix is the primary reference (https://en.wikipedia.org/wiki/The_Matrix): digital rain, the Construct, terminal text, a world that feels like a system you're inside rather than an ordinary website. Dark, immersive, restrained glitch effects, enemy health bars, simple character animation.

Design conviction: *"the game mechanics serve a real purpose: mistakes should matter, the system should remember what I struggle with, and returning should feel like continuing a journey rather than starting over."*

Signature line the learner wants associated with the project: **"You have been here before."**

Visual effects are progressive enhancements — never blockers for core functionality.

## Why This Matters to the Learner

DEJAVU is both a portfolio proof of concept and a chance to practice a repeatable plan-first workflow. The learner's stated measure of success: *"not just whether DEJAVU works, but whether I understand what was built, why decisions were made, and how to repeat this workflow in future projects."* The failure modes they want to avoid are scope creep, losing track of decisions, and an agent changing already-agreed choices.

## What "Working" Looks Like

A locally runnable Flask app. A stranger can:

**Session 1** — type a topic, read the three cards, win or lose a battle, get an explanation on a wrong answer, and have that weak concept saved.

**Session 2 (later, same machine)** — reload or reopen the app, and the mentor greets them with context pulled from saved history, naming a weak concept from *their* earlier session. They can review it or start a new battle.

**The two demo beats** (both real, testable, repeatable — no fabricated memory):

- *The return.* Seeded previous session → app reloaded → mentor greets the returning player using the real saved weak concept → review or new battle. Proves memory survives beyond the browser session.
- *The boss.* A question the player previously got wrong returns as a harder variation, visibly marked as a weak spot. Proves mistakes change gameplay, not just storage.

Demo preparation may seed the database *before* recording, but retrieval and gameplay use the same implemented code path a normal player hits. Any setup mechanism stays out of the normal player experience. The mentor does **not** hardcode a personalized greeting.

## The POC Boundary

**In — needed to prove the kernel and the loop:**

- Topic input and an AI-generated three-card lesson
- Turn-based battle: correct answers damage enemies; incorrect answers cost health and show explanations
- Weak concepts persisted in SQLite — concepts, not merely a list of wrong answers
- A final boss using harder variations of the player's own missed concepts, visibly marked as weak spots
- Persistent learning history across reloads and new visits on the same machine
- A returning-player greeting driven by actual database history through the mentor's **single approved retrieval tool**
- A seeded prior session for reliable demo preparation
- A basic Matrix-inspired visual identity and a simple, readable 2D mentor
- Responsive layout for phone-sized and desktop screens
- AI-generated lessons, questions, explanations, and boss variations produced as **predictable structured output**, with basic validation and a clear error state if generation fails

**Memory-integrity requirement (explicit):** every weak concept must be traceable to an actual incorrect answer or a clearly identified seeded demo record. Boss questions must derive from those saved weak concepts. Mentor context must come through the same approved retrieval tool used in normal operation. **No hardcoded personalized greetings, no fabricated memory, no demo-only retrieval path.**

**Seeded demo history:** seeded records must be **clearly identifiable as seeded data** in the database, while flowing through the same normal retrieval, boss-generation, and gameplay code paths as genuine session history. Seeding prepares data only — it never bypasses the code that reads it.

**Acceptance tests:**

1. An incorrect answer produces a traceable weak-concept record in SQLite.
2. The final boss uses a harder variation of a saved missed concept and identifies it as a weak spot.
3. After reloading or reopening the application, the mentor retrieves accurate learning context from the database through the approved tool.
4. The same core flow remains usable at desktop and phone-sized widths.

If time runs short, **simplify visual polish first.** Never cut persistent memory, mentor retrieval, or the mistake-driven boss.

## Later

Real features, deliberately deferred:

- Full mentor animation states (idle / thinking / speaking) — start with a simple, readable 2D figure with a couple of states
- Sophisticated adaptive difficulty — start with a small, fixed escalation across rounds
- Multiple enemy types and elaborate boss variations
- Optional HTML visual companion for planning review, generated from the approved plan (Markdown stays canonical)

## Explicitly Cut

Named, each with a real reason:

- **Accounts, cloud sync, multi-device** — local SQLite only; not needed to prove mistake-memory, and the learner already excluded it
- **Leaderboards, XP, streaks, progression systems** — extra systems that don't touch the kernel
- **Sound, music, sprite artwork, cinematics** — cost without proof value
- **Teaching a full syllabus or many topics in one session** — one topic per session keeps the lesson short and the demo tight
