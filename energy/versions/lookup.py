from energy.storage import DomainError, require_text
from energy.versions.repository import VersionRepository
from energy.versions.rules import FrozenVersion


def lookup_version(repository: VersionRepository, number: str) -> FrozenVersion:
    require_text(number, 'version number')
    version = repository.find_frozen(number)
    if version is None:
        raise DomainError('unknown_version', f'unknown version {number}')
    return version
