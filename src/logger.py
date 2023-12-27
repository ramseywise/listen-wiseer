import logging
import logging.config

# from pydantic import BaseModel

log_config = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "[listen-wiseer] [%(name)s] [%(asctime)s] [%(levelname)s] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "app": {"handlers": ["default"], "level": "INFO"},
    },
}


def get_logger(logger_name):
    """Get logger config."""
    logging.config.dictConfig(log_config)
    return logging.getLogger(logger_name)

