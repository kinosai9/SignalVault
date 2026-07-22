"""M3-A: Minimal Briefcase entry point for macOS .app bootstrap.

This module is the Briefcase app entry. Its sole job is to import and
delegate to the existing Launcher — no reimplementation, no new lifecycle.

Required by Briefcase: a callable ``main()`` that runs the app and returns
when the app exits.
"""

from signalvault.launcher import launch


def main() -> int:
    """Briefcase entry point — delegates to the Launcher lifecycle.

    Returns an exit code suitable for Briefcase (0 = success).
    """
    return launch()
