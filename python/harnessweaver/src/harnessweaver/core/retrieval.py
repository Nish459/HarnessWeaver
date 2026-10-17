"""Retrieved-context contracts carried by ``context.after`` events."""

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from harnessweaver.core.envelope import Principal

__all__ = ["Acl", "ContextItem"]


class Acl(BaseModel):
    """Who may see a retrieved item. An empty list means "no restriction" for that part."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenants: tuple[str, ...] = ()
    principals: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()

    def allows(self, tenant: str, principal: Principal) -> bool:
        """Return whether ``principal`` in ``tenant`` may see the item.

        The tenant must match when tenants are listed. When principals or roles are
        listed, the principal must be named or hold one of the roles.
        """
        if self.tenants and tenant not in self.tenants:
            return False
        if not self.principals and not self.roles:
            return True
        return principal.id in self.principals or any(principal.has_role(r) for r in self.roles)


class ContextItem(BaseModel):
    """One retrieved document or memory entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    content: str
    source: str = Field(description="Where the item came from, e.g. the context provider name.")
    score: float | None = None
    untrusted: bool = True
    acl: Acl | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
