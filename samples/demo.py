from fractions import Fraction
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from energy.conversion.prepare import prepare_usage
from energy.facts.current import read_current
from energy.facts.posting import post_usage
from energy.facts.reversal import reverse_usage
from energy.intake.read_batch import read_batch
from energy.intake.register import receive_batch
from energy.intake.rows import SourceRow
from energy.reports.build import freeze_report
from energy.reports.read import get_report
from energy.versions.messages import handle_version_lookup
from energy.versions.publish import publish_version
from energy.versions.rules import DeviceRule, VersionDraft
from samples.init_sample import open_stores


def version_draft(entry):
    return VersionDraft(entry['number'], tuple(DeviceRule(**rule) for rule in entry['rules']))


def report_summary(report):
    return {
        'region': report.region,
        'day': report.business_day,
        'total': str(report.total),
        'unit': report.unit,
        'missing': report.missing_count,
        'versions': [fact.version_number for fact in report.facts],
        'rows': [[line.source.row_number, line.source.source, line.rule_source,
                  None if line.quantity is None else str(line.quantity)] for line in report.lines],
    }


def run_day(root: Path) -> None:
    data = json.loads(Path(__file__).with_name('day.json').read_text(encoding='utf-8'))
    day = data['business_day']
    with open_stores(root, initialize=True) as stores:
        east, west = stores.warehouses['east'], stores.warehouses['west']
        version = publish_version(stores.versions, version_draft(data['versions'][0]))

        def lookup(request):
            return handle_version_lookup(stores.versions, request)

        previews = {}
        for entry in data['batches']:
            warehouse = stores.warehouses[entry['region']]
            raw = tuple(SourceRow(**line) for line in entry['rows'])
            receipt = receive_batch(warehouse, entry['region'], day, entry['number'], raw)
            assert read_batch(warehouse, receipt.receipt_number).rows == raw
            previews[entry['number']] = prepare_usage(warehouse, receipt.receipt_number,
                                                       version.number, lookup)
        first_preview = previews['E-014']
        preview_actual = {
            'quantity': [None if line.quantity is None else str(line.quantity)
                         for line in first_preview.lines],
            'rows': [line.source.row_number for line in first_preview.lines],
            'rule_sources': [line.rule_source for line in first_preview.lines],
        }
        preview_expected = {'quantity': ['7/2', '0', None], 'rows': [9, 2, 5],
                            'rule_sources': ['C-17', 'C-17', 'C-17']}
        assert preview_actual == preview_expected
        counts = {'east': len(read_current(east, 'east', day)),
                  'west': len(read_current(west, 'west', day))}
        assert counts == {'east': 0, 'west': 0}
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v1',
            'input': {'raw': [line.source.reading for line in first_preview.lines],
                      'coefficient': str(version.rules[0].coefficient)},
            'expected': preview_expected, 'actual': preview_actual,
            'downstream_expected': {'east': 0, 'west': 0}, 'downstream_actual': counts,
            'code_paths': ['energy/conversion/prepare.py', 'energy/conversion/quantities.py',
                           'energy/facts/current.py'],
            'oracle': 'Multiply 1 and 0 by 7/2, carry missing separately, and count committed facts before posting.',
        }, separators=(',', ':')))

        first = post_usage(east, 'east', 'PE-014', first_preview.number)
        mistaken = post_usage(east, 'east', 'PE-015', previews['E-015'].number)
        posted_west = post_usage(west, 'west', 'PW-009', previews['W-009'].number)
        assert read_current(east, 'east', day) == (first.fact, mistaken.fact)
        initial_east = sum((fact.preview.lines[0].quantity for fact in (first.fact, mistaken.fact)), Fraction(0))
        assert initial_east == Fraction(35, 2)
        assert posted_west.fact.preview.lines[0].quantity == Fraction(7)
        assert post_usage(east, 'east', 'PE-014', first_preview.number) == first
        reverse_usage(east, 'east', 'XE-015', mistaken.fact.fact_number)
        frozen = freeze_report(stores.reports, east, 'R-E-1', 'east', day)
        assert frozen.facts[0].fact_number == first.fact.fact_number
        assert frozen.facts[0].receipt_number == first_preview.receipt_number
        publish_version(stores.versions, version_draft(data['versions'][1]))
        reversal = reverse_usage(east, 'east', 'XE-014', first.fact.fact_number)
        empty = freeze_report(stores.reports, east, 'R-E-2', 'east', day)
        assert (empty.total, empty.missing_count, empty.lines) == (Fraction(0), 0, ())

    with open_stores(root) as stores:
        east, west = stores.warehouses['east'], stores.warehouses['west']
        restored = get_report(stores.reports, 'R-E-1')
        assert restored == frozen
        assert freeze_report(stores.reports, east, 'R-E-1', 'east', day) == restored
        assert east.facts.get_post_receipt('PE-014') == first
        assert east.facts.get_reversal_receipt('XE-014') == reversal
        west_facts = read_current(west, 'west', day)
        assert west_facts == (posted_west.fact,)
        expected = {'region': 'east', 'day': '2026-11-24', 'total': '7/2', 'unit': 'kWh',
                    'missing': 1, 'versions': ['V1-A'],
                    'rows': [[9, 'E-014/9', 'C-17', '7/2'], [2, 'E-014/2', 'C-17', '0'],
                             [5, 'E-014/5', 'C-17', None]]}
        actual = report_summary(restored)
        assert actual == expected
        restored_empty = get_report(stores.reports, 'R-E-2')
        downstream = {'new_east_total': str(restored_empty.total),
                      'new_east_rows': len(restored_empty.lines),
                      'west_total': str(west_facts[0].preview.lines[0].quantity)}
        downstream_expected = {'new_east_total': '0', 'new_east_rows': 0, 'west_total': '7'}
        assert downstream == downstream_expected
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v7',
            'input': {'archived': restored.number, 'current': restored_empty.number,
                      'east_initial_total': str(initial_east), 'reversed': reversal.fact_number},
            'expected': expected, 'actual': actual,
            'downstream_expected': downstream_expected, 'downstream_actual': downstream,
            'code_paths': ['energy/facts/reversal.py', 'energy/reports/breakdown.py',
                           'energy/reports/snapshot.py', 'energy/reports/read.py'],
            'oracle': 'After removing E-015 from the first cutoff, E-014 contributes 7/2 plus zero and one missing row. Removing E-014 only affects the new cutoff. W-009 contributes 2 times 7/2.',
        }, separators=(',', ':')))


def main() -> None:
    with TemporaryDirectory() as directory:
        run_day(Path(directory))


if __name__ == '__main__':
    main()
