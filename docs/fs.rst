==========
Filesystem
==========

.. contents::
    :depth: 1
    :local:
    :backlinks: none


The FS object
-------------

Slowdown is a coroutine-based framework that requires the cooperative
version of disk IO. The :py:class:`~slowdown.fs.FS` object holds those
cooperative interfaces.

.. code-block:: python

    import gevent
    import slowdown.fs

    fs = slowdown.fs.FS()

    def main():
        if not fs.os.path.exists('test.txt'):
            file = fs.open('test.txt', 'wb')
            file.write('OK')
            file.close()

    io_jobs = fs.spawn()
    io_jobs.append(gevent.spawn(main))
    gevent.joinall(io_jobs)

You can get the :py:class:`~slowdown.fs.FS` object from the
:py:class:`~slowdown.__main__.Application` object without creating it
yourself.

.. code-block:: python

    # The first time the script is loaded, the "initialize(mapfs)" of the
    # script is executed.
    def initialize(mapfs):
        global fs
        fs = mapfs.application.fs

    def GET(rw):
        with fs.open('test.html', 'rb') as file:
            content = file.read()
        rw.send_html_and_close(content=content)


Opening files
-------------

You can use the `open` method of the :py:class:`~slowdown.fs.FS` object
to open a file. When the `fs.open()` is called a `gevent.fileobject` is
returned, see `gevent.fileobject`__ for details.

.. note::

    Currently, only opening files in binary mode is supported.

__ http://www.gevent.org/api/gevent.fileobject.html


Miscellaneous FS interfaces
---------------------------

:py:attr:`slowdown.fs.FS.os` is the cooperative version of the `os` module.
It provides the following interfaces:

    access, chmod, chown, close, closerange, fchmod, fchown, fstat,
    fstatvfs, ftruncate, fwalk, lchown, link, listdir, lstat, makedirs,
    mkdir, open, remove, removedirs, rename, renames, rmdir, stat, unlink,
    walk

:py:attr:`slowdown.fs.FS.os.path` is the cooperative version of the
`os.apth` module. It provides the following interfaces:

    abspath, exists, getatime, getctime, getmtime, getsize, isdir, isfile,
    islink, ismount, lexists, realpath, relpath
