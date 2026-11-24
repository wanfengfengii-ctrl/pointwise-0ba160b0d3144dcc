"""Trusted messages exchanged between the version catalog and the two warehouses.

Callers only transport these values between the catalog, ``east`` and ``west``;
they never interpret them.  Each request names the case it belongs to plus a
per-attempt ``token``, and each reply echoes that exact request.  A delayed,
replayed, wrong-version or wrong-warehouse message therefore fails the identity
check on the receiving side and cannot move a decision.
"""

from dataclasses import dataclass


class DeliveryUnavailable(RuntimeError):
    """No usable reply was obtained for the message just delivered."""


class MessageRejected(RuntimeError):
    """A message did not belong to this receiver or was otherwise unusable."""


@dataclass(frozen=True, slots=True)
class PostEligibilityRequest:
    region: str
    version_number: str
    request_number: str
    preview_number: str
    token: str


@dataclass(frozen=True, slots=True)
class PostEligibilityReply:
    request: PostEligibilityRequest
    responder: str
    state: str


@dataclass(frozen=True, slots=True)
class ScopeCheckRequest:
    retirement_number: str
    version_number: str
    region: str
    token: str


@dataclass(frozen=True, slots=True)
class ScopeCheckReply:
    request: ScopeCheckRequest
    responder: str
    fact_numbers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetireNotice:
    retirement_number: str
    version_number: str
    region: str
    token: str


@dataclass(frozen=True, slots=True)
class RetireAck:
    notice: RetireNotice


@dataclass(frozen=True, slots=True)
class ReleaseNotice:
    retirement_number: str
    version_number: str
    region: str
    token: str


@dataclass(frozen=True, slots=True)
class ReleaseAck:
    notice: ReleaseNotice


GATE_OPEN = 'open'
GATE_PENDING = 'pending'
GATE_RETIRED = 'retired'
