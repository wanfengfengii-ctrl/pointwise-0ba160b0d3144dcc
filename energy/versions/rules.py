from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from energy.storage import DomainError, require_text


@dataclass(frozen=True, slots=True)
class DeviceRule:
    device: str
    input_unit: str
    numerator: int
    denominator: int
    source: str

    @property
    def coefficient(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


@dataclass(frozen=True, slots=True)
class VersionDraft:
    number: str
    rules: tuple[DeviceRule, ...]


@dataclass(frozen=True, slots=True)
class FrozenVersion:
    number: str
    rules: tuple[DeviceRule, ...]
    retirable: bool = False


def validate_rules(rules: Iterable[DeviceRule]) -> tuple[DeviceRule, ...]:
    try:
        entries = iter(rules)
    except TypeError as error:
        raise DomainError('invalid_rule', 'rules must be iterable') from error

    by_device = {}
    for rule in entries:
        if not isinstance(rule, DeviceRule):
            raise DomainError('invalid_rule', 'each rule must be a DeviceRule')
        device = require_text(rule.device, 'device', code='invalid_rule')
        unit = require_text(rule.input_unit, 'input unit', code='invalid_rule')
        source = require_text(rule.source, 'rule source', code='invalid_rule')
        if device in by_device:
            raise DomainError('duplicate_device', f'duplicate rule for {device}')
        if type(rule.numerator) is not int or type(rule.denominator) is not int:
            raise DomainError('invalid_rule', 'coefficient terms must be integers')
        if rule.denominator == 0:
            raise DomainError('invalid_rule', 'coefficient denominator must be nonzero')
        coefficient = rule.coefficient
        if coefficient <= 0:
            raise DomainError('invalid_rule', 'coefficient must be positive')
        by_device[device] = DeviceRule(
            device, unit, coefficient.numerator, coefficient.denominator, source
        )
    if not by_device:
        raise DomainError('invalid_rule', 'a version must define at least one device rule')
    return tuple(by_device[device] for device in sorted(by_device))
