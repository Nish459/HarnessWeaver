"""``harnessweaver dev``: a local stack for the app, pre-wired to its spec (ADR-0039).

It writes ``.harness/dev/`` next to the spec: the LiteLLM config ``gateway
litellm`` generates, an OpenTelemetry collector config, a Docker Compose file
with LiteLLM, the collector, Langfuse and harnessd, and a ``.env`` of local
secrets. The ``.env`` is written once and then kept, so its secrets and the
values the developer fills in survive the next run; the other files are
regenerated each time. ``--up`` starts the stack.
"""

import base64
import secrets
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Annotated

import typer

from harnessweaver.core.errors import HarnessError
from harnessweaver.spec import EffectiveSpec, load_spec
from harnessweaver_cli._load import fail, spec_path
from harnessweaver_cli.gateway import gateway_tools, litellm_config, render_litellm, upstream_env
from harnessweaver_cli.spec import Env, Path_, ProfileDirs

__all__ = ["compose_file", "dev", "env_file"]

PROVIDER_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")
"""Provider keys LiteLLM reads from its environment; only the gateway holds them (S1)."""


def _token(prefix: str = "") -> str:
    return prefix + secrets.token_hex(16)


def env_file(effective: EffectiveSpec) -> str:
    """A ``.env`` for the stack: random local secrets, and empty lines for what only
    the developer knows (the provider model behind each gateway model, and the keys).

    The app's own key variable (``models.api_key_env``) gets LiteLLM's master key,
    so the app, harnessd and the gateway agree without further setup.
    """
    names = [
        entry["model_name"]
        for entry in litellm_config(effective, gateway_tools(effective))["model_list"]
    ]
    master = _token("sk-dev-")
    public, secret = _token("pk-lf-"), _token("sk-lf-")
    app_key = effective.spec.models.provider_settings().get("api_key_env", "LITELLM_API_KEY")
    lines = [
        "# Local secrets for `harnessweaver dev`, generated once. Never commit this file.",
        "#",
        "# The provider model behind each gateway model, as LiteLLM names it (provider/model):",
        *[f"{upstream_env(name)}=" for name in names],
        "# Provider keys, which only the gateway holds (S1):",
        *[f"{key}=" for key in PROVIDER_KEYS],
        "",
        f"LITELLM_MASTER_KEY={master}",
        f"{app_key}={master}",
        f"HARNESSD_TOKEN={_token()}",
        f"POSTGRES_PASSWORD={_token()}",
        f"CLICKHOUSE_PASSWORD={_token()}",
        f"REDIS_AUTH={_token()}",
        f"MINIO_ROOT_PASSWORD={_token()}",
        f"SALT={_token()}",
        f"ENCRYPTION_KEY={secrets.token_hex(32)}",
        f"NEXTAUTH_SECRET={_token()}",
        f"LANGFUSE_PUBLIC_KEY={public}",
        f"LANGFUSE_SECRET_KEY={secret}",
        f"LANGFUSE_OTLP_AUTH={base64.b64encode(f'{public}:{secret}'.encode()).decode()}",
        "LANGFUSE_USER_EMAIL=dev@example.com",
        f"LANGFUSE_USER_PASSWORD={_token()}",
    ]
    return "\n".join(lines) + "\n"


def compose_file(spec: Path, env: str | None, profile_dirs: list[Path]) -> str:
    """The Compose file, for this spec and overlay. Each ``--profile-dir`` folder is
    mounted read-only into harnessd's container and put on its profile path, so it
    loads the spec as the developer's machine does."""
    mounts = [f"/profiles/{index}" for index in range(len(profile_dirs))]
    volumes = "".join(
        f"      - {folder.resolve()}:{mount}:ro\n"
        for folder, mount in zip(profile_dirs, mounts, strict=True)
    )
    return (
        _template("compose.yaml")
        .replace("__spec__", spec.name)
        .replace("__env__", env or "")
        .replace("__profile_path__", ":".join(mounts))
        .replace("__profile_volumes__", volumes)
    )


def _template(name: str) -> str:
    return (
        resources.files("harnessweaver_cli")
        .joinpath("templates", "_dev", name)
        .read_text(encoding="utf-8")
    )


def dev(
    path: Path_ = None,
    env: Env = None,
    profile_dir: ProfileDirs = None,
    up: Annotated[bool, typer.Option("--up", help="Start it: docker compose up -d.")] = False,
) -> None:
    """Write a local stack: LiteLLM (from the spec), an OTel collector, Langfuse and harnessd."""
    found = spec_path(path)
    try:
        effective = load_spec(found, env=env, profile_dirs=profile_dir or [])
        litellm = render_litellm(effective)
    except HarnessError as exc:
        raise fail(exc) from None
    directory = found.resolve().parent / ".harness" / "dev"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".gitignore").write_text("*\n", encoding="utf-8")  # nothing here is committed
    (directory / "litellm.yaml").write_text(litellm, encoding="utf-8")
    (directory / "otel-collector.yaml").write_text(_template("otel-collector.yaml"), "utf-8")
    (directory / "compose.yaml").write_text(compose_file(found, env, profile_dir or []), "utf-8")
    secrets_file = directory / ".env"
    if not secrets_file.exists():
        secrets_file.write_text(env_file(effective), encoding="utf-8")
        typer.echo(f"wrote {secrets_file}: fill in the provider models and keys")
    typer.echo(f"wrote the dev stack to {directory}")
    if not up:
        typer.echo(
            f"start it with: harnessweaver dev --up  (or docker compose up -d in {directory})"
        )
        return
    docker = shutil.which("docker")
    if docker is None:
        raise fail("docker isn't installed; install Docker to start the stack")
    done = subprocess.run([docker, "compose", "up", "-d"], cwd=directory, check=False)
    if done.returncode != 0:
        raise typer.Exit(code=done.returncode)
    typer.echo(
        "LiteLLM http://127.0.0.1:4000, harnessd http://127.0.0.1:7070, Langfuse http://127.0.0.1:3000"
    )
