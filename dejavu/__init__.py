"""Application factory and local startup checks for DEJAVU."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import click
from dotenv import load_dotenv
from flask import Flask

from dejavu.db.connection import initialize_database
from dejavu.routes import main


def create_app(test_config: dict | None = None) -> Flask:
    load_dotenv()
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_mapping(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY") or secrets.token_urlsafe(32),
        DATABASE=os.getenv(
            "DEJAVU_DATABASE", str(Path(app.instance_path) / "dejavu.sqlite3")
        ),
        GEMINI_API_KEY=os.getenv("GEMINI_API_KEY", ""),
        GEMINI_MODEL=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        ENABLE_LIVE_GEMINI=os.getenv("ENABLE_LIVE_GEMINI", "false").lower()
        in {"1", "true", "yes"},
        DEJAVU_FAKE_AI=os.getenv("DEJAVU_FAKE_AI", "false").lower()
        in {"1", "true", "yes"},
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.extensions["dejavu_runs"] = {}
    app.extensions["dejavu_page_tickets"] = {}
    app.extensions["dejavu_welcome_once"] = {}

    with app.app_context():
        initialize_database(app.config["DATABASE"])

    app.register_blueprint(main)

    @app.cli.command("init-db")
    def init_db_command() -> None:
        """Create the local database tables if needed."""
        initialize_database(app.config["DATABASE"])
        click.echo("Initialized the DEJAVU database.")

    return app
