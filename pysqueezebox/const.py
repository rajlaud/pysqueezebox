"""Constants for pysqueezebox."""

from typing import TypeAlias

DEFAULT_PORT = 9000
TIMEOUT = 10.0
REPEAT_MODE = ["none", "song", "playlist"]
SHUFFLE_MODE = ["none", "song", "album"]

STATUS_SENSOR_LASTSCAN = "lastscan"
STATUS_SENSOR_NEEDSRESTART = "needsrestart"
STATUS_SENSOR_RESCAN = "rescan"
STATUS_QUERY_LIBRARYNAME = "libraryname"
STATUS_QUERY_MAC = "mac"
STATUS_QUERY_UUID = "uuid"
STATUS_QUERY_VERSION = "version"
STATUS_UPDATE_NEWVERSION = "newversion"
STATUS_UPDATE_NEWPLUGINS = "newplugins"
UPDATE_PLUGINS_RELEASE_SUMMARY = "update_plugins_release_summary"
UPDATE_RELEASE_SUMMARY = "update_release_summary"

QueryResult: TypeAlias = "dict[str, int | str | QueryResult | list[QueryResult]]"
