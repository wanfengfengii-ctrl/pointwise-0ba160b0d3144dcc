from fractions import Fraction

from energy.conversion.prepare import prepare_usage
from energy.intake.read_batch import read_batch
from energy.versions.lookup import lookup_version
from energy.versions.publish import publish_version
from energy.versions.rules import DeviceRule, VersionDraft
from tests.support import OTHER_DAY, WarehouseCase, row


class IntakeTests(WarehouseCase):
    def test_exact_preview(self):
        rows = (row(9, 1), row(2, 0), row(5, None))
        receipt = self.receive(self.east, 'E-014', rows)
        self.assertEqual(receipt.row_count, 3)
        self.assertEqual(read_batch(self.east, receipt.receipt_number).rows, rows)
        preview = self.prepare(self.east, receipt)
        self.assertEqual(preview.unit, 'kWh')
        self.assertEqual(preview.version_number, 'V1-A')
        self.assertEqual(preview.receipt_number, receipt.receipt_number)
        self.assertEqual([line.source.row_number for line in preview.lines], [9, 2, 5])
        self.assertEqual([line.position for line in preview.lines], [0, 1, 2])
        self.assertEqual([line.quantity for line in preview.lines], [Fraction(7, 2), Fraction(0), None])
        self.assertTrue(all(line.coefficient == Fraction(7, 2) for line in preview.lines))
        self.assertEqual([line.rule_source for line in preview.lines], ['C-17'] * 3)
        self.assertEqual([line.source.source for line in preview.lines], ['log/9', 'log/2', 'log/5'])
        self.assertEqual(self.current(self.east), ())
        self.assertEqual(self.current(self.west), ())

    def test_duplicate_source_row(self):
        with self.error('duplicate_row'):
            self.receive(self.east, 'E-014', (row(9, 1), row(9, 2)))
        self.assertIsNone(self.east.batches.find_by_number('E-014'))
        corrected = (row(9, 1), row(2, 2))
        receipt = self.receive(self.east, 'E-014', corrected)
        self.assertEqual(read_batch(self.east, receipt.receipt_number).rows, corrected)
        self.assertEqual(self.receive(self.east, 'E-014', corrected), receipt)

    def test_unit_mismatch(self):
        raw = (row(9, 1000, unit='Wh'),)
        receipt = self.receive(self.east, 'E-014', raw)
        with self.error('unit_mismatch'):
            self.prepare(self.east, receipt)
        self.assertEqual(read_batch(self.east, receipt.receipt_number).rows, raw)
        self.assertIsNone(self.east.previews.find_by_binding(receipt.receipt_number, 'V1-A'))
        self.assertEqual(self.current(self.east), ())
        self.publish('V-WH', 1, 1000, unit='Wh', source='C-WH')
        self.assertEqual(self.prepare(self.east, receipt, 'V-WH').lines[0].quantity, Fraction(1))

    def test_publish_binding(self):
        original = lookup_version(self.versions, 'V1-A')
        self.assertEqual(self.publish(numerator=14, denominator=4), original)
        with self.error('conflict'):
            self.publish(numerator=9)
        with self.error('conflict'):
            self.publish(source='C-18')
        rule = DeviceRule('M1', 'kWh', 2, 3, 'C-19')
        with self.error('duplicate_device'):
            publish_version(self.versions, VersionDraft('V-invalid', (rule, rule)))
        for terms in ((7, 0), (0, 1), (-7, 1), (True, 1), (7, 2.0)):
            with self.subTest(terms=terms), self.error('invalid_rule'):
                self.publish('V-invalid', *terms)
        self.assertIsNone(self.versions.find_frozen('V-invalid'))
        self.assertEqual(publish_version(self.versions, VersionDraft('V-invalid', (rule,))).rules,
                         (rule,))
        another = DeviceRule('M2', 'kWh', 1, 2, 'C-20')
        published = publish_version(self.versions, VersionDraft('V-multi', (another, rule)))
        self.assertEqual(publish_version(self.versions, VersionDraft('V-multi', (rule, another))),
                         published)
        self.assertEqual(lookup_version(self.versions, 'V1-A'), original)

    def test_explicit_version(self):
        self.publish('V1-B', 9, 1, source='C-18')
        receipt = self.receive(self.east, 'E-014', (row(9, 1),))
        old = self.prepare(self.east, receipt)
        new = self.prepare(self.east, receipt, 'V1-B')
        self.assertEqual((old.version_number, old.lines[0].quantity, old.lines[0].rule_source),
                         ('V1-A', Fraction(7, 2), 'C-17'))
        self.assertEqual((new.version_number, new.lines[0].quantity, new.lines[0].rule_source),
                         ('V1-B', Fraction(9), 'C-18'))

    def test_batch_replay(self):
        raw = (row(9, 1), row(2, 0))
        receipt = self.receive(self.east, 'E-014', raw)
        self.assertEqual(self.receive(self.east, 'E-014', list(raw)), receipt)
        for changed, day in ((raw, OTHER_DAY), (raw[::-1], receipt.business_day),
                             ((row(9, 1, source='other'), raw[1]), receipt.business_day),
                             ((row(9, 2), raw[1]), receipt.business_day)):
            with self.subTest(changed=changed, day=day), self.error('conflict'):
                self.receive(self.east, 'E-014', changed, day)
        west = self.receive(self.west, 'E-014', raw)
        self.assertNotEqual(west.receipt_number, receipt.receipt_number)
        with self.error('wrong_region'):
            read_batch(self.west, receipt.receipt_number)
        self.reopen()
        self.assertEqual(self.receive(self.east, 'E-014', raw), receipt)
        self.assertEqual(read_batch(self.east, receipt.receipt_number).rows, raw)

    def test_preview_identity(self):
        receipt = self.receive(self.east, 'E-014', (row(9, 2),))
        old = self.prepare(self.east, receipt)
        self.publish('V1-B', 9, 1, source='C-18')
        new = self.prepare(self.east, receipt, 'V1-B')
        self.assertNotEqual(old.number, new.number)
        self.assertEqual([old.lines[0].quantity, new.lines[0].quantity], [Fraction(7), Fraction(18)])
        self.reopen()
        deliveries = []
        self.messages.before_delivery = deliveries.append
        self.assertEqual(self.prepare(self.east, receipt), old)
        self.assertEqual(self.prepare(self.east, receipt, 'V1-B'), new)
        self.assertEqual(deliveries, [])

    def test_exact_storage(self):
        number = 9007199254740993
        very_large = 2 ** 100
        receipt = self.receive(self.east, 'E-014', (row(9, number), row(2, very_large)))
        preview = self.prepare(self.east, receipt)
        self.reopen()
        restored = self.prepare(self.east, receipt)
        self.assertEqual(restored, preview)
        self.assertEqual(restored.lines[0].source.reading, number)
        self.assertEqual(restored.lines[0].quantity, Fraction(63050394783186951, 2))
        self.assertEqual(restored.lines[1].quantity, Fraction(4436777100798802905238461218816))
        posted = self.post(self.east, 'P-1', restored)
        self.assertEqual(posted.fact.preview.lines[0].quantity, Fraction(63050394783186951, 2))
        self.assertEqual(self.current(self.east), (posted.fact,))

    def test_bad_row(self):
        for invalid in (row(9, True), row(9, 1.0), row(True, 1), row(9, 1, device=' ')):
            with self.subTest(invalid=invalid), self.error('invalid_row'):
                self.receive(self.east, 'E-014', (row(2, 1), invalid))
            self.assertIsNone(self.east.batches.find_by_number('E-014'))
        raw = (row(2, 1), row(9, -1))
        corrected = self.receive(self.east, 'E-014', raw)
        self.assertEqual(read_batch(self.east, corrected.receipt_number).rows, raw)

    def test_invalid_refs(self):
        with self.error('unknown_batch'):
            prepare_usage(self.east, 'east:batch:missing', 'V1-A', self.lookup)
        raw = (row(9, 1), row(2, None, device='M2'))
        receipt = self.receive(self.east, 'E-014', raw)
        with self.error('unknown_version'):
            self.prepare(self.east, receipt, 'V-missing')
        with self.error('missing_rule'):
            self.prepare(self.east, receipt)
        self.assertIsNone(self.east.previews.find_by_binding(receipt.receipt_number, 'V-missing'))
        self.assertIsNone(self.east.previews.find_by_binding(receipt.receipt_number, 'V1-A'))
        self.assertEqual(read_batch(self.east, receipt.receipt_number).rows, raw)
        self.assertEqual(self.current(self.east), ())
