# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
===========================================
:mod:`slowdown.sysutil` -- System utilities
===========================================
"""

import ctypes
import ctypes.util
import os
import os.path
import platform
import pwd
import sys

UNAME_SYSNAME = platform.system()

def cpu_count():
    if  'Windows' == UNAME_SYSNAME:
        return int(os.environ['NUMBER_OF_PROCESSORS'])
    elif 'Darwin' == UNAME_SYSNAME:
        return int(os.popen('sysctl -n hw.ncpu').read())
    else:
        return os.sysconf('SC_NPROCESSORS_ONLN')

def chown(path, user=None, group=None):
    if user is None:
        uid = -1
    else:
        uid = getuid(user)
    if group is None:
        gid = -1
    else:
        gid = getgid(group)
    euid = os.geteuid()
    if euid != 0:
        raise OSError('only root can change owner')
    os.chown(path, uid, gid)

def setuid(user):
    (   "setuid("
            "user:str"
        ") -> None" """

    Set the current process's user id by the specified username.
    """)
    uid  = getuid(user)
    euid = os.geteuid()
    if euid != 0 and euid != uid:
        raise OSError('only root can change users')
    os.setuid(uid)

def getuid(user):
    if isinstance(user, int):
        try:
            pwrec = pwd.getpwuid(user)
        except LookupError:
            raise LookupError('uid {!r} not found'.format(user))
        return user
    else:
        try:
            pwrec = pwd.getpwnam(user)
        except LookupError:
            raise LookupError('no such user: {!r}'.format(user))
        return pwrec[2]

def getgid(group):

    import grp

    if isinstance(group, int):
        try:
            grrec = grp.getgrgid(group)
        except LookupError:
            raise LookupError('gid {!r} not found'.format(group))
        return group
    else:
        try:
            grrec = grp.getgrnam(group)
        except LookupError:
            raise LookupError('no such group: {!r}'.format(group))
        return grrec[2]

def setprocname(procname, key='__PROCNAME__', format='{}'):
    (   "setprocname("
            "procname:str"
        ") -> None" """

    Set the current process's name.
    """)
    libc = load_library('c')
    if key not in os.environ:
        environ = dict(os.environ)
        environ[key] = procname
        os.execlpe(*(
            [sys.executable, format.format(procname) + ' ']
            + sys.argv
            + [environ]
        ))
    procname = ctypes.create_string_buffer(procname.encode() + b'\0')
    if     'Linux' == UNAME_SYSNAME:
        PR_SET_NAME = 15
        libc.prctl(PR_SET_NAME, procname, 0, 0, 0)
    elif 'FreeBSD' == UNAME_SYSNAME:
        libc.setproctitle(procname)
    else:
        raise NotImplementedError(UNAME_SYSNAME)

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
