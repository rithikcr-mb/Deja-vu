# DEJAVU

DEJAVU is a local Flask learning game. The current build provides first-use identity, topic entry, a validated three-card lesson, and the three-round regular battle with persistent mistake history.

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

Then open `http://127.0.0.1:5000/`. The deterministic client returns sample lesson and battle content. Automated checks use controlled fake responses and never call Gemini.

Run the automated checks with the Python standard-library test runner:

```powershell
python -m unittest discover -s tests -v
```

The same `unittest` tests are also discoverable by pytest after installing the declared development dependency.

For live lessons and battle questions, add your Gemini key to the local `.env` file and set `ENABLE_LIVE_GEMINI=true`. Keep `DEJAVU_FAKE_AI=false`, then restart Flask. `.env` is ignored by Git; never paste the key into source files or commit it. Review Google's current data-use terms before sending study material to the API.
