=============
Configuration
=============

.. contents::
    :depth: 1
    :local:
    :backlinks: none


The config file of the slowdown server called `slowdown.conf` is placed in
the `etc` folder. The following is a detailed config example of all the
sections and options.

.. code-block:: apacheconf

    # file: etc/slowdown.conf

    # Predefined directories
    #
    %define HOME /PATH/TO/HOME
    %define BIN  $HOME/bin
    %define ETC  $HOME/etc
    %define PKGS $HOME/pkgs
    %define VAR  $HOME/var
    %define LOGS $HOME/logs

    # Effective User
    # The default is the current user.
    #
    #user nobody

    # Log Level
    #
    # Set log level to logging.DEBUG:
    #verbose 2
    #
    # Set log level to logging.INFO (default):
    #verbose 1
    #
    # Quiet mode:
    #verbose 0

    <resource>
        # Limits for open files
        #
        RLIMIT_NOFILE 65535
    </resource>

    <environment>
        # By default, FileObjectThread is used.
        #
        #GEVENT_FILE thread

        # If single-threaded mode is required, set GEVENT_THREADPOOL to
        # "slowdown.threadpool.DummyThreadPool", which is a threadpool that
        # does not actually use threads and blocks the entrie program.
        #
        #GEVENT_THREADPOOL slowdown.threadpool.DummyThreadPool

        # Other runtime environment
        #
        #ENV value
    </environment>

    # Register modules
    <modules>
        # Load a module or package and run it's "initialize(app)" function.
        # "finalize(app)" function is executed when the server shuts down.
        # Loaded modules can be accessed through "app.modules[MY.MODULE]" .
        #
        load MY.MODULE

        # More modules
        #
        #load ..
    </modules>

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
                pattern ^/mysite(?P<MYSITE>/.*)$$

                <path MYSITE>
                    # The package called 'mysite' placed in
                    # the 'pkgs/' dir is set to handle
                    # incoming requests.
                    #
                    handler mysite
                </path>

                # Another rule
                #
                pattern ^(?P<ITWORKS>/.*)$$

                # Logs
                #
                #accesslog

                <path ITWORKS>
                    # It works!
                    #
                    # A handler comes from the slowdown package.
                    #
                    handler   slowdown.__main__
                    accesslog $LOGS/access.log
                    errorlog  $LOGS/error.log
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
            address  127.0.0.1:9080

            # More addresses
            #
            #address host:port

            router   DEFAULT
        </http>
        <https MY_HTTPS_SERVER>
            address  0.0.0.0:8443
            address  127.0.0.1:9443

            # More addresses
            #
            #address host:port

            router   DEFAULT
            keyfile  $ETC/server.key
            certfile $ETC/server.cert
        </https>

        # More servers
        #
        #<http>...</http>
        #<https>...</https>

    </servers>

.. note::

    Section names, regex group names, option names, must be written in
    uppercase because `ZConfig`_ is case-insensitive. See `ZConfig`_ for
    details.

.. note::

    `$` must escape to `$$` in patterns because `$` is used to define
    variables. See `ZConfig`_ for details.

.. _ZConfig: https://zconfig.readthedocs.io/en/latest/
