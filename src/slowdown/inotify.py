# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""A simple Python wrapper around inotify."""

import ctypes
import ctypes.util
import errno
import gevent.socket
import io
import os
import os.path
import struct
import sys

IN_ACCESS        = 0x00000001  # File was accessed.
IN_MODIFY        = 0x00000002  # File was modified.
IN_ATTRIB        = 0x00000004  # Metadata changed.
IN_CLOSE_WRITE   = 0x00000008  # Writtable file was closed.
IN_CLOSE_NOWRITE = 0x00000010  # Unwrittable file closed.
IN_CLOSE = (IN_CLOSE_WRITE | IN_CLOSE_NOWRITE)  # Close.
IN_OPEN          = 0x00000020  # File was opened.
IN_MOVED_FROM    = 0x00000040  # File was moved from X.
IN_MOVED_TO      = 0x00000080  # File was moved to Y.
IN_MOVE = (IN_MOVED_FROM | IN_MOVED_TO)  # Moves.
IN_CREATE        = 0x00000100  # Subfile was created.
IN_DELETE        = 0x00000200  # Subfile was deleted.
IN_DELETE_SELF   = 0x00000400  # Self was deleted.
IN_MOVE_SELF     = 0x00000800  # Self was moved.

# Events sent by the kernel.
IN_UNMOUNT       = 0x00002000  # Backing fs was unmounted.
IN_Q_OVERFLOW    = 0x00004000  # Event queued overflowed.
IN_IGNORED       = 0x00008000  # File was ignored.

# Helper events.
IN_CLOSE = (IN_CLOSE_WRITE | IN_CLOSE_NOWRITE)  # Close.
IN_MOVE  = (IN_MOVED_FROM  | IN_MOVED_TO)       # Moves.

# Special flags.
IN_ONLYDIR       = 0x01000000  # Only watch the path if it is a
                               # directory.
IN_DONT_FOLLOW   = 0x02000000  # Do not follow a sym link.
IN_EXCL_UNLINK   = 0x04000000  # Exclude events on unlinked
                               # objects.
IN_MASK_ADD      = 0x20000000  # Add to the mask of an already
                               # existing watch.
IN_ISDIR         = 0x40000000  # Event occurred against dir.
IN_ONESHOT       = 0x80000000  # Only send event once.

# All events which a program can wait on.
IN_ALL_EVENTS    = IN_ACCESS | IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE     \
                 | IN_CLOSE_NOWRITE | IN_OPEN | IN_MOVED_FROM             \
                 | IN_MOVED_TO | IN_CREATE | IN_DELETE                    \
                 | IN_DELETE_SELF | IN_MOVE_SELF

# Flags for sys_inotify_init1.
if hasattr(os, 'O_CLOEXEC'):
    IN_CLOEXEC   = os.O_CLOEXEC
IN_NONBLOCK      = os.O_NONBLOCK

default_maxevents   = 1024
default_buffer_size = io.DEFAULT_BUFFER_SIZE
default_fs_encoding = sys.getdefaultencoding()

__all__ = ['Inotify',
           'IN_ACCESS',
           'IN_ALL_EVENTS',
           'IN_ATTRIB',
           'IN_CLOSE',
           'IN_CLOSE_WRITE',
           'IN_CLOSE_NOWRITE',
           'IN_CREATE',
           'IN_DELETE',
           'IN_DELETE_SELF',
           'IN_DONT_FOLLOW',
           'IN_EXCL_UNLINK',
           'IN_IGNORED',
           'IN_ISDIR',
           'IN_MASK_ADD',
           'IN_MODIFY',
           'IN_MOVE',
           'IN_MOVED_FROM',
           'IN_MOVED_TO',
           'IN_MOVE_SELF',
           'IN_NONBLOCK',
           'IN_ONESHOT',
           'IN_ONLYDIR',
           'IN_OPEN',
           'IN_Q_OVERFLOW',
           'IN_UNMOUNT']

class Inotify(object):

    __slots__ = ['cbs', 'encoding', 'fd', 'reader']

    def __init__(self, maxevents=None, buffer_size=None, encoding=None):
        self.fd = libc.inotify_init1(IN_NONBLOCK)
        if -1 == self.fd:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
        self.cbs = {}
        if maxevents is None:
            maxevents = default_maxevents
        raw = InotifyEventRawIo(self.fd, maxevents=maxevents)
        if buffer_size is None:
            buffer_size = default_buffer_size
        self.reader = io.BufferedReader(raw, buffer_size)
        if encoding is None:
            self.encoding = default_fs_encoding
        else:
            self.encoding = encoding

    def __del__(self):
        for wd, dummy in self.cbs.items():
            libc.inotify_rm_watch(self.fd, wd)
        self.reader.close()
        os.close(self.fd)

    def add_watch(self, name, mask, callback):
        wd = \
            libc.inotify_add_watch(
                self.fd,
                as_bytes(name, self.encoding) + b'\0',
                mask
            )
        if -1 == wd:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
        self.cbs[wd] = callback
        return wd

    def rm_watch(self, wd):
        if wd not in self.cbs:
            raise KeyError(wd)
        libc.inotify_rm_watch(self.fd, wd)
        del self.cbs[wd]

    def poll(self):
        data = self.reader.read(inotify_event_len)
        (wd, mask, cookie, len_) = struct.unpack(inotify_event_fmt, data)
        name = self.reader.read(len_).rstrip(b'\0').decode(self.encoding)
        if wd in self.cbs:
            self.cbs[wd](wd, mask, cookie, name)

class InotifyEventRawIo(io.RawIOBase):

    def __init__(self, fd, maxevents=None):
        io.RawIOBase.__init__(self)
        self.fd = fd
        if maxevents is None:
            self.maxevents = default_maxevents
        else:
            self.maxevents = maxevents

    def readinto(self, b):
        gevent.socket.wait_read(self.fd)
        data = os.read(self.fd, self.maxevents)
        length = len(data)
        b[0:length] = data
        return length

    def readable(self):
        return True

class Broken(object):

    def __init__(self, *args):
        raise RuntimeError('inotify is not working properly')

def as_bytes(string, encoding=None):
    """
    as_bytes(string:Union[str,bytes], encoding:str=None) -> bytes
    """
    if   isinstance(string, str):
        return \
            string.encode(
                sys.getdefaultencoding() if encoding is None else encoding
            )
    elif isinstance(string, bytes):
        return string
    else:
        raise \
            TypeError(
                f'expected binary or unicode string, got {repr(string)}'
        )

def find_library(name):
    where = ctypes.util.find_library(name)
    if where is not None:
        return where
    root = 'lib' + name
    dn = os.path.dirname(__file__)
    base = os.path.abspath(dn)
    for fn in os.listdir(base):
        items = fn.split('.')
        if len(items) > 1 and items[0] == root and \
           items[1] in ('so', 'dll', 'dylib'):
            where = os.path.join(base, fn)
            if os.path.isfile(where):
                return where

def load_library(name, use_errno=True):
    where = find_library(name)
    if where is None:
        raise RuntimeError('needs lib{} installed.'.format(name))
    return ctypes.CDLL(where, use_errno=use_errno)

try:
    libc = load_library('c')
    c_uint32_t = ctypes.c_uint

    # Create and initialize inotify instance.
    libc.inotify_init.argtypes = ()
    libc.inotify_init.restype  = ctypes.c_int

    # Create and initialize inotify instance.
    libc.inotify_init1.argtypes = (ctypes.c_int, )
    libc.inotify_init1.restype  =  ctypes.c_int

    # Add watch of object NAME to inotify instance FD.  Notify about
    # events specified by MASK.
    libc.inotify_add_watch.argtypes = \
        (ctypes.c_int, ctypes.c_char_p, c_uint32_t)
    libc.inotify_add_watch.restype  = ctypes.c_int

    # Remove the watch specified by WD from the inotify instance FD.
    libc.inotify_rm_watch.argtypes = (ctypes.c_int, ctypes.c_int)
    libc.inotify_rm_watch.restype  =  ctypes.c_int

    inotify_event_fmt = 'iIII'
    inotify_event_len = struct.calcsize(inotify_event_fmt)
except (RuntimeError, AttributeError):
    libc    = None
    Inotify = Broken
