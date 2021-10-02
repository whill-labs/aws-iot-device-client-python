import logging


class ExceptionAwsIotClient(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


def get_module_logger(modname: str) -> logging.Logger:
    logger = logging.getLogger(modname)
    handler = logging.NullHandler()
    logger.addHandler(handler)
    return logger


__all__ = [
    "mqtt",
    "pubsub",
    "classic_shadow",
    "named_shadow",
    "jobs",
    "get_module_logger",
]
