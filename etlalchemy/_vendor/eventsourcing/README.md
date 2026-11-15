# Vendored `eventsourcing.asyncio`

`etlalchemy/_vendor/eventsourcing/asyncio/` is a copy of the `asyncio` package
of the eventsourcing fork maintained at
`https://github.com/liang-guang-jun/eventsourcing`, branch `asyncio`, commit
`d1616702e3761b067182951c28d25ca271c6b92c` (2026-11-10), on top of upstream
release 9.5.6.

Upstream `eventsourcing` has no asynchronous infrastructure, and the asyncio
work is not published on PyPI, so it is vendored here instead of installed from
a sibling checkout. Everything else — `Aggregate`, `event`, `AggregateCreated`,
`Tracking`, `Mapper`, `Transcoder`, `JSONTranscoder`, `Environment`,
`resolve_topic`, `singledispatchmethod`, `AESCipher`, the persistence exception
hierarchy — comes from the installed official `eventsourcing` distribution,
which the vendored modules import unchanged.

## Local changes

The modules are byte-identical to the fork apart from two mechanical edits:

1. intra-package imports and docstring cross-references are rewritten from
   `eventsourcing.asyncio.<module>` to
   `etlalchemy._vendor.eventsourcing.asyncio.<module>`;
2. `AsyncBaseInfrastructureFactory.construct` falls back to the topic
   `etlalchemy._vendor.eventsourcing.asyncio.sqlalchemy` instead of the
   upstream `eventsourcing.asyncio.sqlalchemy`.

Do not reformat, rename or "improve" these modules: keep them diffable against
the upstream branch, so a later upstream commit can be applied by hand. They are
excluded from `ruff` and from `mypy` (see `pyproject.toml`) and carry the
upstream BSD-3-Clause licence in `LICENSE`.

## Using it

`PERSISTENCE_MODULE` is `etlalchemy._vendor.eventsourcing.asyncio.sqlalchemy`
(see `etlalchemy/app/config/settings.py`), so the factory resolves through
`eventsourcing.utils.resolve_topic`. Application code imports its base classes
from this package:

- `etlalchemy._vendor.eventsourcing.asyncio.application` — `AsyncApplication`,
  `AsyncRepository`, `AsyncNotificationLog`
- `etlalchemy._vendor.eventsourcing.asyncio.persistence` —
  `AsyncTrackingRecorder`, `AsyncInfrastructureFactory`, subscriptions
- `etlalchemy._vendor.eventsourcing.asyncio.projection` — `AsyncProjection`,
  `AsyncProjectionRunner`
- `etlalchemy._vendor.eventsourcing.asyncio.sqlalchemy` —
  `AsyncSQLAlchemyDatastore`, `AsyncSQLAlchemyTrackingRecorder`,
  `AsyncSQLAlchemyFactory`

The project pins `eventsourcing>=9.5.6,<9.6`: the vendored modules lean on a few
helpers that are not part of the library's stable public API, so a minor upgrade
must be validated against this directory.
