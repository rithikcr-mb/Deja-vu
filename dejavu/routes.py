"""Browser routes for identity, topic entry, and the validated lesson."""

from __future__ import annotations

import secrets
import time

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
    get_profile,
    save_first_display_name,
)
from dejavu.services.ai_client import (
    FakeGeminiClient,
    GeminiLessonClient,
    LessonProviderError,
    LiveGenerationDisabled,
    MissingApiKey,
)
from dejavu.services.content import InvalidLessonContent, validate_lesson_result

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


def _consume_lesson_ticket(ticket: str) -> dict | None:
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


def _issue_lesson_ticket(run_id: str, session_id: str) -> str:
    nonce = secrets.token_urlsafe(24)
    current_app.extensions["dejavu_page_tickets"][nonce] = {
        "run_id": run_id,
        "session_id": session_id,
        "expires_at": time.time() + 300,
        "consumed": False,
    }
    return _serializer().dumps({"session_id": session_id, "nonce": nonce})


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
    }
    ticket = _issue_lesson_ticket(run_id, session_id)
    session["run_id"] = run_id
    return redirect(url_for("main.lesson", ticket=ticket), code=303)


@main.get("/lesson/<ticket>")
def lesson(ticket: str):
    run = _consume_lesson_ticket(ticket)
    if run is None:
        return redirect(url_for("main.construct"), code=303)
    return render_template(
        "lesson.html",
        topic=run["topic"],
        cards=run["lesson"].cards,
        fake_mode=current_app.config["DEJAVU_FAKE_AI"],
    )
