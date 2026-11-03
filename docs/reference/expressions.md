# cel-lite expressions

Policy rules, business rules, routing rules and manifest approval rules are written in **cel-lite**, a subset of Google's [Common Expression Language](https://cel.dev) built into the core. It is small, side-effect free, and behaves identically in Python and TypeScript: both pass the same `expr` fixtures. Full CEL is available for policy rules as `policy: { use: cel.policy }` from `harnessweaver-cel`.

```yaml
policy:
  rules:
    - { when: "tool.name == 'refund_payment' && args.amount_usd > 1000", effect: deny }
    - { when: "principal.roles.exists(r, r == 'contractor')", effect: deny }
validation:
  rules:
    - { when: "size(output.summary) > 200", message: "keep the summary under 200 characters" }
routing:
  intent:
    cascade:
      - { use: rules, rules: [{ when: "text.matches('refund|money back')", choice: refund }] }
```

**Every expression is compiled when the spec loads**, against the variables its place allows, so a typo, an unknown function or an unknown variable fails at load, not in the middle of a run (RULES R4).

## Where expressions appear

| Place | Variables | `when` means |
| --- | --- | --- |
| `policy.rules[].when` (hook `tool.before`) | `principal`, `tenant`, `task`, `tool`, `args`, `labels` | The rule applies |
| `policy.rules[].when` (hook `run.start`) | `principal`, `tenant`, `task`, `labels` | The rule applies |
| `validation.rules[].when` | `output`, `input`, `task` | The output **breaks** the rule |
| Manifest `approval.when` | The policy names, as at `tool.before` | A human must approve the call |
| `rules` routing stage, `rules[].when` | `text`, `state`, `options`, `router` | The rule's `choice` wins |

The variables hold JSON-shaped data:

| Variable | Shape |
| --- | --- |
| `principal` | `{id, roles, attrs}` |
| `tenant` | string |
| `task` | the task name, or null |
| `tool` | `{name, version, side_effect, risk, egress, data_access, scopes}` |
| `args` | the call's arguments |
| `labels` | `{data_class, untrusted_seen, private_seen, sources}` |
| `output`, `input` | the candidate output and the run's input, as JSON |
| `text`, `state`, `options`, `router` | the routing request |

## Values and literals

| Type | Literals |
| --- | --- |
| `int` | `42`, `-7`, `0x1F`; 64-bit signed |
| `double` | `1.5`, `2e3`, `1.0` |
| `string` | `'single'` or `"double"` quoted, with escapes such as `\t`, `\n`, `\'`; raw strings `r'\d+'` keep backslashes |
| `bool` | `true`, `false` |
| `null` | `null` |
| `list` | `[1, 'two', true]` (a trailing comma is allowed) |
| `map` | `{'a': 1, 'b': [2]}` |

Comments run from `//` to the end of the line. Triple-quoted strings, unsigned literals (`1u`) and bytes aren't supported.

## Access

| Expression | Value |
| --- | --- |
| `principal.id` | A field |
| `items[1]`, `m['k']` | A list index or a map key |
| `has(a.b)` | Whether the field `b` exists (even if it is null), without failing |
| `has(a.c) ? a.c : 'default'` | A default for a missing field |

A missing field, an index out of range, a negative or non-integer list index, and an unknown variable are evaluation errors. Use `has()` to test first.

## Operators

| Operators | Notes |
| --- | --- |
| `+ - * / %` | Integer division truncates toward zero (`-7 / 2` is `-3`), and `%` follows it (`-7 % 3` is `-1`). Division or modulo by zero, `%` on doubles and integer overflow are errors. `+` also joins strings and lists |
| `== != < <= > >=` | Numbers compare by value across int and double (`1 == 1.0`). Strings and booleans compare with their own kind (`false < true`). Lists and maps compare deeply; map key order doesn't matter. Comparing different kinds with `<` is an error; with `==` it is simply false |
| `in` | Membership in a list, or key membership in a map: `'b' in ['a', 'b']`, `'a' in {'a': 1}` |
| `! && \|\|` | Boolean only. `&&` and `\|\|` absorb errors as CEL does: `x.missing \|\| true` is `true`, `x.missing && false` is `false` |
| `? :` | The condition must be a boolean; only the chosen branch is evaluated |

## Functions and methods

| Function | Example | Value |
| --- | --- | --- |
| `size(x)`, `x.size()` | `size('hello')`, `size([1, 2, 3])` | Characters (code points, so an accented letter counts once), list items or map entries |
| `s.startsWith(p)`, `s.endsWith(p)`, `s.contains(p)` | `'payments:refund'.startsWith('payments:')` | Substring tests |
| `s.matches(re)`, `matches(s, re)` | `'order-123'.matches('[0-9]+')` | Whether the regular expression matches *anywhere* in the string (anchor with `^` and `$`) |
| `int(x)` | `int(3.9)` is `3`, `int('-42')` is `-42` | Truncates doubles; parses strings; a bool is an error |
| `double(x)` | `double(2)` is `2.0`, `double('2.5')` | |
| `string(x)` | `string(42)` is `'42'`, `string(1.5)` is `'1.5'`, `string(100.0)` is `'100'` | Doubles print like JavaScript's `Number#toString` |

Regular expressions use the syntax Python and JavaScript share: character classes, groups, alternation, quantifiers and anchors. Avoid inline flags such as `(?i)`, which JavaScript doesn't accept; spell out both cases instead (`'[Rr]efund'`, or `'(down|Down)'` as Example 02 does).

## Macros

| Macro | Example | Value |
| --- | --- | --- |
| `list.exists(x, p)` | `principal.roles.exists(r, r == 'finance')` | Some item makes `p` true |
| `list.all(x, p)` | `[1, 2, 3].all(x, x > 0)` | Every item does (true for an empty list) |
| `list.exists_one(x, p)` | `[1, 2, 3].exists_one(x, x == 2)` | Exactly one item does |
| `list.map(x, e)` | `[1, 2, 3].map(x, x * 10)` | Each item transformed |
| `list.filter(x, p)` | `[1, 2, 3, 4].filter(x, x % 2 == 0)` | The items that make `p` true |

On a map, the macros range over its keys. The loop variable shadows a variable of the same name. `exists` and `all` absorb errors like `||` and `&&`: an item that fails doesn't matter if another settles the answer.

## Errors

| Kind | When | Error |
| --- | --- | --- |
| Syntax | The expression is malformed, uses a reserved word (`if`, `for`, ...), calls an unknown function or method, gives a function the wrong number of arguments, or (where variables are declared) names an unknown variable | `ExpressionSyntaxError`, raised **when the spec loads** |
| Evaluation | A missing field, a type mismatch, division by zero, an overflow, an invalid regular expression | `ExpressionEvalError`, at run time |

What an evaluation error means depends on where it happens, and always fails safe:

- A policy rule that can't be evaluated never loosens a decision: `deny` and `require_approval` rules count as matching, `allow` rules don't.
- A business rule that can't be evaluated counts as broken (a repair is asked for).
- A manifest `approval.when` that can't be evaluated requires approval.
- A routing rule that can't be evaluated doesn't match.

Expressions are limited to 10,000 characters and 64 levels of nesting.

## Differences from CEL

cel-lite is close enough to CEL that rules move to a full CEL engine unchanged, except for three deliberate differences that keep Python and TypeScript identical:

1. Mixed int and double arithmetic gives a double (`1 + 0.5` is `1.5`) instead of an error.
2. Integral numbers in *data* are treated as ints, because JSON has no separate integer type in JavaScript (`x / 2` with `x` set to `4.0` is `2`).
3. `string(double)` prints like JavaScript's `Number#toString`.

Full CEL (`cel.policy`) is stricter on the first point and treats such an error as an unevaluable rule.
