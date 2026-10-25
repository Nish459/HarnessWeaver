# ADR-0039: Gateway configs and the local dev stack

**Status:** Accepted

## Decision

`harnessweaver gateway litellm` writes a LiteLLM Proxy config from the spec (gateway models from the aliases and default, `model_group_alias`, retries, a timeout from the longest deadline, message logging off unless content capture is on, the `otel` callback, and a default-on `tool_permission` guardrail that denies by default), and `gateway mcp` writes a neutral `ToolAllowList`. A tool is allowed at a gateway only when its manifest needs no run context; one that can need approval, has egress, is limited to some tenants, has rate limits, is disabled or has a mismatched pin is withheld, with the reason. The provider model behind each gateway model comes from `HARNESSWEAVER_UPSTREAM_<NAME>`. Manifests gain `server` for `transport: mcp`. `harnessweaver dev` writes a Compose stack (LiteLLM, an OTel collector, Langfuse, harnessd) into `.harness/dev/`, with digest-pinned images, ports on 127.0.0.1, harnessd and the collector in LiteLLM's network namespace, and secrets generated once into `.env`.

## Why

A gateway can't wait for a person, track what a run has read, or tell tenants apart, so allowing such a tool there would skip a control the spec requires (R1, S3); withholding fails closed and says why. Which provider serves a model is the gateway owner's choice, not the app's. One network namespace lets the spec's `localhost` URLs work on the developer's machine and in the containers without a separate overlay. Langfuse's self-hosted v4 needs its six services.
