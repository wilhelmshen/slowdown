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
with the name `initialize` .

Example:

.. code-block:: python

    # file: entrypoint.py           -- sample module
    #  or
    # file: entrypoint/__init__.py  -- sample package

    import datetime

    def initialize(application):
        global start_time
        start_time = f'Start time: {datetime.datetime.now()}'

    def handler(rw):
        rw.send_html_and_close(
            content=f'<html>{start_time}</html>'
        )

The hook accepts an :py:class:`~slowdown.__main__.Application` object as an
argument.


Server startup scripts
----------------------

.. code-block:: apacheconf

    <modules>
        load MY.PACKAGE
        load MY.MODULE
        load ..
    </modules>

When the server starts, it executes scripts registered in the `<modules>`
section of the config file. Those scripts could be a module or package
and have a function with the name `initialize`.

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

In fact, modules registered with `<path>handler MODULE</path>` have
the same import machanism as modules registered with `<modules>` section
and are stored in :py:attr:`~slowdown.__main__.Application.modules` of
:py:class:`~slowdown.__main__.Application` object.
