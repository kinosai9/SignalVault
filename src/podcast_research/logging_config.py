import logging
from logging.handlers import RotatingFileHandler

from podcast_research.config import LOG_DIR, LOG_LEVEL


def setup_logging(level: str | None = None) -> None:
    lvl = (level or LOG_LEVEL).upper()
    log_format = "%(asctime)s %(levelname)s %(name)s: %(message)s"

    root = logging.getLogger()
    root.setLevel(lvl)

    if root.handlers:
        return

    console = logging.StreamHandler()
    console.setLevel(lvl)
    console.setFormatter(logging.Formatter(log_format))
    root.addHandler(console)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        LOG_DIR / "podcast_research.log",
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(lvl)
    file_handler.setFormatter(logging.Formatter(log_format))
    root.addHandler(file_handler)
