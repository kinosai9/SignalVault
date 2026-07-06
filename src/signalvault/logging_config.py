import logging
from logging.handlers import RotatingFileHandler

from signalvault.config import LOG_DIR, LOG_LEVEL


def setup_logging(level: str | None = None) -> None:
    lvl = (level or LOG_LEVEL).upper()
    log_format = "%(asctime)s %(levelname)s %(name)s: %(message)s"

    root = logging.getLogger()
    root.setLevel(lvl)

    if root.handlers:
        return

    import io
    import sys
    # Wrap stderr with UTF-8 to prevent GBK encoding crashes on Windows
    # when log messages contain emoji or non-GBK Unicode characters.
    utf8_stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    console = logging.StreamHandler(utf8_stderr)
    console.setLevel(lvl)
    console.setFormatter(logging.Formatter(log_format))
    root.addHandler(console)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        LOG_DIR / "signalvault.log",
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(lvl)
    file_handler.setFormatter(logging.Formatter(log_format))
    root.addHandler(file_handler)
