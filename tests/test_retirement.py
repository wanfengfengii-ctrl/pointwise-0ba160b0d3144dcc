from fractions import Fraction

from energy.facts.posting import post_usage
from energy.facts.reversal import reverse_usage
from energy.storage import DomainError
from energy.versions.handoff import (
    DeliveryUnavailable,
    ReleaseNotice,
    RetireNotice,
)
from energy.versions.lookup import lookup_version
from energy.versions.publish import publish_version
from energy.versions.rules import DeviceRule, VersionDraft
from tests.support import DAY, OTHER_DAY, InjectedCommitFailure, WarehouseCase, row


class RetirableRegistrationTests(WarehouseCase):
    def test_retirable_only_on_first_registration(self):
        published = self.publish('V-RET', 7, 1, source='C-70', retirable=True)
        self.assertTrue(published.retirable)
        self.assertTrue(lookup_version(self.versions, 'V-RET').retirable)
        self.assertEqual(self.publish('V-RET', 14, 2, source='C-70', retirable=True), published)
        with self.error('conflict'):
            self.publish('V-RET', 7, 1, source='C-70', retirable=False)
        with self.error('conflict'):
            self.publish('V-RET', 9, 1, source='C-70', retirable=True)
        self.assertFalse(lookup_version(self.versions, 'V1-A').retirable)

    def test_existing_versions_are_ordinary(self):
        self.publish('V-OLD', 1, 1)
        self.reopen()
        self.assertFalse(lookup_version(self.versions, 'V-OLD').retirable)
        with self.error('not_retirable'):
            self.retire('RET-OLD', 'V-OLD')

    def test_retirable_must_be_bool(self):
        with self.error('invalid_rule'):
            publish_version(self.versions, VersionDraft('V-X', (
                DeviceRule('M1', 'kWh', 7, 1, 'C-70'),)), retirable='yes')
        self.assertIsNone(self.versions.find_frozen('V-X'))


class RetirementLookupTests(WarehouseCase):
    def test_unknown_and_number_validation(self):
        self.assertIsNone(self.retirement('RET-nope'))
        for bad in ('', '   ', None):
            with self.subTest(bad=bad), self.error('invalid_input'):
                self.retirement(bad)

    def test_unknown_and_ordinary_versions(self):
        with self.error('unknown_version'):
            self.retire('RET-1', 'V-missing')
        with self.error('not_retirable'):
            self.retire('RET-2', 'V1-A')
        self.assertIsNone(self.retirement('RET-1'))


class RetirementDecisionTests(WarehouseCase):
    def setUp(self):
        super().setUp()
        self.publish('V-RET', 7, 1, source='C-70', retirable=True)

    def prepared_ret(self, warehouse, batch, reading, day=DAY):
        return self.prepared(warehouse, batch, (row(9, reading),), day=day, version='V-RET')

    def test_retire_without_references(self):
        preview = self.prepared_ret(self.east, 'E-7', 1)
        result = self.retire('RET-1', 'V-RET')
        self.assertEqual((result.retirement_number, result.version_number, result.status),
                         ('RET-1', 'V-RET', 'retired'))
        self.assertIsNone(result.blocker)
        self.assertEqual(self.retirement('RET-1'), result)
        with self.error('version_retired'):
            self.post(self.east, 'P-1', preview, exchange=self.exchange)
        self.assertEqual(self.east.facts.list_active_by_version('V-RET'), ())
        self.assertIsNone(self.east.facts.get_post_receipt('P-1'))
        self.assertEqual(self.current(self.east), ())

    def test_replay_returns_terminal(self):
        first = self.retire('RET-1', 'V-RET')
        self.assertEqual(self.retire('RET-1', 'V-RET'), first)
        self.reopen()
        self.assertEqual(self.retirement('RET-1'), first)
        with self.error('version_retired'):
            self.retire('RET-2', 'V-RET')
        with self.error('conflict'):
            self.retire('RET-1', 'V1-A')

    def test_pending_blocks_other_number(self):
        pause = {'region': 'east'}

        def interrupt(target, message):
            if target == pause['region']:
                pause['region'] = None
                raise RuntimeError('link down')

        self.exchange.before_reply = interrupt
        with self.assertRaises(DeliveryUnavailable):
            self.retire('RET-1', 'V-RET')
        pending = self.retirement('RET-1')
        self.assertEqual(pending.status, 'pending')
        with self.error('retirement_in_progress'):
            self.retire('RET-2', 'V-RET')
        self.exchange.before_reply = None
        settled = self.retire('RET-1', 'V-RET')
        self.assertEqual(settled.status, 'retired')

    def test_blocked_identifies_region_and_fact(self):
        west_preview = self.prepared_ret(self.west, 'W-9', 2, day=OTHER_DAY)
        posted = self.post(self.west, 'PW-1', west_preview, exchange=self.exchange)
        east_preview = self.prepared_ret(self.east, 'E-7', 1)
        result = self.retire('RET-1', 'V-RET')
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(result.blocker, ('west', posted.fact.fact_number))
        # East's not-yet-posted request may still go through.
        east = self.post(self.east, 'P-E', east_preview, exchange=self.exchange)
        self.assertEqual(self.current(self.east), (east.fact,))
        # The blocked result is stable across replays and after reversals.
        self.assertEqual(self.retire('RET-1', 'V-RET'), result)
        reverse_usage(self.east, 'east', 'X-E', east.fact.fact_number)
        reverse_usage(self.west, 'west', 'X-W', posted.fact.fact_number)
        self.assertEqual(self.retirement('RET-1').status, 'blocked')
        self.assertEqual(self.retirement('RET-1').blocker, ('west', posted.fact.fact_number))
        # A fresh number can now succeed.
        self.assertEqual(self.retire('RET-2', 'V-RET').status, 'retired')

    def test_blocked_by_own_first_posting(self):
        east_preview = self.prepared_ret(self.east, 'E-7', 1)
        posted = self.post(self.east, 'P-E', east_preview, exchange=self.exchange)
        result = self.retire('RET-1', 'V-RET')
        self.assertEqual(result.blocker, ('east', posted.fact.fact_number))

    def test_zero_and_missing_facts_still_block(self):
        preview = self.prepared_ret(self.east, 'E-7', 0)
        self.assertEqual(preview.lines[0].quantity, Fraction(0))
        posted = self.post(self.east, 'P-E', preview, exchange=self.exchange)
        result = self.retire('RET-1', 'V-RET')
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(result.blocker, ('east', posted.fact.fact_number))
        # A missing-only fact counts too.
        self.publish('V-MISS', 7, 1, source='C-71', retirable=True)
        missing = self.prepared(self.east, 'E-8', (row(9, None),), version='V-MISS')
        posted_missing = self.post(self.east, 'P-M', missing, exchange=self.exchange)
        self.assertEqual(self.retire('RET-M', 'V-MISS').blocker,
                         ('east', posted_missing.fact.fact_number))

    def test_reversed_and_unposted_do_not_block(self):
        east_preview = self.prepared_ret(self.east, 'E-7', 1)
        posted = self.post(self.east, 'P-E', east_preview, exchange=self.exchange)
        reverse_usage(self.east, 'east', 'X-E', posted.fact.fact_number)
        self.prepared_ret(self.west, 'W-9', 3)
        self.assertEqual(self.retire('RET-1', 'V-RET').status, 'retired')

    def test_all_business_days_covered(self):
        self.post(self.east, 'P-1', self.prepared_ret(self.east, 'E-7', 1, day=DAY),
                  exchange=self.exchange)
        self.post(self.west, 'P-2', self.prepared_ret(self.west, 'W-8', 1, day=OTHER_DAY),
                  exchange=self.exchange)
        result = self.retire('RET-1', 'V-RET')
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(result.blocker[0], 'east')

    def test_previewed_but_never_submitted_does_not_block(self):
        # Both warehouses prepare a preview and then retire without submitting.
        self.prepared_ret(self.east, 'E-7', 1)
        self.prepared_ret(self.west, 'W-9', 1)
        self.assertEqual(self.retire('RET-1', 'V-RET').status, 'retired')


class RetirementPostingGateTests(WarehouseCase):
    def setUp(self):
        super().setUp()
        self.publish('V-RET', 7, 1, source='C-70', retirable=True)

    def preview(self, warehouse, batch, reading=1, day=DAY):
        return self.prepared(warehouse, batch, (row(9, reading),), day=day, version='V-RET')

    def test_retired_blocks_first_posting_without_exchange(self):
        preview = self.preview(self.east, 'E-7')
        self.retire('RET-1', 'V-RET')
        with self.error('version_retired'):
            self.post(self.east, 'P-1', preview)
        self.assertIsNone(self.east.facts.get_post_receipt('P-1'))

    def test_existing_receipt_replays_after_retirement(self):
        preview = self.preview(self.east, 'E-7')
        posted = self.post(self.east, 'P-E', preview, exchange=self.exchange)
        self.retire('RET-1', 'V-RET')
        self.assertEqual(self.post(self.east, 'P-E', preview), posted)
        self.assertEqual(self.post(self.east, 'P-E', preview, exchange=self.exchange), posted)

    def test_retirable_posting_needs_exchange(self):
        preview = self.preview(self.east, 'E-7')
        with self.error('retirement_pending'):
            self.post(self.east, 'P-1', preview)
        self.assertIsNone(self.east.facts.get_post_receipt('P-1'))
        self.assertEqual(self.post(self.east, 'P-1', preview,
                                   exchange=self.exchange).fact.preview.version_number, 'V-RET')

    def test_ordinary_posting_ignores_exchange(self):
        ordinary = self.prepared(self.east, 'E-1', (row(9, 2),))
        self.assertEqual(self.post(self.east, 'P-1', ordinary).fact.preview.version_number, 'V1-A')

    def test_round_trip_survives_reopen(self):
        preview = self.preview(self.east, 'E-7')
        posted = self.post(self.east, 'P-E', preview, exchange=self.exchange)
        reverse_usage(self.east, 'east', 'X-E', posted.fact.fact_number)
        self.retire('RET-1', 'V-RET')
        self.reopen()
        self.assertEqual(self.retirement('RET-1').status, 'retired')
        self.assertEqual(self.post(self.east, 'P-E', preview), posted)
        with self.error('version_retired'):
            self.post(self.east, 'P-2', preview)


class RetirementInterleavingTests(WarehouseCase):
    def setUp(self):
        super().setUp()
        self.publish('V-RET', 7, 1, source='C-70', retirable=True)

    def preview(self, warehouse, batch, reading=1, day=DAY):
        return self.prepared(warehouse, batch, (row(9, reading),), day=day, version='V-RET')

    def test_commit_failure_before_post_leaves_no_fact(self):
        preview = self.preview(self.east, 'E-7')
        self.commits.fail_once('post')
        with self.assertRaisesRegex(InjectedCommitFailure, 'post'):
            self.post(self.east, 'P-E', preview, exchange=self.exchange)
        self.reopen()
        self.assertIsNone(self.east.facts.get_post_receipt('P-E'))
        self.assertEqual(self.east.facts.list_active_by_version('V-RET'), ())
        # The version is still open, so retirement succeeds and the un-posted
        # request can never become a fact.
        self.assertEqual(self.retire('RET-1', 'V-RET').status, 'retired')
        with self.error('version_retired'):
            self.post(self.east, 'P-E', preview, exchange=self.exchange)

    def test_lost_post_reply_is_real_and_blocks(self):
        preview = self.preview(self.east, 'E-7')

        def lose_reply():
            self.post(self.east, 'P-E', preview, exchange=self.exchange)
            raise RuntimeError('post reply lost')

        with self.assertRaises(RuntimeError):
            lose_reply()
        self.reopen()
        receipt = self.east.facts.get_post_receipt('P-E')
        self.assertIsNotNone(receipt)
        self.assertEqual(self.retire('RET-1', 'V-RET').blocker,
                         ('east', receipt.fact.fact_number))

    def test_paused_retirement_resumes_same_number(self):
        # Stop delivery to west, so east's check lands but the case cannot settle.
        blocked_target = {'region': 'west'}

        def stop(target, message):
            if target == blocked_target['region']:
                blocked_target['region'] = None
                raise RuntimeError('link down')

        self.exchange.before_delivery = stop
        with self.assertRaises(DeliveryUnavailable):
            self.retire('RET-1', 'V-RET')
        paused = self.retirement('RET-1')
        self.assertEqual(paused.status, 'pending')
        self.exchange.before_delivery = None
        self.reopen()
        self.assertEqual(self.retirement('RET-1').status, 'pending')
        settled = self.retire('RET-1', 'V-RET')
        self.assertEqual(settled.status, 'retired')
        self.assertEqual(self.retire('RET-1', 'V-RET'), settled)

    def test_late_request_delivery_cannot_change_a_blocked_case(self):
        west_preview = self.preview(self.west, 'W-9', day=OTHER_DAY)
        posted = self.post(self.west, 'PW-1', west_preview, exchange=self.exchange)
        east_preview = self.preview(self.east, 'E-7')
        # Deliver nothing to east at first: retirement fails to fully decide.
        blocked_target = {'region': 'east'}
        held = []

        def hold_east(target, message):
            if target == 'east':
                held.append((target, message))
                blocked_target['region'] = None
                raise DeliveryUnavailable('undelivered')

        self.exchange.before_delivery = hold_east
        with self.assertRaises(DeliveryUnavailable):
            self.retire('RET-1', 'V-RET')
        self.exchange.before_delivery = None
        result = self.retire('RET-1', 'V-RET')
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(result.blocker, ('west', posted.fact.fact_number))
        # A stale request from the first attempt, delivered now, changes nothing.
        for target, message in held:
            self.exchange.deliver(target, message)
        self.assertEqual(self.retirement('RET-1'), result)
        # East can still post its own un-posted request.
        east = self.post(self.east, 'P-E', east_preview, exchange=self.exchange)
        self.assertEqual(self.current(self.east), (east.fact,))

    def test_stale_checks_cannot_release_a_live_hold(self):
        preview = self.preview(self.east, 'E-7')
        posted = self.post(self.east, 'P-E', preview, exchange=self.exchange)
        # Start a retirement that will block; keep the release notices.
        notices = []

        def capture(target, message, reply):
            if isinstance(message, ReleaseNotice):
                notices.append((target, message))
            return reply

        self.exchange.before_reply = capture
        result = self.retire('RET-1', 'V-RET')
        self.exchange.before_reply = None
        self.assertEqual(result.status, 'blocked')
        # Re-deliver old release notices now: the blocked result must hold.
        for target, message in notices:
            self.exchange.deliver(target, message)
        self.assertEqual(self.retirement('RET-1').status, 'blocked')
        # A real new retirement, by another number, must be judged afresh.
        reverse_usage(self.east, 'east', 'X-E', posted.fact.fact_number)
        self.assertEqual(self.retire('RET-2', 'V-RET').status, 'retired')

    def test_replayed_retire_notice_cannot_retire_a_fresh_case(self):
        # A successful retirement produces RetireNotices for RET-1.  Capture
        # them, then run a *new* case RET-2 that must be blocked; replaying the
        # old notices must not force RET-2's warehouses shut.
        notices = []

        def capture(target, message, reply):
            if isinstance(message, RetireNotice):
                notices.append((target, message))
            return reply

        self.exchange.before_reply = capture
        self.assertEqual(self.retire('RET-1', 'V-RET').status, 'retired')
        self.exchange.before_reply = None
        self.assertTrue(notices)
        # A fresh post is impossible; make one first impossible to post, then
        # build a new fact by posting before a *second* version is retired.
        # Instead: create a live fact on a second retirable version and confirm
        # old RET-1 notices cannot touch it.
        self.publish('V-RET2', 5, 1, source='C-80', retirable=True)
        second = self.prepared(self.east, 'E-9', (row(9, 2),), version='V-RET2')
        self.post(self.east, 'P-9', second, exchange=self.exchange)
        for target, message in notices:
            self.exchange.deliver(target, message)
        self.assertEqual(self.retirement('RET-1').status, 'retired')
        blocked = self.retire('RET-2', 'V-RET2')
        self.assertEqual(blocked.status, 'blocked')
        self.assertEqual(blocked.blocker[0], 'east')

    def test_retirement_survives_reopen_with_pending(self):
        blocked_target = {'region': 'east'}

        def stop(target, message):
            if target == blocked_target['region']:
                blocked_target['region'] = None
                raise RuntimeError('offline')

        self.exchange.before_delivery = stop
        with self.assertRaises(DeliveryUnavailable):
            self.retire('RET-1', 'V-RET')
        self.exchange.before_delivery = None
        self.reopen()
        self.assertEqual(self.retirement('RET-1').status, 'pending')
        self.assertEqual(self.retire('RET-1', 'V-RET').status, 'retired')


class RetirementPostingInterleavingTests(WarehouseCase):
    def setUp(self):
        super().setUp()
        self.publish('V-RET', 7, 1, source='C-70', retirable=True)

    def preview(self, warehouse, batch, reading=1, day=DAY):
        return self.prepared(warehouse, batch, (row(9, reading),), day=day, version='V-RET')

    def test_posting_paused_then_resumes_same_request(self):
        preview = self.preview(self.east, 'E-7')

        def stop(target, message):
            raise DeliveryUnavailable('catalog offline')

        self.exchange.before_delivery = stop
        with self.error('retirement_pending'):
            self.post(self.east, 'P-E', preview, exchange=self.exchange)
        self.assertIsNone(self.east.facts.get_post_receipt('P-E'))
        self.exchange.before_delivery = None
        receipt = self.post(self.east, 'P-E', preview, exchange=self.exchange)
        self.assertEqual(receipt.fact.preview.version_number, 'V-RET')
        self.assertEqual(self.current(self.east), (receipt.fact,))

    def test_posting_while_pending_is_refused_until_blocked(self):
        # West has a live fact, so the retirement ends up blocked; while it is
        # only pending, east may not post.
        west_receipt = self.post(self.west, 'P-W',
                                 self.preview(self.west, 'W-9', 2), exchange=self.exchange)
        held = []

        def hold_east(target, message):
            if target == 'east':
                held.append((target, message))
                raise DeliveryUnavailable('undelivered')

        self.exchange.before_delivery = hold_east
        with self.assertRaises(DeliveryUnavailable):
            self.retire('RET-1', 'V-RET')
        self.exchange.before_delivery = None
        east_preview = self.preview(self.east, 'E-7')
        with self.error('retirement_pending'):
            self.post(self.east, 'P-E', east_preview, exchange=self.exchange)
        self.assertEqual(self.retire('RET-1', 'V-RET').status, 'blocked')
        self.assertEqual(self.retire('RET-1', 'V-RET').blocker[0], 'west')
        receipt = self.post(self.east, 'P-E', east_preview, exchange=self.exchange)
        self.assertEqual(self.current(self.east), (receipt.fact,))

    def test_misrouted_reply_does_not_advance(self):
        preview = self.preview(self.east, 'E-7')

        def wrong_responder(target, message, reply):
            from dataclasses import replace
            return replace(reply, responder='west')

        self.exchange.before_reply = wrong_responder
        with self.assertRaises(DeliveryUnavailable):
            self.retire('RET-1', 'V-RET')
        self.exchange.before_reply = None
        self.assertEqual(self.retirement('RET-1').status, 'pending')
        self.assertEqual(self.retire('RET-1', 'V-RET').status, 'retired')

    def test_forged_warehouse_notice_is_inert(self):
        preview = self.preview(self.east, 'E-7')
        posted = self.post(self.east, 'P-E', preview, exchange=self.exchange)
        # A retire notice for a case this warehouse never accepted is ignored.
        from energy.versions.handoff import RetireNotice
        forged = RetireNotice('RET-forged', 'V-RET', 'east', 'token')
        self.exchange.deliver('east', forged)
        self.assertEqual(self.east.gate.gate_state('V-RET'), 'open')
        # And the real retirement still sees the live fact.
        self.assertEqual(self.retire('RET-1', 'V-RET').blocker,
                         ('east', posted.fact.fact_number))

    def test_prepared_usage_cannot_first_post_after_empty_check(self):
        # East prepared 7 kWh but neither warehouse has a fact yet.  Pause the
        # retirement right after east's empty check: east now holds a pending
        # gate, so the old preview may not slip a fact in.
        preview = self.preview(self.east, 'E-7')
        paused = {'active': True}

        def stop_west(target, message):
            if target == 'west' and paused['active']:
                paused['active'] = False
                raise DeliveryUnavailable('west offline')

        self.exchange.before_delivery = stop_west
        with self.assertRaises(DeliveryUnavailable):
            self.retire('RET-1', 'V-RET')
        self.exchange.before_delivery = None
        self.assertEqual(self.east.gate.gate_state('V-RET'), 'pending')
        # The old preview cannot become a first posting while the case is open.
        with self.error('retirement_pending'):
            self.post(self.east, 'P-1', preview, exchange=self.exchange)
        self.assertIsNone(self.east.facts.get_post_receipt('P-1'))
        self.assertEqual(self.east.facts.list_active_by_version('V-RET'), ())
        # Resume the same case: with no facts anywhere it retires, and the old
        # preview is refused for good.
        self.assertEqual(self.retire('RET-1', 'V-RET').status, 'retired')
        with self.error('version_retired'):
            self.post(self.east, 'P-1', preview, exchange=self.exchange)
        self.assertIsNone(self.east.facts.get_post_receipt('P-1'))
        self.assertEqual(self.east.facts.list_active_by_version('V-RET'), ())
