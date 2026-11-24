from fractions import Fraction

from energy.facts.current import read_current
from energy.facts.posting import post_usage
from energy.facts.reversal import reverse_usage
from tests.support import DAY, OTHER_DAY, InjectedCommitFailure, ReplyLost, WarehouseCase, row


class AccountingTests(WarehouseCase):
    def test_first_receipt(self):
        preview = self.prepared(self.east, 'E-014', (row(9, 2),))
        first = self.post(self.east, 'P-1', preview)
        self.assertEqual(self.post(self.east, 'P-1', preview), first)
        self.assertEqual(self.east.facts.get_post_receipt('P-1'), first)
        self.assertEqual(self.current(self.east), (first.fact,))
        self.assertEqual(first.fact.sequence, 1)
        self.assertEqual(first.fact.preview.lines[0].quantity, Fraction(7))

    def test_commit_failure(self):
        preview = self.prepared(self.east, 'E-014', (row(9, 2),))
        self.commits.fail_once('post')
        with self.assertRaisesRegex(InjectedCommitFailure, 'post'):
            self.post(self.east, 'P-1', preview)
        self.assertEqual(self.current(self.east), ())
        self.assertIsNone(self.east.facts.get_post_receipt('P-1'))
        self.reopen()
        self.assertEqual(self.current(self.east), ())
        self.assertIsNone(self.east.facts.get_post_receipt('P-1'))
        first = self.post(self.east, 'P-1', preview)
        self.assertEqual(first.fact.preview.lines[0].quantity, Fraction(7))
        self.assertEqual(self.current(self.east), (first.fact,))
        self.assertEqual(self.post(self.east, 'P-1', preview), first)

    def test_regional_reversal(self):
        east_preview = self.prepared(self.east, 'E-014', (row(9, 2),))
        west_preview = self.prepared(self.west, 'W-009', (row(8, 4),))
        east = self.post(self.east, 'P-1', east_preview)
        west = self.post(self.west, 'P-1', west_preview)
        self.assertNotEqual(east.fact.fact_number, west.fact.fact_number)
        reversed_east = reverse_usage(self.east, 'east', 'X-7', east.fact.fact_number)
        self.assertEqual(reversed_east.fact_number, east.fact.fact_number)
        self.assertNotEqual(reversed_east.reversal_number, east.fact.fact_number)
        self.assertEqual(self.current(self.east), ())
        self.assertEqual(self.current(self.west), (west.fact,))
        self.assertEqual(self.post(self.east, 'P-1', east_preview), east)
        with self.error('wrong_region'):
            reverse_usage(self.west, 'west', 'X-7', east.fact.fact_number)

    def test_preview_once(self):
        preview = self.prepared(self.east, 'E-014', (row(9, 2),))
        first = self.post(self.east, 'P-1', preview)
        with self.error('already_posted'):
            self.post(self.east, 'P-2', preview)
        self.assertIsNone(self.east.facts.get_post_receipt('P-2'))
        self.assertEqual(self.current(self.east), (first.fact,))
        reverse_usage(self.east, 'east', 'X-7', first.fact.fact_number)
        with self.error('already_posted'):
            self.post(self.east, 'P-2', preview)
        self.assertEqual(self.current(self.east), ())

    def test_request_rebind(self):
        first_preview = self.prepared(self.east, 'E-014', (row(9, 2),))
        next_preview = self.prepared(self.east, 'E-015', (row(2, 4),))
        receipt = self.post(self.east, 'P-1', first_preview)
        with self.error('conflict'):
            self.post(self.east, 'P-1', next_preview)
        self.assertEqual(self.east.facts.get_post_receipt('P-1'), receipt)
        second = self.post(self.east, 'P-2', next_preview)
        self.assertEqual(self.current(self.east), (receipt.fact, second.fact))

    def test_pinned_basis(self):
        preview = self.prepared(self.east, 'E-014', (row(9, 2),))
        self.publish('V1-B', 9, 1, source='C-18')
        self.reopen()
        receipt = self.post(self.east, 'P-1', preview)
        line = receipt.fact.preview.lines[0]
        self.assertEqual(receipt.fact.preview.version_number, 'V1-A')
        self.assertEqual((line.quantity, line.rule_source), (Fraction(7), 'C-17'))
        self.assertEqual(self.current(self.east), (receipt.fact,))

    def test_lost_reply(self):
        preview = self.prepared(self.east, 'E-014', (row(9, 2),))
        sent_replies = []

        def lose_reply(receipt):
            sent_replies.append(receipt)
            raise ReplyLost('post response lost')

        self.messages.before_reply = lose_reply
        with self.assertRaises(ReplyLost):
            self.messages.call(post_usage, self.east, 'east', 'P-1', preview.number)
        self.messages.before_reply = None
        self.reopen()
        receipt = self.east.facts.get_post_receipt('P-1')
        self.assertEqual([receipt], sent_replies)
        self.assertIsNotNone(receipt)
        self.assertEqual(self.post(self.east, 'P-1', preview), receipt)
        self.assertEqual(self.current(self.east), (receipt.fact,))
        self.assertEqual(receipt.fact.preview.lines[0].quantity, Fraction(7))

    def test_reversal_failure(self):
        preview = self.prepared(self.east, 'E-014', (row(9, 2),))
        receipt = self.post(self.east, 'P-1', preview)
        self.commits.fail_once('reverse')
        with self.assertRaisesRegex(InjectedCommitFailure, 'reverse'):
            reverse_usage(self.east, 'east', 'X-7', receipt.fact.fact_number)
        self.reopen()
        self.assertEqual(self.current(self.east), (receipt.fact,))
        self.assertIsNone(self.east.facts.get_reversal_receipt('X-7'))
        reversal = reverse_usage(self.east, 'east', 'X-7', receipt.fact.fact_number)
        self.assertEqual(reversal.fact_number, receipt.fact.fact_number)
        self.assertEqual(self.current(self.east), ())

    def test_reversal_replay(self):
        first = self.post(self.east, 'P-1', self.prepared(self.east, 'E-014', (row(9, 2),)))
        second = self.post(self.east, 'P-2', self.prepared(self.east, 'E-015', (row(2, 4),)))
        reversal = reverse_usage(self.east, 'east', 'X-7', first.fact.fact_number)
        self.reopen()
        self.assertEqual(reverse_usage(self.east, 'east', 'X-7', first.fact.fact_number), reversal)
        with self.error('conflict'):
            reverse_usage(self.east, 'east', 'X-7', second.fact.fact_number)
        with self.error('already_reversed'):
            reverse_usage(self.east, 'east', 'X-8', first.fact.fact_number)
        with self.error('unknown_fact'):
            reverse_usage(self.east, 'east', 'X-8', 'east:fact:missing')
        self.assertIsNone(self.east.facts.get_reversal_receipt('X-8'))
        self.assertEqual(self.east.facts.get_post_receipt('P-1'), first)
        self.assertEqual(self.current(self.east), (second.fact,))

    def test_scope_date(self):
        preview = self.prepared(self.east, 'E-014', (row(9, 2),), day=OTHER_DAY)
        with self.error('wrong_region'):
            post_usage(self.east, 'west', 'P-1', preview.number)
        with self.error('wrong_region'):
            post_usage(self.west, 'west', 'P-1', preview.number)
        with self.error('unknown_preview'):
            post_usage(self.east, 'east', 'P-1', 'east:preview:missing')
        receipt = self.post(self.east, 'P-1', preview)
        self.assertEqual(read_current(self.east, 'east', DAY), ())
        self.assertEqual(read_current(self.east, 'east', OTHER_DAY), (receipt.fact,))
        self.assertEqual(read_current(self.west, 'west', OTHER_DAY), ())
        with self.error('wrong_region'):
            read_current(self.east, 'west', OTHER_DAY)
        for bad in ('2026-02-29', '20261124', '2026-W48-2', None):
            with self.subTest(bad=bad), self.error('invalid_day'):
                read_current(self.east, 'east', bad)
