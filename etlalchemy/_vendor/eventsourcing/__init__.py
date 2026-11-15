"""Vendored part of the ``eventsourcing`` project.

Only the ``asyncio`` subpackage lives here, because it is not published on
PyPI: the rest of the library (aggregates, events, transcodings, the cipher and
the SQLAlchemy-free persistence interfaces) is imported from the installed
official ``eventsourcing`` distribution. See ``README.md`` for the origin and
the local changes.
"""
