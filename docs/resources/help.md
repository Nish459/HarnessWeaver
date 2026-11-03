# Get help

How to ask a question, report a bug or a vulnerability, and help the project.

## Star the repository

Star [HarnessWeaver on GitHub](https://github.com/Wise-DreamerZ/HarnessWeaver) so other people can find it. Watch it, with "Releases only" if you like, to hear when a version is published.

## Ask a question, or report a bug

Open an [issue on GitHub](https://github.com/Wise-DreamerZ/HarnessWeaver/issues). A good report says:

- what you ran: the command, or the smallest code and spec that show the problem;
- what you expected, and what happened instead, with the full error;
- the output of `uv run harnessweaver --version`, and `uv run harnessweaver doctor harness.yaml` when a spec is involved.

!!! warning "Never paste secrets"
    Traces and `doctor` output hold no content, so they are safe to share. Prompts, model outputs, tool arguments, API keys and personal data are not. Replace them with obviously fake values, such as `sk-test-...` and `ann@example.com`.

Before you open one, [Troubleshooting](../how-to/troubleshooting.md) explains every load error and block code, and [Debugging](../tutorial/debugging.md) shows how to find out why a run did what it did.

## Report a vulnerability

Please don't open a public issue for a security problem. The [Security policy](security.md) says how to report one privately.

## Help others

Answer an issue you know the answer to, or share an example, a plugin or a template you built. Plugins can live in your own repository under any name: [Plugins](../advanced/plugins.md) explains how.

## Contribute

Fix a bug, improve these docs, add a provider or a plugin. [Contributing](contributing.md) explains how the repository works, the rules every change follows, and how changes are reviewed.
