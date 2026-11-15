# Glossary

Every domain word this documentation uses, defined once.

*Diátaxis type: reference* · **Audience:** everybody · **Prerequisites:** none

## Domain and architecture

| Term | Definition |
|---|---|
| **Aggregate** | The consistency boundary of one thing — a catalog, a table, a term. Its state is the result of its events, and no outside code may change it. |
| **Aggregate root** | The object you load by id and send commands to. |
| **Bounded context** | A package that owns one vocabulary and one job (`catalog`, `iam`, …). Contexts are independent; they reference each other by id. |
| **Command** | A method on an aggregate or an application that may record events. |
| **Event** | An immutable fact that already happened, e.g. `Table.Discarded`. Declared as a frozen dataclass inside the aggregate. |
| **Event store** | The append-only table holding every event of a context. |
| **Stream** | The events of one aggregate, in order, with a version per event. |
| **Optimistic concurrency** | Two writers on one stream: the second gets `RecordConflictError` and must retry. |
| **Application** | The use-case layer (`CatalogApplication`). Loads aggregates, calls commands, saves an atomic unit of work. |
| **Unit of work** | The set of aggregates saved together, e.g. a child plus the parent that registers it. |
| **Projection** | The subscriber that turns events into read-model rows. |
| **Read model / view** | The tables a query is answered from, and the class that writes them (`SQLAlchemyCatalogView`). |
| **Tracking row** | The marker that ties one projected event to the transaction that applied it, so nothing is applied twice. |
| **Soft delete** | `discard()` sets `discarded_at`; reads filter it out and the name may be reused. |

## Delivery

| Term | Definition |
|---|---|
| **Delivery layer** | FastAPI routes or FastMCP tools — two faces of the same use case. |
| **Tool** | An MCP operation a model may call, e.g. `create_catalog`. |
| **Resource** | An MCP read addressed by URI, e.g. `catalog:///all`. |
| **Prompt** | An MCP template that asks a model for a specific job, e.g. `rename-safely`. |
| **Annotation** | The `readOnlyHint` / `destructiveHint` metadata that tells the agent whether a tool writes. |
| **`readOnlyHint`** | The tool never writes; the agent runs it without asking. |
| **`destructiveHint`** | The tool may delete; the agent asks first unless a rule says otherwise. |

## Metadata

| Term | Definition |
|---|---|
| **Catalog** | The top of the metadata tree: one data estate. |
| **Schema** | A group of tables inside a catalog. |
| **Table** | A relation inside a schema; owns its fields. |
| **Field** | A column: name, canonical data type, nullability, comment. |
| **Data type** | The normalised type of a field (`varchar(255)`), not the source dialect's spelling. |
| **Semantic model** | One aggregate holding entities, relationships, diagrams and node positions. |
| **Entity** | A table as it appears in a semantic model. |
| **Relationship** | A link between entity fields; `from_refs`/`to_refs` pair by position. |
| **Diagram** | A named view of the model's entities. `All` always shows every entity. |
| **Node** | An entity's position on one diagram. |
| **Domain** | The root of a vocabulary tree. |
| **Term** | A business word with definition, aliases, colour, status and links. |
| **Path** | A term's address inside its domain, e.g. `Revenue/ARR`. |
| **Alias** | An alternative name a term is also known by. |
| **Term status** | `draft`, `approved`, `deprecated` — content states, unlike colour. |
| **Link** | A term's attachment to a catalog or semantic object. |

## Platform

| Term | Definition |
|---|---|
| **Source connection** | A read-only pointer at an external database, with one credential. |
| **Import run** | One execution of an import: counters, status, `include_tables`, `schema_mapping`. |
| **Schema mapping** | Renaming a source schema while importing; several sources may map to one target. |
| **Tenant** | An isolation boundary for users, groups and permissions. |
| **Identity** | One credential of a user: `PASSWORD`, `OIDC` or `API_KEY`. |
| **Session** | A time-limited, revocable grant of a token. |
| **Bearer token** | `iam_sess_<session_id>` — opaque, and the only thing a client sends. |
| **Scope** | A permission in `resource:action` form, e.g. `catalog:write`. |
| **Permission grant** | A scope granted to a group, evaluated by Casbin. |
| **System administrator** | A user with the sysadmin flag; exempt from tenant scoping. |
| **Provider** | Either an authentication provider (OIDC) or an LLM provider — always disambiguated in this documentation. |
| **Conversation** | A chat with the agent; owns messages and runs. |
| **Run** | One turn of a conversation: status, tool calls, approvals, error. |
| **Approval** | A pending question about one destructive tool call. |
| **Checkpoint** | LangGraph's persisted graph state, one thread per run. |
| **Steering** | Changing a run while it is in flight — explicitly not supported. |
| **URN** | The `urn:catalog/…` address a model writes so the chat can link an object. |
| **Redaction** | Masking argument values (`token`, `password`, …) in the previews that reach the browser. |

## See also

- [Architecture](../concepts/architecture.md) — how the words fit together
- [Event sourcing](../concepts/event-sourcing.md) — aggregate, event, stream
- [Read model](../concepts/read-model.md) — projection, tracking, view
