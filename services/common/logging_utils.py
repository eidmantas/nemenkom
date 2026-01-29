"""
Shared logging setup for services.
"""

import logging

import config


def setup_logging() -> None:
    """
    Configure logging once using config.LOG_LEVEL.
    Safe to call multiple times.
    """
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    level_name = str(config.LOG_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
