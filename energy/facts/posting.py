from uuid import uuid4

from energy.facts.warehouse import RegionalWarehouse
from energy.facts.repository import FactReceipt
from energy.storage import DomainError, require_text
from energy.versions.handoff import (
    GATE_OPEN,
    GATE_PENDING,
    GATE_RETIRED,
    DeliveryUnavailable,
    MessageRejected,
    PostEligibilityReply,
    PostEligibilityRequest,
    ReleaseAck,
    ReleaseNotice,
    RetireAck,
    RetireNotice,
    ScopeCheckReply,
    ScopeCheckRequest,
)


def require_post_eligibility(warehouse: RegionalWarehouse, region: str, request_number: str,
                             preview, exchange) -> None:
    """Prove, just before a fresh first posting, that the version is still open."""
    if not preview.retirable:
        return
    local = warehouse.gate.gate_state(preview.version_number)
    if local == GATE_RETIRED:
        raise DomainError('version_retired', f'version {preview.version_number} is retired')
    if local == GATE_PENDING:
        raise DomainError('retirement_pending',
                          f'version {preview.version_number} has a retirement pending')
    if exchange is None:
        raise DomainError('retirement_pending',
                          f'version {preview.version_number} needs a retirement check')
    request = PostEligibilityRequest(region, preview.version_number, request_number,
                                     preview.number, uuid4().hex)
    try:
        reply = exchange('catalog', request)
    except DeliveryUnavailable as error:
        raise DomainError('retirement_pending',
                          'the retirement check could not be answered') from error
    if not isinstance(reply, PostEligibilityReply) or reply.request != request:
        raise DomainError('retirement_pending', 'no usable eligibility reply')
    if reply.state == GATE_RETIRED:
        raise DomainError('version_retired', f'version {preview.version_number} is retired')
    if reply.state != GATE_OPEN:
        raise DomainError('retirement_pending',
                          f'version {preview.version_number} has a retirement pending')


def post_usage(warehouse: RegionalWarehouse, region: str, request_number: str,
               preview_number: str, *, exchange=None) -> FactReceipt:
    warehouse.scope.require_region(region)
    warehouse.scope.require_local_reference('preview', preview_number)
    require_text(request_number, 'posting request number')

    # A committed request replays its receipt locally, whatever has happened
    # since to the fact or the version.
    previous = warehouse.facts.get_post_receipt(request_number)
    if previous is not None:
        if previous.fact.preview.number != preview_number:
            raise DomainError('conflict', f'post request {request_number} is already bound')
        return previous

    preview = warehouse.previews.find_by_number(preview_number)
    if preview is None:
        raise DomainError('unknown_preview', f'unknown preview {preview_number}')

    require_post_eligibility(warehouse, region, request_number, preview, exchange)
    return warehouse.facts.commit_post(request_number, preview_number)


def handle_warehouse_message(warehouse: RegionalWarehouse, message):
    """Answer one message addressed to this warehouse.

    ``ScopeCheckRequest`` installs the pending hold and reads this warehouse's
    un-reversed facts of one version in a single local transaction.
    ``RetireNotice`` makes that hold permanent; ``ReleaseNotice`` lifts it.
    A message for another region or another case can never match the sender's
    request, so it does not advance any decision.
    """
    if isinstance(message, ScopeCheckRequest):
        if message.region != warehouse.scope.region:
            raise MessageRejected(
                f'message for {message.region} reached {warehouse.scope.region}')
        facts = warehouse.scope_check(message.retirement_number, message.version_number)
        return ScopeCheckReply(
            request=message,
            responder=warehouse.scope.region,
            fact_numbers=tuple(fact.fact_number for fact in facts),
        )
    if isinstance(message, RetireNotice):
        if message.region != warehouse.scope.region:
            raise MessageRejected(
                f'message for {message.region} reached {warehouse.scope.region}')
        warehouse.settle_hold(message.retirement_number, message.version_number, 'retired')
        return RetireAck(message)
    if isinstance(message, ReleaseNotice):
        if message.region != warehouse.scope.region:
            raise MessageRejected(
                f'message for {message.region} reached {warehouse.scope.region}')
        warehouse.settle_hold(message.retirement_number, message.version_number, 'released')
        return ReleaseAck(message)
    raise MessageRejected(f'unsupported warehouse message {type(message).__name__}')
