# DEJAVU

DEJAVU is a local Flask learning game. The current build provides first-use identity, topic entry, a validated three-card lesson, the three-round regular battle with persistent mistake history, the returning-player mentor, the final boss built from the player's own saved weaknesses, and a focused weakness review for one saved concept.

## Run locally on Windows

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Keep `ENABLE_LIVE_GEMINI=false` until the Gemini key and data-use choice are confirmed. To try a deterministic sample lesson without making a network call, run:

```powershell
$env:DEJAVU_FAKE_AI = "true"
python -m flask --app app init-db
python -m flask --app app run --host 127.0.0.1
```

Then open `http://127.0.0.1:5000/`. The deterministic client returns sample lesson, battle, boss, and review content. Automated checks use controlled fake responses and never call Gemini.

## Seed a separate demo database

`seed-demo` creates one clearly marked prior session with three weak concepts and four linked mistake events. It writes only when the database has no learning sessions and refuses, with a non-zero exit status, if any session already exists. The app selects its database through the existing `DEJAVU_DATABASE` setting, so point that at a separate demo file before initializing or seeding:

```powershell
$env:DEJAVU_DATABASE = "instance/slice3-demo.sqlite3"
python -m flask --app app init-db
python -m flask --app app seed-demo
python -m flask --app app run --host 127.0.0.1
```

Keep the same environment variable set for the Flask process so the app reads the seeded demo database. Running `seed-demo` again refuses because the session already exists. To reset only the demo file, stop the app, remove `instance/slice3-demo.sqlite3`, and repeat the commands. Never remove `instance/dejavu.sqlite3`, which holds your normal local history.

Run the automated checks with the Python standard-library test runner:

```powershell
python -m unittest discover -s tests -v
```

The same `unittest` tests are also discoverable by pytest after installing the declared development dependency.

For live lessons, battle questions, boss questions and review questions, add your Gemini key to the local `.env` file and set `ENABLE_LIVE_GEMINI=true`. Keep `DEJAVU_FAKE_AI=false`, then restart Flask. `.env` is ignored by Git; never paste the key into source files or commit it. Review Google's current data-use terms before sending study material to the API.

## Demo runbook

Use a separate demo database so the recording never touches `instance/dejavu.sqlite3`. Run every command from the project folder.

**1. Select a temporary demo database**

```powershell
$env:DEJAVU_DATABASE = "instance/demo-run.sqlite3"
```

**2. Initialize it** (creates the tables; safe to repeat on an existing file)

```powershell
python -m flask --app app init-db
```

**3. Seed the demo history** (only works on a database with no learning sessions)

```powershell
python -m flask --app app seed-demo
```

**4a. Rehearsed demo with deterministic fake AI** - no network call, no key needed, always the same content

```powershell
$env:DEJAVU_FAKE_AI = "true"
$env:ENABLE_LIVE_GEMINI = "false"
python -m flask --app app run --host 127.0.0.1
```

**4b. Live demo with Gemini**

```powershell
$env:DEJAVU_FAKE_AI = "false"
$env:ENABLE_LIVE_GEMINI = "true"
python -m flask --app app run --host 127.0.0.1
```

`.env` already holds `GEMINI_API_KEY` and `GEMINI_MODEL`; the server reads them on startup. Never echo or screenshot the key.

**5. Stop the server and restore the environment**

Press `Ctrl+C` in the server window, then clear the session variables so the next command uses your normal database again:

```powershell
Remove-Item Env:DEJAVU_DATABASE
Remove-Item Env:DEJAVU_FAKE_AI
Remove-Item Env:ENABLE_LIVE_GEMINI
```

To discard the demo file completely, delete `instance/demo-run.sqlite3`. Never delete `instance/dejavu.sqlite3`.

Notes for the recording:

- Restart the server after any code or schema change. The app creates missing tables on startup, so a restart is what applies a new schema to an existing database file.
- The live provider sometimes returns a transient `503` ("this model is currently experiencing high demand"). The app shows the recoverable "Download failed" message and keeps the topic editable, so press `DOWNLOAD LESSON` again.
- The Gemini free tier allows a limited number of requests **per day, per model** (20 for the models used here). One full live demo run needs about five requests: one lesson, one battle set, two boss sets and one review set. When the daily quota is used up the provider answers `429 RESOURCE_EXHAUSTED`; the app then says so instead of pretending a retry will help. The quota resets after roughly 24 hours, and the quota is counted separately for each model, so pointing `GEMINI_MODEL` at a different available model restores live generation. `gemini-3.5-flash-lite` was verified end to end (lesson, battle, boss and review) when `gemini-3.8-flash` was quota-blocked.
- Rehearse with `DEJAVU_FAKE_AI=true` first. It uses no quota and always produces the same content.
- The seeded demo history already contains the weak concepts, so the mentor, the boss weak spots and the two-question review are all reachable without playing a battle first.
