============
Installation
============

.. contents::
    :depth: 1
    :local:
    :backlinks: none


Installation
------------

Slowdown are published on the `Python Package Index`__ , and can be
installed with the following command.

.. code-block:: console

    $ pip install -U slowdown

You can also install Slowdown directly from a clone of the
`Git repository`__ .

.. code-block:: console

    $ git clone https://github.com/wilhelmshen/slowdown
    $ cd slowdown
    $ pip install .

or

.. code-block:: console

    $ pip install git+https://github.com/wilhelmshen/slowdown

__ https://pypi.org/project/slowdown/
__ https://github.com/wilhelmshen/slowdown


Server creation
---------------

Server should be created before a web site is setted up. You can use
`virtualenv`_ and the ``slowdown --init`` command to create a server.

.. code-block:: console

    $ virtualenv --python=/usr/bin/python3 myproj
    $ myproj/bin/slowdown --init
    Initialize a project in myproj? [Y/n]: Y
    Creating myproj/bin ... exists
    Creating myproj/etc ... exists
    Creating myproj/var ... done
    Creating myproj/pkgs ... done
    Creating myproj/var/log ... done
    Creating myproj/bin/slowdown ... exists
    Creating myproj/etc/slowdown.conf ... done
    DONE! Completed all initialization steps.

You can also use the ``slowdown --init`` command with the
``--home DIRECTORY`` option to specify a server home directory. System-wide
python interpreter will be used.

.. code-block:: console

    $ slowdown --init --home=/PATH/TO/myproj
    Initialize a project in /PATH/TO/myproj? [Y/n]: Y
    Creating myproj/bin ... done
    Creating myproj/etc ... done
    Creating myproj/var ... done
    Creating myproj/pkgs ... done
    Creating myproj/logs ... done
    Creating myproj/bin/slowdown ... done
    Creating myproj/etc/slowdown.conf ... done
    DONE! Completed all initialization steps.

After all initialization steps are completed, the server folder called ``myproj`` will be created as follow.

.. code-block:: text

    myproj/
        bin/
            slowdown
        etc/
            slowdown.conf
        lib/
        var/
        logs/
        pkgs/

.. object:: bin/slowdown

    The startup script.

.. object:: etc/slowdown.conf

    The config file of slowdown server.

.. object:: pkgs/

    Contains python packages that are used as web site containers.

Now you can start the web server by the following command:

.. code-block:: console

    $ myproj/bin/slowdown
    Serving HTTP on 0.0.0.0 port 8080 ...

.. _virtualenv: https://virtualenv.pypa.io/
