# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
=========================================
:mod:`slowdown.gvars` -- Global variables
=========================================
"""

from . import logging

__all__ = ['logger']

levels = [logging.DISABLED, logging.INFO, logging.DEBUG]
logger = logging.Logger()
