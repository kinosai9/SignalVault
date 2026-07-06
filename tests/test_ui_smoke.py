"""UI smoke tests for critical pages using Playwright.

These tests verify that key pages render correctly with CSS loaded,
key DOM elements present, and no server errors.

Run with: python -m pytest tests/test_ui_smoke.py -v
Requires: playwright (pip install playwright && python -m playwright install chromium)
"""

import threading
import time

import pytest
import uvicorn

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from podcast_research.api.app import create_app

pytestmark = pytest.mark.skipif(
    not PLAYWRIGHT_AVAILABLE,
    reason="playwright not installed (pip install playwright && playwright install chromium)",
)

SERVER_PORT = 18766
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


@pytest.fixture(scope="module")
def server():
    """Start FastAPI server in a background thread for the test module."""
    app = create_app()

    server = uvicorn.Server(
        config=uvicorn.Config(
            app, host="127.0.0.1", port=SERVER_PORT, log_level="error"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to be ready
    import httpx

    for _ in range(20):
        try:
            resp = httpx.get(f"{BASE_URL}/api/health", timeout=1.0)
            if resp.status_code == 200:
                break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError("Server failed to start within 4 seconds")

    yield BASE_URL

    server.should_exit = True


@pytest.fixture(scope="module")
def browser():
    """Launch Playwright Chromium browser."""
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser, server):
    """Create a new page for each test."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    yield page
    ctx.close()


# ── Source Pages Smoke Tests ──────────────────────────────────────


def test_channels_page_loads(page, server):
    """Verify /sources/channels loads (may redirect if vault not configured)."""
    resp = page.goto(f"{server}/sources/channels")
    assert resp.status == 200

    # Navigation link exists (may not have .active class if redirected)
    nav_links = page.locator("nav a")
    assert nav_links.count() >= 1

    # CSS is loaded regardless of page
    css_link = page.locator('link[rel="stylesheet"]')
    assert css_link.count() >= 1
    href = css_link.first.get_attribute("href")
    assert "style.css" in href


def test_channels_page_css_loaded(page, server):
    """Verify CSS stylesheet is actually loaded on channels page."""
    resp = page.goto(f"{server}/sources/channels")
    assert resp.status == 200

    # Check that the CSS link is present with correct href
    css_link = page.locator('link[rel="stylesheet"]')
    assert css_link.count() >= 1
    href = css_link.first.get_attribute("href")
    assert "style.css" in href
    assert "v=" in href  # cache bust parameter present

    # Verify a styled element renders with non-zero dimensions
    shell = page.locator("aside.app-sidebar")
    assert shell.is_visible()

    # Check that the main content area has computed styles
    main_el = page.locator("main.container")
    assert main_el.is_visible()


def test_channels_videos_page_loads(page, server):
    """Verify /sources/channels/{id}/videos loads with DOM structure."""
    # First navigate to channels page to get a channel link
    page.goto(f"{server}/sources/channels")

    # Try to find and click a channel link
    channel_links = page.locator('a[href*="/sources/channels/"]')
    if channel_links.count() > 0:
        # Click the first channel link that goes to videos
        first_link = None
        for i in range(channel_links.count()):
            href = channel_links.nth(i).get_attribute("href") or ""
            if "/videos" in href:
                first_link = href
                break

        if first_link:
            resp = page.goto(f"{server}{first_link}")
            assert resp.status == 200

            # App shell visible
            assert page.locator("aside.app-sidebar").is_visible()

            # CSS loaded on videos page too
            css_link = page.locator('link[rel="stylesheet"]')
            assert css_link.count() >= 1


def test_channels_page_no_console_errors(page, server):
    """Verify no JavaScript console errors on channels page."""
    errors = []

    def on_error(msg):
        if msg.type == "error":
            errors.append(msg.text)

    page.on("console", on_error)
    page.goto(f"{server}/sources/channels")
    page.wait_for_load_state("networkidle")

    assert len(errors) == 0, f"Console errors: {errors}"


# ── Other Critical Pages ──────────────────────────────────────────


def test_dashboard_loads(page, server):
    """Verify dashboard page loads."""
    resp = page.goto(f"{server}/dashboard")
    assert resp.status == 200
    assert page.locator("aside.app-sidebar").is_visible()


def test_reports_page_loads(page, server):
    """Verify reports list page loads."""
    resp = page.goto(f"{server}/reports")
    assert resp.status == 200
    assert page.locator("aside.app-sidebar").is_visible()


def test_search_page_loads(page, server):
    """Verify search page loads."""
    resp = page.goto(f"{server}/search")
    assert resp.status == 200
    assert page.locator("aside.app-sidebar").is_visible()
