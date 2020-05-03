"""
This a library to control a Logitech Media Server asynchronously.

This library is intended for integration with Home Assistant.

Much of the code was adapted from the Home Assistant squeezebox integration.
The current convention is for all API-specific code to be part of a third
party library hosted on PyPi, so I created a separate library.

The function names track the terms used by the LMS API, so they do not all
match the old Home Assistant squeezebox integration.

Thank you to the original author of the squeezebox integration. If it is you,
please let me know so I can credit you here.

(c) 2020 Raj Laud raj.laud@gmail.com
"""

import logging

from .discovery import async_discover
# pylint: disable=unused-import
from .player import Player
from .server import Server

# http://docs.python.org/2/howto/logging.html#library-config
# Avoids spurious error messages if no logger is configured by the user

logging.getLogger(__name__).addHandler(logging.NullHandler())
