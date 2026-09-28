import ctypes
import logging
import os
import signal
import sys


_PR_SET_PDEATHSIG = 1


def install_parent_death_signal(logger_name='simo.processes'):
    """Terminate this Linux child when the process that created it exits.

    Call this at the beginning of a multiprocessing child, before it opens
    database connections or starts application code.  It intentionally does
    nothing on platforms that do not provide Linux's prctl().
    """
    if sys.platform != 'linux':
        return

    parent_pid = os.getppid()
    try:
        libc = ctypes.CDLL('libc.so.6', use_errno=True)
        if libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM) != 0:
            raise OSError(ctypes.get_errno(), 'prctl(PR_SET_PDEATHSIG) failed')
    except OSError:
        logging.getLogger(logger_name).exception(
            'Could not install worker parent-death signal.'
        )
        return

    if os.getppid() != parent_pid:
        # The parent died between getppid() and prctl().  SIGTERM would not be
        # delivered in that case, so do not allow this worker to continue.
        os._exit(1)
