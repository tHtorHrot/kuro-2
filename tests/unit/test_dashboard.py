"""Dashboard route serves the bundled static page (no secrets inside)."""

from pathlib import Path


def test_dashboard_file_exists():
    page = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "api" / "dashboard.html"
    if not page.is_file():  # pragma: no cover - layout guard
        page = Path("src/jarvis/api/dashboard.html")
    text = page.read_text(encoding="utf-8")
    assert "/api/v1/tasks" in text and "protect_content" not in text
    assert "localStorage" not in text and "sessionStorage" not in text


def test_dashboard_route_registered():
    import sys

    sys.path.insert(0, "src")
    from jarvis.api.dashboard import router

    assert any(getattr(route, "path", "") == "/dashboard" for route in router.routes)
