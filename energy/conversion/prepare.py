from collections.abc import Callable

from energy.conversion.quantities import convert_reading
from energy.conversion.repository import Preview, PreviewLine
from energy.conversion.units import require_matching_unit
from energy.facts.warehouse import RegionalWarehouse
from energy.intake.read_batch import read_batch
from energy.storage import DomainError, require_text
from energy.versions.messages import VersionLookupReply, VersionLookupRequest


def prepare_usage(
    warehouse: RegionalWarehouse, receipt_number: str, version_number: str,
    lookup: Callable[[VersionLookupRequest], VersionLookupReply],
) -> Preview:
    require_text(version_number, 'version number')
    batch = read_batch(warehouse, receipt_number)
    previous = warehouse.previews.find_by_binding(receipt_number, version_number)
    if previous is not None:
        return previous

    request = VersionLookupRequest(warehouse.scope.region, version_number)
    reply = lookup(request)
    if not isinstance(reply, VersionLookupReply) or reply.request != request:
        raise DomainError('wrong_reply', 'version reply does not match the request')
    if reply.version is None:
        raise DomainError('unknown_version', f'unknown version {version_number}')
    if reply.version.number != version_number:
        raise DomainError('wrong_reply', 'version reply contains a different frozen version')

    rules = {rule.device: rule for rule in reply.version.rules}
    lines = []
    for position, source in enumerate(batch.rows):
        rule = rules.get(source.device)
        if rule is None:
            raise DomainError('missing_rule', f'no rule for {source.device} in {version_number}')
        require_matching_unit(source, rule)
        coefficient = rule.coefficient
        lines.append(PreviewLine(position, source, coefficient, rule.source,
                                 convert_reading(source.reading, coefficient)))
    return warehouse.previews.store_once(batch.receipt, version_number, tuple(lines),
                                         retirable=reply.version.retirable)
