# Security policy

HarnessWeaver puts controls around AI applications, so a flaw in it can weaken every app that relies on it. Thank you for reporting one responsibly.

## Reporting a vulnerability

**Please don't open a public issue.** Report it privately through GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**, or go to <https://github.com/Wise-DreamerZ/HarnessWeaver/security/advisories/new>.

Please include:

- what is affected (package and version, or commit), and in which configuration (the relevant part of the spec);
- what an attacker can do, and the steps to reproduce it, ideally as an offline test;
- any fix or mitigation you have in mind.

You will get an acknowledgement, and updates as the report is investigated and fixed. We will agree on a disclosure date with you, and credit you in the advisory unless you prefer otherwise.

## Supported versions

The latest two minor versions of each package get security fixes, as described in [Versioning](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/deployment/versions.md).

## Scope

In scope: the packages in this repository (the `harnessweaver` core, `harnessweaver-cli`, `harnessweaver-sidecar` and its container image, the first-party plugins, `@harnessweaver/core` and `@harnessweaver/ai-sdk`), and the configurations they generate (gateway configs, the local dev stack).

Especially relevant are ways to:

- run a tool, a model call or a run outside the controls its spec declares (a bypassed guard, policy rule, budget, approval or lock);
- make a probabilistic component grant something (RULES R3);
- get raw prompts, outputs, tool arguments or results into logs, spans or traces before redaction (R9);
- reach harnessd without its token, or make it act for a principal the client didn't name;
- execute generated code outside its sandbox (S4);
- load a plugin that the spec or the org's `plugins.allow` doesn't permit (S8).

Out of scope: third-party plugins (report to their authors), the models and services an app connects to, and the heuristic nature of guards such as `injection.heuristic`, which is documented as cheap and easy to evade (a concrete bypass of a *deterministic* control is in scope).

## How HarnessWeaver is secured

The threat model, the invariants the framework enforces and hardening advice for deployments are in [Security](https://github.com/Wise-DreamerZ/HarnessWeaver/blob/main/docs/deployment/security.md). Supply-chain measures (RULES S5): dependencies are locked, CI actions are pinned by commit SHA, and container base images are pinned by digest.
