import logging
from functools import wraps
from inspect import iscoroutinefunction
from logging import getLogger
from channels.exceptions import AcceptConnection, DenyConnection, StopConsumer

logger = getLogger()


class StreamToLogger(object):
    """
    Fake file-like stream object that redirects writes to a logger instance.
    """
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''

    def write(self, buf):
        temp_linebuf = self.linebuf + buf
        self.linebuf = ''
        for line in temp_linebuf.splitlines(True):
            # From the io.TextIOWrapper docs:
            #   On output, if newline is None, any '\n' characters written
            #   are translated to the system default line separator.
            # By default sys.stdout.write() expects '\n' newlines and then
            # translates them so this is still cross platform.
            if line[-1] == '\n':
                self.logger.log(self.log_level, line.rstrip())
            else:
                self.linebuf += line

    def flush(self):
        if self.linebuf != '':
            self.logger.log(self.log_level, self.linebuf.rstrip())
        self.linebuf = ''




def propagate_exceptions(func):
    async def wrapper(*args, **kwargs):  # we're wrapping an async function
        try:
            return await func(*args, **kwargs)
        except (AcceptConnection, DenyConnection, StopConsumer):  # these are handled by channels
            raise
        except Exception as exception:  # any other exception
            # avoid logging the same exception multiple times
            if not getattr(exception, "caught", False):
                setattr(exception, "caught", True)
                logger.error(
                    "Exception occurred in {}:".format(func.__qualname__),
                    exc_info=exception,
                )
            raise  # propagate the exception
    return wraps(func)(wrapper)


def capture_socket_errors(consumer_class):
    for method_name, method in list(consumer_class.__dict__.items()):
        if iscoroutinefunction(method):  # an async method
            # wrap the method with a decorator that propagate exceptions
            setattr(consumer_class, method_name, propagate_exceptions(method))
    return consumer_class