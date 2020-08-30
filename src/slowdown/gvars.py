# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
=========================================
:mod:`slowdown.gvars` -- Global variables
=========================================
"""

import sys
import logging

__all__ = ['logger']

logger = logging.getLogger(__package__)
logger.addHandler(logging.StreamHandler(sys.stdout))
