# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
=========================================================
:mod:`slowdown.logging` -- Cooperative and simple logging
=========================================================
"""

import gevent
import gevent.queue
import logging
import os.path
import sys
import time
import weakref

default_file_queue_maxsize = 2048

__all__ = ['File', 'Logger']

DISABLED  = 0xffff
CRITICAL  = logging.CRITICAL
assert DISABLED  >  CRITICAL
FATAL     = CRITICAL
ERROR     = logging.ERROR
WARNING   = logging.WARNING
INFO      = logging.INFO
DEBUG     = logging.DEBUG
NOTSET    = logging.NOTSET
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
            self.file.write(self.format_errorlog(CRITICAL, msg))
            if self.immediately:
                self.file.flush()

    def fatal(self, msg):
        (   "fatal("
                "msg:str"
            ") -> None" """

        Log a message with severity 'FATAL' on the error log.
        """)
        if FATAL >= self.level:
            self.file.write(self.format_errorlog(FATAL, msg))
            if self.immediately:
                self.file.flush()

    def error(self, msg):
        (   "error("
                "msg:str"
            ") -> None" """

        Log a message with severity 'ERROR' on the error log.
        """)
        if ERROR >= self.level:
            self.file.write(self.format_errorlog(ERROR, msg))
            if self.immediately:
                self.file.flush()

    def warning(self, msg):
        (   "warning("
                "msg:str"
            ") -> None" """

        Log a message with severity 'WARNING' on the error log.
        """)
        if WARNING >= self.level:
            self.file.write(self.format_errorlog(ERROR, msg))
            if self.immediately:
                self.file.flush()

    def warn(self, msg):
        (   "warn("
                "msg:str"
            ") -> None" """

        Log a message with severity 'WARNING' on the error log.
        """)
        if WARNING >= self.level:
            self.file.write(self.format_errorlog(ERROR, msg))
            if self.immediately:
                self.file.flush()

    def info(self, msg):
        (   "info("
                "msg:str"
            ") -> None" """

        Log a message with severity 'INFO' on the error log.
        """)
        if INFO >= self.level:
            self.file.write(self.format_errorlog(INFO, msg))
            if self.immediately:
                self.file.flush()

    def debug(self, msg):
        (   "debug("
                "msg:str"
            ") -> None" """

        Log a message with severity 'DEBUG' on the error log.
        """)
        if DEBUG >= self.level:
            self.file.write(self.format_errorlog(DEBUG, msg))
            if self.immediately:
                self.file.flush()

    def format_errorlog(self, level, msg):
        return \
            self.errorlog_fmt.format(
                time=time.strftime(self.strftime_fmt),
                level=self.level_name_map[level],
                msg=msg
            )

class File(object):

    (   "File("
            "fs:slowdown.fs.FS, "
            "filename:str, "
            "encoding:str='utf-8'"
        ")"
    )
    __slots__ = ['encoding', 'file', 'filename', 'queue', '__weakref__']

    def __init__(self, fs, filename, maxsize=-1, encoding='utf-8'):
        if -1 == maxsize:
            maxsize = default_file_queue_maxsize
        self.file = fs.open(filename, 'ab')
        self.queue = gevent.queue.Queue (maxsize)
        self.encoding = encoding
        self.filename = filename

    def spawn(self):
        _logfile = weakref.ref(self)
        return [gevent.spawn(write_loop, _logfile)]

    def write(self, data):
        if isinstance(data, str):
            self.queue.put(data.encode(self.encoding))
        else:
            self.queue.put(data)

    def flush(self):
        self.queue.put('')

def write_loop(_logfile):
    its_time_to_flush = False
    while True:
        logfile = _logfile()
        if logfile is None:
            return
        try:
            data = logfile.queue.get()
        except gevent.GreenletExit as err:
            return logfile.file.close()
        except:
            logfile.file.close()
            raise
        if data:
            try:
                logfile.file.write(data)
            except:
                logfile.file.close()
                raise
            if logfile.queue.empty() and its_time_to_flush:
                try:
                    logfile.file.flush()
                except:
                    logfile.file.close()
                    raise
                its_time_to_flush = False
        else:
            if logfile.queue.empty():
                try:
                    logfile.file.flush()
                except:
                    logfile.file.close()
                    raise
                its_time_to_flush = False
            else:
                its_time_to_flush = True
