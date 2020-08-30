# Copyright (c) 2020 Wilhelm Shen. See LICENSE for details.

"""\
============================================
:mod:`slowdown.captcha` -- Captcha generator
============================================

This module provides a captcha generator implementation for high concurrent
services.

Typically, each request generates a captcha. However, this module generates
a pool of captcha ahead, it's not possible to create captcha at each time.
The captcha pool refreshes over time.

Example:

    >>> c = \\
    ...     Captcha(
    ...         text_len=4,  # the length of the verification code
    ...                      # the default is 4
    ...
    ...         cache_size=60,  # the size of captcha pool
    ...                         # the default is 60
    ...
    ...         expiration_time=90,  # the expiration time of the captcha
    ...                              # the default is 90
    ...
    ...         image_format= 'jpeg'  # the default is 'jpeg'
    ...     )
    >>> media = c.new()
    >>> media.text  # the verification code
    7E8a
    >>> media.get_img(alt='mycaptcha')
    <img src="data:image/jpeg;base64,ZXhhbXBsZQ==' alt='mycaptcha' />
    >>> f'<img src="{media.img_src}" />'
    <img src="data:image/jpeg;base64,ZXhhbXBsZQ==' />
    >>> f'<img src="data:image/jpeg;base64,{media.image_base64}">'
    <img src="data:image/jpeg;base64,ZXhhbXBsZQ==' />
    >>> with open('mycaptcha.jpeg', 'w') as file_out:  # save to a file
    >>>     file_out.write(media.image)
"""

try:
    import captcha.image
except ModuleNotFoundError:
    raise \
        ModuleNotFoundError(
            'No module named \'captcha.image\', '
            'but can be installed with: \'pip install captcha\''
        )

import base64
import random
import time

default_text_len     = 4
default_image_format = 'jpeg'
default_cache_size   = 60
default_expiration_time = 90

__all__ = ['Captcha', 'Media']

class Captcha(object):

    (   "Captcha("
            "text_len:int=-1, "
            "cache_size:int=-1, "
            "expiration_time:int=-1, "
            "image_format:str='jpeg'"
        ") -> Captcha" """

    Captcha generator.
    """)

    __slots__ = ['cache',
                 'expiration_time',
                 'cache_size',
                 'image_format',
                 'image_generator',
                 'text_len']

    def __init__(self, text_len=-1, cache_size=-1, expiration_time=-1,
                 image_format=None):
        if -1 == text_len:
            self.text_len = default_text_len
        else:
            self.text_len = text_len
        if -1 == cache_size:
            self.cache_size = default_cache_size
        else:
            self.cache_size = cache_size
        if -1 == expiration_time:
            self.expiration_time = default_expiration_time
        else:
            self.expiration_time = expiration_time
        if image_format is None:
            self.image_format = default_image_format
        else:
            self.image_format = image_format
        self.image_generator = captcha.image.ImageCaptcha()
        expiration_time = int(time.time()) \
                        + self.expiration_time
        self.cache = \
            [
                Media(
                    ''.join(
                        random.choice(alphabet)
                        for dummy in
                            range(self.text_len)
                    ),
                    expiration_time,
                    self.image_generator,
                    self.image_format
                )
                for dummy in
                    range(self.cache_size)
            ]

    def new(self):
        (   "new() -> Media" """

        Acquire a new captcha.
        """)
        now   = int(time.time())
        index = random.randint(0, self.cache_size-1)
        item  = self.cache[index]
        if item.expiration_time > now:
            return item
        item = \
            Media(
                ''.join(
                    random.choice(alphabet)
                    for dummy in
                        range(self.text_len)
                ),
                now + self.expiration_time,
                self.image_generator,
                self.image_format
            )
        self.cache[index] = item
        return item

class Media(object):

    """
    Captcha data holder.
    """

    __slots__ = ['expiration_time',
                 'image_generator',
                 'image_format',
                 'text',
                 '_image',
                 '_image_base64']

    def __init__(self, text, expiration_time, image_generator,
                 image_format):
        self.text            =            text
        self.expiration_time = expiration_time
        self.image_generator = image_generator
        self.image_format    =    image_format

    @property
    def image(self):
        """
        The raw data of the captcha image.

        :rtype: bytes
        """
        image = getattr(self, '_image', None)
        if image is None:
            image = self                                              \
                  . image_generator                                   \
                  . generate(self.text, format=self.image_format)     \
                  . getvalue()
            self._image = image
            return image
        else:
            return image

    @property
    def image_base64(self):
        """
        The base64 encoded image.

        :rtype: str
        """
        image_base64 = getattr(self, '_image_base64', None)
        if image_base64 is None:
            image = getattr(self, '_image', None)
            if image is None:
                image = self                                          \
                      . image_generator                               \
                      . generate(self.text, format=self.image_format) \
                      . getvalue()
                self._image = image
            image_base64 = base64.b64encode(image).decode('utf-8')
            self._image_base64 = image_base64
            return image_base64
        else:
            return image_base64

    @property
    def img_src(self):
        """
        The URL that contains the captcha image for the HTML IMG tag's
        src attribute.

        :rtype: str
        """
        return f'data:image/{self.image_format};base64,{self.image_base64}'

    def get_img(self, alt=None):
        (   "get_img("
                "alt:str=None"
            ") -> str" """

        Returns a HTML IMG tag that contains the captcha image.
        """)
        if alt is None:
            return f'<img src="{self.img_src}" />'
        else:
            alt = alt                    \
                . replace('&', '&amp;' ) \
                . replace('<', '&lt;'  ) \
                . replace('>', '&gt;'  ) \
                . replace('"', '&quot;') \
                . replace("'", '&#x27;')
            return f'<img src="{self.img_src}" alt="{alt}" />'

    img = property(get_img)

alphabet = '23456789abcdefghijkmnprstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ'
