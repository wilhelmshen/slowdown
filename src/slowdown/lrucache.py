# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
===========================================================
:mod:`slowdown.lrucache` -- Least Recently Used (LRU) Cache
===========================================================

This module provides an implementation of the Least Recently Used (LRU)
cache.

Example:

    >>> import slowdown.lrucache
    >>> import time
    >>> cache = \\
    ...     slowdown.lrucache.LRUCache(
    ...         size=20000,            # cache size, the default is 20000
    ...
    ...         expiration_time=600.,  # the expiration time of the data,
    ...                                # the default is 600 seconds.
    ...
    ...         cleancycle=60.         # clear expired data at this
    ...                                # specified time, the default is
    ...                                # 60. seconds.
    ...     )
    >>> cache['A'] = DATA_1
    >>> cache['B'] = DATA_2
    >>> cache['C'] = DATA_3
    >>> if 'A' in cache:
    ...     del cache['A']
    >>> cache.get('B')
    DATA_2
    >>> cache.pop('B')
    DATA_2
    >>> time.sleep(601.)
    >>> time.get('C')
    None
"""

import time

from . import exceptions

default_cachesize             = 20000
default_cache_cleancycle      = 60.
default_cache_expiration_time = 600.

__all__ = ['LRUCache']

class Node(object):

    __slots__ = ['defunct',
                 'expires',
                 'key',
                 'next_',
                 'prev_',
                 'value']

    def __init__(self, key):
        self.next_   = None
        self.prev_   = None
        self.key     = key
        self.value   = None
        self.expires = 0.
        self.defunct = 0

class LRUCache(object):

    (   "LRUCache("
            "size:int=-1, "
            "expiration_time:float=-1, "
            "cleancycle:float=-1"
        ") -> LRUCache" """

    Dict-like Least Recently Used (LRU) cache.
    """)

    __slots__ = ['cleancycle',
                 'data',
                 'head',
                 'expiration_time',
                 'expires',
                 'size',
                 'tail']

    def __init__(self, size=-1, expiration_time=-1, cleancycle=-1):
        if -1 == size:
            self.size = default_cachesize
        else:
            self.size = size
        if -1 == expiration_time:
            self.expiration_time = default_cache_expiration_time
        else:
            self.expiration_time = expiration_time
        if -1 == cleancycle:
            self.cleancycle = default_cache_cleancycle
        else:
            self.cleancycle = cleancycle
        self.expires = time.time() + cleancycle
        self.data = {}
        self.head = Node(None)
        self.tail = Node(None)
        self.head.next_ = self.tail
        self.tail.prev_ = self.head

    def __setitem__(self, key, value):
        """
        Set self[key] to value
        """
        node = self.data.get(key, None)
        if node is None:
            node = Node(key)
            self.data[key] = node
        else:
            node_prev = node.prev_
            node_next = node.next_
            node_prev.next_ = node_next
            node_next.prev_ = node_prev
        now = time.time()
        node.expires = now + self.expiration_time
        node.value = value
        tail = self.tail
        tail_prev  = tail.prev_
        node.prev_ = tail_prev
        node.next_ = tail
        tail_prev.next_ = node
        tail.prev_ = node
        if len(self.data) > self.size or now > self.expires:
            self.garbage_collect(now)

    def __delitem__(self, key):
        """
        Delete self[key]
        """
        now = time.time()
        if now > self.expires:
            self.garbage_collect(now)
        node = self.data.pop(key, None)
        if node is not None:
            node_prev = node.prev_
            node_next = node.next_
            node_prev.next_ = node_next
            node_next.prev_ = node_prev

    def __contains__(self, key):
        """
        True if the dictionary has the specified key, else False.
        """
        return key in self.data

    def pop(self, key, default=None):
        """
        D.pop(key[, default]) -> value

        remove specified key and return the corresponding value.
        """
        now = time.time()
        if now > self.expires:
            self.garbage_collect(now)
        node = self.data.pop(key, None)
        if node is None:
            return default
        else:
            node_prev = node.prev_
            node_next = node.next_
            node_prev.next_ = node_next
            node_next.prev_ = node_prev
            return node.value

    def get(self, key, default=None):
        """
        Return the value for key if key is in the dictionary, else default.
        """
        node = self.data.get(key)
        now = time.time()
        if node is None:
            if now > self.expires:
                self.garbage_collect(now)
            return default
        if now > node.expires:
            self.garbage_collect(now)
            return default
        node.expires = now + self.expiration_time
        node_prev = node.prev_
        node_next = node.next_
        node_prev.next_ = node_next
        node_next.prev_ = node_prev
        tail = self.tail
        tail_prev  = tail.prev_
        node.prev_ = tail_prev
        node.next_ = tail
        tail_prev.next_ = node
        tail.prev_ = node
        if now > self.expires:
            self.garbage_collect(now)
        return node.value

    def garbage_collect(self, now):
        self.expires = now + self.cleancycle
        data = self.data
        size = self.size
        head = self.head
        tail = self.tail
        node = head.next_
        exceptions_ = []
        while node is not tail and now > node.expires:
            key = node.key
            try:
                del data[key]
            except KeyError as exc:
                exceptions_.append(exc)
            node  = node.next_
            head.next_ = node
            node.prev_ = head
        while node is not tail and len(data) > size:
            key = node.key
            try:
                del data[key]
            except KeyError as exc:
                exceptions_.append(exc)
            node  = node.next_
            head.next_ = node
            node.prev_ = head
        if exceptions_:
            if 1 == len(exceptions_):
                raise exceptions_[0]
            else:
                raise exceptions.Exceptions(exceptions_)
