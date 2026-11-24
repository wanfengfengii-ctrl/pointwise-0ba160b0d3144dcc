from energy.storage import DomainError, require_text
from energy.versions.repository import VersionRepository
from energy.versions.rules import FrozenVersion, VersionDraft, validate_rules


def publish_version(repository: VersionRepository, draft: VersionDraft) -> FrozenVersion:
    if not isinstance(draft, VersionDraft):
        raise DomainError('invalid_rule', 'publish_version requires a VersionDraft')
    number = require_text(draft.number, 'version number')
    return repository.save_frozen(FrozenVersion(number, validate_rules(draft.rules)))
