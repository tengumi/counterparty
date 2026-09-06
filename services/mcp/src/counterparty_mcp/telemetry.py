"""Keep library validation diagnostics from logging arbitrary tool input values."""

import logging

from fastmcp.utilities.logging import get_logger


class _ArgumentValueFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and record.msg.startswith("Invalid arguments for tool"):
            record.msg = "Report tool argument validation failed"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


def protect_library_validation_logs() -> None:
    """Sanitize the pinned FastMCP server logger once, retaining operational failures."""
    logger = get_logger("fastmcp.server.server")
    if not any(isinstance(item, _ArgumentValueFilter) for item in logger.filters):
        logger.addFilter(_ArgumentValueFilter())
