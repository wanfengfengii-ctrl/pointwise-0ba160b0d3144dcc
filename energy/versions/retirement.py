"""Version retirement.

The catalog accepts one retirement per exact version at a time.  It asks each
warehouse, under a local hold, which of its facts of that version are still
un-reversed: any such fact blocks retirement, none of them lets it succeed.
Both warehouses take part in the same decision.

The decision is recorded in the catalog *before* any notice is delivered, so a
reversal that happens after the decision cannot turn a blocked case into a
retired one, and a replay can never re-evaluate it.  The case settles only once
both warehouses have acknowledged the notices; until then it stays ``pending``
and can be advanced again with the same number and the same version.
"""

from uuid import uuid4

from energy.storage import DomainError, require_text
from energy.versions.handoff import (
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
from energy.versions.repository import VersionRepository

REGIONS = ('east', 'west')


def _ask_warehouse(exchange, region, request):
    try:
        reply = exchange(region, request)
    except DeliveryUnavailable:
        raise
    except Exception as error:
        raise DeliveryUnavailable(f'{region} did not answer') from error
    if not isinstance(reply, ScopeCheckReply) or reply.request != request:
        raise DeliveryUnavailable(f'{region} gave no usable reply')
    if reply.responder != region:
        raise DeliveryUnavailable(f'reply came from {reply.responder}, not {region}')
    return reply


def _notify(exchange, region, notice, ack_type):
    try:
        reply = exchange(region, notice)
    except DeliveryUnavailable:
        raise
    except Exception as error:
        raise DeliveryUnavailable(f'{region} did not acknowledge') from error
    if not isinstance(reply, ack_type) or reply.notice != notice:
        raise DeliveryUnavailable(f'{region} did not acknowledge')
    return reply


def _token(retirement_number, version_number, region, kind):
    return f'{retirement_number}|{version_number}|{region}|{kind}|{uuid4().hex}'


def _deliver_decision(versions, record, exchange):
    if record.decision == 'blocked':
        for region in REGIONS:
            _notify(exchange, region,
                    ReleaseNotice(record.retirement_number, record.version_number, region,
                                  _token(record.retirement_number, record.version_number,
                                         region, 'release')),
                    ReleaseAck)
    else:
        for region in REGIONS:
            _notify(exchange, region,
                    RetireNotice(record.retirement_number, record.version_number, region,
                                 _token(record.retirement_number, record.version_number,
                                        region, 'retire')),
                    RetireAck)
    return versions.settle_retirement(record.retirement_number)


def retire_version(versions: VersionRepository, retirement_number: str,
                   version_number: str, exchange):
    require_text(retirement_number, 'retirement number')
    require_text(version_number, 'version number')

    existing = versions.find_retirement(retirement_number)
    if existing is not None and existing.version_number != version_number:
        raise DomainError(
            'conflict',
            f'retirement {retirement_number} is bound to {existing.version_number}',
        )

    version = versions.find_frozen(version_number)
    if version is None:
        raise DomainError('unknown_version', f'unknown version {version_number}')
    if not version.retirable:
        raise DomainError('not_retirable', f'version {version_number} is not retirable')

    if existing is not None:
        if existing.status in ('blocked', 'retired'):
            return existing
        if existing.decision is not None:
            return _deliver_decision(versions, existing, exchange)
    else:
        versions.begin_retirement(retirement_number, version_number)

    answers = {}
    for region in REGIONS:
        request = ScopeCheckRequest(retirement_number, version_number, region,
                                    _token(retirement_number, version_number, region, 'check'))
        answers[region] = _ask_warehouse(exchange, region, request)

    blocker = None
    for region in REGIONS:
        facts = answers[region].fact_numbers
        if facts:
            blocker = (region, facts[0])
            break

    record = versions.record_decision(
        retirement_number, 'blocked' if blocker is not None else 'retired', blocker)
    return _deliver_decision(versions, record, exchange)


def get_retirement(versions: VersionRepository, retirement_number: str):
    """Read a retirement the catalog already saved; no warehouse is contacted."""
    require_text(retirement_number, 'retirement number')
    return versions.find_retirement(retirement_number)


def handle_catalog_message(versions: VersionRepository, message):
    """Answer a message addressed to the version catalog."""
    if isinstance(message, PostEligibilityRequest):
        version = versions.find_frozen(message.version_number)
        if version is None:
            raise MessageRejected(f'unknown version {message.version_number}')
        state = versions.gate_state(message.version_number) if version.retirable else 'open'
        return PostEligibilityReply(request=message, responder='catalog', state=state)
    raise MessageRejected(f'unsupported catalog message {type(message).__name__}')


__all__ = [
    'DeliveryUnavailable',
    'get_retirement',
    'handle_catalog_message',
    'retire_version',
]
