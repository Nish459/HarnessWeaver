# ADR-0027: Code-executing tools use transport: code

**Status:** Accepted

## Decision

Code-executing tools use `transport: code`: the code in one argument runs in the `Sandbox` the manifest names (`sandbox: monty` is short for `monty.sandbox`), with `limits` (time, memory, printed output); other transports can't name a sandbox.

## Why

The guide marks code tools only with `sandbox: monty`; a transport of its own makes it explicit that the host never runs the code (S4) and lets the load check refuse a code tool without a sandbox.
