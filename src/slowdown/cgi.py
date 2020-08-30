# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
=======================================================
:mod:`slowdown.cgi` -- Common Gateway Interface support
=======================================================

This module provides CGI protocol support for `Slowdown Web Programming` .

Examples:

    >>> form = \\
    ...     slowdown.cgi.Form(
    ...         rw,             # the incoming `slowdown.http.File` object.
    ...
    ...         max_size=10240  # the length of the http content containing
    ...                         # the CGI form data should be less than
    ...                         # `max_size` (bytes).
    ... )
    >>> form['checkboxA']
    'a'
    >>> # If more than one form variable comes with the same name,
    >>> # a list is returned.
    >>> form['checkboxB']
    ['a', 'b', 'c']

    >>> # The CGI message must be read completely in order to
    >>> # respond further, so use 'for .. in' to ensure that
    >>> # no parts are unprocessed.
    >>> for part in \\
    ...     multipart(
    ...         rw,  # the incoming `slowdown.http.File` object
    ...
    ...         # Uploaded files always store their binary filenames in
    ...         # multi-parts heads. Those filenames require an encoding
    ...         # to convert to strings.
    ...         filename_encoding='utf-8'  # the default is 'iso8859-1'
    ...     ):
    >>>     # The reading of the current part must be completed
    >>>     # before the next part.
    >>>     if part.filename is None:  # ordinary form variable
    >>>         print (f'key  : {part.name  }')
    ...         print (f'value: {part.read()}')
    >>>     else:  # file upload
    >>>         with open(part.filename, 'w') as file_out:
    >>>             while True:
    >>>                 data = part.read(8192)
    >>>                 file_out.write(data)
    >>>                 if not data:
    >>>                     break
"""

import cgi
import io
import sys
import urllib.error

from . import http
from . import urlencode

__all__ = ['BadRequest', 'Form', 'multipart', 'MultipartReader']

default_form_max_size       = 0x200000
default_form_key_encoding   = 'utf-8'
default_form_value_encoding = 'utf-8'

class Form(dict):

    (   "Form("
            "rw:slowdown.http.File, "
            "max_size:int=None, "
            "key_encoding:str='utf-8', "
            "value_encoding:str='utf-8'"
        ") -> dict" """

    The CGI form parser.
    """)

    def __init__(self, rw, max_size=None,
                   key_encoding=default_form_key_encoding,
                 value_encoding=default_form_value_encoding):
        dict.__init__(self)
        if max_size is None:
            max_size = default_form_max_size
        if rw.left > max_size:
            raise BadRequest( 'request body (Content-Length) is larger '
                             f'than the configured limit ({max_size})')
        self.  key_encoding =   key_encoding
        self.value_encoding = value_encoding
        if rw.left > 0:
            b_query_string = rw.read()
            self.update_query_string(b_query_string)
        u_query_string = rw.environ['QUERY_STRING']
        if u_query_string:
            self.update_query_string(
                u_query_string.encode(http.http_header_encoding)
            )

    def update_query_string(self, b_query_string):
        for item in b_query_string.split(b'&'):
            kv = item.split(b'=', 1)
            if len(kv) != 2:
                continue
            b_k, b_v = kv
            if self.key_encoding is None:
                k = urlencode.unquote_plus(b_k)
            else:
                k = urlencode.unquote_plus(b_k).decode(self.  key_encoding)
            if self.value_encoding is None:
                v = urlencode.unquote_plus(b_v)
            else:
                v = urlencode.unquote_plus(b_v).decode(self.value_encoding)
            value = self.get(k)
            if value is None:
                self[k] = v
            elif isinstance(value, (str, bytes)):
                self[k] = [value, v]
            elif isinstance(value, list):
                value.append(v)
            else:
                raise AssertionError('value must be a list or a bytes '
                                     'but got {!r}'.format(value))

def multipart(rw, filename_encoding=None, buffer_size=None):
    (   "multipart("
            "rw:slowdown.http.File, "
            "filename_encoding:str=None, "
            "buffer_size:int=None"
        ") -> Iterator[MultipartReader]"
    )
    if buffer_size is None:
        buffer_size = io.DEFAULT_BUFFER_SIZE
    p_dict = cgi.parse_header(rw.environ['CONTENT_TYPE'])[1]
    boundary = p_dict['boundary'].encode(http.http_header_encoding)
    data = rw.readline(2048)
    if b'\r\n' == data[-2:]:
        if b'--' + boundary != data[:-2]:
            raise BadRequest()
        nl = b'\r\n'
    elif 10 == data[-1]:
        if b'--' + boundary != data[:-1]:
            raise BadRequest()
        nl = b'\n'
    else:
        raise BadRequest()
    raw = MultipartRawIO (rw, boundary, nl)
    yield MultipartReader(rw, raw, buffer_size)
    while rw.left > 0:
        if not raw.met_EOF:
            raise RuntimeError('Previous reading has not finished')
        raw = MultipartRawIO (rw, boundary, nl)
        yield MultipartReader(rw, raw, buffer_size)

class MultipartReader(io.BufferedReader):

    __slots__ = ['environ',
                 'filename',
                 'name',
                 '_filename_encoding']

    def __init__(self, rw, raw, buffer_size=None):
        if buffer_size is None:
            buffer_size = io.DEFAULT_BUFFER_SIZE
        environ = {}
        data = rw.readline(2048)
        size = len(data)
        self._filename_encoding = http.http_header_encoding
        while 1:
            match = http.regx_headers.match(data)
            if match is None:
                if b'\r\n' == data or b'\n' == data:
                    break
                raise BadRequest('Invalid http headers')
            (b_key, b_value) = match.groups()
            key = b_key.decode(self._filename_encoding) \
                       .replace('-', '_') \
                       .upper()
            environ['HTTP_' + key] = \
                b_value.decode(self._filename_encoding)
            data = rw.readline(2048)
            size += len(data)
            if size > 8192:
                raise BadRequest('Request header is too large')
        g_dict = cgi.parse_header(environ['HTTP_CONTENT_DISPOSITION'])[1]
        io.BufferedReader.__init__(self, raw, buffer_size)
        self.name     = g_dict.get('name')
        self.filename = g_dict.get('filename')
        self.environ  = environ

    @property
    def filename_encoding(self):
        return self._filename_encoding

    @filename_encoding.setter
    def filename_encoding(self, encoding):
        if encoding != self._filename_encoding:
            if self.name is not None:
                self.name = self.name.encode(self._filename_encoding) \
                                     .decode(encoding)
            if self.filename is not None:
                self.filename = \
                    self.filename.encode(self._filename_encoding) \
                                 .decode(encoding)
            self._filename_encoding = encoding

class MultipartRawIO(io.RawIOBase):

    __slots__ = ['guess_size',
                 'met_EOF',
                 'next_',
                 'next_len',
                 'nl',
                 'nl_len',
                 'rw',
                 'stop_',
                 'stop_len',
                 'tail']

    def __init__(self, rw, boundary, nl):
        io.RawIOBase.__init__(self)
        if b'\r\n' == nl:
            self.nl     = b'\r\n'
            self.nl_len = 2
            self.next_  = b'--%s\r\n' % boundary
            self.stop_  = b'--%s--\r\n' % boundary
        elif b'\n' == nl:
            self.nl     = b'\n'
            self.nl_len = 1
            self.next_  = b'--%s\n' % boundary
            self.stop_  = b'--%s--\n' % boundary
        else:
            raise BadRequest()
        self.next_len = len(self.next_)
        self.stop_len = len(self.stop_)
        self.rw = rw
        self.guess_size = rw.left - self.nl_len - self.stop_len
        self.met_EOF = False
        self.tail = None

    def readinto(self, b):
        if self.met_EOF:
            return 0
        data = self.rw.readline(2048)
        if not data:
            raise BadRequest()
        size = len(data)
        if LF == data[-1]:
            if self.tail is None:
                if 2 == self.nl_len:
                    if size > 1 and b'\r\n' == data[size-2:size]:
                        res = size - 2
                        self.tail = b'\r\n'
                        if 0 == res:
                            return self.readinto(b)
                        else:
                            b[0:res] = data[0:res]
                            return res
                    else:
                        b[0:size] = data
                        assert self.tail is None
                        return size
                else:
                    assert 1 == self.nl_len
                    res = size - 1
                    self.tail = b'\n'
                    if 0 == res:
                        return self.readinto(b)
                    else:
                        b[0:res] = data[0:res]
                        return res
            if size == self.next_len and \
               data == self.next_    and \
               self.tail == self.nl:
                self.tail = None
                self.met_EOF = True
                return 0
            if size == self.stop_len and \
               data == self.stop_    and \
               self.tail == self.nl:
                if self.rw.left != 0:
                    raise BadRequest()
                self.tail = None
                self.met_EOF = True
                return 0
            if 2 == self.nl_len:
                if size > 1 and b'\r\n' == data[size-2:size]:
                    tail_len = len(self.tail)
                    data_len = size - 2
                    res = tail_len + data_len
                    b[0:tail_len] = self.tail
                    b[tail_len:res] = data[0:data_len]
                    self.tail = b'\r\n'
                    assert res > 0
                    return res
                elif b'\r' == self.tail and b'\n' == data:
                    self.tail = b'\r\n'
                    return self.readinto(b)
                else:
                    tail_len = len(self.tail)
                    res = tail_len + size
                    b[0:tail_len] = self.tail
                    b[tail_len:res] = data
                    self.tail = None
                    assert res > 0
                    return res
            else:
                assert 1 == self.nl_len
                b[0:1] = b'\n'
                b[1:size] = data[0:size-1]
                assert b'\n' == self.tail
                assert size > 0
                return size
        elif 2 == self.nl_len:
            if self.tail is None:
                if CR == data[-1]:
                    res = size - 1
                    self.tail = b'\r'
                    if 0 == res:
                        return self.readinto(b)
                    else:
                        b[0:res] = data[0:res]
                        return res
                else:
                    b[0:size] = data
                    assert self.tail is None
                    assert size > 0
                    return size
            if CR == data[-1]:
                tail_len = len(self.tail)
                data_len = size - 1
                res = tail + data_len
                b[0:tail_len] = self.tail
                b[tail_len:res] = data[0:data_len]
                self.tail = b'\r'
                assert res > 0
                return res
            else:
                tail_len = len(self.tail)
                res = tail_len + size
                b[0:tail_len] = self.tail
                b[tail_len:res] = data
                self.tail = None
                assert res > 0
                return res
        else:
            assert 1 == self.nl_len
            if self.tail is None:
                b[0:size] = data
                assert self.tail is None
                assert size > 0
                return size
            else:
                assert b'\n' == self.tail
                res = size + 1
                b[0:1] = b'\n'
                b[1:res] = data
                self.tail = None
                assert res > 0
                return res

    def readable(self):
        return True

class BadRequest(urllib.error.HTTPError):

    def __init__(self, msg='Bad Request'):
        urllib.error.HTTPError.__init__(self, None, 400, msg, None, None)

CR = ord(b'\r')
LF = ord(b'\n')
