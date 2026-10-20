"""Browser routes for identity, topic entry, and the validated lesson."""

from __future__ import annotations

import secrets
import sqlite3
import time
from uuid import uuid4

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from dejavu.db.repository import (
    abandon_if_in_progress,
    create_learning_session,
    finish_session_if_in_progress,
    get_profile,
    record_mistake,
    save_first_display_name,
)
from dejavu.services.battle import (
    advance_after_answer,
    apply_answer,
    battle_view,
    current_question,
    grade_answer,
    new_encounter,
    retry_round,
)
from dejavu.services.ai_client import (
    FakeGeminiClient,
    GeminiLessonClient,
    LessonProviderError,
    LiveGenerationDisabled,
    MissingApiKey,
)
from dejavu.services.content import (
    InvalidBattleContent,
    InvalidLessonContent,
    validate_battle_set,
    validate_lesson_result,
)

main = Blueprint("main", __name__)
UNLEARNABLE_MESSAGE = (
    "The Construct couldn't identify a learnable topic. Try Process Scheduling "
    "or DBMS Normalization, or edit your topic."
)
DOWNLOAD_ERROR = "Download failed. Your lesson wasn't created. Try again."


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="dejavu-page-ticket")


def _client():
    configured_client = current_app.config.get("LESSON_CLIENT")
    if configured_client is not None:
        return configured_client
    if current_app.config["DEJAVU_FAKE_AI"]:
        return FakeGeminiClient()
    if not current_app.config["ENABLE_LIVE_GEMINI"]:
        raise LiveGenerationDisabled(
            "Live Gemini generation is disabled until its key and data-use tier are confirmed."
        )
    api_key = current_app.config["GEMINI_API_KEY"].strip()
    if not api_key:
        raise MissingApiKey("GEMINI_API_KEY is not configured in the local .env file.")
    return GeminiLessonClient(api_key, current_app.config["GEMINI_MODEL"])


def _abandon_run(run_id: str | None, session_id: str | None = None) -> None:
    runs = current_app.extensions["dejavu_runs"]
    run = runs.pop(run_id, None) if run_id else None
    linked_session_id = session_id or (run and run["session_id"])
    if linked_session_id:
        abandon_if_in_progress(current_app.config["DATABASE"], linked_session_id)


def _consume_page_ticket(ticket: str) -> dict | None:
    """Consume a signed, one-use ticket; invalid tickets cannot resume a run."""
    payload = None
    expired = False
    try:
        payload = _serializer().loads(ticket, max_age=300)
    except SignatureExpired:
        expired = True
        try:
            payload = _serializer().loads(ticket)
        except BadSignature:
            payload = None
    except BadSignature:
        payload = None

    ticket_ledger = current_app.extensions["dejavu_page_tickets"]
    entry = ticket_ledger.get(payload.get("nonce")) if isinstance(payload, dict) else None
    run_id = session.get("run_id")
    run = current_app.extensions["dejavu_runs"].get(run_id)
    valid = bool(
        not expired
        and entry
        and not entry["consumed"]
        and entry["expires_at"] > time.time()
        and entry["run_id"] == run_id
        and run
        and run["session_id"] == payload.get("session_id")
    )
    if valid:
        entry["consumed"] = True
        return run

    if isinstance(payload, dict):
        linked_session = payload.get("session_id")
        linked_run = entry["run_id"] if entry else run_id
        _abandon_run(linked_run, linked_session)
    elif run_id:
        _abandon_run(run_id)
    session.pop("run_id", None)
    return None


def _issue_page_ticket(run_id: str, session_id: str) -> str:
    nonce = secrets.token_urlsafe(24)
    current_app.extensions["dejavu_page_tickets"][nonce] = {
        "run_id": run_id,
        "session_id": session_id,
        "expires_at": time.time() + 300,
        "consumed": False,
    }
    return _serializer().dumps({"session_id": session_id, "nonce": nonce})


def _active_run() -> tuple[str | None, dict | None]:
    run_id = session.get("run_id")
    return run_id, current_app.extensions["dejavu_runs"].get(run_id)


def _cached_action_redirect(run_id: str, run: dict, action_id: str):
    cached = run["actions"].get(action_id)
    if cached is None:
        return None
    try:
        payload = _serializer().loads(cached["ticket"])
    except BadSignature:
        payload = None
    ledger = current_app.extensions["dejavu_page_tickets"]
    entry = ledger.get(payload.get("nonce")) if isinstance(payload, dict) else None
    if entry and not entry["consumed"] and entry["expires_at"] > time.time():
        return redirect(url_for(cached["endpoint"], ticket=cached["ticket"]), code=303)
    _abandon_run(run_id)
    session.pop("run_id", None)
    return redirect(url_for("main.construct"), code=303)


def _complete_action(run_id: str, run: dict, action_id: str):
    ticket = _issue_page_ticket(run_id, run["session_id"])
    run["actions"][action_id] = {
        "ticket": ticket,
        "endpoint": "main.battle",
    }
    return redirect(url_for("main.battle", ticket=ticket), code=303)


def _render_lesson(run: dict, error: str | None = None):
    return render_template(
        "lesson.html",
        topic=run["topic"],
        cards=run["lesson"].cards,
        fake_mode=current_app.config["DEJAVU_FAKE_AI"],
        battle_setup_id=run["battle_setup_id"],
        battle_error=error,
    )


def _render_battle(run: dict, error: str | None = None):
    return render_template(
        "battle.html",
        topic=run["topic"],
        battle=battle_view(run["battle"]),
        fake_mode=current_app.config["DEJAVU_FAKE_AI"],
        error=error,
    )


@main.get("/")
def index():
    profile = get_profile(current_app.config["DATABASE"])
    if not profile["display_name"]:
        return redirect(url_for("main.identity"))
    return redirect(url_for("main.construct"))


@main.get("/identity")
def identity():
    profile = get_profile(current_app.config["DATABASE"])
    if profile["display_name"]:
        return redirect(url_for("main.construct"))
    return render_template("identity.html", error=None, name="")


@main.post("/identity")
def save_identity():
    name = request.form.get("display_name", "").strip()
    if not name:
        return render_template(
            "identity.html", error="Enter a name to continue.", name=""
        ), 400
    saved_name = save_first_display_name(current_app.config["DATABASE"], name)
    current_app.extensions["dejavu_welcome_once"][1] = saved_name
    return redirect(url_for("main.construct"), code=303)


@main.get("/construct")
def construct():
    ticket = request.args.get("ticket")
    if ticket:
        run = _consume_page_ticket(ticket)
        if run and run.get("return_to_construct"):
            run_id = session.pop("run_id", None)
            current_app.extensions["dejavu_runs"].pop(run_id, None)
    profile = get_profile(current_app.config["DATABASE"])
    if not profile["display_name"]:
        return redirect(url_for("main.identity"))
    welcome_name = current_app.extensions["dejavu_welcome_once"].pop(1, None)
    return render_template(
        "construct.html",
        name=profile["display_name"],
        welcome_name=welcome_name,
        topic=request.args.get("topic", ""),
        error=request.args.get("error"),
        error_kind=request.args.get("kind", "generation"),
        fake_mode=current_app.config["DEJAVU_FAKE_AI"],
    )


@main.post("/topic")
def request_lesson():
    topic = request.form.get("topic", "")
    if not topic.strip():
        return render_template(
            "construct.html",
            name=get_profile(current_app.config["DATABASE"])["display_name"],
            welcome_name=None,
            topic=topic,
            error="Enter a topic to begin your download.",
            error_kind="input",
            fake_mode=current_app.config["DEJAVU_FAKE_AI"],
        ), 400

    # Moving to a different topic ends any unfinished local run. The saved
    # session transition is conditional, so a terminal status is never replaced.
    previous_run_id = session.pop("run_id", None)
    if previous_run_id:
        _abandon_run(previous_run_id)

    try:
        result = validate_lesson_result(_client().generate_lesson(topic.strip()))
    except LiveGenerationDisabled as error:
        return redirect(
            url_for("main.construct", topic=topic, error=str(error), kind="setup")
        ), 303
    except MissingApiKey as error:
        return redirect(
            url_for("main.construct", topic=topic, error=str(error), kind="setup")
        ), 303
    except (LessonProviderError, InvalidLessonContent):
        return redirect(
            url_for("main.construct", topic=topic, error=DOWNLOAD_ERROR)
        ), 303

    if result.outcome == "unlearnable_topic":
        return redirect(
            url_for("main.construct", topic=topic, error=UNLEARNABLE_MESSAGE, kind="topic")
        ), 303

    session_id = create_learning_session(current_app.config["DATABASE"], topic.strip())
    run_id = secrets.token_urlsafe(24)
    current_app.extensions["dejavu_runs"][run_id] = {
        "session_id": session_id,
        "topic": topic.strip(),
        "lesson": result,
        "battle_setup_id": str(uuid4()),
        "actions": {},
    }
    ticket = _issue_page_ticket(run_id, session_id)
    session["run_id"] = run_id
    return redirect(url_for("main.lesson", ticket=ticket), code=303)


@main.get("/lesson/<ticket>")
def lesson(ticket: str):
    run = _consume_page_ticket(ticket)
    if run is None:
        return redirect(url_for("main.construct"), code=303)
    return _render_lesson(run)


@main.post("/battle/start")
def start_battle():
    run_id, run = _active_run()
    if not run_id or not run:
        return redirect(url_for("main.construct"), code=303)
    action_id = request.form.get("action_id", "")
    replay = _cached_action_redirect(run_id, run, action_id)
    if replay:
        return replay
    if action_id != run["battle_setup_id"] or run.get("battle"):
        return redirect(url_for("main.construct"), code=303)

    lesson_cards = [card.model_dump() for card in run["lesson"].cards]
    try:
        raw_battle = _client().generate_battle(run["topic"], lesson_cards)
        battle_set = validate_battle_set(raw_battle)
    except (LessonProviderError, InvalidBattleContent):
        return _render_lesson(
            run,
            "Battle setup failed. Your lesson is safe; try generating the questions again.",
        )

    run["battle"] = new_encounter(battle_set)
    run["battle_setup_id"] = None
    return _complete_action(run_id, run, action_id)


@main.get("/battle/<ticket>")
def battle(ticket: str):
    run = _consume_page_ticket(ticket)
    if run is None or not run.get("battle"):
        return redirect(url_for("main.construct"), code=303)
    return _render_battle(run)


@main.post("/battle/answer")
def answer_battle_question():
    run_id, run = _active_run()
    if not run_id or not run or not run.get("battle"):
        return redirect(url_for("main.construct"), code=303)
    encounter = run["battle"]
    action_id = request.form.get("action_id", "")
    replay = _cached_action_redirect(run_id, run, action_id)
    if replay:
        return replay
    if action_id != encounter["attempt_id"]:
        return redirect(url_for("main.construct"), code=303)
    try:
        selected_index = int(request.form.get("answer", ""))
        result = grade_answer(encounter, selected_index)
    except (TypeError, ValueError):
        return _render_battle(run, "Choose one of the four answers before locking it.")

    if not result["is_correct"]:
        question = current_question(encounter)
        try:
            record_mistake(
                current_app.config["DATABASE"],
                session_id=run["session_id"],
                question_instance_id=action_id,
                concept_label=question["concept_label"],
                concept_explanation=question["concept_explanation"],
                question_text=question["question"],
                chosen_answer=result["chosen_answer"],
                correct_answer=result["correct_answer"],
                explanation=result["explanation"],
            )
        except (sqlite3.Error, ValueError):
            return _render_battle(
                run,
                "Your answer could not be saved. The question is still open; retry safely.",
            )

    apply_answer(encounter, result)
    return _complete_action(run_id, run, action_id)


@main.post("/battle/advance")
def advance_battle():
    run_id, run = _active_run()
    if not run_id or not run or not run.get("battle"):
        return redirect(url_for("main.construct"), code=303)
    encounter = run["battle"]
    action_id = request.form.get("action_id", "")
    replay = _cached_action_redirect(run_id, run, action_id)
    if replay:
        return replay
    if action_id != encounter["transition_id"]:
        return redirect(url_for("main.construct"), code=303)
    try:
        advance_after_answer(encounter)
    except ValueError:
        return redirect(url_for("main.construct"), code=303)
    return _complete_action(run_id, run, action_id)


@main.post("/battle/retry")
def retry_battle_round():
    run_id, run = _active_run()
    if not run_id or not run or not run.get("battle"):
        return redirect(url_for("main.construct"), code=303)
    encounter = run["battle"]
    action_id = request.form.get("action_id", "")
    replay = _cached_action_redirect(run_id, run, action_id)
    if replay:
        return replay
    if action_id != encounter["transition_id"]:
        return redirect(url_for("main.construct"), code=303)
    try:
        retry_round(encounter)
    except ValueError:
        return redirect(url_for("main.construct"), code=303)
    return _complete_action(run_id, run, action_id)


@main.post("/battle/return")
def return_from_battle():
    run_id, run = _active_run()
    if not run_id or not run or not run.get("battle"):
        return redirect(url_for("main.construct"), code=303)
    encounter = run["battle"]
    action_id = request.form.get("action_id", "")
    replay = _cached_action_redirect(run_id, run, action_id)
    if replay:
        return replay
    if action_id != encounter["transition_id"]:
        return redirect(url_for("main.construct"), code=303)
    status = (
        "defeated"
        if encounter["phase"] == "answered" and encounter["next_action"] == "defeat"
        else "abandoned"
    )
    finish_session_if_in_progress(
        current_app.config["DATABASE"], run["session_id"], status
    )
    run["return_to_construct"] = True
    ticket = _issue_page_ticket(run_id, run["session_id"])
    run["actions"][action_id] = {"ticket": ticket, "endpoint": "main.construct"}
    return redirect(url_for("main.construct", ticket=ticket), code=303)
