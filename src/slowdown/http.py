# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
=================================================
:mod:`slowdown.http` -- HTTP/1.1 protocol support
=================================================

This module defines a class, :class:`File`, which enhances
`gevent.socket.socket` by supporting buffering file interfaces and the
HTTP/1.1 protocol.

When the underlying **handler** of `gevent.server.Server` accepts
parameters `socket` and `address`, this module provides another class,
`Handler`, which turn the function that accepts the parameter **rw**
(which is a :class:`File` object) into the standard **handler** of
`gevent.server.Server` .

In general, the :class:`File` object is sometimes called **rw** , which
means the `Read-Write Pair` .

Examples:

::

    # Working with gevent.server.Server

    import gevent.server
    import slowdown.http

    def handler(rw):

        # HTTP headers are stored in a dict named `environ`
        print (rw.environ['REMOTE_ADDR'])
        print (rw.environ['REMOTE_PORT'])
        print (rw.environ['PATH_INFO'])

        # Read the HTTP content. Bytes are returned.
        data = rw.read()

        # Send response to client
        rw.start_response(
            status='200 OK',  # the default is '200 OK'

            # the default is []
            headers=[('Content-Type', 'text/plain')]
        )
        rw.write(b'It works!')
        rw.close()

    server = \\
        gevent.server.Server(
            ('0.0.0.0', 8080),
            slowdown.http.Handler(handler)
        )
    server.serve_forever()

::

    # Using cookies

    import http.cookies
    def handler(rw):

        # Get cookies
        # `None` will be returned if there are no cookies exists.
        cookie = rw.cookie  # `http.cookies.SimpleCookie` object

        # Set cookies
        new_cookie = http.cookies.SimpleCookie()
        new_cookie['key'] = 'value'
        rw.send_html_and_close(
            content='<html>OK</html>',
            cookie=new_cookie
        )

Fast response utils:

================= =======================================
 Response Status                   Method
================= =======================================
        /          :meth:`File.send_response_and_close`
        /          :meth:`File.send_html_and_close`
     **304**       :meth:`File.not_modified`
     **400**       :meth:`File.bad_request`
     **403**       :meth:`File.forbidden`
     **404**       :meth:`File.not_found`
     **405**       :meth:`File.method_not_allowed`
     **413**       :meth:`File.request_entity_too_large`
     **414**       :meth:`File.request_uri_too_large`
     **500**       :meth:`File.internal_server_error`
     **300**       :meth:`File.multiple_choices`
     **301**       :meth:`File.moved_permanently`
     **302**       :meth:`File.found`
     **303**       :meth:`File.see_other`
     **307**       :meth:`File.temporary_redirect`
================= =======================================

Example::

    def handler(rw):
        return rw.not_found()
"""

import errno
import gevent
import gevent.socket
import gevent.ssl
import html
import http.cookies
import random
import re
import sys
import urllib.parse

from . import gvars
from . import logging
from . import urlencode

http_header_encoding  = 'utf-8'  # or 'iso8859-1'
http_content_encoding = 'utf-8'
default_mime_type = 'application/octet-stream'
header_parsing_timeout = 60.
max_keep_alive = 300.

__all__ = ['File', 'Handler', 'new_environ']

class File(object):

    (   "File("
            "socket:gevent.socket.socket, "
            "reader:io.BufferedReader, "
            "environ:dict"
        ")"
    )
    __slots__ = ['chunked',
                 'closed',
                 'disconnected',
                 'environ',
                 'headers_sent',
                 'left',
                 'reader',
                 'socket']

    def __init__(self, socket, reader, environ):
        self.socket  = socket   #: The original socket object
        self.reader  = reader   #: The reading stream
        self.environ = environ  #: The HTTP headers
        self.left    = environ['locals.content_length']
        self.chunked = False
        self.closed  = False
        self.headers_sent = None
        self.disconnected = False

    @property
    def cookie(self):
        """
        Accessing cookies as a `http.cookies.SimpleCookie` object

        :rtype: http.cookies.SimpleCookie
        """

        cookie_str = self.environ.get('HTTP_COOKIE')
        if cookie_str is None:
            return None
        return http.cookies.SimpleCookie(cookie_str)

    def start_response(self, status='200 OK', headers=None, cookie=None):
        (   "start_response("
                "status:str='200 OK', "
                "headers:List[Tuple[str, str]])=None, "
                "cookie:http.cookies.SimpleCookie=None"
            ") -> None" """

        Send the http header.
        """)
        if self.closed:
            raise BrokenPipeError(errno.EPIPE, 'Broken pipe')
        if self.headers_sent is not None:
            raise RuntimeError('header already sent')
        b_status  = as_bytes(status, http_header_encoding)
        b_version = as_bytes(self.environ['SERVER_PROTOCOL'],
                             http_header_encoding)
        buf = [b'%s %s' % (b_version, b_status)]
        if headers is not None:
            for key, value in headers:
                b_key   = as_bytes(  key, http_header_encoding)
                b_value = as_bytes(value, http_header_encoding)
                buf.append(b'%s: %s' % (urlencode.quote(b_key), b_value))
        if cookie is not None:
            assert isinstance(cookie, http.cookies.BaseCookie)
            for dummy, morsel in sorted(cookie.items()):
                value   = morsel.OutputString()
                b_value = as_bytes(value, http_header_encoding)
                buf.append(b'Set-Cookie: ' + b_value)
        buf.append(b'\r\n')
        self.socket.sendall(b'\r\n'.join(buf))
        self.headers_sent = status

    def start_chunked(self, status='200 OK', headers=None, cookie=None):
        (   "start_chunked("
                "status:str='200 OK', "
                "headers:List[Tuple[str, str]])=None, "
                "cookie:http.cookies.SimpleCookie=None"
            ") -> None" """

        Set the transfer encoding to 'chunked' and send the http header.
        """)
        if self.closed:
            raise BrokenPipeError(errno.EPIPE, 'Broken pipe')
        if self.headers_sent is not None:
            raise RuntimeError('header already sent')
        b_status  = as_bytes(status)
        b_version = as_bytes(self.environ['SERVER_PROTOCOL'],
                             http_header_encoding)
        buf = [b'%s %s' % (b_version, b_status),
               b'Transfer-Encoding: chunked']
        if headers is not None:
            for key, value in headers:
                b_key   = as_bytes(  key, http_header_encoding)
                b_value = as_bytes(value, http_header_encoding)
                buf.append(b'%s: %s' % (urlencode.quote(b_key), b_value))
        if cookie is not None:
            assert isinstance(cookie, http.cookies.BaseCookie)
            for dummy, morsel in sorted(cookie.items()):
                value   = morsel.OutputString()
                b_value = as_bytes(value, http_header_encoding)
                buf.append(b'Set-Cookie: ' + b_value)
        buf.append(b'\r\n')
        self.socket.sendall(b'\r\n'.join(buf))
        self.headers_sent = status
        self.chunked = True

    def send_response_and_close(self, status='200 OK', headers=None,
                                content=None, cookie=None):
        (   "send_response_and_close("
                "status:str='200 OK', "
                "headers:List[Tuple[str, str]])=None, "
                "content:Union[str, bytes]=None, "
                "cookie:http.cookies.SimpleCookie=None"
            ") -> None"
        )
        if self.closed:
            raise BrokenPipeError(errno.EPIPE, 'Broken pipe')
        if self.headers_sent is not None:
            raise RuntimeError('header already sent')
        b_status  = as_bytes(status)
        b_version = as_bytes(self.environ['SERVER_PROTOCOL'],
                             http_header_encoding)
        buf = [b'%s %s' % (b_version, b_status)]
        if headers is not None:
            for key, value in headers:
                b_key   = as_bytes(  key, http_header_encoding)
                b_value = as_bytes(value, http_header_encoding)
                buf.append(b'%s: %s' % (urlencode.quote(b_key), b_value))
        if cookie is not None:
            assert isinstance(cookie, http.cookies.BaseCookie)
            for dummy, morsel in sorted(cookie.items()):
                value   = morsel.OutputString()
                b_value = as_bytes(value, http_header_encoding)
                buf.append(b'Set-Cookie: ' + b_value)
        if content is None:
            buf.append(b'\r\n')
        else:
            buf.append(b'Content-Length: %d\r\n' % len(content))
            buf.append(content)
        self.socket.sendall(b'\r\n'.join(buf))
        self.headers_sent = status
        self.closed = True

    def send_html_and_close(self, status='200 OK', headers=None,
                            content=None, cookie=None, encoding=None):
        (   "send_html_and_close("
                "status:str='200 OK',"
                "headers:List[Tuple[str, str]])=None, "
                "content:Union[str, bytes]=None, "
                "cookie:http.cookies.SimpleCookie=None, "
                "encoding:str=None"
            ") -> None"
        )
        if self.closed:
            raise BrokenPipeError(errno.EPIPE, 'Broken pipe')
        if self.headers_sent is not None:
            raise RuntimeError('header already sent')
        b_status  = as_bytes(status)
        b_version = as_bytes(self.environ['SERVER_PROTOCOL'],
                             http_header_encoding)
        buf = [b'%s %s' % (b_version, b_status)]
        if headers is not None:
            for key, value in headers:
                b_key   = as_bytes(  key, http_header_encoding)
                b_value = as_bytes(value, http_header_encoding)
                buf.append(b'%s: %s' % (urlencode.quote(b_key), b_value))
        if cookie is not None:
            assert isinstance(cookie, http.cookies.BaseCookie)
            for dummy, morsel in sorted(cookie.items()):
                value   = morsel.OutputString()
                b_value = as_bytes(value, http_header_encoding)
                buf.append(b'Set-Cookie: ' + b_value)
        if content is None:
            buf.append(b'\r\n')
        else:
            if   isinstance(content, bytes):
                b_content = content
            elif isinstance(content, str):
                if encoding is None:
                    encoding = sys.getdefaultencoding()
                b_content = as_bytes(content, encoding)
            else:
                raise TypeError('expected binary or unicode string, '
                                'got {!r}'.format(content))
            if encoding is None:
                buf.append(b'Content-Type: text/html\r\n'
                           b'Content-Length: %d\r\n' % len(b_content))
            else:
                buf.append(b'Content-Type: text/html; charset: %s\r\n'
                           b'Content-Length: %d\r\n'
                           % (as_bytes(encoding), len(b_content)))
            buf.append(b_content)
        self.socket.sendall(b'\r\n'.join(buf))
        self.headers_sent = status
        self.closed = True

    def read(self, size=-1):
        (   "read("
                "size:int=-1"
            ") -> bytes" """

        Read the HTTP content at most size bytes, returned as a bytes
        object.
        """)
        if self.closed:
            return b''
        left = self.left
        if -1 == size or size > left:
            size = left
        data = self.reader.read(size)
        self.left = left - len(data)
        return data

    def readline(self, size=-1):
        (    "readline("
                "size:int=-1"
            ") -> bytes" """

        Next line from the HTTP content, as a bytes object.
        """)
        if self.closed:
            return b''
        left = self.left
        if -1 == size or size > left:
            size = left
        data = self.reader.readline(size)
        self.left = left - len(data)
        return data

    def write(self, data):
        (   "write("
                "data:bytes"
            ") -> None" """

        Send bytes to client.
        """)
        if self.closed:
            raise BrokenPipeError(errno.EPIPE, 'Broken pipe')
        if self.chunked:
            self.socket.sendall(b'%x\r\n%s\r\n' % (len(data), data))
        else:
            self.socket.sendall(data)

    def sendall(self, data):
        (   "sendall("
                "data:bytes"
            ") -> None" """

        Send bytes to client.
        """)
        if self.closed:
            raise BrokenPipeError(errno.EPIPE, 'Broken pipe')
        if self.chunked:
            self.socket.sendall(b'%x\r\n%s\r\n' % (len(data), data))
        else:
            self.socket.sendall(data)

    def flush(self):
        """
        Does nothing.
        """

    def close(self, disconnect=False):
        (   "close("
                "disconnect:bool=False"
            ") -> None" """

        :param bool disconnect:

            - **True**  close the connection
            - **False** complete the current request and keep alive
        """)
        if self.chunked and not self.closed:
            self.socket.sendall(b'0\r\n\r\n')
        if disconnect:
            self.reader.close()
            self.socket.close()
            self.disconnected = True
        self.closed = True

    def not_modified(self, headers=None, content=None):
        (   "not_modified("
                "headers:List[Tuple[str, str]]=None, "
                "content:Union[str,bytes]=None"
            ") -> None" """

        304 Not Modified.
        """)
        self.send_response_and_close('304 Not Modified', headers, content)

    def bad_request(self, headers=None, content=None):
        (   "bad_request("
                "headers:List[Tuple[str, str]]=None, "
                "content:Union[str, bytes]=None"
            ") -> None" """

        400 Bad Request.
        """)
        if content is None:
            self.send_html_and_close(
                '400 Bad Request',
                headers,
                http_400_content,
                encoding=http_content_encoding
            )
        else:
            self.send_response_and_close(
                '400 Bad Request',
                headers,
                content
            )

    def forbidden(self, headers=None, content=None):
        (   "forbidden("
                "headers:List[Tuple[str, str]]=None, "
                "content:Union[str,bytes]=None"
            ") -> None" """

        403 Forbidden.
        """)
        if content is None:
            content = \
                http_403_content_template.format(
                    html.escape(
                        urllib.parse.unquote(self.environ['REQUEST_URI'])
                    )
                )
            self.send_html_and_close(
                '403 Forbidden',
                headers,
                content,
                encoding=http_content_encoding
            )
        else:
            self.send_response_and_close(
                '403 Forbidden',
                headers,
                content
            )

    def not_found(self, headers=None, content=None):
        (   "not_found("
                "headers:List[Tuple[str, str]]=None, "
                "content:Union[str,bytes]=None"
            ") -> None" """

        404 Not Found.
        """)
        if content is None:
            content = \
                http_404_content_template.format(
                    html.escape(
                        urllib.parse.unquote(self.environ['REQUEST_URI'])
                    )
                )
            self.send_html_and_close(
                '404 Not Found',
                headers,
                content,
                encoding=http_content_encoding
            )
        else:
            self.send_response_and_close(
                '404 Not Found',
                headers,
                content
            )

    def method_not_allowed(self, headers=None, content=None):
        (   "method_not_allowed("
                "headers:List[Tuple[str, str]]=None, "
                "content:Union[str,bytes]=None"
            ") -> None" """

        405 Method Not Allowed.
        """)
        if content is None:
            content = \
                http_405_content_template.format(
                    self.environ['REQUEST_METHOD']
                )
            self.send_html_and_close(
                '405 Method Not Allowed',
                headers,
                content,
                encoding=http_content_encoding
            )
        else:
            self.send_response_and_close(
                '405 Method Not Allowed',
                headers,
                content
            )

    def request_entity_too_large(self, headers=None, content=None):
        (   "request_entity_too_large("
                "headers:List[Tuple[str, str]]=None, "
                "content:Union[str,bytes]=None"
            ") -> None" """

        413 Request Entity Too Large.
        """)
        if content is None:
            self.send_html_and_close(
                '413 Request Entity Too Large',
                headers,
                http_413_content,
                encoding=http_content_encoding
            )
        else:
            self.send_response_and_close(
                '413 Request Entity Too Large',
                headers,
                content
            )

    def request_uri_too_large(self, headers=None, content=None):
        (   "request_uri_too_large("
                "headers:List[Tuple[str, str]]=None, "
                "content:Union[str,bytes]=None"
            ") -> None" """

        414 Request-URI Too Large.
        """)
        if content is None:
            self.send_html_and_close(
                '414 Request-URI Too Large',
                headers,
                http_414_content,
                encoding=http_content_encoding
            )
        else:
            self.send_response_and_close(
                '414 Request-URI Too Large',
                headers,
                content
            )

    def internal_server_error(self, headers=None, content=None):
        (   "internal_server_error("
                "headers:List[Tuple[str, str]]=None, "
                "content:Union[str,bytes]=None"
            ") -> None" """

        500 Internal Server Error.
        """)
        if content is None:
            self.send_html_and_close(
                '500 Internal Server Error',
                headers,
                http_500_content,
                encoding=http_content_encoding
            )
        else:
            self.send_response_and_close(
                '500 Internal Server Error',
                headers,
                content
            )

    def send_30X_response_and_close(self, status, urls,
                                    single_url_template,
                                    multiple_urls_template, headers=None,
                                    content=None, url_encoding=None):
        try:
            host = self.environ['HTTP_HOST']
        except KeyError:
            return self.bad_request()
        if isinstance(self.socket, gevent.ssl.SSLSocket):
            base = 'https://%s/' % host
        else:
            base = 'http://%s/'  % host
        if url_encoding is None:
            url_encoding = sys.getdefaultencoding()
        if isinstance(urls, (list, tuple, set)):
            locations = []
            for url in urls:
                if   isinstance(url, bytes):
                    u_location = url.decode(url_encoding)
                    u_location = translate_url(base, u_location)
                    b_location = as_bytes(u_location, url_encoding)
                elif isinstance(url, str):
                    u_location = translate_url(base, url)
                    b_location = as_bytes(u_location, url_encoding)
                else:
                    raise TypeError('expected binary or unicode string, '
                                    'got {!r}'.format(url))
                locations.append((u_location, b_location))
            location = random.choice(locations)
            if headers is None:
                headers = [('Location', location[1])]
            else:
                headers.append(('Location', location[1]))
            if content is None:
                hrefs = \
                    ''.join(
                        http_30X_multiple_urls_href_template.format(
                            u_location,
                            urlencode.quote(b_location)
                                     .decode(http_header_encoding)
                        ) for u_location, b_location in locations
                    )
                content = multiple_urls_template.format(hrefs)
                self.send_html_and_close(
                    status,
                    headers,
                    content.encode(http_content_encoding),
                    encoding=http_content_encoding,
                )
            else:
                self.send_response_and_close(
                    status,
                    headers,
                    content
                )
        else:
            if   isinstance(urls, bytes):
                u_location = urls.decode(url_encoding)
                u_location = translate_url(base, u_location)
                b_location = as_bytes(u_location, url_encoding)
            elif isinstance(urls, str):
                u_location = translate_url(base, urls)
                b_location = as_bytes(u_location, url_encoding)
            else:
                raise TypeError('expected binary or unicode string, '
                                'got {!r}'.format(urls))
            if headers is None:
                headers = [('Location', b_location)]
            else:
                headers.append(('Location', b_location))
            if content is None:
                content = \
                    single_url_template.format(
                        u_location,
                        urlencode.quote(b_location)
                                 .decode(http_header_encoding)
                    )
                self.send_html_and_close(
                    status,
                    headers,
                    content.encode(http_content_encoding),
                    encoding=http_content_encoding
                )
            else:
                self.send_response_and_close(
                    status,
                    headers,
                    content
                )

    def multiple_choices(self, urls, headers=None, content=None,
                         url_encoding=None):
        (   "multiple_choices("
                "urls:Union[str,List[str]], "
                "headers:List[Tuple[str, str]]=None, "
                "content:Union[str,bytes]=None, "
                "url_encoding:str=None"
            ") -> None" """

        300 Multiple Choices.
        """)
        self.send_30X_response_and_close(
            '300 Multiple Choices',
            urls,
            http_300_single_url_template,
            http_300_multiple_urls_template,
            headers,
            content,
            url_encoding=url_encoding
        )

    def moved_permanently(self, urls, headers=None, content=None,
                          url_encoding=None):
        (   "moved_permanently("
                "urls:Union[str,List[str]], "
                "headers:List[Tuple[str, str]]=None, "
                "content:Union[str,bytes]=None, "
                "url_encoding:str=None"
            ") -> None" """

        301 Moved Permanently.
        """)
        self.send_30X_response_and_close(
            '301 Moved Permanently',
            urls,
            http_301_single_url_template,
            http_301_multiple_urls_template,
            headers,
            content,
            url_encoding=url_encoding
        )

    def found(self, urls, headers=None, content=None, url_encoding=None):
        (   "found("
                "urls:Union[str,List[str]],"
                "headers:List[Tuple[str, str]]=None, "
                "content:Union[str,bytes]=None, "
                "url_encoding:str=None"
            ") -> None" """

        302 Found.
        """)
        self.send_30X_response_and_close(
            '302 Found',
            urls,
            http_302_single_url_template,
            http_302_multiple_urls_template,
            headers,
            content,
            url_encoding=url_encoding
        )

    def see_other(self, urls, headers=None, content=None,
                  url_encoding=None):
        (   "see_other("
                "urls:Union[str,List[str]], "
                "headers:List[Tuple[str, str]]=None, "
                "content:Union[str,bytes]=None, "
                "url_encoding:str=None"
            ") -> None" """

        300 See Other.
        """)
        self.send_30X_response_and_close(
            '303 See Other',
            urls,
            http_303_single_url_template,
            http_303_multiple_urls_template,
            headers,
            content,
            url_encoding=url_encoding
        )

    def temporary_redirect(self, urls, headers=None, content=None,
                           url_encoding=None):
        (   "temporary_redirect("
                "urls:Union[str,List[str]], "
                "headers:List[Tuple[str, str]]=None, "
                "content:Union[str,bytes]=None, "
                "url_encoding:str=None"
            ") -> None" """

        307 Temporary Redirect.
        """)
        self.send_30X_response_and_close(
            '307 Temporary Redirect',
            urls,
            http_307_single_url_template,
            http_307_multiple_urls_template,
            headers,
            content,
            url_encoding=url_encoding
        )

class Handler(object):

    (   "Handler("
            "handler:Callable[[File], None], "
            "verbose:int=0, "
            "file_type=File"
        ")" """

    :param int verbose:

        - **0** quiet
        - **1** working at the log level `logging.INFO`
        - **2** working at the log level `logging.DEBUG`
    """)

    __slots__ = ['file_type', 'handler', 'verbose']

    def __init__(self, handler, verbose=0, file_type=File):
        self.handler   =   handler
        self.verbose   =   verbose
        self.file_type = file_type

    def __call__(self, socket, address):
        (   "__call__("
                "socket:gevent.socket.socket, "
                "address:Tuple[str, int]"
            ") -> None"
        )
        reader = socket.makefile(mode='rb')
        try:
            while 1:
                with gevent.Timeout(header_parsing_timeout):
                    try:
                        environ = new_environ(reader, server_side=True)
                    except:
                        if self.verbose and \
                           logging.DEBUG >= gvars.levels[self.verbose]:
                            raise
                        else:
                            return
                environ['REMOTE_ADDR'] = address[0]
                environ['REMOTE_PORT'] = address[1]
                rw = self.file_type(socket, reader, environ)
                try:
                    self.handler(rw)
                except:
                    if self.verbose and \
                       logging.DEBUG >= gvars.levels[self.verbose]:
                        raise
                    else:
                        return
                if not rw.closed or rw.disconnected:
                    return
                if environ.get('HTTP_CONNECTION', '') \
                          .lower() == 'keep_alive':
                    keep_alive = environ.get('HTTP_KEEP_ALIVE', '300')
                else:
                    keep_alive = environ.get('HTTP_KEEP_ALIVE')
                if keep_alive is None or \
                   not regx_keep_alive.match(keep_alive):
                    return
                left = rw.left
                if 8192 > left > 0:
                    reader.read(left)
                if left != 0:
                    return
                n_keep_alive = min(int(keep_alive), max_keep_alive)
                try:
                    gevent.socket.wait_read(socket.fileno(), n_keep_alive)
                except:
                    if self.verbose and \
                       logging.DEBUG >= gvars.levels[self.verbose]:
                        raise
                    else:
                        return
        finally:
            reader.close()
            socket.close()

def new_environ(reader, server_side=True):
    (   "new_environ("
            "reader:File, "
            "server_side:bool=True"
        ") -> dict" """

    Parse the HTTP header.
    """)
    if server_side:
        size = 0
        while size < 8192:
            data = reader.readline(4096)
            if b'' == data:
                raise BrokenPipeError(errno.EPIPE, 'Broken pipe')
            match = regx_first_header_server_side.match(data)
            if match is None:
                size += len(data)
                continue
            (b_method, b_uri, b_version) = match.groups()
            if b_method:
                break
            else:
                size += len(data)
                continue
        else:
            raise ValueError('Invalid http headers')
        environ = \
            {    'REQUEST_URI': b_uri.decode(http_header_encoding),
              'REQUEST_METHOD': b_method.decode(http_header_encoding),
             'SERVER_PROTOCOL': b_version.decode(http_header_encoding)}
    else:
        size = 0
        while size < 8192:
            data = reader.readline(4096)
            if b'' == data:
                raise BrokenPipeError(errno.EPIPE, 'Broken pipe')
            match = regx_first_header_client_side.match(data)
            if match is None:
                size += len(data)
                continue
            (b_version, b_status, b_message) = match.groups()
            if b_status:
                break
            else:
                size += len(data)
                continue
        else:
            raise ValueError('Invalid http headers')
        environ = \
            { 'RESPONSE_STATUS': b_status.decode(http_header_encoding),
             'RESPONSE_MESSAGE': b_message.decode(http_header_encoding),
              'SERVER_PROTOCOL': b_version.decode(http_header_encoding)}
    data = reader.readline(2048)
    size = len(data)
    while 1:
        match = regx_headers.match(data)
        if match is None:
            if b'\r\n' == data or b'\n' == data:
                break
            raise ValueError('Invalid http headers')
        (b_key, b_value) = match.groups()
        key = b_key.decode(http_header_encoding) \
                   .replace('-', '_') \
                   .upper()
        environ['HTTP_' + key] = b_value.decode(http_header_encoding)
        data = reader.readline(2048)
        size += len(data)
        if size > 8192:
            raise ValueError('Request header is too large')
    if 'HTTP_CONTENT_LENGTH' in environ:
        environ['CONTENT_LENGTH'] = environ.get('HTTP_CONTENT_LENGTH', 0)
        left = environ.get('HTTP_CONTENT_LENGTH', '0').strip()
        if len(left) > 16:
            raise ValueError('Content-Length is too large')
        n_left = int(left)
        if n_left < 0 or n_left > 0x2386f26fc0ffff:
            raise ValueError('Invalid Content-Length')
        environ['locals.content_length'] = n_left
    else:
        environ['locals.content_length'] = 0
    if server_side:
        p = b_uri.find(b'?')
        if p != -1:
            b_path_info = \
                b'%2F'.join(
                    urlencode.unquote(x)
                        for x in regx_quoted_slash.split(b_uri[:p])
                )
            environ['PATH_INFO'] = \
                b_path_info.decode(http_header_encoding)
            environ['QUERY_STRING'] = \
                b_uri[p+1:].decode(http_header_encoding)
        else:
            b_path_info = \
                b'%2F'.join(
                    urlencode.unquote(x)
                        for x in regx_quoted_slash.split(b_uri)
                )
            environ['PATH_INFO'] = \
                b_path_info.decode(http_header_encoding)
            environ['QUERY_STRING'] = ''
    environ['SCRIPT_NAME'] = ''
    environ.setdefault(
        'CONTENT_TYPE',
        environ.setdefault('HTTP_CONTENT_TYPE', default_mime_type)
    )
    return environ

def translate_url(base, url):
    if not base.endswith('/'):
        base = base + '/'
    url = url.lstrip('/')
    p = url.rfind('/')
    if -1 == p:
        result = base + url
        if result.startswith('//'):
            return result[1:]
        return result
    parts = []
    for part in url[:p].split('/'):
        if '..' == part:
            if len(parts) > 0:
                parts.pop()
        elif '' == part or '.' == part:
            continue
        else:
            parts.append(part)
    if not parts:
        result = base + url[p:]
        if result.startswith('//'):
            return result[1:]
        return result
    result = '{}{}{}'.format(base, '/'.join(parts), url[p:])
    if result.startswith('//'):
        return result[1:]
    return result

def as_bytes(string, encoding=None):
    (   "as_bytes("
            "string:Union[str,bytes], "
            "encoding:str=None"
        ") -> bytes"
    )
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

regx_quoted_slash = re.compile(br'(?:i)%2F')
regx_headers = \
    re.compile(
        br'^[\s\t]*([^\r\n:]+)[\s\t]*:[\s\t]*([^\r\n]*)[\s\t]*\r?\n$'
    )
regx_first_header_server_side = \
    re.compile((
        br'^(?:[ \t]*(\w+)[ \t]+([^\r\n]+)[ \t]+(HTTP/[0-2]\.[0-9])[ \t]*|'
        br'[ \t]*)\r?\n$'
    ), re.I)
regx_first_header_client_side = \
    re.compile((
        br'^(?:[ \t]*(HTTP/[0-2]\.[0-9])[ \t]+([0-9]+)[ \t]+([^\r\n]+)[ \t'
        br']*|[ \t]*)\r?\n$'
    ), re.I)
regx_keep_alive = re.compile(r'^\s*[1-9][0-9]{0,6}\s*$')
http_400_content = '''\
<html><head><title>400 Bad Request</title></head><body><h1>Bad Request</h1\
>Your browser sent a request that this server could not understand.<p>clie\
nt sent HTTP/1.1 request without hostname (see RFC2616 section 14.23): /<p\
><hr /><address>Python-{}.{}.{}</address></body></html>''' \
.format(*sys.version_info)
http_403_content_template = '''\
<html><head><meta http-equiv="Content-Type" content="text/html; charset={}\
"><title>403 Forbidden</title></head><body><h1>Forbidden</h1><p>You don\'t\
have permission to list the contents of {{}} on this server.</p><hr /><add\
ress>Python-{}.{}.{}</address></body></html>''' \
.format(*tuple([http_content_encoding]+list(sys.version_info)))
http_404_content_template = '''\
<html><head><meta http-equiv="Content-Type" content="text/html; charset={}\
"><title>404 Not Found</title></head><body><h1>Not Found</h1><p>The reques\
ted URL {{}} was not found on this server.</p><hr /><address>Python-{}.{}.\
{}</address></body></html>''' \
.format(*tuple([http_content_encoding]+list(sys.version_info)))
http_405_content_template = '''\
<html><head><title>405 Method Not Allowed</title></head><body><h1>Method N\
ot Allowed</h1><p>The method {{}} is not allowed for the requested URL.</p\
><hr /><address>Python-{}.{}.{}</address></body></html>''' \
.format(*sys.version_info)
http_413_content = '''\
<html><head><title>413 Request Entity Too Large</title></head><body><h1>41\
3 Request Entity Too Large</h1><hr /><address>Python-{}.{}.{}</address></b\
ody></html>'''.format(*sys.version_info)
http_414_content = '''\
<html><head><title>414 Request-URI Too Large</title></head><body><h1>414 R\
equest-URI Too Large</h1><hr /><address>Python-{}.{}.{}</address></body></\
html>'''.format(*sys.version_info)
http_500_content = '''\
<html><head><title>500 Internal Server Error</title></head><body><h1>Inter\
nal Server Error</h1><p>The server encountered an internal error and was u\
nable to complete your request.</p><hr /><address>Python-{}.{}.{}</address\
></body></html>'''.format(*sys.version_info)
http_30X_single_url_template = '''\
<html><head><meta http-equiv="Content-Type" content="text/html; charset={}\
"><title>{{}}</title></head><body><p>{{}} <a href="{{{{}}}}">{{{{}}}}</a><\
/p><hr /><address>Python-{}.{}.{}</address></body></html>''' \
.format(*tuple([http_content_encoding]+list(sys.version_info)))
http_30X_multiple_urls_template = '''\
<html><head><meta http-equiv="Content-Type" content="text/html; charset={}\
"><title>{{}}</title></head><body><h1>{{}}</h1><ul>{{{{}}}}</ul><hr /><add\
ress>Python-{}.{}.{}</address></body></html>''' \
.format(*tuple([http_content_encoding]+list(sys.version_info)))
http_30X_multiple_urls_href_template = '<li><a href="{}">{}</a></li>\r\n'
http_300_single_url_template = \
    http_30X_single_url_template.format(
        'Object has several resources', 'This resource can be found at'
    )
http_300_multiple_urls_template = \
    http_30X_multiple_urls_template.format(
        'Object has several resources',
        'Object has several resources -- see URI list'
    )
http_301_single_url_template = \
    http_30X_single_url_template.format(
        'Object moved permanently',
        'This resource has permanently moved to'
    )
http_301_multiple_urls_template = \
    http_30X_multiple_urls_template.format(
        'Object moved permanently',
        'Object moved permanently -- see URI list'
    )
http_302_single_url_template = \
    http_30X_single_url_template.format(
        'Object moved temporarily',
        'This resource resides temporarily at'
    )
http_302_multiple_urls_template = \
    http_30X_multiple_urls_template.format(
        'Object moved temporarily',
        'Object moved temporarily -- see URI list'
    )
http_303_single_url_template = \
    http_30X_single_url_template.format(
        'Object moved',
        'This resource can be found at'
    )
http_303_multiple_urls_template = \
    http_30X_multiple_urls_template.format(
        'Object moved',
        'Object moved -- see Method and URL list'
    )
http_307_single_url_template = \
    http_30X_single_url_template.format(
        'Object moved temporarily',
        'This resource has moved temporarily to'
    )
http_307_multiple_urls_template = \
    http_30X_multiple_urls_template.format(
        'Object moved temporarily',
        'Object moved temporarily -- see URI list'
    )
