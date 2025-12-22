"""Compatibility shim for hub-style imports.

Many SIMO modules historically import the Celery app as `from celeryc import celery_app`
because hub deployments include a top-level `celeryc.py`.

The packaged code keeps the implementation in `simo.celeryc`. This shim allows
running tests (and other package-based entry points) without needing a separate
hub wrapper module.
"""

from simo.celeryc import *  # noqa

