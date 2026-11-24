from dataclasses import dataclass
from fractions import Fraction
import json

from energy.conversion.quantities import decode_fraction, decode_quantity, encode_quantity
from energy.intake.rows import SourceRow, decode_source, encode_source


@dataclass(frozen=True, slots=True)
class ReportLine:
    position: int
    source: SourceRow
    coefficient: Fraction
    rule_source: str
    quantity: Fraction | None


@dataclass(frozen=True, slots=True)
class ReportFact:
    fact_number: str
    sequence: int
    preview_number: str
    version_number: str
    batch_number: str
    receipt_number: str
    lines: tuple[ReportLine, ...]


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    number: str
    region: str
    business_day: str
    unit: str
    total: Fraction
    missing_count: int
    facts: tuple[ReportFact, ...]

    @property
    def lines(self) -> tuple[ReportLine, ...]:
        return tuple(line for fact in self.facts for line in fact.lines)


def _encode_fact(fact: ReportFact) -> dict:
    return {
        'fact_number': fact.fact_number,
        'sequence': fact.sequence,
        'preview_number': fact.preview_number,
        'version_number': fact.version_number,
        'batch_number': fact.batch_number,
        'receipt_number': fact.receipt_number,
        'lines': [
            {'position': line.position, 'source': encode_source(line.source),
             'coefficient': encode_quantity(line.coefficient), 'rule_source': line.rule_source,
             'quantity': encode_quantity(line.quantity)}
            for line in fact.lines
        ],
    }


def _decode_fact(data: dict) -> ReportFact:
    lines = tuple(
        ReportLine(line['position'], decode_source(*line['source']),
                   decode_fraction(line['coefficient']), line['rule_source'],
                   decode_quantity(line['quantity']))
        for line in data['lines']
    )
    return ReportFact(data['fact_number'], data['sequence'], data['preview_number'],
                      data['version_number'], data['batch_number'], data['receipt_number'], lines)


def encode_snapshot(snapshot: ReportSnapshot) -> str:
    return json.dumps({
        'number': snapshot.number,
        'region': snapshot.region,
        'business_day': snapshot.business_day,
        'unit': snapshot.unit,
        'total': encode_quantity(snapshot.total),
        'missing_count': snapshot.missing_count,
        'facts': [_encode_fact(fact) for fact in snapshot.facts],
    }, separators=(',', ':'))


def decode_snapshot(payload: str) -> ReportSnapshot:
    data = json.loads(payload)
    return ReportSnapshot(data['number'], data['region'], data['business_day'], data['unit'],
                          decode_fraction(data['total']), data['missing_count'],
                          tuple(_decode_fact(fact) for fact in data['facts']))
