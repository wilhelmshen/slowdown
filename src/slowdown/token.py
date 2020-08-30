# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
========================================================
:mod:`slowdown.token` -- The python token implementation
========================================================

Example:

    >>> tokenizer = \\
    ...     AES_RC4(
    ...         aes_key=Crypto.Random.get_random_bytes(16),  # 16 Bytes
    ...         rc4_key=Crypto.Random.get_random_bytes(8),   #  8 Bytes
    ...
    ...         # The decryption of tokens can speed up by caching.
    ...         # The default `cache_size` is 256.
    ...         cache_size=256,
    ...
    ...         # Tokens shoud be limited to a maximum length
    ...         # to avoid attacks on man-made tokens.
    ...         # The default `max_token` is 1048.
    ...         max_token=1048
    ...     )
    >>> token = \\
    ...     tokenizer.pack(
    ...         {
                    'expiration_time': time.time()+3600,
    ...                    'username': 'guest'
    ...         }
    ...     )
    >>> tokenizer.unpack(token)
    {'expiration_time': 1600000000.0, 'username': 'guest'}
"""

import base64
import binascii
import Crypto.Cipher.AES
import Crypto.Cipher.ARC4
import Crypto.Random
import Crypto.Util.Padding
import hashlib
import marshal
import xxhash

from . import lrucache

default_aes_cache_size = 256
default_hash_salt_size = 8
default_hash_func = lambda s: hashlib.sha256(s).digest()
default_max_token = 1048
default_magic_bytes = xxhash.xxh32_digest(b'slowdown.token')

__all__ = ['AES_RC4', 'Hash']

class Hash(object):

    (   "Hash("
            "key:bytes, "
            "salt_size:int=-1, "
            "max_token:int=-1, "
            "hash_func=None"
        ")" """

    Hash token.
    """)

    __slots__ = ['data_idx',
                 'hash_func',
                 'key',
                 'max_token',
                 'salt_size']

    def __init__(self, key, slat_size=-1, max_token=-1, hash_func=None):
        if -1 == salt_size:
            self.salt_size = default_hash_salt_size
        else:
            self.salt_size = salt_size
        if -1 == max_token:
            self.max_token = default_max_token
        else:
            self.max_token = max_token
        if hash_func is None:
            self.hash_func = default_hash_func
        else:
            self.hash_func = hash_func
        self.key      = key
        self.data_idx = self.salt_size + sha256_digest_size

    def pack(self, data):
        (   "pack("
                "data:object"
            ") -> str" """

        Generate a token from the marshalable data.
        """)
        serialized = marshal.dumps(data)
        salt       = Crypto.Random.get_random_bytes(self.salt_size)
        digest     = self.hash_func(salt+serialized).digest()
        b          = salt + digest + serialized
        token      = base64.b64encode(b).decode('utf-8')
        if len(token) > self.max_token:
            raise ValueError('the generated token is too large')
        return token

    def unpack(self, token):
        (   "unpack("
                "token:str"
            ") -> object" """

        Validate the token and return the data contained in the token
        string.
        """)
        if len(token) > self.max_token:
            raise ValueError('token too large')
        b          = base64.b64decode(token)
        salt       = b[             0:self.salt_size]
        digest     = b[self.salt_size:self.data_idx ]
        serialized = b[self.data_idx :              ]
        if self.hash_func(salt+serialized).digest() != digest:
            raise VerificationError('Invalid token')
        return marshal.loads(serialized)

class AES_RC4(object):

    (   "AES_RC4("
            "aes_key:bytes=None, "
            "rc4_key:bytes=None, "
            "cache_size:int=-1, "
            "max_token:int=-1, "
            "magic_bytes:str=None"
        ")" """

    The token encrypted by both AES and ARC4 algorithms.
    """)

    __slots__ = ['aes_key',
                 'cache',
                 'magic_bytes',
                 'magic_bytes_len',
                 'max_token',
                 'rc4_key']

    def __init__(self, aes_key=None, rc4_key=None, cache_size=-1,
                 max_token=-1, magic_bytes=None):
        if aes_key is None:
            self.aes_key = Crypto.Random.get_random_bytes(16)
        else:
            self.aes_key = aes_key
        if rc4_key is None:
            if aes_key is not None:
                raise ValueError('the rc4_key must be specified')
            self.rc4_key = Crypto.Random.get_random_bytes(8)
        else:
            self.rc4_key = rc4_key
        if -1 == cache_size:
            cache_size = default_aes_cache_size
        self.cache = lrucache.LRUCache(size=cache_size)
        if -1 == max_token:
            self.max_token = default_max_token
        else:
            self.max_token = max_token
        if magic_bytes is None:
            self.magic_bytes = default_magic_bytes
        else:
            self.magic_bytes = magic_bytes
        if not isinstance(self.magic_bytes, bytes):
            raise TypeError('magic_bytes must be a bytes object')
        self.magic_bytes_len = len(self.magic_bytes)

    def pack(self, data):
        (   "pack("
                "data:object"
            ") -> str" """

        Generate a encrypted token from the marshalable data.
        """)
        serialized = self.magic_bytes + marshal.dumps(data)
        salt = Crypto.Random.get_random_bytes(8)
        key  = xxhash.xxh64_digest(salt + self.rc4_key)
        cipher = Crypto.Cipher.ARC4.new(key)
        ct     = cipher.encrypt(serialized)
        serialized = salt + ct
        salt = Crypto.Random.get_random_bytes(16)
        key  = hashlib.md5(salt + self.aes_key).digest()
        cipher = Crypto.Cipher.AES.new(key, Crypto.Cipher.AES.MODE_CBC)
        ct     = \
            cipher.encrypt(
                Crypto.Util.Padding.pad(
                    serialized,
                    Crypto.Cipher.AES.block_size
                )
            )
        serialized = salt + cipher.iv + ct
        token = base64.b64encode(serialized).decode('utf-8')
        if len(token) > self.max_token:
            raise ValueError('the generated token is too large')
        self.cache[token] = Holder(data)
        return token

    def unpack(self, token):
        (   "unpack("
                "token:str"
            ") -> object" """

        Validate the token and return the data contained in the encrypted
        token string.
        """)
        if len(token) > self.max_token:
            raise ValueError('token too large')
        holder = self.cache.get(token)
        if holder is None:
            block_size = Crypto.Cipher.AES.block_size
            serialized = base64.b64decode(token)
            p      = 16 + block_size
            salt   = serialized[ 0:16]
            iv     = serialized[16:p ]
            ct     = serialized[ p:  ]
            if len(salt) != 16         or \
               len( iv ) != block_size or \
               len( ct )  % block_size != 0:
                raise VerificationError('Invalid token')
            key    = hashlib.md5(salt + self.aes_key).digest()
            cipher = \
                Crypto.Cipher.AES.new(
                    key,
                    Crypto.Cipher.AES.MODE_CBC,
                    iv
                )
            serialized = \
                Crypto.Util.Padding.unpad(
                    cipher.decrypt(ct),
                    Crypto.Cipher.AES.block_size
                )
            salt   = serialized[0:8]
            ct     = serialized[8: ]
            key    = xxhash.xxh64_digest(salt + self.rc4_key)
            cipher = Crypto.Cipher.ARC4.new(key)
            serialized = cipher.encrypt(ct)
            if serialized[0:self.magic_bytes_len] != self.magic_bytes:
                raise VerificationError('Invalid token')
            data = marshal.loads(serialized[self.magic_bytes_len:])
            self.cache[token] = Holder(data)
            return data
        else:
            return holder.data

class Holder(object):

    __slots__ = ['data', '__weakref__']

    def __init__(self, data):
        self.data = data

class VerificationError(ValueError):

    pass

sha256_digest_size = len(hashlib.sha256(b'MEANINGLESS').digest())
