# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
====================================================================
:mod:`slowdown.__main__` -- The implementation of the startup script
====================================================================

This module contains the configuration schema and the startup script
implementation of the Slowdown Server::

    usage: slowdown [-h] [-f FILE] [-u USER] [--proc NAME]
                    [--home DIRECTORY]  [--root DIRECTORY]
                    [--init] [-v | -q]

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
        root='PATH/TO/ROOT/DIRECTORY',

        # the execution user
        user='USER',

        proc='PROCESS NAME',

        # The log level
        # 0 - quiet
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

import sys

sys.dont_write_bytecode = True

import argparse
import copy
import errno
import html
import io
import logging
import os
import os.path
import traceback
import ZConfig.loader

from . import gvars
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

    import gevent
    import gevent.exceptions

    try:
        gevent.joinall(jobs)
    except gevent.exceptions.BlockingSwitchOutError:
        pass

def spawn(**kwargs):
    """
    Spawn server threads base on the configuration.
    """
    options, args, cfg, parser = parse(**kwargs)
    # --init: convert the working virtualenv home folder to the
    #         project home
    if args.init:
        initproj(args)
        return Jobs()
    # --proc: specify the process name
    if options.proc is not None:
        sysutil.setprocname(options.proc)
    # --root: root dir, probably $HOME/var
    if options.root is not None:
        os.chdir(options.root)
    # -v, -vv: set the log level
    if   0 == options.verbose:
        gvars.logger.setLevel(logging.ERROR)
    elif 1 == options.verbose:
        gvars.logger.setLevel(logging.INFO)
    else:
        gvars.logger.setLevel(logging.DEBUG)
    for key, value in default_environment.items():
        os.environ[key.upper()] = value
    if cfg.environment is not None:
        for key, value in cfg.environment.data.items():
            os.environ[key.upper()] = value
    section = cfg.resource
    if section is not None:
        if section.rlimit_nofile is not None:
            if section.rlimit_nofile < 1:
                raise ValueError('RLIMIT_NOFILE must be greater than zero')

            import resource

            try:
                resource.setrlimit(
                    resource.RLIMIT_NOFILE,
                    (
                        cfg.resource.rlimit_nofile,
                        cfg.resource.rlimit_nofile
                    )
                )
            except Exception:
                gvars.logger.warning('Require root permission to allocate '
                                     'resources')
    # Add $HOME/pkgs that contains the user package to sys.path
    pkgs_dir = os.path.join(options.home, 'pkgs')
    if pkgs_dir not in sys.path:
        sys.path.append(pkgs_dir)
    try:
        (routers,
         servers,
         handlers,
         modules) = \
            prepare(cfg, options.verbose)
    except Exception as err:
        gvars.logger.exception(f'{os.path.basename(sys.argv[0])}: '
                               f'{options.file}: {err}')
        if hasattr(err, 'errno'):
            sys.exit(err.errno)
        else:
            sys.exit(errno.EINVAL)

    import gevent
    import gevent.signal
    import weakref

    from . import fs
    from . import mapfs

    fs_ = fs.FS()
    app = \
        Application(
                 fs_=fs_,
             servers=servers,
            handlers=handlers,
             modules=modules,
             options=options,
                 cfg=cfg,
             verbose=options.verbose
        )
    jobs = Jobs(fs_.spawn())
    for entrypoint, module in modules.items():
        if hasattr(module, 'startup') and callable(module.startup):
            jobs.append(gevent.spawn(module.startup, app))
        if not hasattr(module, 'handler'):
            home = os.path.abspath(os.path.dirname(module.__file__))
            www  = os.path.join(home, '__www__')
            cgi  = os.path.join(home, '__cgi__')
            if not os.path.isdir(www):
                www = None
            if not os.path.isdir(cgi):
                cgi = None
            if www is not None or cgi is not None:
                module.handler = mapfs.Mapfs(fs_, www=www, cgi=cgi)
    if cfg.scripts is not None:
        for run in cfg.scripts.run:
            module = load_module(run, options.verbose)
            if hasattr(module, 'main') and callable(module.main):
                jobs.append(gevent.spawn(module.main, app))
    if options.user is not None:
        sysutil.setuid(options.user)
    gevent.signal.signal(gevent.signal.SIGQUIT, app.shutdown)
    gevent.signal.signal(gevent.signal.SIGTERM, app.shutdown)
    gevent.signal.signal(gevent.signal.SIGINT , app.shutdown)
    app._jobs         = weakref.ref(jobs)
    jobs._application = weakref.ref(app)
    return jobs

def initproj(args):
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
        code = startup_script_template \
             . format(interpreter_path=sys.executable)
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
            file_out.write(config_file_template.encode())
        print ('done')
    elif not os.path.isfile(conf_path):
        print (f'ERROR! {dir_} exists, but is not a file.')
    else:
        print ('exists')
    print ('DONE! Completed all initialization steps.')

def prepare(cfg, verbose=0):

    from . import router

    routers = {}
    if cfg.routers is not None:
        for section in cfg.routers.data:
            routers[section.getSectionName()] = router.Router(section)
    servers  = {}
    handlers = {}
    modules  = {}
    for name, router in routers.items():
        for host in router.groups.values():
            for entrypoint, args in host.groups.values():
                if entrypoint not in modules:
                    modules[entrypoint] = \
                        load_module(
                            entrypoint,
                            verbose
                        )
        handlers[name.upper()] = Handler(router)

    import gevent.server
    import gevent.ssl

    from . import http

    for section in cfg.servers.data:
        section_type = section.getSectionType()
        if 'http' == section_type:
            servers[section.getSectionName().upper()] = []
            for address in section.address:
                servers[section.getSectionName().upper()].append(
                    gevent.server.StreamServer(
                        address,
                        http.Handler(handlers[section.router.upper()],
                                     verbose)
                    )
                )
        elif 'https' == section_type:
            servers[section.getSectionName().upper()] = []
            ssl_context = \
                gevent.ssl.SSLContext(gevent.ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(section.certfile, section.keyfile)
            for address in section.address:
                servers[section.getSectionName().upper()].append(
                    gevent.server.StreamServer(
                        address,
                        http.Handler(handlers[section.router.upper()],
                                     verbose),
                        ssl_context=ssl_context
                    )
                )
    for serverlist in servers.values():
        for server in serverlist:
            server.start()
            if server.ssl_enabled:
                scheme = 'HTTPS'
            else:
                scheme = 'HTTP'
            gvars.logger.info(f'Serving {scheme} on {server.server_host} '
                              f'port {server.server_port} ...')
    return (routers, servers, handlers, modules)

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
            return (None, args, None, parser)
        else:
            try:
                cfg, nil = \
                    ZConfig.loader.loadConfig(
                        schema,
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
        cfg, nil = loadConfig(schema, config)
    defaults = copy.copy(kwargs)
    defaults['add_help'] = True
    if cfg.user is not None:
        defaults['user'] = cfg.user
    if cfg.proc is not None:
        defaults['proc'] = cfg.proc
    if cfg.home is not None:
        defaults['home'] = cfg.home
    if cfg.root is not None:
        defaults['root'] = cfg.root
    defaults['verbose'] = cfg.verbose
    parser = ParserFactory(**defaults)
    args = parser.parse_args()
    options = Options()
    if config is None:
        options.file = args.file
    else:
        options.file = None
    options.home = args.home
    options.proc = args.proc
    options.user = args.user
    if args.root is None:
        options.root = root_by_home(args.home) \
                       if cfg.root is None else cfg.root
    else:
        options.root = args.root
    if   args.quiet:
        options.verbose = 0
    elif args.verbose is not None:
        options.verbose = args.verbose
    else:
        options.verbose = defaults['verbose']
    return (options, args, cfg, parser)

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
    default_user = kwargs.get('user')
    if default_user is None:
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
                     f'the default is "{default_user}"'),
            default=default_user
        )
    default_proc = kwargs.get('proc')
    if default_proc is None:
        parser.add_argument(
                    '--proc',
               dest='proc',
               type=str,
            metavar='NAME',
               help='specify the process name',
        )
    else:
        parser.add_argument(
                    '--proc',
               dest='proc',
               type=str,
            metavar='NAME',
               help=f'process name, the default is "{default_proc}"',
            default=default_proc
        )
    parser.add_argument(
                 '--home',
            dest='home',
            type=str,
        metavar='DIRECTORY',
            help=f'home dir, the default is {default_home}',
        default=default_home
    )
    default_root = kwargs.get('root')
    if default_root is None:
        default_root = root_by_home(default_home)
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
               help=f'working dir, the default is {default_root}',
            default=None
        )
    parser.add_argument(
                '--init',
           dest='init',
         action='store_true',
           help=('convert the working python virtualenv home folder to '
                 'the project home'),
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
               help=('print debug messages '
                     f'(the default level is {default_verbose})'),
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

class Jobs(list):

    pass

class Application(object):

    """
    A runtime object created by the `__main__.main` function that
    contains configuration information from the command line, profile,
    and the arguments in the `__main__.main` function.
    """

    def __init__(self, fs_, servers, handlers, modules, options, cfg,
                 verbose=0):
        #: the cooperative file system interface
        self.fs       = fs_
        self.servers  = servers
        self.handlers = handlers
        self.modules  = modules
        self.options  = options   #: final configuration

        #: the configuration of the profile created by ZConfig.loadConfig()
        self.cfg      = cfg

        self.verbose  = verbose
        self._jobs    = None

    def shutdown(self, *args):
        """
        Stop servers and exit the program.
        """
        exceptions_ = []
        if self.modules:
            modules = self.modules
            self.modules = []
            for module in modules:
                if hasattr(module, 'shutdown') and \
                   callable(module.shutdown):
                    try:
                        module.shutdown()
                    except Exception as err:
                        exceptions_.append(err)
        if self._jobs is not None and self._jobs() is not None:
            for servers in self.servers.values():
                for server in servers:
                    server.stop()

            import gevent
            import gevent.exceptions

            try:
                gevent.killall(self._jobs())
            except gevent.exceptions.BlockingSwitchOutError:
                pass
            self._jobs = None
        if exceptions_:
            if 0 == len(exceptions_):
                raise exceptions_[0]
            else:

                from . import exceptions

                raise exceptions.Exceptions(exceptions_)
        sys.exit(0)

class Options(object):

    pass

class Handler(object):

    """
    This class is used to handle the HTTP requests that arrive at the
    `gevent.server.Server` .
    """

    __slots__ = ['router']

    def __init__(self, router_):
        self.router = router_

    def __call__(self, rw):
        environ = rw.environ
        result  = \
            self.router(
                environ.get('HTTP_HOST', ''),
                    environ['PATH_INFO']
            )
        if result is None:
            return rw.bad_request()
        module = sys.modules.get(result.entrypoint)
        if module is None or not hasattr(module, 'handler'):
            return rw.not_found()
        environ['locals.path_info'] = result.path_info
        environ['locals.args'     ] = result.args
        return module.handler(rw)

def handler(rw):
    rw.send_html_and_close(content=itworks_content)

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

def root_by_home(home):
    return os.path.join(home, 'var')

def exc():
    file = io.StringIO()
    traceback.print_exc(file=file)
    return file.getvalue()

def loadSchema(data):
    loader = ZConfig.loader.SchemaLoader()
    file   = io.StringIO(data)
    with loader.createResource(file, '<string>') as r:
        return loader.loadResource(r)

def loadConfig(schema, data):
    loader = ZConfig.loader.ConfigLoader(schema)
    file   = io.StringIO(data)
    with loader.createResource(file, '<string>') as r:
        return loader.loadResource(r)

# By default, DummyThreadPool is used, which is a threadpool that does not
# actually use threads and blocks the entrie program.
default_environment = \
    {
        'GEVENT_THREADPOOL': 'slowdown.threadpool.DummyThreadPool'
    }
# built-in ZConfig schema
schema = loadSchema('''<schema>
<sectiontype  name="environment">
    <key name="+" attribute="data" required="no" />
</sectiontype>

<sectiontype  name="resource">
    <key name="RLIMIT_NOFILE" datatype="integer" required="no"  />
</sectiontype>

<sectiontype name="scripts">
    <multikey name="run"      datatype="string"  required="no"  />
</sectiontype>

<sectiontype  name="path">
    <key      name="handler"  datatype="string"  required="yes" />
    <key      name="+"        attribute="args" />
</sectiontype>
<sectiontype  name="host">
    <multikey name="pattern"  datatype="string"  required="yes" />
    <multisection  name="+"      type="path"     attribute="groups"
              required="yes" />
</sectiontype>
<sectiontype  name="router">
    <multikey name="pattern" datatype="string"   required="no"  />
    <multisection   name="+"     type="host"     attribute="groups"
              required="yes" />
</sectiontype>
<sectiontype  name="routers">
    <multisection name="+" type="router" attribute="data" required="no" />
</sectiontype>

<abstracttype name="server"/>
<sectiontype  name="servers">
    <multisection name="+" type="server" attribute="data"
                  required="no" />
</sectiontype>
<sectiontype  name="http"    implements="server">
    <multikey name="address" datatype="inet-binding-address"
              required="yes" />
    <key name="router"  datatype="string" required="yes" />
</sectiontype>
<sectiontype  name="https"   implements="server">
    <multikey name="address" datatype="inet-binding-address"
              required="yes" />
    <key name="router"      datatype="string"        required="yes" />
    <key name="keyfile"     datatype="existing-file" required="yes" />
    <key name="certfile"    datatype="existing-file" required="yes" />
</sectiontype>

<key name="user"    datatype="identifier"            required="no"  />
<key name="proc"    datatype="string"                required="no"  />
<key name="home"    datatype="existing-directory"    required="no"  />
<key name="root"    datatype="existing-directory"    required="no"  />
<key name="verbose" datatype="integer" default="0"   required="no"  />

<section type="environment" attribute="environment"  required="no"  />
<section type="resource"    attribute="resource"     required="no"  />
<section type="scripts"     attribute="scripts"      required="no"  />
<section type="routers"     attribute="routers"      required="no"  />
<section type="servers"     attribute="servers"      required="no"  />
</schema>''')
startup_script_template = '''\
#!{interpreter_path}

"""
The startup script for the slowdown server.

httpd [-f config] [-u user] [-p proc] [--home directory] \\
[--root directory] [-v[v]|-q] [-h]
"""

if '__main__' == __name__:

    import sys

    sys.dont_write_bytecode = True

    import slowdown.__main__

    slowdown.__main__.main()
'''
config_file_template = '''\
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
