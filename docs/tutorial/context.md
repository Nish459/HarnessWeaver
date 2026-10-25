# Retrieval and memory

A good answer comes from your help center, not from the model's memory. But retrieved text is risky. It can belong to another customer, it can carry injected instructions, and the model can claim it cited something it never saw. The harness **governs retrieval**: it re-checks every item's access list, labels it untrusted, caps how much reaches the model, and runs your context guards, before anything gets to the model.

## Some help articles

Add `data/help.yaml`. The third article is for one customer only:

```yaml title="data/help.yaml"
--8<-- "docs_src/tutorial/context/data/help.yaml"
```

`acl: { tenants: [globex] }` says only runs for the tenant `globex` may see that article. An item can also list `principals` and `roles`. Empty lists restrict nothing.

## Declare a context source

```yaml title="harness.yaml (the context section)"
--8<-- "docs_src/tutorial/context/harness.yaml:35:39"
```

`help` is a source that uses the built-in `memory` provider: documents held in memory, from the file, searched lexically. `max_items` keeps the best three.

## Fetch, then answer with citations

```python title="helpdesk/flows.py" hl_lines="13-15"
--8<-- "docs_src/tutorial/context/helpdesk/flows.py"
```

The prompt lists the articles by id and asks for a citation:

```markdown title="prompts/answer@2.md"
--8<-- "docs_src/tutorial/context/prompts/answer@2.md"
```

Then make the harness check the citations, with a guard on the `answer` task's output only:

```yaml title="harness.yaml (the answer task)" hl_lines="5-7"
--8<-- "docs_src/tutorial/context/harness.yaml:56:62"
```

`grounded.citations` checks that the answer's sentences cite an item in square brackets, such as `[help-refunds]`, and that each citation names an item **this run actually retrieved**. A made-up source doesn't count. `action: repair` sends an uncited answer back to the model. It's a task guard because the triage task's output isn't prose.

## Run it

```yaml title="harness.offline.yaml"
--8<-- "docs_src/tutorial/context/harness.offline.yaml"
```

```python title="main.py"
--8<-- "docs_src/tutorial/context/main.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main.py
completed
A refund takes up to five business days to reach your card [help-refunds].
```

## Who sees what

Fetch the same question for two tenants:

```python title="main_fetch.py"
--8<-- "docs_src/tutorial/context/main_fetch.py"
```

```console
$ HARNESSWEAVER_ENV=offline uv run python main_fetch.py
acme ['help-refunds', 'help-invoices']
globex ['help-refunds', 'help-globex-sla', 'help-invoices']
```

Acme never sees Globex's contract terms. The provider returned the article, and the harness dropped it, because its ACL excludes the run's tenant.

## How retrieval is governed

Every item, fetched or passed in, is governed **inside** the context call, before any `context.after` middleware sees it, so no middleware order can let a bad item through ([ADR-0030](../adr/0030-context-governance.md)):

1. **ACL re-check.** An item whose ACL excludes the run's tenant or principal is dropped, even when its provider returned it. With `require_acl: true`, an item with no ACL is dropped too.
2. **Labels.** The item's `source` becomes the source's name, and it is **untrusted** unless the source is `label: trusted` (RULES S3).
3. **Caps.** `max_items`, then `max_tokens`, in order.
4. Each drop is a `harness.context` note in the trace, with the item's id and never its content.

Then the `context` guard stage runs on each kept item. There a guard's `block` drops the item, not the run:

```yaml
guardrails:
  context:
    - { id: context-injection, use: injection.heuristic, action: block }
```

Untrusted items that are kept mark the run as having **seen untrusted content**. That label matters in [Tools](tools.md): a run that has seen untrusted content and private data can't send data out without a person's approval.

## Your own search

The built-in providers are `memory` (documents in memory, searched lexically) and `passthrough`, which fetches nothing. Vector stores and search services come as plugins. Until you have one, retrieve with your own client and let the harness govern the results:

```yaml
context:
  web: { use: passthrough }
```

```python
items = [hw.ContextItem(id=hit.id, content=hit.text, source="web") for hit in my_search(question)]
checked = await s.context("web").check(items)
```

The same ACL, label, cap and guard rules apply. [Providers](../reference/providers.md#context-sources) lists every source setting.

## Memory

`s.memory` is a small key-value store for the run's tenant, principal and task:

```python
await s.memory.put("last_order", "A-1002", ttl=timedelta(hours=1))
order = await s.memory.get("last_order")   # None once expired or absent
```

The harness picks the namespace, so no tenant or principal reads another's entries ([ADR-0031](../adr/0031-namespaced-memory.md)). Entries expire after `ttl`, or the spec's `memory.default_ttl`. It is a store, not a memory model: what an agent remembers, and when, is your app's business (RULES R12).

## Recap

- A **context source** fetches items. The harness re-checks ACLs, labels items untrusted, caps them, and runs the context guards before the model sees anything.
- `grounded.citations` makes an answer cite only what the run really retrieved.
- `s.memory` keeps namespaced key-value entries per tenant, principal and task.
