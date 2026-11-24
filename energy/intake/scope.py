from dataclasses import dataclass
from datetime import date

from energy.storage import DomainError, require_text


REGIONS = ('east', 'west')


@dataclass(frozen=True, slots=True)
class WarehouseScope:
    region: str

    def __post_init__(self) -> None:
        if self.region not in REGIONS:
            raise DomainError('invalid_region', f'unknown region {self.region!r}')

    def require_region(self, region: str) -> None:
        if region != self.region:
            raise DomainError('wrong_region', f'{region!r} does not match warehouse {self.region}')

    def qualify(self, kind: str, number: str) -> str:
        return f'{self.region}:{kind}:{number}'

    def require_local_reference(self, kind: str, number: str) -> None:
        require_text(number, f'{kind} number')
        region, _, _ = number.partition(':')
        if region in REGIONS and number.startswith(f'{region}:{kind}:'):
            self.require_region(region)


def normalize_business_day(value: str) -> str:
    if not isinstance(value, str):
        raise DomainError('invalid_day', 'business day must be YYYY-MM-DD')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise DomainError('invalid_day', f'invalid business day {value!r}') from error
    if parsed.isoformat() != value:
        raise DomainError('invalid_day', 'business day must be YYYY-MM-DD')
    return value
