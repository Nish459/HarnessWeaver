"""The plugin contract, discovery and the per-harness registry (DESIGNS No. 13, ADR-0015)."""

import sys
from importlib.metadata import EntryPoint
from typing import Any

import anyio
import pytest
from pydantic import BaseModel

import harnessweaver as hw
from harnessweaver.core.decisions import Decision, DecisionRequest
from harnessweaver.core.plugins import (
    ENTRY_POINT_GROUP,
    ProviderInfo,
    adapter_info,
    provider_info,
    runner_info,
)
from harnessweaver.core.registry import PluginCatalog, PluginSource, Registry
from harnessweaver.core.registry import catalog as catalog_module
from harnessweaver.core.semver import VersionRange
from harnessweaver.errors import (
    IncompatibleContract,
    PluginConflict,
    PluginNotAllowed,
    SpecError,
    UnknownProvider,
)


class Settings(BaseModel):
    endpoint: str


@hw.provider(
    port="Guardrail", name="pii", config=Settings, deterministic=True, latency_class="fast"
)
class Pii:
    def __init__(self, config: Settings) -> None:
        self.config = config

    async def check(self, content: str, env: hw.Envelope) -> hw.GuardResult:
        return hw.GuardResult.allow()


@hw.decider("vip")
async def vip(request: DecisionRequest) -> Decision:
    return Decision.abstain()


@hw.middleware(hooks=["tool.before"], fail_mode="closed", timeout="2s")
async def no_weekend(event: Any, env: hw.Envelope) -> hw.Outcome | None:
    return hw.Suspend(reason="weekend") if env.clock.is_weekend() else None


@hw.runner("flow", reaches=["run.start", "run.end"])
class Flow:
    async def execute(self, ctx: Any, input: Any, resume: Any) -> Any:
        return input


@hw.adapter("client", wraps=["acme.Client"], reaches=["model.before", "model.after"])
class ClientAdapter:
    pass


@hw.provider(port="Guardrail", name="acme.borrowed")
class Borrowed:
    """Claims a name in someone else's namespace."""


PLUGINS: dict[str, hw.Plugin] = {
    "acme": hw.Plugin(
        namespace="acme",
        version="1.2.0",
        providers=[Pii, vip],
        middleware=[no_weekend],
        runners=[Flow],
        adapters=[ClientAdapter],
        profiles={"baseline": "profiles/baseline.yaml"},
        templates={"rag": "templates/rag"},
    ),
    "old": hw.Plugin(namespace="old", version="0.9.0", contract=">=0.1,<1"),
    "other": hw.Plugin(namespace="other", version="1.0.0", providers=[Borrowed]),
}


def importer(target: str) -> object:
    module, _, attribute = target.partition(":")
    if module == "broken":
        raise ImportError("nope")
    if attribute == "plugin":
        return PLUGINS[module]
    return "not a plugin"


def catalog(*sources: PluginSource) -> PluginCatalog:
    return PluginCatalog(sources, importer=importer)


def source(namespace: str, target: str | None = None, dist: str | None = None) -> PluginSource:
    return PluginSource(namespace, target or f"{namespace}:plugin", "entry_point", dist)


def test_decorators_attach_metadata() -> None:
    info = provider_info(Pii)
    assert (info.port, info.name, info.deterministic, info.latency_class) == (
        "Guardrail",
        "pii",
        True,
        "fast",
    )
    assert info.contract.contains(hw.CONTRACT_VERSION)
    built = info.build({"endpoint": "http://pii.internal"})
    assert built.config.endpoint == "http://pii.internal"
    assert provider_info(vip).build() is vip
    assert runner_info(Flow).reaches == {hw.HookPoint.RUN_START, hw.HookPoint.RUN_END}
    assert adapter_info(ClientAdapter).wraps == ("acme.Client",)
    assert no_weekend.name == "no_weekend"
    assert no_weekend.timeout is not None
    assert no_weekend.timeout.total_seconds() == 2
    names = sorted(c.name for c in PLUGINS["acme"].contributions())
    assert names == ["acme.client", "acme.flow", "acme.no_weekend", "acme.pii", "acme.vip"]


@pytest.mark.anyio
async def test_function_middleware_can_be_called_directly() -> None:
    env = hw.Envelope.new(tenant="t", principal="p", clock=hw.FakeClock())
    event = hw.ToolCallEvent(call=hw.ToolCall(id="c", name="x"), tool=hw.ToolInfo(name="x"))
    assert await no_weekend(event, env) is None
    assert no_weekend.build() is no_weekend.target


def test_decorator_misuse() -> None:
    with pytest.raises(ValueError, match="unknown port"):
        hw.provider(port="Nope", name="x")
    for planned in ("DatasetStore", "ErrorClassifier", "ToolRegistry", "Validator"):
        # Planned ports aren't ports yet: nothing would ever call their providers.
        with pytest.raises(ValueError, match="unknown port"):
            hw.provider(port=planned, name="x")
    # The harness always builds its own governor, so a spec can't swap out the
    # checks that enforce the baseline (R1).
    with pytest.raises(ValueError, match="unknown port"):
        hw.provider(port="ToolGovernor", name="x")
    with pytest.raises(ValueError, match="latency_class"):
        hw.provider(port="Guardrail", name="x", latency_class="instant")
    with pytest.raises(ValueError, match="R3"):
        hw.provider(port="PolicyEngine", name="x")
    with pytest.raises(ValueError, match="invalid name"):
        hw.provider(port="Guardrail", name="Bad Name")
    with pytest.raises(ValueError, match="contract"):
        hw.provider(port="Guardrail", name="x", contract="not a range")
    with pytest.raises(TypeError):
        hw.provider(port="Guardrail", name="x")(len)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        hw.decider("x")(lambda request: None)  # type: ignore[arg-type,return-value]
    with pytest.raises(TypeError):
        hw.runner("x", reaches=[])(len)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        hw.adapter("x", wraps=[], reaches=[])(len)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="decorated"):
        provider_info(object())
    with pytest.raises(TypeError, match="decorated"):
        runner_info(object())
    with pytest.raises(TypeError, match="decorated"):
        adapter_info(object())


def test_middleware_decorator_misuse() -> None:
    async def handler(event: Any, env: hw.Envelope) -> None:
        return None

    with pytest.raises(ValueError, match="baseline"):
        hw.middleware(hooks=["run.start"], fail_mode="closed", band="baseline")(handler)
    with pytest.raises(ValueError, match="unknown hook"):
        hw.middleware(hooks=["tool.during"], fail_mode="closed")(handler)
    with pytest.raises(ValueError, match="at least one"):
        hw.middleware(hooks=[], fail_mode="closed")(handler)
    with pytest.raises(ValueError, match="fail_mode"):
        hw.middleware(hooks=["run.start"], fail_mode="sometimes")(handler)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="positive"):
        hw.middleware(hooks=["run.start"], fail_mode="open", timeout=0)(handler)
    with pytest.raises(ValueError, match="invalid middleware name"):
        hw.middleware(hooks=["run.start"], fail_mode="open", name="Bad")(handler)
    with pytest.raises(TypeError, match="async"):
        hw.middleware(hooks=["run.start"], fail_mode="open")(lambda event, env: None)
    with pytest.raises(TypeError, match="class middleware"):
        hw.middleware(hooks=["run.start"], fail_mode="open", config=Settings)(handler)


def test_class_middleware_builds_from_settings() -> None:
    @hw.middleware(hooks=["run.start"], fail_mode="closed", config=Settings)
    class RateLimit:
        def __init__(self, config: Settings) -> None:
            self.config = config

        async def __call__(self, event: Any, env: hw.Envelope) -> None:
            return None

    @hw.middleware(hooks=["run.start"], fail_mode="closed")
    class NoSettings:
        async def __call__(self, event: Any, env: hw.Envelope) -> None:
            return None

    assert RateLimit.name == "rate_limit"
    assert RateLimit.build({"endpoint": "x"}).config.endpoint == "x"  # type: ignore[attr-defined]
    with pytest.raises(SpecError, match="endpoint"):
        RateLimit.build({})
    with pytest.raises(SpecError, match="takes no settings"):
        NoSettings.build({"x": 1})
    with pytest.raises(SpecError, match="takes no settings"):
        no_weekend.build({"x": 1})
    env = hw.Envelope.new(tenant="t", principal="p")
    with pytest.raises(TypeError, match="build"):
        anyio.run(RateLimit.__call__, hw.RunStartEvent(), env)


def test_plugin_validation() -> None:
    with pytest.raises(ValueError, match="namespace"):
        hw.Plugin(namespace="Acme", version="1.0.0")
    with pytest.raises(ValueError, match="version"):
        hw.Plugin(namespace="acme", version="one")
    with pytest.raises(ValueError, match="contract"):
        hw.Plugin(namespace="acme", version="1.0.0", contract="??")
    with pytest.raises(TypeError, match="middleware"):
        hw.Plugin(namespace="acme", version="1.0.0", middleware=[vip])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="decorated"):
        hw.Plugin(namespace="acme", version="1.0.0", providers=[Settings])
    with pytest.raises(ValueError, match="invalid name"):
        hw.Plugin(namespace="acme", version="1.0.0", profiles={"Bad": "x.yaml"})


def test_the_catalog_imports_lazily_and_once() -> None:
    calls: list[str] = []

    def counting(target: str) -> object:
        calls.append(target)
        return importer(target)

    found = PluginCatalog([source("acme")], importer=counting)
    assert calls == []
    first = found.load("acme")
    assert found.load("acme") is first
    assert calls == ["acme:plugin"]
    assert first.plugin.namespace == "acme"


def test_catalog_failures() -> None:
    with pytest.raises(UnknownProvider, match="no installed plugin"):
        catalog().load("acme")
    with pytest.raises(PluginConflict, match="several"):
        catalog(source("acme", dist="a"), source("acme", dist="b")).load("acme")
    with pytest.raises(PluginConflict, match="must match"):
        catalog(source("acme", "other:plugin")).load("acme")
    with pytest.raises(SpecError, match="can't import"):
        catalog(source("acme", "broken:plugin")).load("acme")
    with pytest.raises(SpecError, match=r"not a harnessweaver\.Plugin"):
        catalog(source("acme", "acme:thing")).load("acme")


def test_catalog_problems_report_shared_and_reserved_namespaces() -> None:
    found = catalog(source("pii"), source("acme", dist="a"), source("acme", dist="b"))
    assert found.problems() == [
        "namespace 'acme' is claimed by several plugins: a, b",
        "namespace 'pii' is reserved for the built-in plugin",
    ]
    assert list(found.sources()) == ["acme", "pii"]


def test_local_plugins() -> None:
    found = catalog(source("other"))
    local = found.load_local("acme:plugin")
    assert local.source.origin == "local"
    assert local.source.namespace == "acme"
    with pytest.raises(PluginConflict, match="already claims"):
        found.load_local("other:plugin")
    reserved = PluginCatalog(importer=lambda target: hw.Plugin(namespace="pii", version="1.0.0"))
    with pytest.raises(PluginConflict, match="reserved"):
        reserved.load_local("x")
    with pytest.raises(PluginConflict, match=r"two plugins\.local"):
        Registry(catalog(), local=["acme:plugin", "acme:plugin"])


def test_registry_resolves_names_by_namespace() -> None:
    registry = Registry(catalog(source("acme")))
    assert registry.plugins() == []
    assert registry.provider("Guardrail", "acme.pii").name == "pii"
    assert registry.provider("Decider", "acme.vip").kind == "function"
    assert registry.middleware("acme.no_weekend") is no_weekend
    assert registry.runner("acme.flow").name == "flow"
    assert [a.name for a in registry.adapters()] == ["client"]
    assert registry.runner("direct").name == "direct"
    assert registry.provider("StateStore", "memory").name == "memory"
    assert [p.plugin.namespace for p in registry.plugins()] == ["acme", "harnessweaver"]
    assert registry.names("middleware") == ["acme.no_weekend"]
    assert registry.catalog is not None
    with pytest.raises(UnknownProvider, match=r"it provides: acme\.pii"):
        registry.provider("Guardrail", "acme.secrets")
    assert registry.provider("Guardrail", "pii.regex").deterministic
    with pytest.raises(UnknownProvider):
        registry.provider("Guardrail", "pii.presidio")


def test_registry_enforces_allow_lists_and_contracts() -> None:
    with pytest.raises(PluginNotAllowed):
        Registry(catalog(source("acme")), allow=["openai"]).middleware("acme.no_weekend")
    assert Registry(catalog(), allow=[]).runner("direct").name == "direct"
    with pytest.raises(IncompatibleContract):
        Registry(catalog(source("old"))).ensure("old")
    with pytest.raises(PluginConflict, match="outside its namespace"):
        Registry(catalog(source("other"))).ensure("other")


def test_registry_rejects_bad_contributions() -> None:
    @hw.middleware(hooks=["run.start"], fail_mode="closed", name="twice")
    async def one(event: Any, env: hw.Envelope) -> None:
        return None

    twice = hw.Plugin(namespace="dup", version="1.0.0", middleware=[one, one])
    future = hw.Plugin(namespace="future", version="1.0.0", providers=[_future_provider()])
    sneaky = hw.Plugin(namespace="sneaky", version="1.0.0", providers=[_probabilistic_policy()])
    plugins = {"dup": twice, "future": future, "sneaky": sneaky}
    found = PluginCatalog(
        [source(n) for n in plugins], importer=lambda target: plugins[target.partition(":")[0]]
    )
    with pytest.raises(PluginConflict, match="twice"):
        Registry(found).ensure("dup")
    with pytest.raises(IncompatibleContract):
        Registry(found).ensure("future")
    with pytest.raises(SpecError, match="R3"):
        Registry(found).ensure("sneaky")


def _future_provider() -> type:
    @hw.provider(port="Guardrail", name="g", contract=">=2,<3")
    class Future:
        pass

    return Future


def _probabilistic_policy() -> type:
    class Sneaky:
        pass

    info = ProviderInfo(
        port="PolicyEngine",
        name="judge",
        target=Sneaky,
        config=None,
        contract=VersionRange.parse(">=1.0,<2"),
        deterministic=False,
        latency_class="slow",
    )
    Sneaky.__harnessweaver_provider__ = info  # type: ignore[attr-defined]
    return Sneaky


def test_discover_reads_entry_point_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    point = EntryPoint(name="acme", value="acme_harness:plugin", group=ENTRY_POINT_GROUP)  # type: ignore[attr-defined]
    monkeypatch.setattr(catalog_module, "entry_points", lambda group: [point])
    found = PluginCatalog.discover()
    (acme,) = found.sources()["acme"]
    assert acme.target == "acme_harness:plugin"
    assert acme.module == "acme_harness"
    assert "acme_harness" not in sys.modules  # discovery imports nothing (S8)
    assert isinstance(PluginCatalog.default(), PluginCatalog)


GRADERS = {"exact", "contains", "regex", "schema_valid", "field_equals", "numeric_close"}
GRADERS |= {"citation_present", "guard_fired", "status", "llm_judge"}


def test_built_in_names_are_reserved() -> None:
    assert {"direct", "session", "workflow", "memory", "sqlite", "pii"} <= hw.RESERVED_NAMESPACES
    builtin = PluginCatalog().load("harnessweaver")
    assert builtin.source.origin == "builtin"
    assert {c.name for c in builtin.plugin.contributions()} == {
        "direct",
        "session",
        "workflow",
        "memory",
        "sqlite",
        "scripted",
        "regex.deny",
        "pii.regex",
        "secrets.scan",
        "injection.heuristic",
        "size.limit",
        "topic.deny",
        "llm.judge",
        "cel_lite",
        "callback",
        "console",
        "webhook",
        "email",
        "rules",
        "lexical",
        "semantic",
        "llm",
        "semantic.hashing",
        "passthrough",
        "grounded.citations",
    } | GRADERS
