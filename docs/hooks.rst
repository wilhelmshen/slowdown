=====
Hooks
=====

.. contents::
    :depth: 1
    :local:
    :backlinks: none


Package initialization hooks
----------------------------

If a module or package containing a handler is registered in the routing
configuration, the server will automatically load the module or package and
executes its existing initialization hook. The hook is a callable object
with the name `startup` .

Example:

.. code-block:: python

    # file: entrypoint.py           -- sample module
    #  or
    # file: entrypoint/__init__.py  -- sample package

    import datetime

    def startup(application):
        global start_time
        start_time = f'Start time: {datetime.datetime.now()}'

    def handler(rw):
        rw.send_html_and_close(
            content=f'<html>{start_time}</html>'
        )

The hook accepts an :py:class:`~slowdown.__main__.Application` object as an
argument.


Server startup scripts
-----------------------------

.. code-block:: apacheconf

    <scripts>
        run PACKAGE
        run MODULE
        run ..
    </scripts>

When the server starts, it executes scripts registered in the `scripts`
section of the config file. Those scripts could be a module or package
and have a function with the name `main`.

Example:

.. code-block:: python

    # file: script.py           -- sample module
    #  or
    # file: script/__init__.py  -- sample package

    import slowdown.gvars

    def main(application):
        slowdown.gvars.logger.INFO(
            'Some work is done when the server starts'
        )

The main function accepts an :py:class:`~slowdown.__main__.Application`
object as an argument.
