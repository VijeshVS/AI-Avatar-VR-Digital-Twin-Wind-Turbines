"""The operator console is served by the same process that serves the API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from telemetry.main import app

client = TestClient(app)


def test_index_is_served() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "WIND TURBINE DIGITAL TWIN" in response.text
    assert "/static/app.js" in response.text


def test_assets_are_served() -> None:
    script = client.get("/static/app.js")
    styles = client.get("/static/style.css")

    assert script.status_code == 200
    assert "api/state" in script.text
    assert styles.status_code == 200
    assert "--accent" in styles.text


def test_console_uses_the_shared_clock_api() -> None:
    script = client.get("/static/app.js").text

    assert "/api/session" in script
    assert "command({ scenario" in script
    assert "command({ focus" in script


def test_console_has_the_copilot_panel() -> None:
    page = client.get("/").text
    script = client.get("/static/app.js").text

    assert 'id="ai-question"' in page
    assert 'id="ai-mode"' in page
    assert 'id="ai-steps"' in page
    assert "/api/assistant" in script
    assert "mode: answerMode" in script


def test_console_supports_an_ask_deeplink() -> None:
    script = client.get("/static/app.js").text

    assert "URLSearchParams" in script
    assert "pendingAsk" in script


def test_index_is_not_in_the_openapi_schema() -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/state" in paths
    assert "/" not in paths
