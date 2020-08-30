# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
========================================
:mod:`slowdown.exceptions` -- Exceptions
========================================
"""

__all__ = ['Exceptions']

class Exceptions(Exception):

    """
    Raised when more than one exception occurs.
    """

    def __init__(self, exceptions=None):
        if exceptions is None:
            self.exceptions = []
        else:
            self.exceptions = exceptions
