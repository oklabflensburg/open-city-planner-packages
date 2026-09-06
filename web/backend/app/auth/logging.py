"""Keep auth one-time tokens and provider codes out of Uvicorn access logs."""

import logging


class AuthAccessFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            peer, method, target, version, status = record.args
            if isinstance(target, str) and target.startswith("/api/v1/auth/"):
                record.args = (peer, method, target.split("?", 1)[0], version, status)
        return True
