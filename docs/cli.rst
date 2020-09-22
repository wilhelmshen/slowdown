======================
Command line interface
======================

.. contents::
    :depth: 1
    :local:
    :backlinks: none


Usage
-----

The slowdown service can be controlled by a program called ``slowdown``,
which is located in the ``bin`` dir.

.. code-block:: console

    usage: bin/slowdown [-h] [-f FILE] [-u USER] [--home DIRECTORY]
                        [--root DIRECTORY] [--init] [-v | -vv | -q]


Options
-------

.. program:: bin/slowdown

.. option:: -h, --help

    Show help message

.. option:: -f FILE, --file FILE

    Config file, the default is ``/SERVER-HOME/etc/slowdown.conf``

.. option:: -u USER, --user USER

    Server will running as the specified user, the default is the current
    user.

.. option:: --home DIRECTORY

    Home folder of the server.

.. option:: --root DIRECTORY

    The working directory.

.. option:: --init

    Convert the folder specified by the ``--home DIRECTORY`` option to the
    home folder of the server.

.. option:: -v

    Set debug level to **logging.INFO** .

.. option:: -vv

    Set debug level to **logging.DEBUG** .

.. option:: -q

    Do not print debug messages.

.. note::

    The default value will be taken from the profile, but shall be
    overwritten by the command line arguments.


Examples
--------

Start server and accept full debug messages:

.. code-block:: console

    $ bin/slowdown -vv

Start server as a specified user `nobody`:

.. code-block:: console

    $ sudo bin/slowdown -u nobody

Start server using a specified profile:

.. code-block:: console

    $ bin/slowdown -f /PATH/TO/profile.conf
