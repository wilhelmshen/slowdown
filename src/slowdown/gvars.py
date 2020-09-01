# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
=========================================
:mod:`slowdown.gvars` -- Global variables
=========================================
"""

import sys
import logging

__all__ = ['logger']

verbose_log_level_map = \
    {
        0: logging.ERROR,
        1: logging.INFO,
        2: logging.DEBUG
    }
logger = logging.getLogger(__package__)
logger.addHandler(logging.StreamHandler(sys.stderr))
