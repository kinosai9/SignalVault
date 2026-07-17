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

from signalvault.api.app import create_app

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


def test_settings_csrf_error_mobile_has_no_horizontal_overflow(page, server):
    """Expired HTML form requests render the branded 403 safely on mobile."""
    page.set_viewport_size({"width": 390, "height": 844})
    resp = page.goto(f"{server}/settings/ai")
    assert resp.status == 200

    with page.expect_navigation() as navigation:
        page.evaluate(
            """() => {
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = '/settings/ai';
                document.body.appendChild(form);
                form.submit();
            }"""
        )

    assert navigation.value.status == 403
    assert page.locator("#csrf-error-title").inner_text() == "请求已失效"
    assert page.locator(".app-shell").count() == 1
    assert page.locator('[name="_csrf_token"]').count() == 0
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0


# ── C3 First-run Onboarding ──────────────────────────────────────


def test_onboarding_welcome_desktop_keeps_primary_action_visible(page, server):
    """1366×768 keeps the first decision visible without hunting for it."""
    page.set_viewport_size({"width": 1366, "height": 768})
    resp = page.goto(f"{server}/setup/welcome")
    assert resp.status == 200
    assert page.locator(".setup-progress").is_visible()
    assert page.locator(".setup-panel h1").inner_text().startswith("把分散的信息")
    primary = page.locator(".setup-actions .btn-primary")
    assert primary.is_visible()
    assert primary.bounding_box()["y"] < 768


def test_onboarding_ai_mobile_stacks_actions_without_overflow(page, server):
    """390×844 uses stacked actions and never exposes an existing key."""
    page.set_viewport_size({"width": 390, "height": 844})
    resp = page.goto(f"{server}/setup/ai")
    assert resp.status == 200
    assert page.locator('[name="api_key"]').input_value() == ""
    assert page.locator(".setup-step.is-current strong").inner_text() == "AI 服务"
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0
    action_widths = page.locator(".setup-form .setup-actions .btn").evaluate_all(
        "els => els.map(el => el.getBoundingClientRect().width)"
    )
    assert all(width >= 300 for width in action_widths)


def test_onboarding_complete_mobile_has_safe_summary(page, server):
    """The completion summary remains readable at 390×844."""
    page.set_viewport_size({"width": 390, "height": 844})
    resp = page.goto(f"{server}/setup/complete")
    assert resp.status == 200
    assert page.locator(".setup-summary-grid article").count() == 3
    assert page.get_by_text("SQLite 主数据源", exact=True).is_visible()
    assert page.locator(".setup-complete .btn-primary").is_visible()
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0
