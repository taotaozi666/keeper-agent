"""仅将 EXPLAIN 优化器展开说明降为 DEBUG，保留其他驱动警告。"""

import logging
import re

from app.core.log import logger


class ExplainNoteFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if re.match(r"^/\* select#\d+ \*/", message):
            logger.debug("MySQL EXPLAIN optimizer note: {}", message)
            return False
        return True


def configure_db_logging():
    driver_logger = logging.getLogger("asyncmy")
    if not any(isinstance(item, ExplainNoteFilter) for item in driver_logger.filters):
        driver_logger.addFilter(ExplainNoteFilter())
