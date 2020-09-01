# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
====================================================================
:mod:`slowdown.__main__` -- The implementation of the startup script
====================================================================

This module contains the configuration schema and the startup script
implementation of the Slowdown Server::

    usage: slowdown [-h] [-f FILE] [-u USER] [--home DIRECTORY]
                    [--root DIRECTORY] [--init] [-v | -vv | -q]

Examples:

::

    # Read the configuration from the command line and profile
    slowdown.__main__.main()

    # Specify some parameters.
    # Those parameters can be used to override the configuration in the
    # config file.
    slowdown.__main__.main(
        # Home directory, including bin, etc, lib, var folders.
        home='PATH/TO/HOME/DIRECTORY',

        # the working directory
        root='PATH/TO/ROOT/DIRECTORY',  # probably $HOME/var

        # the execution user
        user='USER',                    # probably nobody

        # The log level
        # 0 - logging.ERROR
        # 1 - logging.INFO
        # 2 - logging.DEBUG
        verbose=0 or 1 or 2
    )

::

    # Use string instead of config file.
    slowdown.__main__.main(
        config='''
            <routers>
                <router ALL>
                    pattern ^(?P<MYHOST>.*)$$
                    <host MYHOST>
                        pattern ^(?P<MYPATH>/.*)$$
                        <path MYPATH>
                            handler MYPACKAGE
                        </path>
                    </host>
                </router>
            </routers>
            <servers>
                <http MYSERVERS>
                    address 127.0.0.1:8080
                    router  ALL
                </http>
            </servers>
        '''
    )
"""

import argparse
import copy
import collections
import gevent
import gevent.exceptions
import gevent.server
import gevent.signal
import gevent.ssl
import io
import logging
import os
import os.path
import re
import resource
import sys
import traceback
import weakref
import ZConfig.loader

from . import exceptions
from . import fs
from . import gvars
from . import http
from . import mapfs
from . import sysutil
from . import   __doc__   as package__doc__
from . import __version__

__all__ = ['Application', 'main']

def main(**kwargs):
    (   "main("
            "config:str=None, "
            "home:str=None, "
            "root:str=None, "
            "user:str=None, "
            "proc:str=None, "
            "verbose:int=0"
        ") -> None"
    )
    try:
        jobs = spawn(**kwargs)
    except SystemExit as err:
        sys.exit(err.code)
    try:
        gevent.joinall(jobs)
    except gevent.exceptions.BlockingSwitchOutError:
        pass

class Application(dict):

    __slots__ = ['anonymous_servers',
                 'args',
                 'cfg',
                 'fs',
                 'jobs',
                 'opts',
                 'routers',
                 'modules',
                 'scripts',
                 'servers',
                 'verbose',
                 '__weakref__']

    def exit(self, *args):
        """
        Stop servers and exit the program.
        """
        exceptions_ = []
        for module in set(list(self.scripts.values()) +
                          list(self.modules.values())):
            if hasattr(module, 'finalize') and callable(module.finalize):
                try:
                    module.finalize(self)
                except Exception as err:
                    exceptions_.append(err)
        if getattr(self, 'jobs', None):
            for servers in list(self.servers.values()) + \
                           [self.anonymous_servers]:
                for server in servers:
                    server.stop()
            try:
                gevent.killall(self.jobs)
            except gevent.exceptions.BlockingSwitchOutError:
                pass
            self.jobs = None
        if exceptions_:
            if 0 == len(exceptions_):
                raise exceptions_[0]
            else:
                raise exceptions.Exceptions(exceptions_)
        sys.exit(0)

def spawn(**kwargs):
    """
    Spawn server threads base on the configuration.
    """
    opts, args, cfg, parser = parse(**kwargs)
    # --init: convert the working folder to the home folder
    if args.init:
        init(args)
        return Jobs()
    # --root: root dir, probably $HOME/var
    if opts.root is not None:
        os.chdir(opts.root)
    # -q, -v, -vv: set the log level
    gvars.logger.setLevel(gvars.verbose_log_level_map[opts.verbose])
    os.environ.update(
        (key.upper(), value) for key, value in
        list(default_environment.items()) +
        list(cfg.environment.items())
    )
    if cfg.resource is not None:
        if 'RLIMIT_NOFILE' in cfg.resource:
            try:
                resource.setrlimit(
                    resource.RLIMIT_NOFILE,
                    (
                        int(cfg.resource['RLIMIT_NOFILE']),
                        int(cfg.resource['RLIMIT_NOFILE'])
                    )
                )
            except Exception:
                gvars.logger.warning('Require root permission to allocate '
                                     'resources')
    # Add $HOME/pkgs that contains the user package to sys.path
    pkgs_dir = os.path.join(opts.home, 'pkgs')
    if pkgs_dir not in sys.path:
        sys.path.append(pkgs_dir)
    app = Application()
    routers = {}
    scripts = {}
    modules = {}
    named_servers = {}
    anonymous_servers = []
    verbose = opts.verbose
    for entrypoint in cfg.scripts.run:
        if entrypoint not in scripts:
            scripts[entrypoint] = load_module(entrypoint, verbose)
    for router_name, router in cfg.routers.items():
        for host_name, host_section in router.groups.items():
            for path_name, path_section in host_section.groups.items():
                if path_section.handler not in modules:
                    entrypoint = path_section.handler
                    modules[entrypoint] = load_module(entrypoint, verbose)
        routers[router_name] = http.Handler(Handler(app, router), verbose)
    for section in cfg.servers.data:
        servers = []
        if 'HTTP' == section.type_:
            for address in section.addresses:
                servers.append(
                    gevent.server.StreamServer(
                        address,
                        routers[section.router]
                    )
                )
        elif 'HTTPS' == section.type_:
            ssl_context = \
                gevent.ssl.SSLContext(
                    gevent.ssl.PROTOCOL_TLS_SERVER
                )
            ssl_context.load_cert_chain(section.certfile, section.keyfile)
            for address in section.addresses:
                servers.append(
                    gevent.server.StreamServer(
                        address,
                        routers[section.router],
                        ssl_context=ssl_context
                    )
                )
            else:
                raise NotImplementedError(f'scheme "{section.type_}" '
                                          'not supported')
        if section.name is None:
            anonymous_servers.extend(servers)
        else:
            named_servers[section.name] = servers
    for entrypoint, module in modules.items():
        if not hasattr(module, 'handler'):
            base = os.path.abspath(os.path.dirname(module.__file__))
            www  = os.path.join(base, '__www__')
            cgi  = os.path.join(base, '__cgi__')
            if not os.path.isdir(www):
                www = None
            if not os.path.isdir(cgi):
                cgi = None
            if www is not None or cgi is not None:
                module.handler = mapfs.Mapfs(fs_, www=www, cgi=cgi)
    fs_  = fs.FS()
    jobs = Jobs(fs_.spawn())
    app.fs   = fs_
    app.jobs = jobs
    app.cfg  = cfg
    app.opts = opts
    app.args = args
    app.routers = routers
    app.scripts = scripts
    app.modules = modules
    app.servers = named_servers
    app.anonymous_servers = anonymous_servers
    jobs._application = weakref.ref(app)
    for module in set(list(scripts.values()) + list(modules.values())):
        if hasattr(module, 'initialize') and callable(module.initialize):
            jobs.append(gevent.spawn(module.initialize, app))
    for servers in list(named_servers.values()) + [anonymous_servers]:
        for server in servers:
            server.start()
            if server.ssl_enabled:
                scheme = 'HTTPS'
            else:
                scheme = 'HTTP'
            gvars.logger.info(f'Serving {scheme} on {server.server_host} '
                              f'port {server.server_port} ...')
    exit = exit_func(weakref.ref(app))
    gevent.signal.signal(gevent.signal.SIGQUIT, exit)
    gevent.signal.signal(gevent.signal.SIGTERM, exit)
    gevent.signal.signal(gevent.signal.SIGINT , exit)
    if opts.user is not None:
        try:
            sysutil.setuid(opts.user)
        except Exception as err:
            parser.error(f'{err}')
    for module in scripts.values():
        if hasattr(module, 'main') and callable(module.main):
            jobs.append(gevent.spawn(module.main, app))
    return jobs

def exit_func(_app):

    def wrapper(*args):
        app = _app()
        if app is not None:
            app.exit()

    return wrapper

class Jobs(list):

    __slots__ = ['_application']

class Handler(object):

    """
    This class is used to handle the HTTP requests that arrive at the
    `gevent.server.Server` .
    """

    __slots__ = ['application', 'router']

    def __init__(self, application, router):
        self.application = application
        self.router      = router

    def __call__(self, rw):
        environ = rw.environ
        result  = \
            self.router(
                environ.get('HTTP_HOST', ''),
                    environ['PATH_INFO']
            )
        if result is None:
            return rw.bad_request()
        module = self.application.modules.get(result.path_section.handler)
        if module is None or not hasattr(module, 'handler'):
            return rw.not_found()
        environ['locals.path_info'] = result.path_info
        environ['locals.match'    ] = result
        return module.handler(rw)

def load_module(entrypoint, verbose=0):
    try:
        if '.' in entrypoint:
            return \
                __import__(
                    entrypoint.strip(),
                    fromlist=[entrypoint.split('.')[-1].strip()]
                )
        else:
            return __import__(entrypoint.strip())
    except Exception as err:
        msg = exc()
        broken = Broken(entrypoint, err, msg, verbose)
        sys.modules[entrypoint] = broken
        if verbose > 0:
            gvars.logger.error(msg)
        return broken

class Broken(type(sys)):

    """
    Returned by `load_module` when an import error occurs.
    """

    __slots__ = ['content', 'exception', 'verbose']

    def __init__(self, entrypoint, err, tb, verbose=0):
        type(sys).__init__(self, entrypoint)
        self.exception = err
        self.content = \
            http_500_content.format(
                html.escape(tb).replace( ' ', '&nbsp;')
                               .replace('\n', '<br />')
            )
        self.verbose = verbose

    def handler(self, rw):
        """
        The HTTP handler that always sends the '500 Internal Server Error'
        page.
        """
        if self.verbose > 1:
            return \
                rw.send_html_and_close(
                    '500 Internal Server Error',
                    headers=None,
                    content=self.content,
                    encoding=http_content_encoding
                )
        else:
            return rw.internal_server_error()

def exc():
    file = io.StringIO()
    traceback.print_exc(file=file)
    return file.getvalue()

def handler(rw):
    rw.send_html_and_close(content=itworks_content)

# By default, DummyThreadPool is used, which is a threadpool that does not
# actually use threads and blocks the entrie program.
default_environment = \
    {
        'GEVENT_THREADPOOL': 'slowdown.threadpool.DummyThreadPool'
    }

http_content_encoding = 'utf-8'
itworks_content  = '''\
<html><head><title>200 OK</title></head><body><h1>It works!</h1><hr />
<address>Python-{}.{}.{}</address></body></html>''' \
.format(*sys.version_info)
http_500_content = '''\
<html><head><title>500 Internal Server Error</title></head><body><h1>Inter\
nal Server Error</h1><p>The server encountered an internal error and was u\
nable to complete your request.</p><p>{{}}</p><hr /><address>Python-{}.{}.\
{}</address></body></html>'''.format(*sys.version_info)

###########################################################################
#                         Command line interface                          #
###########################################################################

def parse(**kwargs):
    config = kwargs.get('config')
    if config is None:
        defaults = copy.copy(kwargs)
        defaults['add_help'] = False
        parser = ParserFactory(**defaults)
        args = parser.parse_args()
        defaults['home'] = args.home
        parser = ParserFactory(**defaults)
        args = parser.parse_args()
        if args.init:
            if args.show_help_message:
                parser.error('argument --init: not allowed with '
                             'argument -h/--help')
            return ParseResult(None, args, None, parser)
        else:
            try:
                cfg, nil = \
                    ZConfig.loader.loadConfig(
                        loadSchema(),
                        args.file
                    )
            except ZConfig.ConfigurationError as err:
                if not os.path.isfile(args.file):
                    parser.error(
                        f'profile {args.file} is missing, try --init to '
                         'create one or use --home to specify a project '
                         'home contains the profile.'
                    )
                else:
                    parser.error(
                        f'configuration error occurs in {args.file}: '
                        f'{err.message} (line {err.lineno})'
                    )
    else:
        if not isinstance(config, str):
            raise TypeError('keyword argument "config" must be a string '
                            f'but got {repr(config)}')
        cfg, nil = loadConfig(loadSchema(), config)
    defaults = copy.copy(kwargs)
    defaults['add_help'] = True
    if cfg.user is not None:
        defaults['user'] = cfg.user
    if cfg.home is not None:
        defaults['home'] = cfg.home
    if cfg.root is not None:
        defaults['root'] = cfg.root
    defaults['verbose'] = cfg.verbose
    parser = ParserFactory(**defaults)
    args = parser.parse_args()
    opts = Options()
    if config is None:
        opts.file = args.file
    else:
        opts.file = None
    opts.home = args.home
    opts.user = args.user
    if args.root is None:
        if cfg.root is None:
            opts.root = get_default_root(args.home)
        else:
            opts.root = cfg.root
    else:
        opts.root = args.root
    if   args.quiet:
        opts.verbose = 0
    elif args.verbose is not None:
        assert isinstance(args.verbose, int)
        max_verbose = max(gvars.verbose_log_level_map.keys())
        if args.verbose >= max_verbose:
            opts.verbose = max_verbose
        else:
            opts.verbose = args.verbose
    else:
        opts.verbose = defaults['verbose']
    return ParseResult(opts, args, cfg, parser)

def ParserFactory(**kwargs):
    default_home = kwargs.get('home')
    if default_home is None:
        default_home = \
            os.path.realpath(
                os.path.join(
                    os.path.dirname(sys.argv[0]),
                    os.path.pardir
                )
            )
    else:
        if not isinstance(default_home, str):
            raise TypeError('keyword argument "home" must be a string but '
                            f'got {repr(default_home)}')
    config       = kwargs.get('config')
    default_file = kwargs.get('file')
    if default_file is None:
        if config is None:
            name = \
                os.path.splitext(
                    os.path.basename(sys.argv[0])
                )[0] + '.conf'
            default_file = os.path.join(default_home, 'etc', name)
    else:
        if not isinstance(default_file, str):
            raise TypeError('keyword argument "file" must be a string but '
                            f'got {repr(default_file)}')
        if config is not None:
            raise ValueError('keyword argument "file" not allowed with '
                             'keyword argument "config"')
    add_help = kwargs.get('add_help', False)
    parser = \
        argparse.ArgumentParser(
                description=package__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter,
                   add_help=add_help
        )
    if not add_help:
        parser.add_argument(
                    '-h',
                    '--help',
               dest='show_help_message',
             action='store_true',
               help='show this help message and exit',
            default=False
        )
    if config is None:
        parser.add_argument(
                    '-f',
                    '--file',
               dest='file',
               type=str,
            metavar='FILE',
            default=default_file,
               help=f'config file, the default is {default_file}'
        )
    if kwargs.get('user') is None:
        parser.add_argument(
                    '-u',
                    '--user',
               dest='user',
               type=str,
            metavar='USER',
               help=('server will running as the specified user, '
                     'the default is the current user')
        )
    else:
        parser.add_argument(
                    '-u',
                    '--user',
               dest='user',
               type=str,
            metavar='USER',
               help=('server will running as the specified user, '
                     f'the default is "{kwargs["user"]}"'),
            default=kwargs['user']
        )
    parser.add_argument(
                 '--home',
            dest='home',
            type=str,
        metavar='DIRECTORY',
            help=f'home dir, the default is {default_home}',
        default=default_home
    )
    if kwargs.get('root') is None:
        default_root = get_default_root(default_home)
        parser.add_argument(
                    '--root',
               dest='root',
               type=str,
            metavar='DIRECTORY',
               help=f'working dir, the default is {default_root}',
            default=None
        )
    else:
        parser.add_argument(
                    '--root',
               dest='root',
               type=str,
            metavar='DIRECTORY',
               help=f'working dir, the default is {kwargs["root"]}',
            default=None
        )
    parser.add_argument(
                '--init',
           dest='init',
         action='store_true',
           help='convert the working folder to the home folder',
        default=False
    )
    default_verbose = kwargs.get('verbose')
    if default_verbose is None or 0 == default_verbose:
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
                    '-v',
                    '--verbose',
               dest='verbose',
             action='count',
               help='print debug messages to stdout',
        )
        group.add_argument(
                    '-q',
                    '--quiet',
               dest='quiet',
             action='store_true',
               help='do not print debug messages (default)',
            default=False
        )
    elif isinstance(default_verbose, int):
        if default_verbose < 0:
            raise ValueError('verbose must be greater than -1')
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
                    '-v',
                    '--verbose',
               dest='verbose',
             action='count',
               help=('print debug messages, the default is '
                     f'"-{"v" * default_verbose}"'),
            default=default_verbose
        )
        group.add_argument(
                    '-q',
                    '--quiet',
               dest='quiet',
             action='store_true',
               help='do not print debug messages to stdout',
            default=False
        )
    else:
        raise TypeError('keyword argument "verbose" must be type of int, '
                        f'got {repr(default_verbose)}')
    return parser

class Options(object):

    __slots__ = ['file', 'home', 'root', 'verbose', 'user']

ParseResult = \
    collections.namedtuple(
        'ParseResult',
        [
            'args',
            'cfg',
            'opts',
            'parser'
        ]
    )

def get_default_root(home):
    return os.path.join(home, 'var')

###########################################################################
#                             Initialization                              #
###########################################################################

def init(args):
    home = args.home
    while True:
        a1 = input(f'Initialize a project in {home}? [Y/n]:')
        a2 = a1.strip().lower()
        if   a2 in ['n', 'no']:
            print ('Do nothing, quit.')
            return
        elif a2 in ['', 'y', 'yes']:
            break
        else:
            print (f'Unknown answer {a1}.')
    # create etc, var, pkgs dirs
    bin_dir  = os.path.join( home  , 'bin' )
    etc_dir  = os.path.join( home  , 'etc' )
    lib_dir  = os.path.join( home  , 'lib' )
    pkgs_dir = os.path.join( home  , 'pkgs')
    var_dir  = os.path.join( home  , 'var' )
    log_dir  = os.path.join(var_dir, 'log' )
    for dir_ in [bin_dir, etc_dir, var_dir, pkgs_dir]:
        sys.stdout.write(f'Creating {dir_} ... ')
        sys.stdout.flush()
        if   not os.path.exists(dir_):
            os.makedirs(dir_)
            print ('done')
        elif not os.path.isdir(dir_):
            print ('faild')
            print (f'ERROR! {dir_} exists, but is not a directory.')
            return
        else:
            print ('exists')
    # create startup script if not exists
    name = os.path.splitext(os.path.basename(sys.argv[0]))[0]
    script_name = name
    script_path = os.path.join(bin_dir, script_name)
    sys.stdout.write(f'Creating {script_path} ... ')
    sys.stdout.flush()
    if   not os.path.exists(script_path):
        code = script_in.format(interpreter=sys.executable)
        with open(script_path, 'wb') as file_out:
            file_out.write(code.encode())
        print ('done')
    elif not os.path.isfile(script_path):
        print (f'ERROR! {dir_} exists, but is not a file.')
    else:
        print ('exists')
    # create config file if not exists
    conf_name = name + '.conf'
    conf_path = os.path.join(etc_dir, conf_name)
    sys.stdout.write(f'Creating {conf_path} ... ')
    sys.stdout.flush()
    if   not os.path.exists(conf_path):
        with open(conf_path, 'wb') as file_out:
            file_out.write(config_in.encode())
        print ('done')
    elif not os.path.isfile(conf_path):
        print (f'ERROR! {dir_} exists, but is not a file.')
    else:
        print ('exists')
    print ('DONE! Completed all initialization steps.')

script_in = '''\
#!{interpreter}
# -*- coding: utf-8 -*-
import re
import slowdown.__main__
import sys
if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\.pyw|\.exe)?$', '', sys.argv[0])
    sys.exit(slowdown.__main__.main())
'''
config_in = '''\
# Effective User
# The default is the current user.
#
#user nobody

# Process Name
#
#proc slowdown

# Log Level
#
# Set log level to logging.DEBUG:
#verbose 2
# Set log level to logging.INFO:
#verbose 1
# Quiet mode (default):
verbose 0

<resource>
    # Limits for open files
    #
    RLIMIT_NOFILE 65535
</resource>

<environment>
    # By default, DummyThreadPool is used, which is a threadpool that
    # does not actually use threads and blocks the entrie program.
    #
    #GEVENT_THREADPOOL slowdown.threadpool.DummyThreadPool

    # Other runtime environment
    #
    #ENV value
</environment>

# URL Routing based on regular expression.
<routers>
    <router DEFAULT>

        # A regular expression to match hosts
        # Group name must be uppercased
        #
        pattern ^(?P<ALL_HOSTS>.*)$$

        <host ALL_HOSTS>

            # A reqular expression to match PATH_INFO and set
            # rw.environ['locals.path_info'] to the named group.
            # Group name must be uppercased.
            #
            pattern ^(?P<ITWORKS>/.*)$$

            <path ITWORKS>

                # It works!
                #
                # A handler comes from
                # the slowdown package.
                handler slowdown.__main__

            </path>
        </host>

        # More hosts ..
        #
        #<host HOSTNAME>...</host>
    </router>

    # More routers
    #
    #<router>...</router>
</routers>

<servers>
    <http MY_HTTP_SERVER>
        address  0.0.0.0:8080

        # More addresses
        #
        #address host:port

        router   DEFAULT
    </http>

    #<https MY_HTTPS_SERVER>
    #    address  0.0.0.0:8443
    #    address  127.0.0.1:9443
    #
    #    # More addresses
    #    #
    #    #address host:port
    #
    #    router   DEFAULT
    #    keyfile  /PATH/TO/server.key
    #    certfile /PATH/TO/server.cert
    #</https>

    # More servers
    #
    #<http>...</http>
    #<https>...</https>
</servers>

# Run scripts at startup
<scripts>
    # More scripts
    #
    # Run a module or package with `main` function:
    #run SCRIPT
</scripts>
'''

###########################################################################
#                              Configuration                              #
###########################################################################

def loadSchema(*args):
    loader = ZConfig.loader.SchemaLoader()
    file   = \
        io.StringIO(
            f'<schema>{"".join([schema] + list(args))}</schema>'
        )
    with loader.createResource(file, '<string>') as r:
        return loader.loadResource(r)

def loadConfig(schema, data):
    loader = ZConfig.loader.ConfigLoader(schema)
    file   = io.StringIO(data)
    with loader.createResource(file, '<string>') as r:
        return loader.loadResource(r)

def EnvironmentSection(section):
    return \
        dict(
            (key.upper(), value) for key, value in
            section.data.items()
        )

def ResourceSection(section):
    data = \
        dict(
            (key.upper(), value) for key, value in
            section.data.items()
        )
    if 'RLIMIT_NOFILE' in data:
        if int(data['RLIMIT_NOFILE']) < 1:
            raise ValueError('RLIMIT_NOFILE must be greater than zero')
    return data

def ScriptsSection(section):
    return section.run

def Routers(section):
    return dict((router.name, router) for router in section.data)

class Router(object):

    __slots__ = ['args', 'groups', 'name', 'regex', 'section']

    def __init__(self, section):
        self.name    = section_name_normalize(section)
        self.args    = section.args
        self.section = section
        self.groups  = {}
        self.regex   = \
            re.compile(
                '|'.join(
                    f'(?:{pattern})' for pattern in section.pattern
                )
            )
        for subsection in section.groups:
            for name in re.split(r'[\s,|]+', subsection.name):
                if name in self.groups:
                    raise ValueError(f'duplicate group name "{name}" '
                                     'exists')
                self.groups[name] = subsection

    def __call__(self, host, path_info):
        (   "__call__("
                "host:str, "
                "path_info:str"
            ") -> MatchResult" """

        Look for the package from **HTTP_HOSTS** and **PATH_INFO** .
        """)
        for match1 in self.regex.finditer(host):
            if match1.lastgroup is None:
                continue
            key1   = match1.lastgroup.upper()
            group1 = self.groups.get(key1)
            if group1 is not None:
                break
        else:
            return None
        for match2 in group1.regex.finditer(path_info):
            if match2.lastgroup is None:
                continue
            key2   = match2.lastgroup.upper()
            group2 = group1.groups.get(key2)
            if group2 is None:
                return None
            return \
                MatchResult(
                    match1.groupdict()[key1],
                    match2.groupdict()[key2],
                    self,
                    group1,
                    group2
                )
        else:
            return None

class HostSection(object):

    __slots__ = ['args', 'groups', 'name', 'regex', 'section']

    def __init__(self, section):
        self.name    = section_name_normalize(section)
        self.args    = section.args
        self.section = section
        self.groups  = {}
        self.regex   = \
            re.compile(
                '|'.join(
                    f'(?:{pattern})' for pattern in section.pattern
                )
            )
        for subsection in section.groups:
            for name in re.split(r'[\s,|]+', subsection.name):
                if name in self.groups:
                    raise ValueError(f'duplicate group name "{name}" '
                                     'exists')
                self.groups[name] = subsection

class PathSection(object):

    __slots__ = ['args', 'handler', 'name', 'section']

    def __init__(self, section):
        self.name    = section_name_normalize(section)
        self.args    = section.args
        self.section = section
        self.handler = section.handler

def RegexString(s):
    try:
        re.compile(s)
    except re.error as err:
        raise ValueError(f'invalid regular expression {repr(s)}: {err}')
    return s

class MatchResult(object):

    """
    Returned by `Router.__call__` when a package is matched.
    """

    __slots__ = ['host',
                 'host_section',
                 'path_info',
                 'path_section',
                 'router_section']

    def __init__(self, host, path_info, router_section, host_section,
                 path_section):
        self.host      = host       #: matched host
        self.path_info = path_info  #: matched path_info
        #: the matching `<router>` configuration section
        self.router_section = router_section
        #: the matching `<host>` configuration section
        self.host_section = host_section
        #: the matching `<path>` configuration section
        self.path_section = path_section

def section_name_normalize(section):
    return \
        ','.join(
            name for name in
            re.split(
                r'[\s,|]+',
                section.getSectionName().upper()
            ) if name
        )

class HTTPSection(object):

    __slots__ = ['addresses', 'name', 'router', 'section', 'type_']

    def __init__(self, section):
        if section.getSectionName() is None:
            self.name  = None
        else:
            self.name  = section.getSectionName().upper()
        self.type_     = section.getSectionType().upper()
        self.router    = section.router.upper()
        self.addresses = section.address
        self.section   = section

class HTTPSSection(HTTPSection):

    __slots__ = ['certfile', 'keyfile']

    def __init__(self, section):
        HTTPSection.__init__(self, section)
        self.certfile = section.certfile
        self.keyfile  = section.keyfile

#: built-in schema
schema = '''
<sectiontype name="environment"
             datatype="slowdown.__main__.EnvironmentSection">
    <key name="+" attribute="data" required="no" />
</sectiontype>
<sectiontype name="resource" datatype="slowdown.__main__.ResourceSection">
    <key name="+" attribute="data" required="no" />
</sectiontype>
<sectiontype name="scripts">
    <multikey name="run" datatype="string" required="no" />
</sectiontype>

<sectiontype name="path" datatype="slowdown.__main__.PathSection">
    <key name="handler" datatype="string" required="yes" />
    <key name="+" attribute="args" />
</sectiontype>
<sectiontype name="host" datatype="slowdown.__main__.HostSection">
    <multikey name="pattern" datatype="slowdown.__main__.RegexString"
              required="yes" />
    <multisection name="+" type="path" attribute="groups" required="yes" />
    <key name="+" attribute="args" />
</sectiontype>
<sectiontype name="router" datatype="slowdown.__main__.Router">
    <multikey name="pattern" datatype="slowdown.__main__.RegexString"
              required="no" />
    <multisection name="+" type="host" attribute="groups" required="yes" />
    <key name="+" attribute="args" />
</sectiontype>
<sectiontype name="routers" datatype="slowdown.__main__.Routers">
    <multisection name="+" type="router" attribute="data" required="no" />
</sectiontype>

<abstracttype name="server" />
<sectiontype name="servers">
    <multisection name="*" type="server" attribute="data" required="no" />
</sectiontype>
<sectiontype name="http" implements="server"
             datatype="slowdown.__main__.HTTPSection">
    <multikey name="address" datatype="inet-binding-address"
              required="yes" />
    <key name="router" datatype="string" required="yes" />
</sectiontype>
<sectiontype name="https" implements="server"
             datatype="slowdown.__main__.HTTPSSection">
    <multikey name="address" datatype="inet-binding-address"
              required="yes" />
    <key name="router" datatype="string" required="yes" />
    <key name="keyfile" datatype="existing-file" required="yes" />
    <key name="certfile" datatype="existing-file" required="yes" />
</sectiontype>

<key name="user" datatype="identifier" required="no" />
<key name="home" datatype="existing-directory" required="no" />
<key name="root" datatype="existing-directory" required="no" />
<key name="verbose" datatype="integer" default="0" required="no" />
<section type="environment" attribute="environment" required="no" />
<section type="resource" attribute="resource" required="no" />
<section type="scripts" attribute="scripts" required="no" />
<section type="routers" attribute="routers" required="no" />
<section type="servers" attribute="servers" required="no" />
'''
