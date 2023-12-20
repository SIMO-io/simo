import logging
from simo.core.utils.model_helpers import get_log_file_path
from django.utils import timezone
from logging.handlers import RotatingFileHandler



def get_gw_logger(gateway_id):
    from .models import Gateway
    logger = logging.getLogger("Gateway Logger [%d]" % gateway_id)
    logger.propagate = False
    if not logger.handlers:
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            "%m-%d %H:%M:%S"
        )
        formatter.converter = \
            lambda *args, **kwargs: timezone.localtime().timetuple()
        from simo.core.utils.model_helpers import get_log_file_path
        gw = Gateway.objects.get(pk=gateway_id)
        file_handler = RotatingFileHandler(
            get_log_file_path(gw), maxBytes=102400,  # 100KB
            backupCount=3, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger



def get_component_logger(component):
    logger = logging.getLogger(
        "Component Logger [%d]" % component.id
    )
    logger.propagate = False
    if not logger.handlers:
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            "%m-%d %H:%M:%S"
        )
        formatter.converter = \
            lambda *args, **kwargs: timezone.localtime().timetuple()
        file_handler = RotatingFileHandler(
            get_log_file_path(component), maxBytes=102400,  # 100KB
            backupCount=3, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger
