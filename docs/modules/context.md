# Context and memory

The context module governs what retrieval puts in front of a model. A **context source** fetches items for a query; the harness then re-checks every item's ACL, labels it, caps the total, and runs the context guards, before anything reaches the model. **Memory** is a separate key-value store, namespaced so that no tenant or principal can read another's entries.

```yaml
context:
  help: { use: memory, file: data/help_center.yaml, max_items: 4, max_tokens: 800, require_acl: true }
  web:  { use: passthrough }          # the app retrieves; the harness governs
memory: { use: memory, default_ttl: 30d }
guardrails:
  context:
    - { id: context-injection, use: injection.heuristic, action: block }   # a block drops the item
```

```python
articles = await s.context("help").fetch(question)            # retrieve, then govern
checked = await s.context("web").check(items_from_my_search)  # govern what you retrieved yourself
```

## Items

A `ContextItem` has an `id`, `content`, `source`, `score`, `untrusted`, an optional `acl`, and `metadata`. An `Acl` has `tenants`, `principals` and `roles`: when `tenants` is set, the run's tenant must be one of them; when `principals` or `roles` is set, the run's principal must be listed or hold one of the roles. Empty lists restrict nothing.

```yaml
# data/help_center.yaml, for the memory provider
documents:
  - id: help-refunds
    content: Refunds go back to the card you paid with within five business days.
    acl: { tenants: [] }                     # open
  - id: help-globex-sla
    content: Globex's contract promises a reply within four hours.
    acl: { tenants: [globex] }               # Globex only
```

## Governance

Every item, fetched or passed in, is governed **inside** the context call, before the `context.after` middleware sees it, so no middleware order can let a bad item through ([ADR-0030](../adr/0030-context-governance.md)):

1. **ACL re-check.** An item whose ACL excludes the run's tenant or principal is dropped, even when its provider returned it. With `require_acl: true`, an item with no ACL is dropped too. A `ContextProvider` must itself return only what the envelope's tenant and principal may see; this is defense in depth.
2. **Labels.** The item's `source` becomes the source's name, and it is untrusted unless the source is `label: trusted` (RULES S3).
3. **Caps.** `max_items`, then `max_tokens` (one token per four characters), in order.
4. Each drop is a `harness.context` trace note with the item's id, never its content (R9, R13).

Then the `context` guard stage and any other `context.after` middleware run. At the context stage a guard's `block` drops that item, not the run. Untrusted items that are kept set the run's `untrusted_seen` label, which the lethal-trifecta check reads.

The ids of the items a run keeps are remembered (in its checkpoint too), so `grounded.citations` can tell a real source from a made-up one.

## Providers

| Provider | What it does | Settings |
| --- | --- | --- |
| `memory` | Documents held in memory (inline or from a file), searched lexically like the `lexical` routing stage (token cosine) | `documents`: a list of `{id, content, acl, metadata}`; or `file`: a YAML file with a `documents` list, relative to the spec |
| `passthrough` | Fetches nothing; governs the items your code passes to `s.context(name).check(items)` | none |

Vector stores and search services come as plugins (*planned*: pgvector, OpenSearch, Qdrant). Until then, retrieve with your own client and pass the results through a `passthrough` source, so the same ACL, label, cap and guard rules apply.

## Memory

`s.memory` keeps key-value entries for the run's `(tenant, principal, task)` ([ADR-0031](../adr/0031-namespaced-memory.md)):

```python
await s.memory.put("last_order", "A-1001", ttl=timedelta(hours=1))
order = await s.memory.get("last_order")           # None once expired or absent
await s.memory.delete("last_order")
entries = await s.memory.entries()       # a dict of the live entries
```

- Entries expire after `ttl`, or `memory.default_ttl`, on the run's clock.
- The harness picks the namespace, so nobody reads another tenant's or principal's entries.
- The built-in `memory` provider keeps entries in the process; they don't survive a restart.
- It is a store, not a memory model (RULES R12): what an agent remembers, and when, is your app's or its framework's business.

## TypeScript

`@harnessweaver/core` supports the `memory` and `passthrough` providers with the same governance: `s.context("help").fetch(query)` and `s.context("web").check(items)`.
