from dataclasses import dataclass

from energy.intake.scope import WarehouseScope
from energy.storage import DomainError
from energy.versions.lookup import lookup_version
from energy.versions.repository import VersionRepository
from energy.versions.rules import FrozenVersion


@dataclass(frozen=True, slots=True)
class VersionLookupRequest:
    region: str
    version_number: str


@dataclass(frozen=True, slots=True)
class VersionLookupReply:
    request: VersionLookupRequest
    version: FrozenVersion | None


def handle_version_lookup(
    repository: VersionRepository, request: VersionLookupRequest
) -> VersionLookupReply:
    WarehouseScope(request.region)
    try:
        version = lookup_version(repository, request.version_number)
    except DomainError as error:
        if error.code != 'unknown_version':
            raise
        version = None
    return VersionLookupReply(request, version)
