# harnessweaver-sidecar

`harnessd`, the [HarnessWeaver](../../README.md) sidecar. It serves the Python core over HTTP/JSON so apps in any language can use the same spec, guards, routing, policy and tool governance.

```bash
uv add harnessweaver-sidecar
harnessd --port 7070          # binds 127.0.0.1 by default (RULES S6)
```

> Status: package skeleton. Only `GET /v1/health` is implemented so far.
