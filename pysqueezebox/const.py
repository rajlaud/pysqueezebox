"""Constants for pysqueezebox."""

from typing import TypeAlias

DEFAULT_PORT = 9000
TIMEOUT = 10.0
REPEAT_MODE = ["none", "song", "playlist"]
SHUFFLE_MODE = ["none", "song", "album"]

QueryResult: TypeAlias = "dict[str, int | str | QueryResult | list[QueryResult]]"
