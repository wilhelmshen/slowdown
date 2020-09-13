#!/usr/bin/env python3

import re
import setuptools

with open('src/slowdown/__init__.py') as f:
    version = re.search(r"__version__\s*=\s*'(.*)'", f.read()).group(1)
with open('README.rst') as f:
    readme  = f.read()

setuptools.setup(
                name='slowdown',
             version=version,
         description='A coroutine-based web framework',
    long_description=readme,
             license='MIT',
            keywords=('coroutine cooperative gevent greenlet web '
                      'framework async asynchronous http server'),
              author='Wilhelm Shen',
        author_email='wilhelmshen@pyforce.com',
                 url='http://slowdown.pyforce.com',
         package_dir={'': 'src'},
            packages=['slowdown'],
    install_requires=
             [
                      'captcha>=0.3',
                       'gevent>=20.4.0',
                 'pycryptodome>=3.9.7',
                       'xxhash>=1.4.4',
                      'ZConfig>=3.5.0'
             ],
         classifiers=
             [
                 'License :: OSI Approved :: MIT License',
                 'Programming Language :: Python :: 3.6',
                 'Programming Language :: Python :: 3.7',
                 'Programming Language :: Python :: 3.8',
                 'Programming Language :: Python :: 3.9',
                 'Programming Language :: Python :: Implementation :: '+
                                                              'CPython',
                 'Operating System :: POSIX',
                 'Topic :: Internet',
                 'Topic :: Internet :: WWW/HTTP :: Dynamic Content :: '+
                                                  'CGI Tools/Libraries',
                 'Topic :: Internet :: WWW/HTTP :: HTTP Servers',
                 'Topic :: Software Development :: Libraries :: '+
                                                 'Python Modules',
                 'Topic :: Software Development :: Libraries :: '+
                                         'Application Frameworks',
                 'Intended Audience :: Developers',
                 'Development Status :: 4 - Beta'
             ],
     python_requires='>=3.6',
        entry_points=
             {
                 'console_scripts': ['slowdown=slowdown.__main__:main']
             }
)
