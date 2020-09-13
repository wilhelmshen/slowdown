# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
=========================================================
:mod:`slowdown.logging` -- Cooperative and simple logging
=========================================================

This module providers a logging implementation for high concurrent
services. Instead of performing file operations immediately, this module
performs writes in the background when the buffer is full.

Example:

    >>> file = RotatingFile(application.fs, '$LOGS/error-%Y%m.log')
    >>> logger = Logger(file, level=DEBUG)
    >>> logger.debug('debug msg')
    >>> logger.info('info msg')
    >>> logger.level = ERROR
    >>> logger.error('error msg')
    >>> logger.critical('fatal msg')
"""

import gevent
import gevent.queue
import os.path
import sys
import time
import weakref

from logging import CRITICAL, DEBUG, ERROR, FATAL, INFO, NOTSET, WARNING

default_file_queue_maxsize = 2048

__all__ = ['File', 'Logger', 'RotatingFile']

DISABLED  = 0xffff
assert DISABLED > CRITICAL
levelcode = \
    {
        'DISABLED': DISABLED,
        'CRITICAL': CRITICAL,
           'FATAL': FATAL,
           'ERROR': ERROR,
         'WARNING': WARNING,
            'INFO': INFO,
           'DEBUG': DEBUG,
          'NOTSET': NOTSET
    }
default_strftime_fmt  = '%Y-%m-%d %H:%M:%S'
default_errorlog_fmt  = '{time} {level} {msg}'
default_accesslog_fmt = '{time} {msg}'

class Logger(object):

    (   "Logger("
            "file:File=None, "
            "level:int=NOTSET, "
            "immediately:bool=True, "
            "accesslog_fmt:str=None, "
            "errorlog_fmt:str=None, "
            "strftime_fmt:str=None"
        ")"
    )
    __slots__ = ['accesslog_fmt',
                 'errorlog_fmt',
                 'file',
                 'immediately',
                 'level',
                 'level_name_map',
                 'strftime_fmt']

    def __init__(self, file=None, level=NOTSET, immediately=True,
                 accesslog_fmt=None, errorlog_fmt=None,
                                     strftime_fmt=None):
        if file is None:
            self.file = sys.stdout
        else:
            self.file = file
        self.level = level
        self.immediately = immediately
        if accesslog_fmt is None:
            accesslog_fmt = default_accesslog_fmt
        if accesslog_fmt.endswith('\n'):
            self.accesslog_fmt = accesslog_fmt
        else:
            self.accesslog_fmt = accesslog_fmt + '\n'
        if errorlog_fmt is None:
            errorlog_fmt = default_errorlog_fmt
        if errorlog_fmt.endswith('\n'):
            self.errorlog_fmt = errorlog_fmt
        else:
            self.errorlog_fmt = errorlog_fmt + '\n'
        if strftime_fmt is None:
            self.strftime_fmt = default_strftime_fmt
        else:
            self.strftime_fmt = strftime_fmt
        self.level_name_map = \
            dict(
                (value, key) for key, value in
                levelcode.items()
           )

    def access(self, msg):
        (   "access("
                "msg:str"
            ") -> None" """

        Log a message on the access log.
        """)
        self.file.write(
            self.accesslog_fmt.format(
                time=time.strftime(self.strftime_fmt),
                msg=msg
            )
        )
        if self.immediately:
            self.file.flush()

    def critical(self, msg):
        (   "critical("
                "msg:str"
            ") -> None" """

        Log a message with severity 'CRITICAL' on the error log.
        """)
        if CRITICAL >= self.level:
            self._log_error(CRITICAL, msg)

    def fatal(self, msg):
        (   "fatal("
                "msg:str"
            ") -> None" """

        Log a message with severity 'FATAL' on the error log.
        """)
        if FATAL >= self.level:
            self._log_error(FATAL, msg)

    def error(self, msg):
        (   "error("
                "msg:str"
            ") -> None" """

        Log a message with severity 'ERROR' on the error log.
        """)
        if ERROR >= self.level:
            self._log_error(ERROR, msg)

    def warning(self, msg):
        (   "warning("
                "msg:str"
            ") -> None" """

        Log a message with severity 'WARNING' on the error log.
        """)
        if WARNING >= self.level:
            self._log_error(WARNING, msg)

    def warn(self, msg):
        (   "warn("
                "msg:str"
            ") -> None" """

        Log a message with severity 'WARNING' on the error log.
        """)
        if WARNING >= self.level:
            self._log_error(WARNING, msg)

    def info(self, msg):
        (   "info("
                "msg:str"
            ") -> None" """

        Log a message with severity 'INFO' on the error log.
        """)
        if INFO >= self.level:
            self._log_error(INFO, msg)

    def debug(self, msg):
        (   "debug("
                "msg:str"
            ") -> None" """

        Log a message with severity 'DEBUG' on the error log.
        """)
        if DEBUG >= self.level:
            self._log_error(DEBUG, msg)

    def _log_error(self, level, msg):
        self.file.write(
            self.errorlog_fmt.format(
                time=time.strftime(self.strftime_fmt),
                level=self.level_name_map[level],
                msg=msg
            )
        )
        if self.immediately:
            self.file.flush()

class RotatingFile(object):

    (   "RotatingFile("
            "fs:slowdown.fs.FS, "
            "fmt:str, "
            "maxsize:int=-1, "
            "encoding:str='utf-8'"
        ")" """

    The name of the log file is obtained via time.strftime( :param:`fmt` )
    """)

    __slots__ = ['closed',
                 'curr',
                 'encoding',
                 'file',
                 'fmt',
                 'fs',
                 'maxsize',
                 '__weakref__']

    def __init__(self, fs, fmt, maxsize=-1, encoding='utf-8'):
        if -1 == maxsize:
            self.maxsize = default_file_queue_maxsize
        else:
            self.maxsize = maxsize
        self.closed   = False
        self.curr     = None
        self.encoding = encoding
        self.file     = None
        self.fmt      = fmt
        self.fs       = fs

    def __del__(self):
        if not self.closed:
            self.close()

    def write(self, data):
        if self.closed:
            raise ValueError('I/O operation on closed file.')
        path = time.strftime(self.fmt)
        if self.curr == path:
            self.file.write(data)
        else:
            file      = self.file
            self.curr = time.strftime(self.fmt)
            self.file = \
                File(
                    self.fs,
                    self.curr,
                    self.maxsize,
                    self.encoding
                )
            self.file.write(data)
            if file is not None:
                file.close()
                file.syncer.join()

    def flush(self):
        if self.closed:
            raise ValueError('I/O operation on closed file.')
        path = time.strftime(self.fmt)
        if self.curr == path:
            self.file.flush()
        else:
            file      = self.file
            self.curr = time.strftime(self.fmt)
            self.file = \
                File(
                    self.fs,
                    self.curr,
                    self.maxsize,
                    self.encoding
                )
            self.file.flush()
            if file is not None:
                file.close()
                file.syncer.join()

    def close(self):
        if not self.closed:
            self.closed = True
            file = self.file
            self.curr = None
            self.file = None
            if file is not None:
                try:
                    file.close()
                    file.syncer.join()
                except:
                    self.closed = False
                    raise

class File(object):

    (   "File("
            "fs:slowdown.fs.FS, "
            "filename:str, "
            "encoding:str='utf-8'"
        ")"
    )
    __slots__ = ['closed',
                 'encoding',
                 'file',
                 'filename',
                 'queue',
                 'syncer',
                 '__weakref__']

    def __init__(self, fs, filename, maxsize=-1, encoding='utf-8'):
        if -1 == maxsize:
            maxsize = default_file_queue_maxsize
        self.file = fs.open(filename, 'ab')
        self.queue = gevent.queue.Queue (maxsize)
        self.encoding = encoding
        self.filename = filename
        self.closed = False
        self.syncer = gevent.spawn(syncer, weakref.ref(self))

    def __del__(self):
        if not self.closed:
            self.close()

    def write(self, data):
        if self.closed:
            raise ValueError('I/O operation on closed file.')
        if isinstance(data, str):
            self.queue.put(data.encode(self.encoding))
        else:
            self.queue.put(data)

    def flush(self):
        if self.closed:
            raise ValueError('I/O operation on closed file.')
        self.queue.put('')

    def close(self):
        if not self.closed:
            self.file.close()
            self.closed = True
            self.queue.put(None)
            self.syncer.join()

def syncer(_logfile):
    its_time_to_flush = False
    while True:
        logfile = _logfile()
        if logfile is None:
            return
        try:
            data = logfile.queue.get()
        except gevent.GreenletExit as err:
            logfile.file.close()
            logfile.closed = True
            return
        except:
            logfile.file.close()
            logfile.closed = True
            raise
        if data:
            try:
                logfile.file.write(data)
            except:
                logfile.file.close()
                logfile.closed = True
                raise
            if logfile.queue.empty() and its_time_to_flush:
                try:
                    logfile.file.flush()
                except:
                    logfile.file.close()
                    logfile.closed = True
                    raise
                its_time_to_flush = False
        elif data is '':
            if logfile.queue.empty():
                try:
                    logfile.file.flush()
                except:
                    logfile.file.close()
                    logfile.closed = True
                    raise
                its_time_to_flush = False
            else:
                its_time_to_flush = True
        elif data is None:
            return
        else:
            raise TypeError('cannot handle this data type')
