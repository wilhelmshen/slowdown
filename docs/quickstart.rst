===============
Getting Started
===============

.. contents::
    :depth: 1
    :local:
    :backlinks: none


Overview
--------

Slowdown is a coroutine-based Python web framework based on `gevent`__.
Slowdown is written in pure `Python`__ and supports Python 3.6+.

.. code-block:: python

    # file: mysite/__cgi__/index_html.py

    def GET(rw):
        rw.send_html_and_close(content='<html>Hello, World!</html>')

__ https://www.gevent.org/
__ https://www.python.org/


Creating a server
-----------------

You can use `virtualenv`_ to create a server by the following commands.

.. code-block:: console

    $ virtualenv --python=/usr/bin/python3 myproj
    $ myproj/bin/pip3 install slowdown
    $ myproj/bin/slowdown --init
    Initialize a project in /PATH/TO/myproj? [Y/n]: Y
    Creating myproj/bin ... exists
    Creating myproj/etc ... exists
    Creating myproj/var ... done
    Creating myproj/pkgs ... done
    Creating myproj/var/log ... done
    Creating myproj/bin/slowdown ... exists
    Creating myproj/etc/slowdown.conf ... done
    DONE! Completed all initialization steps.

Let's look at what `virtualenv`_ and ``slowdown --init`` created.

.. code-block:: text

    myproj/
        bin/
            slowdown
        etc/
            slowdown.conf
        lib/
        var/
        pkgs/

Start the slowdown server:

.. code-block:: console

    $ myproj/bin/slowdown -vv
    Serving HTTP on 0.0.0.0 port 8080 ...

.. _virtualenv: https://virtualenv.pypa.io/


The first website
-----------------

Web sites are placed in the ``pkgs`` dir as regular python packages and
sometimes has the following structure:

.. code-block:: text
    :emphasize-lines: 3-6

    myproj/
        pkgs/
            mysite/
                __init__.py
                __www__/
                __cgi__/


Static files in the ``__www__`` dir shall be sent to the browser. And
scripts in the ``__cgi__`` dir will be executed when requested.

So, you can create a python package as a container for site resources.

.. code-block:: console

    $ mkdir myproj/pkgs/mysite
    $ touch myproj/pkgs/mysite/__init__.py
    $ mkdir myproj/pkgs/mysite/__www__
    $ mkdir myproj/pkgs/mysite/__cgi__

And add a script named ``index.html.py`` to the ``__cgi__`` folder.

.. code-block:: python

    # file: myproj/pkgs/mysite/__cgi__/index_html.py

    def HTTP(rw):
        rw.send_html_and_close(content='<html>Hello, World!</html>')

The ``index.html`` file in the ``__www__`` folder gives the same effect:

.. code-block:: html

    <!-- file: myproj/pkgs/mysite/__www__/index.html -->

    <html>Hello, World!</html>

Then edit the config file ``myproj/etc/slowdown.conf`` :

.. code-block:: apacheconf
    :emphasize-lines: 7

    <routers>
        <router DEFAULT>
            pattern ^(?P<ALL_HOST>.*)$$
            <host ALL_HOST>
                pattern ^(?P<ALL_PATH>/.*)$$
                <path ALL_PATH>
                    handler mysite
                </path>
            </host>
        </router>
    </routers>
    <servers>
        <http MY_HTTP_SERVER>
            address 0.0.0.0:8080
            router  DEFAULT
        </http>
    </servers>

Now you've got a minimized website. You can start the web server by the
following command:

.. code-block:: console

    $ myproj/bin/slowdown -vv
    Serving HTTP on 0.0.0.0 port 8080 ...

Browse ``http://127.0.0.1:8080/`` and you'll see the `Hello, World!` page.
