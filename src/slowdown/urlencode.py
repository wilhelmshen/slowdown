# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

import sys
import urllib.parse

__all__ = ['quote', 'quote_plus', 'unquote', 'unquote_plus']

def quote(string, safe='/', encoding=None, errors=None):
    (   "quote("
            "string:Union[str,bytes]"
        ") -> bytes"
    )
    return \
        as_bytes(
            urllib.parse.quote(string, safe, encoding, errors)
        )

def quote_plus(string, safe='', encoding=None, errors=None):
    (   "quote_plus("
            "string:Union[str,bytes]"
        ") -> bytes"
    )
    return \
        as_bytes(
            urllib.parse.quote_plus(string, safe, encoding, errors)
        )

def unquote(string, encoding='utf-8', errors='replace'):
    (   "unquote("
            "string:Union[str,bytes]"
        ") -> bytes"
    )
    return \
        as_bytes(
            urllib.parse.unquote(string.decode(), encoding, errors)
        )

def unquote_plus(string, encoding='utf-8', errors='replace'):
    (   "unquote_plus("
            "string:Union[str,bytes]"
        ") -> bytes"
    )
    return \
        as_bytes(
            urllib.parse.unquote_plus(
                string.decode(),
                encoding,
                errors
            )
        )

def as_bytes(string, encoding=None):
    (   "as_bytes("
            "string:Union[str,bytes], "
            "encoding:str=None"
        ") -> bytes"
    )
    if   isinstance(string, str):
        return \
            string.encode(
                sys.getdefaultencoding() if encoding is None else encoding
            )
    elif isinstance(string, bytes):
        return string
    else:
        raise \
            TypeError(
                f'expected binary or unicode string, got {repr(string)}'
            )
