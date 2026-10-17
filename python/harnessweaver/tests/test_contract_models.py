import pytest
from pydantic import TypeAdapter, ValidationError

import harnessweaver as hw
from harnessweaver.core.hooks import EVENT_TYPES


def test_decisions_validate_their_shape() -> None:
    assert hw.Decision.exact("billing").confidence == 1.0
    assert hw.Decision.abstain().choice is None
    with pytest.raises(ValidationError):
        hw.Decision(kind=hw.DecisionKind.EXACT)
    with pytest.raises(ValidationError):
        hw.Decision(kind=hw.DecisionKind.PROBABILISTIC, choice="x")
    with pytest.raises(ValidationError):
        hw.Decision(kind=hw.DecisionKind.ABSTAIN, choice="x")
    with pytest.raises(ValidationError):
        hw.Decision.probabilistic("x", confidence=1.5)


def test_tighten_never_loosens() -> None:
    allow, approve, deny = (
        hw.PolicyEffect.ALLOW,
        hw.PolicyEffect.REQUIRE_APPROVAL,
        hw.PolicyEffect.DENY,
    )
    assert hw.tighten(allow, approve) is approve
    assert hw.tighten(deny, allow) is deny
    assert hw.tighten(approve, allow) is approve


def test_guard_results() -> None:
    assert hw.GuardResult.allow().action is hw.GuardAction.ALLOW
    finding = hw.Finding(type="EMAIL", start=8, end=21)
    redacted = hw.GuardResult.redact("mail me <EMAIL>", findings=(finding,))
    assert redacted.content == "mail me <EMAIL>"
    assert hw.GuardResult.block("secret found").action is hw.GuardAction.BLOCK
    with pytest.raises(ValidationError):
        hw.GuardResult(action=hw.GuardAction.REDACT)


def test_messages_check_role_fields() -> None:
    call = hw.ToolCall(id="c1", name="lookup", arguments={"id": 1})
    assert hw.Message.assistant(tool_calls=(call,)).tool_calls == (call,)
    assert hw.Message.tool("c1", "ok").tool_call_id == "c1"
    with pytest.raises(ValidationError):
        hw.Message(role=hw.Role.USER, content="x", tool_calls=(call,))
    with pytest.raises(ValidationError):
        hw.Message(role=hw.Role.TOOL, content="x")
    with pytest.raises(ValidationError):
        hw.Message(role=hw.Role.USER, content="x", tool_call_id="c1")


def test_usage_adds_up() -> None:
    total = hw.Usage(input_tokens=10, output_tokens=5) + hw.Usage(input_tokens=1, output_tokens=2)
    assert (total.input_tokens, total.output_tokens, total.total_tokens) == (11, 7, 18)


def test_acl() -> None:
    alice = hw.Principal(id="alice", roles=("finance",))
    assert hw.Acl().allows("acme", alice)
    assert not hw.Acl(tenants=("globex",)).allows("acme", alice)
    assert hw.Acl(tenants=("acme",), roles=("finance",)).allows("acme", alice)
    assert hw.Acl(principals=("alice",)).allows("acme", alice)
    assert not hw.Acl(principals=("bob",), roles=("ops",)).allows("acme", alice)


def test_tool_info_flags_private_data() -> None:
    assert hw.ToolInfo(name="crm", data_access=("pii:customer",)).reads_private_data
    assert not hw.ToolInfo(name="weather").reads_private_data


def test_approval_decision_edit_needs_args() -> None:
    approver = hw.Principal(id="manager", roles=("finance",))
    hw.ApprovalDecision(approval_id="a1", decision="edit", approver=approver, edited_args={"x": 1})
    with pytest.raises(ValidationError):
        hw.ApprovalDecision(approval_id="a1", decision="edit", approver=approver)
    with pytest.raises(ValidationError):
        hw.ApprovalDecision(approval_id="a1", decision="approve", approver=approver, edited_args={})


def test_run_status_terminal_states() -> None:
    assert hw.RunStatus.COMPLETED.is_terminal
    assert not hw.RunStatus.AWAITING_APPROVAL.is_terminal


def test_every_hook_point_has_one_event_type() -> None:
    assert set(EVENT_TYPES) == set(hw.HookPoint)
    for hook, event_type in EVENT_TYPES.items():
        assert event_type.model_fields["hook"].default == hook.value


def test_hook_events_parse_by_discriminator() -> None:
    adapter = TypeAdapter[hw.HookEvent](hw.HookEvent)
    event = adapter.validate_python(
        {
            "hook": "tool.before",
            "call": {"id": "c1", "name": "refund_payment", "arguments": {"amount_usd": 250}},
            "tool": {"name": "refund_payment", "risk": "high", "side_effect": "write_external"},
        }
    )
    assert isinstance(event, hw.ToolCallEvent)
    assert event.tool.risk is hw.Risk.HIGH


def test_outcomes_parse_by_kind() -> None:
    adapter = TypeAdapter[hw.Outcome](hw.Outcome)
    assert isinstance(adapter.validate_python({"kind": "suspend", "reason": "r"}), hw.Suspend)
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "allow"})
