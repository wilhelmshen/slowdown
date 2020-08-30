# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
=================================================
:mod:`slowdown.threadpool` -- The fake threadpool
=================================================

A fake threadpool that does not actually use threads.

Tasks performed in the fake threadpool shall block the entire program.
The only purpose of this pool is to replace the standard
`gevent.threadpool.ThreadPool` by changing the environment variable
*GEVENT_THREADPOOL* before importing the gevent package
so that the program can work in single-threaded mode.

example:

    >>> import os
    >>> os.environ['GEVENT_THREADPOOL'] = \
    ...     'slowdown.threadpool.DummyThreadPool'
    >>> import gevent
"""

import gevent
import gevent.event

__all__ = ['DummyThreadPool']

class DummyThreadPool(object):

    """
    A fake threadpool that does not actually use threads.

    Every task applied to this pool is executed in the main thread
    and blocks the entrie program.
    """

    __slots__ = ['hub', 'maxsize', 'size']

    def __init__(self, maxsize, hub=None):
        self.maxsize = maxsize
        self.hub = hub
        self.size = 0

    def apply(self, func, args=None, kwds=None):
        if args is None:
            if kwds is None:
                return func()
            else:
                return func(**kwds)
        else:
            if kwds is None:
                return func(*args)
            else:
                return func(*args, **kwds)

    def apply_async(self, func, args=None, kwds=None, callback=None):
        return \
            gevent.greenlet.Greenlet.spawn(
                self.apply_cb,
                func,
                args,
                kwds,
                callback
            )

    def apply_cb(self, func, args=None, kwds=None, callback=None):
        result = self.apply(func, args, kwds)
        if callback is not None:
            callback(result)
        return result

    def imap(self, func, *iterables, **kwargs):
        maxsize = kwargs.pop('maxsize', None)
        if kwargs:
            raise TypeError('Unsupported keyword arguments')
        for args in zip(*iterables):
            yield func(*args)

    def imap_unordered(self, func, *iterables, **kwargs):
        return self.imap(func, *iterables, **kwargs)

    def join(self):
        pass

    def map(self, func, iterable):
        return [func(*i) for i in iterable]

    def map_async(self, func, iterable, callback=None):
        return \
            gevent.greenlet.Greenlet.spawn(
                self.map_cb,
                func,
                iterable,
                callback
            )

    def map_cb(self, func, iterable, callback=None):
        result = self.map(func, iterable)
        if callback is not None:
            callback(result)
        return result

    def spawn(func, *args, **kwargs):
        result = gevent.event.AsyncResult()
        try:
            thread_result = \
                self.apply(
                    func,
                    args   if   args else None,
                    kwargs if kwargs else None
                )
        except Exception as err:
            result.set_exception(err)
        else:
            result.set(thread_result)
        return result

    def kill(self):
        pass

    def adjust(self):
        pass
