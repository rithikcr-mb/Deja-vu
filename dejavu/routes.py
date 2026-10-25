"""Browser routes for identity, topic entry, and the validated lesson."""

from __future__ import annotations

import secrets
import sqlite3
import time
from datetime import datetime, timezone
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
    get_weak_concept_with_latest_event,
    get_weak_concepts_with_latest_event,
    record_boss_weak_spot_mistake,
    record_mistake,
    record_review_outcome,
    save_first_display_name,
)
from dejavu.services.ai_schemas import BOSS_MAX_QUESTIONS
from dejavu.services.battle import (
    advance_after_answer,
    advance_boss_after_answer,
    apply_answer,
    apply_boss_answer,
    battle_view,
    boss_view,
    current_question,
    grade_answer,
    grade_boss_answer,
    new_boss_encounter,
    new_encounter,
    retry_boss,
    retry_round,
)
from dejavu.services.ai_client import (
    QUOTA_MESSAGE,
    FakeGeminiClient,
    GeminiLessonClient,
    LessonProviderError,
    LiveGenerationDisabled,
    MissingApiKey,
    ProviderQuotaExceeded,
)
from dejavu.services.content import (
    InvalidBattleContent,
    InvalidBossContent,
    InvalidLessonContent,
    InvalidReviewContent,
    build_boss_candidates,
    generate_boss_set,
    generate_review_set,
    validate_battle_set,
    validate_lesson_result,
)
from dejavu.services.mentor_context import MentorContext, get_mentor_context
from dejavu.services.review import (
    advance_review,
    apply_review_answer,
    grade_review_answer,
    new_review,
    review_view,
)

main = Blueprint("main", __name__)
UNLEARNABLE_MESSAGE = (
    "The Construct couldn't identify a learnable topic. Try Process Scheduling "
    "or DBMS Normalization, or edit your topic."
)
DOWNLOAD_ERROR = "Download failed. Your lesson wasn't created. Try again."
BOSS_SETUP_ERROR = (
    "Boss generation failed. Your progress and saved mistakes are safe; try again."
)
BOSS_SAVE_ERROR = (
    "Your answer could not be saved. The question is still open; retry safely."
)
BOSS_ANSWER_ERROR = "Choose one of the four answers before locking it."
REVIEW_SETUP_ERROR = (
    "Review questions could not be created. Your saved weakness and mistake "
    "history are safe; try again."
)
REVIEW_ANSWER_ERROR = "Choose one of the four answers before locking it."
REVIEW_SAVE_ERROR = (
    "Your review answer could not be saved. The question is still open; retry safely."
)
MENTOR_ERRORS = {
    "concept_unavailable": (
        "That saved weakness is not available any more. Choose another one."
    ),
    "review_setup": (
        "Review questions could not be created. Your saved weakness and mistake "
        "history are safe; try again."
    ),
    "review_unavailable": (
        "Live review generation is not available right now. Your saved weakness "
        "and mistake history are safe."
    ),
    "review_quota": QUOTA_MESSAGE,
}


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


def _issue_review_ticket(review_id: str) -> str:
    """Issue a one-use ticket for a review screen."""
    nonce = secrets.token_urlsafe(24)
    current_app.extensions["dejavu_review_tickets"][nonce] = {
        "review_id": review_id,
        "expires_at": time.time() + 300,
        "consumed": False,
    }
    return _serializer().dumps({"session_id": review_id, "nonce": nonce})


def _consume_review_ticket(ticket: str) -> dict | None:
    """Consume a signed, one-use review ticket; an invalid ticket resumes nothing."""
    payload = None
    try:
        payload = _serializer().loads(ticket, max_age=300)
    except (SignatureExpired, BadSignature):
        payload = None
    if not isinstance(payload, dict):
        return None
    ledger = current_app.extensions["dejavu_review_tickets"]
    entry = ledger.get(payload.get("nonce"))
    review_id = payload.get("session_id")
    if (
        entry
        and not entry["consumed"]
        and entry["expires_at"] > time.time()
        and entry["review_id"] == review_id
    ):
        entry["consumed"] = True
        return current_app.extensions["dejavu_reviews"].get(review_id)
    return None


def _active_review() -> dict | None:
    review_id = session.get("review_id")
    if not review_id:
        return None
    return current_app.extensions["dejavu_reviews"].get(review_id)


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


def _complete_action(
    run_id: str, run: dict, action_id: str, *, endpoint: str = "main.battle"
):
    ticket = _issue_page_ticket(run_id, run["session_id"])
    run["actions"][action_id] = {
        "ticket": ticket,
        "endpoint": endpoint,
    }
    return redirect(url_for(endpoint, ticket=ticket), code=303)


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
        boss_setup_id=run.get("boss_setup_id"),
        fake_mode=current_app.config["DEJAVU_FAKE_AI"],
        error=error,
    )


def _render_boss(run: dict, error: str | None = None):
    return render_template(
        "boss.html",
        topic=run["topic"],
        boss=boss_view(run["boss"]),
        fake_mode=current_app.config["DEJAVU_FAKE_AI"],
        error=error,
    )


def _render_victory(run: dict):
    return render_template(
        "victory.html",
        topic=run["topic"],
        boss=boss_view(run["boss"]),
        fake_mode=current_app.config["DEJAVU_FAKE_AI"],
    )


def _generate_boss_encounter(run: dict) -> dict:
    rows = get_weak_concepts_with_latest_event(
        current_app.config["DATABASE"], BOSS_MAX_QUESTIONS
    )
    candidates = build_boss_candidates(rows)
    lesson_cards = [card.model_dump() for card in run["lesson"].cards]
    boss_set = generate_boss_set(
        _client(),
        topic=run["topic"],
        lesson_cards=lesson_cards,
        candidates=candidates,
    )
    return new_boss_encounter(boss_set)


def _persist_boss_mistake(run: dict, result: dict) -> None:
    """Commit the boss event before the route applies its HP effect."""
    database = current_app.config["DATABASE"]
    common = {
        "session_id": run["session_id"],
        "question_instance_id": result["attempt_id"],
        "question_text": result["question_text"],
        "chosen_answer": result["chosen_answer"],
        "correct_answer": result["correct_answer"],
        "explanation": result["explanation"],
    }
    if result["kind"] == "weak_spot":
        weak_concept_id = result["weak_concept_id"]
        if weak_concept_id is None:
            raise ValueError("A weak-spot answer needs a saved concept link.")
        record_boss_weak_spot_mistake(
            database,
            weak_concept_id=weak_concept_id,
            **common,
        )
        return
    if result["kind"] == "adaptive":
        concept_label = result["concept_label"]
        concept_explanation = result["concept_explanation"]
        if not concept_label or not concept_explanation:
            raise ValueError("An adaptive answer needs concept details.")
        record_mistake(
            database,
            concept_label=concept_label,
            concept_explanation=concept_explanation,
            question_kind="boss",
            **common,
        )
        return
    raise ValueError("Unknown boss question kind.")


def _format_utc(value: str) -> str:
    """Display a stored UTC timestamp without inventing a new date or time."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return value
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def _render_mentor(context: MentorContext, error: str | None = None):
    seeded_history = bool(
        (context.last_session and context.last_session.origin == "seeded_demo")
        or any(
            concept.latest_mistake.origin == "seeded_demo"
            for concept in context.weak_concepts
        )
    )
    return render_template(
        "mentor.html",
        context=context,
        seeded_history=seeded_history,
        format_utc=_format_utc,
        error=error,
    )


def _render_review(review: dict, error: str | None = None):
    return render_template(
        "review.html",
        review=review_view(review),
        fake_mode=current_app.config["DEJAVU_FAKE_AI"],
        error=error,
    )


@main.get("/")
def index():
    context = get_mentor_context()
    if not context.display_name:
        return redirect(url_for("main.identity"))
    if not context.has_session_history:
        return redirect(url_for("main.construct"))
    current_app.extensions["dejavu_welcome_once"].pop(1, None)
    return _render_mentor(context, error=MENTOR_ERRORS.get(request.args.get("error", "")))


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
    # Re-enter the landing dispatcher: a new name with existing history returns
    # through the mentor, while a genuinely new player still gets Construct.
    return redirect(url_for("main.index"), code=303)


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
    except ProviderQuotaExceeded as error:
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
        "boss_setup_id": str(uuid4()),
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
    except ProviderQuotaExceeded as error:
        return _render_lesson(run, str(error))
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


@main.post("/boss/start")
def start_boss():
    run_id, run = _active_run()
    if not run_id or not run or not run.get("battle"):
        return redirect(url_for("main.construct"), code=303)
    action_id = request.form.get("action_id", "")
    replay = _cached_action_redirect(run_id, run, action_id)
    if replay:
        return replay
    if (
        action_id != run.get("boss_setup_id")
        or run.get("boss")
        or run["battle"]["phase"] != "complete"
    ):
        return redirect(url_for("main.construct"), code=303)

    try:
        encounter = _generate_boss_encounter(run)
    except ProviderQuotaExceeded as error:
        return _render_battle(run, str(error))
    except (LessonProviderError, InvalidBossContent, sqlite3.Error, ValueError):
        return _render_battle(run, BOSS_SETUP_ERROR)

    run["boss"] = encounter
    run["boss_setup_id"] = None
    return _complete_action(run_id, run, action_id, endpoint="main.boss")


@main.get("/boss/<ticket>")
def boss(ticket: str):
    run = _consume_page_ticket(ticket)
    if run is None or not run.get("boss"):
        return redirect(url_for("main.construct"), code=303)
    return _render_boss(run)


@main.post("/boss/answer")
def answer_boss_question():
    run_id, run = _active_run()
    if not run_id or not run or not run.get("boss"):
        return redirect(url_for("main.construct"), code=303)
    encounter = run["boss"]
    action_id = request.form.get("action_id", "")
    if action_id != encounter["attempt_id"]:
        return redirect(url_for("main.construct"), code=303)
    replay = _cached_action_redirect(run_id, run, action_id)
    if replay:
        return replay
    try:
        selected_index = int(request.form.get("answer", ""))
    except (TypeError, ValueError):
        return _render_boss(run, BOSS_ANSWER_ERROR)
    try:
        result = grade_boss_answer(encounter, selected_index)
    except ValueError:
        return redirect(url_for("main.construct"), code=303)

    if not result["is_correct"]:
        try:
            _persist_boss_mistake(run, result)
        except (sqlite3.Error, ValueError):
            return _render_boss(run, BOSS_SAVE_ERROR)

    apply_boss_answer(encounter, result)
    if encounter["next_action"] == "victory":
        finish_session_if_in_progress(
            current_app.config["DATABASE"], run["session_id"], "completed"
        )
        return _complete_action(
            run_id, run, action_id, endpoint="main.boss_victory"
        )
    return _complete_action(run_id, run, action_id, endpoint="main.boss")


@main.post("/boss/advance")
def advance_boss():
    run_id, run = _active_run()
    if not run_id or not run or not run.get("boss"):
        return redirect(url_for("main.construct"), code=303)
    encounter = run["boss"]
    action_id = request.form.get("action_id", "")
    if action_id != encounter["transition_id"]:
        return redirect(url_for("main.construct"), code=303)
    replay = _cached_action_redirect(run_id, run, action_id)
    if replay:
        return replay
    try:
        advance_boss_after_answer(encounter)
    except ValueError:
        return redirect(url_for("main.construct"), code=303)
    return _complete_action(run_id, run, action_id, endpoint="main.boss")


@main.post("/boss/retry")
def retry_boss_encounter():
    run_id, run = _active_run()
    if not run_id or not run or not run.get("boss"):
        return redirect(url_for("main.construct"), code=303)
    encounter = run["boss"]
    action_id = request.form.get("action_id", "")
    if action_id != encounter["transition_id"]:
        return redirect(url_for("main.construct"), code=303)
    replay = _cached_action_redirect(run_id, run, action_id)
    if replay:
        return replay
    try:
        retry_boss(encounter)
    except ValueError:
        return redirect(url_for("main.construct"), code=303)
    return _complete_action(run_id, run, action_id, endpoint="main.boss")


@main.post("/boss/return")
def return_from_boss():
    run_id, run = _active_run()
    if not run_id or not run or not run.get("boss"):
        return redirect(url_for("main.construct"), code=303)
    encounter = run["boss"]
    action_id = request.form.get("action_id", "")
    if action_id != encounter["transition_id"]:
        return redirect(url_for("main.construct"), code=303)
    replay = _cached_action_redirect(run_id, run, action_id)
    if replay:
        return replay
    if encounter["phase"] == "answered" and encounter["next_action"] == "victory":
        status = "completed"
    elif encounter["phase"] == "answered" and encounter["next_action"] == "defeat":
        status = "defeated"
    else:
        status = "abandoned"
    finish_session_if_in_progress(
        current_app.config["DATABASE"], run["session_id"], status
    )
    run["return_to_construct"] = True
    ticket = _issue_page_ticket(run_id, run["session_id"])
    run["actions"][action_id] = {"ticket": ticket, "endpoint": "main.construct"}
    return redirect(url_for("main.construct", ticket=ticket), code=303)


@main.get("/boss/victory/<ticket>")
def boss_victory(ticket: str):
    run = _consume_page_ticket(ticket)
    if run is None or not run.get("boss"):
        return redirect(url_for("main.construct"), code=303)
    encounter = run["boss"]
    if encounter["phase"] != "answered" or encounter["next_action"] != "victory":
        return redirect(url_for("main.construct"), code=303)

    finish_session_if_in_progress(
        current_app.config["DATABASE"], run["session_id"], "completed"
    )
    response = _render_victory(run)
    run_id = session.pop("run_id", None)
    if run_id:
        current_app.extensions["dejavu_runs"].pop(run_id, None)
    return response


@main.post("/review/start")
def start_review():
    """Start a focused review for one trusted saved weak concept."""
    raw_concept_id = request.form.get("concept_id", "")
    try:
        concept_id = int(raw_concept_id)
    except (TypeError, ValueError):
        return redirect(url_for("main.index", error="concept_unavailable"), code=303)
    if isinstance(concept_id, bool) or concept_id < 1:
        return redirect(url_for("main.index", error="concept_unavailable"), code=303)

    concept = get_weak_concept_with_latest_event(
        current_app.config["DATABASE"], concept_id
    )
    if concept is None:
        return redirect(url_for("main.index", error="concept_unavailable"), code=303)

    try:
        review_set = generate_review_set(
            _client(),
            concept_label=concept["label"],
            concept_explanation=concept["explanation"],
        )
    except (LiveGenerationDisabled, MissingApiKey):
        return redirect(url_for("main.index", error="review_unavailable"), code=303)
    except ProviderQuotaExceeded:
        return redirect(url_for("main.index", error="review_quota"), code=303)
    except (LessonProviderError, InvalidReviewContent):
        return redirect(url_for("main.index", error="review_setup"), code=303)

    review_id = str(uuid4())
    review = new_review(
        review_set,
        review_id=review_id,
        weak_concept_id=concept["concept_id"],
        concept_label=concept["label"],
        concept_explanation=concept["explanation"],
        original_question=concept["question_text"],
        original_chosen_answer=concept["chosen_answer"],
        original_correct_answer=concept["correct_answer"],
        original_explanation=concept["mistake_explanation"],
    )
    previous_review_id = session.pop("review_id", None)
    if previous_review_id:
        current_app.extensions["dejavu_reviews"].pop(previous_review_id, None)
    current_app.extensions["dejavu_reviews"][review_id] = review
    session["review_id"] = review_id
    ticket = _issue_review_ticket(review_id)
    return redirect(url_for("main.review", ticket=ticket), code=303)


@main.get("/review/<ticket>")
def review(ticket: str):
    active = _consume_review_ticket(ticket)
    if active is None:
        return redirect(url_for("main.index"), code=303)
    return _render_review(active)


@main.post("/review/answer")
def answer_review_question():
    active = _active_review()
    if active is None:
        return redirect(url_for("main.index"), code=303)
    action_id = request.form.get("action_id", "")
    if action_id != active["attempt_id"] or active["phase"] != "question":
        # A repeated or stale submission never re-grades and never writes a
        # second outcome; it simply shows the current review state again.
        ticket = _issue_review_ticket(active["review_id"])
        return redirect(url_for("main.review", ticket=ticket), code=303)
    try:
        selected_index = int(request.form.get("answer", ""))
    except (TypeError, ValueError):
        return _render_review(active, REVIEW_ANSWER_ERROR)
    try:
        result = grade_review_answer(active, selected_index)
    except ValueError:
        return _render_review(active, REVIEW_ANSWER_ERROR)

    try:
        record_review_outcome(
            current_app.config["DATABASE"],
            review_id=active["review_id"],
            question_instance_id=result["attempt_id"],
            weak_concept_id=active["weak_concept_id"],
            question_text=result["question_text"],
            chosen_answer=result["chosen_answer"],
            correct_answer=result["correct_answer"],
            is_correct=result["is_correct"],
            explanation=result["explanation"],
        )
    except (sqlite3.Error, ValueError):
        return _render_review(active, REVIEW_SAVE_ERROR)

    apply_review_answer(active, result)
    ticket = _issue_review_ticket(active["review_id"])
    return redirect(url_for("main.review", ticket=ticket), code=303)


@main.post("/review/advance")
def advance_review_question():
    active = _active_review()
    if active is None:
        return redirect(url_for("main.index"), code=303)
    action_id = request.form.get("action_id", "")
    if action_id != active["transition_id"] or active["next_action"] != "next_question":
        ticket = _issue_review_ticket(active["review_id"])
        return redirect(url_for("main.review", ticket=ticket), code=303)
    try:
        advance_review(active)
    except ValueError:
        return redirect(url_for("main.index"), code=303)
    ticket = _issue_review_ticket(active["review_id"])
    return redirect(url_for("main.review", ticket=ticket), code=303)


@main.post("/review/complete")
def complete_review():
    """Close the two questions and show the review summary."""
    active = _active_review()
    if active is None:
        return redirect(url_for("main.index"), code=303)
    action_id = request.form.get("action_id", "")
    if action_id != active["transition_id"] or active["next_action"] != "complete":
        ticket = _issue_review_ticket(active["review_id"])
        return redirect(url_for("main.review", ticket=ticket), code=303)
    try:
        advance_review(active)
    except ValueError:
        return redirect(url_for("main.index"), code=303)
    ticket = _issue_review_ticket(active["review_id"])
    return redirect(url_for("main.review", ticket=ticket), code=303)


@main.post("/review/finish")
def finish_review():
    """Close the review and return to the mentor."""
    active = _active_review()
    if active is None:
        return redirect(url_for("main.index"), code=303)
    action_id = request.form.get("action_id", "")
    if action_id != active["transition_id"]:
        return redirect(url_for("main.index"), code=303)
    current_app.extensions["dejavu_reviews"].pop(active["review_id"], None)
    session.pop("review_id", None)
    return redirect(url_for("main.index"), code=303)


@main.post("/review/new-topic")
def finish_review_for_new_topic():
    """Close the review and continue to the Construct."""
    active = _active_review()
    if active is None:
        return redirect(url_for("main.construct"), code=303)
    action_id = request.form.get("action_id", "")
    if action_id != active["transition_id"]:
        return redirect(url_for("main.construct"), code=303)
    current_app.extensions["dejavu_reviews"].pop(active["review_id"], None)
    session.pop("review_id", None)
    return redirect(url_for("main.construct"), code=303)
