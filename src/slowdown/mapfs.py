# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
=============================================================
:mod:`slowdown.mapfs` -- Mapping URLs to filesystem locations
=============================================================

This module provides a tiny web framework that simply maps the URL to the
disk location.

Example::

    import gevent
    import gevent.server
    import slowdown.fs
    import slowdown.http
    import slowdown.mapfs

    fs = slowdown.fs.FS()  # locl filesystem
    mapfs = \\
        slowdown.mapfs.Mapfs(

            # Mapfs requires an FS object to indicate a specific
            # filesystem that contains static files and scripts.
            fs = fs,

            www='/PATH/TO/DOCUMENT/ROOT',  # static files directory
            cgi='/PATH/TO/SCRIPTS'         # scripts directory
        )

    server = \\
        gevent.server.Server(
            ('0.0.0.0', 8080),
            slowdown.http.Handler(mapfs)
        )
    server.start()           # start the server
    io_jobs = fs.spawn()     # begin IO loops
    gevent.joinall(io_jobs)

Static files in the folder specified by the `www` parameter shall be sent
to the browser. And scripts in the `scripts` folder will be executed
when requested.

The static file will be sent if the file and script are matched by the same
URL. If no files or scripts are matched, the existing index.html file or
index_html script will be the choice.

Swap files and hidden files whose names start with dot, end with tilde
``~`` , and have .swp, .swx suffixes are ignored.

Script samples:

::

    # file: pkgs/__cgi__/a/b/c/test1.py
    # test: http(s)://ROUTER/a/b/c/test1/d/e/f

    import slowdown.cgi

    def GET(rw):  # only GET requests are processed
        path1       = rw.environ['PATH_INFO']  # -> the original path
        path2       = rw.environ['locals.path_info']    # -> /d/e/f/
        script_name = rw.environ['locals.script_name']  # -> /a/b/c/test1
        return \\
            rw.start_html_and_close(
                content='<html>It works!</html>'
            )

    def POST(rw):  # only POST requests are processed
        form = slowdown.cgi.Form(rw)
        return \\
            rw.start_html_and_close(
                content=f'<html>{form}</html>'
            )

::


    # file: pkgs/__cgi__/a/b/c/d/test2.py
    # test: http(s)://ROUTER/a/b/c/d/test2/e/f/g

    import slowdown.cgi

    # You can define a handler called HTTP to handle all
    # request methods just in one place.
    #
    # Be ware, don't define HTTP and GET/POST at the same time.
    def HTTP(rw):
        path_info   = rw.environ['locals.path_info'  ]  # -> /e/f/g
        script_name = rw.environ['locals.script_name']  # -> /a/b/c/d/test2
        if 'GET' == rw.environ['REQUEST_METHOD']:
            return \\
                rw.start_html_and_close(
                    content='<html>It works!</html>'
                )
        elif 'POST' == rw.environ['REQUEST_METHOD']:
            form = slowdown.cgi.Form(rw)
            return \\
                rw.start_html_and_close(
                    content=f'<html>{form}</html>'
                )
        else:
            return rw.method_not_allowed()
"""

import gevent
import hashlib
import io
import mimetypes
import os
import os.path
import stat
import time
import types
import weakref
import zlib

from . import http
from . import inotify
from . import lrucache

default_index_html   = 'index.html'
default_index_script = 'index.html'
default_max_file_cache_size  = 0x200000
default_static_files_cache_size = 20000
default_scripts_cache_size      = 20000
default_reader_blocksize = 4096
buffer_size = 0x10000

__all__ = ['Mapfs']

class Mapfs(object):

    (   "Mapfs("
            "fs:slowdown.fs.FS, "
            "www:str, "
            "cgi:str, "
            "max_file_cache_size:int=0x200000, "
            "index_html:str='index.html', "
            "index_script:str='index_html'"
        ")" """

    A tiny web framework that simply maps the URL to the disk location.

    :param slowdown.fs.FS fs: the filesystem that contains
                              static files and scripts.
    :param str www: the directory where static files are stored.
    :param str cgi: the directory where scripts are stored.
    """)

    __slots__ = ['application',
                 'cgi_dir',
                 'fs',
                 'index_html',
                 'index_script',
                 'max_file_cache_size',
                 'reloading_scripts',
                 'reloading_static_files',
                 'script_watchers',
                 'scripts',
                 'scripts_cache',
                 'static_files',
                 'static_file_watchers',
                 'static_files_cache',
                 'www_dir']

    def __init__(self, application, www, cgi, max_file_cache_size=None,
                 index_html=None, index_script=None):
        self.application = application
        self.fs          = application.fs
        self.www_dir     = www
        self.cgi_dir     = cgi
        self.static_file_watchers = {}
        self.script_watchers      = {}
        if max_file_cache_size is None:
            self.max_file_cache_size = default_max_file_cache_size
        else:
            self.max_file_cache_size = max_file_cache_size
        if index_html is None:
            self.index_html = default_index_html
            assert isinstance(self.index_html, str)
        else:
            if not isinstance(index_html, str):
                raise TypeError('index_html must be a unicode string, '
                                f'got {repr(index_html)}')
            self.index_html = index_html
        if index_script is None:
            self.index_script = default_index_script
            assert isinstance(self.index_script, str)
        else:
            if not isinstance(index_script, str):
                raise TypeError('index_script must be a unicode string, '
                                f'got {repr(index_script)}')
            self.index_script = index_script
        self.reloading_static_files = 0.
        self.reloading_scripts = 0.
        if www:
            self.reload_static_files(immediate=True)
        else:
            self.static_files = set()
            self.static_files_cache = \
                lrucache.LRUCache(size=default_static_files_cache_size)
        if cgi:
            self.reload_scripts(immediate=True)
        else:
            self.scripts = set()
            self.scripts_cache = \
                lrucache.LRUCache(size=default_scripts_cache_size)

    def __del__(self):
        for wd, dummy in self.static_file_watchers.items():
            try:
                self.fs.inotify.rm_watch(wd)
            except KeyError:
                pass
        for wd, dummy in self.script_watchers.items():
            try:
                self.fs.inotify.rm_watch(wd)
            except KeyError:
                pass

    def __call__(self, rw):
        (   "__call__("
                "rw:slowdown.http.File"
            ")"
        )
        environ = rw.environ
        path_info  = environ.get('locals.path_info')
        if path_info is None:
            path_info = environ['PATH_INFO']
        script_name = os.path.normpath('/' + path_info.lstrip('/'))
        if path_info.endswith('/'):
            if '/' == script_name:
                path_info = '/' + self.index_html
            else:
                path_info = f'{script_name}/{self.index_html}'
        else:
            path_info = script_name
        cache_ = self.static_files_cache.get(path_info)
        if cache_ is not None:
            if_modified_since = environ.get('HTTP_IF_MODIFIED_SINCE')
            if if_modified_since is None:
                if_none_match = environ.get('HTTP_IF_NONE_MATCH')
                if if_none_match is not None and \
                   if_none_match == cache_.etag:
                    if 'GET' == environ['REQUEST_METHOD'].upper():
                        return rw.not_modified()
                    else:
                        return rw.method_not_allowed()
            elif if_modified_since == cache_.last_modified:
                if 'GET' == environ['REQUEST_METHOD'].upper():
                    return rw.not_modified()
                else:
                    return rw.method_not_allowed()
            return self.send_static_file_cache(rw, environ, cache_)
        if path_info in self.static_files:
            return self.cache_and_send_static_file(rw, environ, path_info)
        for l_script_name, l_path_info in gen_routers(script_name):
            if l_script_name is None:
                return rw.request_uri_too_large()
            if l_script_name not in self.scripts:
                if '/' == l_script_name:
                    l_script_name = '/' + self.index_script
                else:
                    l_script_name = f'{l_script_name}/{self.index_script}'
                if l_script_name not in self.scripts:
                    continue
            module = self.scripts_cache.get(l_script_name)
            if module is None:
                module = self.load_script(l_script_name)
                if hasattr(module, 'initialize') and \
                   callable(module.initialize):
                    module.initialize(self)
                self.scripts_cache[l_script_name] = module
            method = environ['REQUEST_METHOD'].upper()
            handler = getattr(module, method, None)
            if handler is None or not callable(handler):
                handler = getattr(module, 'HTTP', None)
                if handler is None or not callable(handler):
                    continue
            environ['locals.script_name'] = l_script_name
            environ[  'locals.path_info'] = l_path_info
            return handler(rw)
        else:
            return rw.not_found()

    def load_script(self, script_name):
        l_script_name = os.path.normpath('/' + script_name.strip('/'))
        if l_script_name not in self.scripts:
            raise ImportError(f'No module named {l_script_name}')
        module = self.scripts_cache.get(l_script_name)
        if module is None:
            path = os.path.join(self.cgi_dir,
                                l_script_name.strip('/') + '.py')
            file_in = self.fs.open(path, 'rb')
            try:
                code_b = file_in.read()
            finally:
                file_in.close()
            code   = code_b.decode()
            module = types.ModuleType('__main__')
            exec (code, module.__dict__)
            self.scripts_cache[l_script_name] = module
            return module
        else:
            return module

    def cache_and_send_static_file(self, rw, environ, path_info):
        filename = os.path.join(self.www_dir, path_info.strip('/'))
        try:
            st = self.fs.os.stat(filename)
        except (IOError, OSError):
            self.static_files.discard(path_info)
            return rw.not_found()
        if 'GET' != environ['REQUEST_METHOD'].upper():
            return rw.method_not_allowed()
        if stat.S_ISDIR(st.st_mode):
            self.static_files.discard(path_info)
            return rw.not_found()
        gmtime = time.gmtime(st.st_mtime)
        last_modified = \
            '{}, {}-{}-{}'.format(
                abbreviated_weekday_names[gmtime.tm_wday],
                gmtime.tm_mday,
                abbreviated_month_names[gmtime.tm_mon],
                time.strftime('%Y %H:%M:%S GMT', gmtime)
            )
        size = st.st_size
        etag = \
            hashlib.md5(b'%s%d' % (
                last_modified.encode(http.http_header_encoding),
                size
            )).hexdigest()
        if_modified_since = environ.get('HTTP_IF_MODIFIED_SINCE')
        if if_modified_since is None:
            if_none_match = environ.get('HTTP_IF_NONE_MATCH')
            if if_none_match is not None and if_none_match == etag:
                return rw.not_modified()
        elif if_modified_since == last_modified:
            return rw.not_modified()
        ext = os.path.splitext(filename)[1].lower()
        mime_type = _mimetypes.get(ext, http.default_mime_type)
        try:
            file_in = self.fs.open(filename, 'rb')
        except OSError:
            return rw.forbidden()
        if size > self.max_file_cache_size:
            try:
                headers = [(  'Content-Type', mime_type    ),
                           ('Content-Length', f'{size}'    ),
                           (          'Etag', etag         ),
                           ( 'Last-Modified', last_modified)]
                rw.start_response(status='200 OK', headers=headers)
                data = file_in.read(buffer_size)
                while data:
                    rw.write(data)
                    data = file_in.read(buffer_size)
                return rw.close()
            finally:
                file_in.close()
        try:
            file_out = io.BytesIO()
            data = file_in.read(buffer_size)
            while data:
                file_out.write(data)
                data = file_in.read(buffer_size)
        finally:
            file_in.close()
        rawdata = file_out.getvalue()
        rawlen = len(rawdata)
        rawheaders = [('Last-Modified', last_modified),
                      ( 'Content-Type', mime_type    ),
                      (         'Etag', etag         )]
        zdata = zlib.compress(rawdata, 9)[2:-4]
        zlen = len(zdata)
        if rawlen - zlen > 1024:
            zheaders = [(   'Last-Modified', last_modified),
                        (    'Content-Type', mime_type    ),
                        ('Content-Encoding', 'deflate'    ),
                        (            'Etag', etag         )]
        else:
            zdata    = None
            zheaders = None
        cache_ = Cache(last_modified,
                       etag,
                       rawdata,
                       rawheaders,
                       zdata,
                       zheaders)
        self.static_files_cache[path_info] = cache_
        return self.send_static_file_cache(rw, environ, cache_)

    def send_static_file_cache(self, rw, environ, cache_):
        accept_encoding = environ.get('HTTP_ACCEPT_ENCODING')
        if cache_.zdata     is not None and \
           accept_encoding  is not None and \
           'deflate' in accept_encoding:
            rw.send_response_and_close(
                status  = '200 OK',
                headers = cache_.zheaders,
                content = cache_.zdata
            )
        else:
            rw.send_response_and_close(
                status  = '200 OK',
                headers = cache_.rawheaders,
                content = cache_.rawdata
            )

    def find_files(self, dir_, suffixes=None):
        dirlen = len(dir_)
        files  = set()
        dirs   = {dir_}
        for dirpath, dirnames, filenames in self.fs.os.walk(dir_):
            if filenames:
                base = dirpath[dirlen:]
                if '' == base:
                    base = '/'
                if suffixes is None:
                    for filename in filenames:
                        ext = os.path.splitext(filename)[1].lower()
                        if filename.startswith('.')    or \
                           ext in ignore_ext  or \
                           ext.endswith('~'):
                            continue
                        files.add(os.path.join(base, filename))
                else:
                    for filename in filenames:
                        ext = os.path.splitext(filename)[1].lower()
                        if filename.startswith('.')    or \
                           ext in ignore_ext  or \
                           ext.endswith('~'):
                            continue
                        for suffix in suffixes:
                            p = len(filename) - len(suffix)
                            if p > 0 and filename[p:] == suffix:
                                files.add(
                                    os.path.join(base, filename[:p])
                                )
                                break
            if dirnames:
                for dirname in dirnames:
                    if dirname.startswith('.'):
                        continue
                    dirs.add(os.path.join(dirpath, dirname))
        return (files, dirs)

    def reload_static_files(self, immediate=False):
        if not immediate:
            if self.reloading_static_files > 0.:
                self.reloading_static_files = time.time() \
                                            + reload_delay_time
                return
            self.reloading_static_files = time.time() + reload_delay_time
            gevent.sleep(reload_delay_time)
            while self.reloading_static_files > time.time():
                gevent.sleep(reload_delay_time)
            self.reloading_static_files = 0.
        while self.static_file_watchers:
            (wd, dummy) = self.static_file_watchers.popitem()
            try:
                self.fs.inotify.rm_watch(wd)
            except KeyError:
                pass
        (files, dirs) = self.find_files(self.www_dir)
        for dirname in dirs:
            wd = \
                self.fs.inotify.add_watch(
                    dirname,
                    mask_all,
                    self.process_static_file_event
                )
            self.static_file_watchers[wd] = dirname
        self.static_files = files
        self.static_files_cache = \
            lrucache.LRUCache(size=default_static_files_cache_size)

    def reload_scripts(self, immediate=False):
        if not immediate:
            if self.reloading_scripts > 0.:
                self.reloading_scripts = time.time() + reload_delay_time
                return
            self.reloading_scripts = time.time() + reload_delay_time
            gevent.sleep(reload_delay_time)
            while self.reloading_scripts > time.time():
                gevent.sleep(reload_delay_time)
            self.reloading_scripts = 0.
        while self.script_watchers:
            (wd, dummy) = self.script_watchers.popitem()
            try:
                self.fs.inotify.rm_watch(wd)
            except KeyError:
                pass
        (files, dirs) = self.find_files(self.cgi_dir, suffixes)
        for dirname in dirs:
            wd = \
                self.fs.inotify.add_watch(
                    dirname,
                    mask_all,
                    self.process_script_event
                )
            self.script_watchers[wd] = dirname
        self.scripts = files
        self.scripts_cache = \
            lrucache.LRUCache(size=default_scripts_cache_size)

    def process_static_file_event(self, wd, mask, cookie, name):
        if name.startswith('.'):
            return
        if mask & inotify.IN_ISDIR:
            return self.reload_static_files()
        ext = os.path.splitext(name)[1].lower()
        if ext in ignore_ext or ext.endswith('~'):
            return
        dirname = self.static_file_watchers[wd]
        dirlen  = len(self.www_dir)
        assert dirname[:dirlen] == self.www_dir
        base = dirname[dirlen:]
        if '' == base:
            base = '/'
        l_path_info = os.path.join(base, name)
        if l_path_info in self.static_files_cache:
            del self.static_files_cache[l_path_info]
        if   mask & mask_modify:
            self.static_files.add(l_path_info)
        elif mask & mask_delete:
            if l_path_info in self.static_files:
                self.static_files.remove(l_path_info)

    def process_script_event(self, wd, mask, cookie, name):
        if name.startswith('.'):
            return
        if mask & inotify.IN_ISDIR:
            return self.reload_scripts()
        (root, ext) = os.path.splitext(name)
        ext = ext.lower()
        if ext not in suffixes or ext in ignore_ext or ext.endswith('~'):
            return
        dirname = self.script_watchers[wd]
        dirlen  = len(self.cgi_dir)
        assert dirname[:dirlen] == self.cgi_dir
        base = dirname[dirlen:]
        if '' == base:
            base = '/'
        l_script_name = os.path.join(base, root)
        if l_script_name in self.scripts_cache:
            del self.scripts_cache[l_script_name]
        if   mask & mask_modify:
            self.scripts.add(l_script_name)
        elif mask & mask_delete:
            if l_script_name in self.scripts:
                self.scripts.remove(l_script_name)

def gen_routers(request_uri_with_out_query_string, max_depth=32):
    assert request_uri_with_out_query_string.startswith('/')
    script_name = request_uri_with_out_query_string = \
        os.path.normpath(request_uri_with_out_query_string)
    depth = 0
    while depth < max_depth:
        path_info = request_uri_with_out_query_string[len(script_name):]
        if path_info.startswith('/'):
            yield (script_name, path_info)
        else:
            yield (script_name, '/' + path_info)
        script_name, name = os.path.split(script_name)
        if '/' == script_name or not name:
            yield ('/', request_uri_with_out_query_string)
            break
        depth += 1
    else:
        yield (None, None)

class Cache(object):

    __slots__ = ['etag',
                 'last_modified',
                 'rawdata',
                 'rawheaders',
                 'zdata',
                 'zheaders']

    def __init__(self, last_modified, etag, rawdata, rawheaders, zdata,
                 zheaders):
        self.last_modified = last_modified
        self.etag = etag
        self.rawdata = rawdata
        self.rawheaders = rawheaders
        self.zdata = zdata
        self.zheaders = zheaders

abbreviated_weekday_names = \
    {0: 'Mon', 1: 'Tue', 2: 'Wed',  3: 'Thu',  4: 'Fri',  5: 'Sat',
     6: 'Sun'}
abbreviated_month_names   = \
    {1: 'Jan', 2: 'Feb', 3: 'Mar',  4: 'Apr',  5: 'May',  6: 'Jun',
     7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'}
mask_modify = inotify.IN_CREATE | inotify.IN_MODIFY | inotify.IN_MOVED_TO
mask_delete = inotify.IN_DELETE | inotify.IN_MOVED_FROM
mask_all    = mask_modify | mask_delete
ignore_ext = {'.swp', '.swx'}
reload_delay_time = 2.
suffixes = ['.py']
if not mimetypes.inited:
    mimetypes.init()
_mimetypes = mimetypes.types_map.copy()
