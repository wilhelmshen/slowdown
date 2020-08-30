# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
=============================================
:mod:`slowdown.router` -- HTTP-Routing module
=============================================
"""

import re

__all__ = ['Result', 'Router']

class Router(object):

    (   "Router("
            "section:ZConfig.matcher.SectionValue"
        ")" """

    Look for packages from *HTTP_HOSTS* and *PATH_INFO*
    by reading the configuration in `ZConfig.matcher.SectionValue` object
    to handle incoming requests.

    The router schema is placed in the `__main__.schema` variable.
    """)

    __slots__ = ['groups', 'hosts']

    def __init__(self, section):
        for pattern in section.pattern:
            try:
                re.compile(pattern)
            except re.error as err:
                raise ValueError(f'<router {section.getSectionName()}>: '
                                 f'pattern {pattern}: {err}')
        self.hosts = re.compile('|'.join(section.pattern))
        self.groups = {}
        for subsection in section.groups:
            names = subsection.getSectionName().upper()
            try:
                group = Host(subsection)
            except (ValueError, TypeError, KeyError) as err:
                raise \
                    err.__class__(
                        f'<router {section.getSectionName()}>: '
                        f'<host {names}>: {err}'
                    )
            for name in re.split(r'[\s,|]+', names):
                if name in self.groups:
                    raise \
                        ValueError(
                            f'<router {section.getSectionName()}>: '
                            f'duplicate group name "{name}" exists'
                        )
                self.groups[name] = group

    def __call__(self, host, path_info):
        (   "Router("
                "host:str, "
                "path_info:str"
            ") -> Result" """

        Look for the package from *HTTP_HOSTS* and *PATH_INFO* .
        """
        for match1 in self.hosts.finditer(host):
            if match1.lastgroup is None:
                continue
            key    = match1.lastgroup.upper()
            group1 = self.groups.get(key)
            if group1 is not None:
                host_ = match1.groupdict()[key]
                break
        else:
            return None
        for match2 in group1.urls.finditer(path_info):
            if match2.lastgroup is None:
                continue
            key    = match2.lastgroup.upper()
            group2 = group1.groups.get(key)
            if group2 is None:
                return None
            entrypoint, args = group2
            return Result(entrypoint, host_, match2.groupdict()[key], args)
        else:
            return None

class Host(object):

    __slots__ = ['groups', 'urls']

    def __init__(self, section):
        for pattern in section.pattern:
            try:
                re.compile(pattern)
            except re.error as err:
                raise ValueError(f'pattern {pattern}: {err}')
        self.urls = re.compile('|'.join(section.pattern))
        self.groups = {}
        for subsection in section.groups:
            names = subsection.getSectionName().upper()
            for name in re.split(r'[\s,|]+', names):
                if name in self.groups:
                    raise ValueError(f'duplicate group name "{name}" '
                                     'exists')
                self.groups[name] = (subsection.handler, subsection.args)

class Result(object):

    """
    Returned by `Router.__call__` when a package is matched.
    """

    __slots__ = ['entrypoint', 'host', 'path_info', 'args']

    def __init__(self, entrypoint, host, path_info, args):
        self.entrypoint = entrypoint  #: matched package name
        self.host       = host        #: matched host
        self.path_info  = path_info   #: matched path_info

        #: the matching configuration section of the dict format
        self.args       = args
