# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
=======================================================
:mod:`slowdown.fs` -- Cooperative file system interface
=======================================================

This module provides cooperative versions of the `os` and `os.path`
module, base on the `gevent.threadpool.ThreadPool` .
"""

import gevent
import gevent.fileobject
import io
import os
import sys

from . import inotify

__all__ = ['FS']

class FS(object):

    """
    The cooperative file system interface.
    """

    __slots__ = ['inotify',
                 'io',
                 'open',
                 'os',
                 '__weakref__']

    def __init__(self):
        self.inotify  = inotify.Inotify()
        self.io       = IO()  #: The cooperative version of `io` module.
        self.os       = OS()  #: The cooperative version of `os` module.

        #: The cooperative version of built-in `open` function.
        self.open     = self.io.open

    def spawn(self):
        """
        Begin IO loop tasks.
        """
        return [gevent.spawn(inotify_loop, self.inotify)]

def inotify_loop(inotify_):
    while True:
        inotify_.poll()

class IO(object):

    __slots__ = ['open']

    def __init__(self):
        self.open = IOOpen()

class IOOpen(object):

    def __call__(self, path, mode='rb', closefd=True, *args, **kwds):
        # the version of gevent should be greater than 20.04.0
        # to support the string type path.
        return \
            gevent.fileobject.FileObject(
                        path,
                   mode=mode,
                closefd=closefd,
                       *args,
                      **kwds
            )

os_all = '''\
access,chmod,chown,close,closerange,fchmod,fchown,fstat,fstatvfs,ftruncate\
,fwalk,lchown,link,listdir,lstat,makedirs,mkdir,open,remove,removedirs,ren\
ame,renames,rmdir,stat,unlink,walk'''.split(',')
os_all = [name for name in os_all if hasattr(os, name)]
for name in os_all:
    exec ('''\
from os import {name} as original_os_{name}
def os_{name}(*args, **kwds):
    return \\
        gevent.get_hub().threadpool.apply(
            original_os_{name}, args, kwds
        )
os_{name}.__doc__ = original_os_{name}.__doc__'''.format(name=name))
path_all = '''\
abspath,exists,getatime,getctime,getmtime,getsize,isdir,isfile,islink,ismo\
unt,lexists,realpath,relpath'''.split(',')

class OS(object):

    """
    The cooperative version of `os` module.
    """

    __slots__ = os_all + ['path']

    def __init__(self):
        for name in os_all:
            setattr(self, name, globals()['os_'+name])
        self.path = Path()  #: The cooperative version of `os.path` module.

path_all = [name for name in path_all if hasattr(os.path, name)]
for name in path_all:
    exec ('''\
from os.path import {name} as original_path_{name}
def path_{name}(*args, **kwds):
    return \\
        gevent.get_hub().threadpool.apply(
            original_path_{name}, args, kwds
        )
path_{name}.__doc__ = original_path_{name}.__doc__'''.format(name=name))

class Path(object):

    """
    The cooperative version of `os.path` module.
    """

    __slots__ = path_all

    def __init__(self):
        for name in path_all:
            setattr(self, name, globals()['path_'+name])
