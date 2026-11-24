from contextlib import closing
from fractions import Fraction

from energy.facts.reversal import reverse_usage
from energy.facts.warehouse import initialize_warehouse, open_warehouse
from energy.reports.breakdown import build_breakdown
from energy.reports.read import get_report
from energy.reports.repository import ReportRepository
from energy.versions.lookup import lookup_version
from tests.support import DAY, OTHER_DAY, InjectedCommitFailure, WarehouseCase, row


class ReportTests(WarehouseCase):
    def test_frozen_report(self):
        preview = self.prepared(self.east, 'E-014', (row(9, 2), row(2, 0), row(5, None)))
        receipt = self.post(self.east, 'P-1', preview)
        frozen = self.freeze(self.east, 'R-E-1')
        self.assertEqual((frozen.region, frozen.business_day, frozen.unit), ('east', DAY, 'kWh'))
        self.assertEqual((frozen.total, frozen.missing_count), (Fraction(7), 1))
        self.publish('V1-B', 9, 1, source='C-18')
        reverse_usage(self.east, 'east', 'X-7', receipt.fact.fact_number)
        self.reopen()
        restored = get_report(self.reports, 'R-E-1')
        self.assertEqual(restored, frozen)
        self.assertEqual(restored.facts[0].fact_number, receipt.fact.fact_number)
        self.assertEqual(restored.facts[0].version_number, 'V1-A')
        self.assertEqual(restored.facts[0].receipt_number, preview.receipt_number)
        self.assertEqual([(line.source.row_number, line.source.source, line.rule_source, line.quantity)
                          for line in restored.lines], [
            (9, 'log/9', 'C-17', Fraction(7)), (2, 'log/2', 'C-17', Fraction(0)),
            (5, 'log/5', 'C-17', None),
        ])
        self.assertEqual(self.current(self.east), ())

    def test_report_rebind(self):
        self.post(self.east, 'P-1', self.prepared(self.east, 'E-014', (row(9, 2),)))
        original = self.freeze(self.east, 'R-E-1')
        with self.error('conflict'):
            self.freeze(self.east, 'R-E-1', OTHER_DAY)
        self.assertEqual(original.total, Fraction(7))
        self.assertEqual(get_report(self.reports, 'R-E-1'), original)

    def test_order(self):
        first = self.post(self.east, 'P-Z', self.prepared(self.east, 'E-Z', (row(9, 1), row(2, 0))))
        second = self.post(self.east, 'P-A', self.prepared(self.east, 'E-A', (row(8, 2), row(1, None))))
        self.freeze(self.east, 'R-E-1')
        self.reopen()
        restored = get_report(self.reports, 'R-E-1')
        self.assertEqual([fact.sequence for fact in restored.facts], [1, 2])
        self.assertEqual([(fact.fact_number, fact.batch_number, line.source.row_number, line.source.source)
                          for fact in restored.facts for line in fact.lines], [
            (first.fact.fact_number, 'E-Z', 9, 'log/9'), (first.fact.fact_number, 'E-Z', 2, 'log/2'),
            (second.fact.fact_number, 'E-A', 8, 'log/8'), (second.fact.fact_number, 'E-A', 1, 'log/1'),
        ])
        self.assertEqual((restored.total, restored.missing_count), (Fraction(21, 2), 1))

    def test_empty_day(self):
        receipt = self.post(self.east, 'P-1', self.prepared(self.east, 'E-014', (row(9, 2),)))
        original = self.freeze(self.east, 'R-E-1')
        reverse_usage(self.east, 'east', 'X-7', receipt.fact.fact_number)
        empty = self.freeze(self.east, 'R-E-2')
        self.assertEqual((empty.facts, empty.lines, empty.total, empty.unit, empty.missing_count),
                         ((), (), Fraction(0), 'kWh', 0))
        self.assertEqual((original.total, get_report(self.reports, 'R-E-1')), (Fraction(7), original))
        self.assertEqual(self.freeze(self.east, 'R-E-3', OTHER_DAY).facts, ())

    def test_repeat_initialization(self):
        added = self.publish('V-user', 11, 3, source='operator/catalog')
        east = self.post(self.east, 'PE', self.prepared(self.east, 'E-014', (row(9, 2),)))
        west = self.post(self.west, 'PW', self.prepared(self.west, 'W-009', (row(8, 2),), version='V-user'))
        snapshot = self.freeze(self.east, 'R-E-1')
        reversal = reverse_usage(self.east, 'east', 'XE', east.fact.fact_number)
        self.reopen(initialize=True)
        self.assertEqual(lookup_version(self.versions, 'V-user'), added)
        self.assertEqual(self.east.facts.get_post_receipt('PE'), east)
        self.assertEqual(self.east.facts.get_reversal_receipt('XE'), reversal)
        self.assertEqual(self.current(self.east), ())
        self.assertEqual(self.current(self.west), (west.fact,))
        self.assertEqual(get_report(self.reports, 'R-E-1'), snapshot)
        with self.error('wrong_region'):
            initialize_warehouse(self.west_path, 'east')
        with self.error('wrong_region'):
            open_warehouse(self.east_path, 'west')
        self.reopen()
        self.assertEqual(self.current(self.west), (west.fact,))
        self.assertEqual(self.east.facts.get_reversal_receipt('XE'), reversal)

    def test_same_binding(self):
        first = self.post(self.east, 'P-1', self.prepared(self.east, 'E-014', (row(9, 2),)))
        original = self.freeze(self.east, 'R-E-1')
        reverse_usage(self.east, 'east', 'X-7', first.fact.fact_number)
        self.post(self.east, 'P-2', self.prepared(self.east, 'E-015', (row(8, 4),)))
        self.reopen()
        self.assertEqual(self.freeze(self.east, 'R-E-1'), original)
        self.assertEqual(self.freeze(self.east, 'R-E-2').total, Fraction(14))

    def test_region_rebind(self):
        self.post(self.east, 'P-1', self.prepared(self.east, 'E-014', (row(9, 2),)))
        self.post(self.west, 'P-1', self.prepared(self.west, 'W-009', (row(8, 4),)))
        original = self.freeze(self.east, 'R-E-1')
        with self.error('conflict'):
            self.freeze(self.west, 'R-E-1')
        self.assertEqual(get_report(self.reports, 'R-E-1'), original)
        self.assertEqual(self.freeze(self.west, 'R-W-1').total, Fraction(14))

    def test_write_failure(self):
        self.post(self.east, 'P-1', self.prepared(self.east, 'E-014', (row(9, 2), row(5, None))))
        self.commits.fail_once('report')
        with self.assertRaisesRegex(InjectedCommitFailure, 'report'):
            self.freeze(self.east, 'R-E-1')
        self.reopen()
        with self.error('unknown_report'):
            get_report(self.reports, 'R-E-1')
        rebuilt = self.freeze(self.east, 'R-E-1')
        self.assertEqual((rebuilt.total, rebuilt.missing_count), (Fraction(7), 1))
        self.assertEqual([line.source.row_number for line in rebuilt.lines], [9, 5])
        self.assertEqual(get_report(self.reports, 'R-E-1'), rebuilt)

    def test_store_rechecks_binding_after_competing_archive(self):
        self.post(self.east, 'P-1', self.prepared(self.east, 'E-014', (row(9, 2),)))
        with closing(ReportRepository(self.catalog_path)) as competing:
            self.assertIsNone(competing.find('R-1'))
            old_cut = build_breakdown('R-1', 'east', DAY, self.current(self.east))
            other_region = build_breakdown('R-1', 'west', DAY, self.current(self.west))
            self.post(self.east, 'P-2', self.prepared(self.east, 'E-015', (row(2, 4),)))
            winner = self.freeze(self.east, 'R-1')
            self.assertEqual((old_cut.total, winner.total), (Fraction(7), Fraction(21)))
            self.assertEqual(competing.store_once(old_cut), winner)
            with self.error('conflict'):
                competing.store_once(other_region)
            self.assertEqual(get_report(competing, 'R-1'), winner)
