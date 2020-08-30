=======
Routing
=======

.. contents::
    :depth: 1
    :local:
    :backlinks: none


Defining a Router
-----------------

.. code-block:: apacheconf

    # file: etc/slowdown.conf

    <routers>

        <router ROUTER_NAME>
            pattern REGEX1
            pattern REGEX2
            pattern   ..

            <host GROUP_NAME>
                pattern REGEX1
                pattern REGEX2
                pattern   ..

                <path GROUP_NAME>
                    handler entrypoint
                </path>
            </host>

            <host .. >
               ..
            </host>
        </router>

        <router .. >
             ..
        </router>
    </routers>

1) The only `<routers>` tag contains all `<router>` tags.
#) The `<router>` tag contains many `patterns` and `<host>` tags.
   The `<host>` tag must have a uppercased name, that corresponds to the
   name of the group contained in a pattern.
#) The `<host>` tag contains many `patterns` and `<path>` tags.
   The `<path>` tag must have a uppercased name, that corresponds to the
   name of the group contained in a pattern.
#) The `<path>` tag must have a single `handler` option to link to a
   python moudle/package that is usually called an `entrypoint`.
#) When the server starts, the definition of all routers in the config file
   is loaded. Requests that match the appropriate rule are give to the
   appropriate `handler` .

.. note::
    The `re` module is used here, and patterns should be written according
    to the `python regex` convention.

.. note::

    The browser may send `HOSTS` header with a port, so the host pattern
    should contains the possible port. Just like this
    ``(?P<SAMPLE>example\.com(?:\:80)?)``.

Handler
-------

.. code-block:: apacheconf

    <path NAME>
        handler entrypoint
    </path>

The `handler` option in the config file is used to link to a module or
package. The module or package being linked to needs to define a
callable object named `handler` to processes the request.

.. code-block:: python

    # file: pkgs/entrypoint.py

    def handler(rw):
        rw.send_html_and_close('<html>Hello, World!</html>')

or

.. code-block:: python

    # file: pkgs/entrypoint/__init__.py

    def handler(rw):
        rw.send_html_and_close('<html>Hello, World!</html>')

Handlers can be written in many ways.

.. code-block:: python

    # file: pkgs/entrypoint.py

    class Handler(object):

        def __call__(rw):
            rw.send_html_and_close('<html>Hello, World!</html>')

    handler = Handler()

.. code-block:: python

    # file: pkgs/entrypoint/__init__.py

    handler = \
        lambda rw: \
            rw.send_html_and_close('<html>Hello, World!</html>')


Mapping URLs to filesystem locations
------------------------------------

:py:class:`~slowdown.mapfs.Mapfs` is a `Handler` class that maps URLs to
filesystem locations.

.. code-block:: python

    # file: pkgs/entrypoint.py

    import slowdown.fs
    import slowdown.mapfs

    fs = slowdown.fs.FS()  # locl filesystem
    handler = \
        slowdown.mapfs.Mapfs(
            # Mapfs requires an FS object to indicate a specific
            # filesystem that contains static files and scripts.
            fs = fs,

            www='/PATH/TO/DOCUMENT/ROOT',  # static files directory
            cgi='/PATH/TO/SCRIPTS'         # scripts directory
        )

Typically you don't need to create :py:class:`~slowdown.mapfs.Mapfs` object
manually, you just create a package that doesn't contain the `handler`
function, and the slowdown server automatically creates the `handler` at
startup.

.. code-block:: text

    myproj/
        pkgs/
            mysite/
                __init__.py
                __www__/
                __cgi__/

The automatically generated `handler` uses the `__www__` dir under the
package dir as the folder of static files, and the `__cgi__` dir under the
package dir as the folder of script files.
