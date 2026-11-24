"""Walk through both retirement paths against real local databases.

Run from the project root::

    python3 -B -m samples.retirement_demo

No-reference path: east prepares 7 kWh from an already-received batch, V7 is
retired, and the old preview can no longer make a first posting.  Blocked
path: west posts a V7 fact on another business day and freezes its daily
report; retirement is refused with west and that fact number, east may still
post its pending request, and after both facts are reversed a fresh retirement
number succeeds.  The old blocked case and the archived report are unchanged
after a reopen.
"""

from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from energy.conversion.prepare import prepare_usage
from energy.facts.current import read_current
from energy.facts.exchange import LocalExchange
from energy.facts.posting import post_usage
from energy.facts.reversal import reverse_usage
from energy.intake.register import receive_batch
from energy.intake.rows import SourceRow
from energy.reports.build import freeze_report
from energy.reports.read import get_report
from energy.storage import DomainError
from energy.versions.handoff import DeliveryUnavailable
from energy.versions.messages import handle_version_lookup
from energy.versions.publish import publish_version
from energy.versions.retirement import get_retirement, retire_version
from energy.versions.rules import DeviceRule, VersionDraft
from samples import demo as base_demo
from samples.init_sample import open_stores

DAY = '2026-11-24'
OTHER_DAY = '2026-11-25'
DRAFT = VersionDraft('V7', (DeviceRule('M1', 'kWh', 7, 1, 'C-70'),))


def prepare_seven(warehouse, lookup, batch_number, *, day=DAY):
    rows = (SourceRow(9, 'M1', 'kWh', 1, f'{batch_number}/9'),)
    batch = receive_batch(warehouse, warehouse.scope.region, day, batch_number, rows)
    return prepare_usage(warehouse, batch.receipt_number, DRAFT.number, lookup)


def expect(error_code, action, *args, **kwargs):
    try:
        action(*args, **kwargs)
    except DomainError as error:
        assert error.code == error_code, (error.code, error_code)
        return error
    raise AssertionError(f'expected {error_code}')


def no_reference_path(root: Path) -> dict:
    with open_stores(root, initialize=True) as stores:
        east = stores.warehouses['east']
        publish_version(stores.versions, DRAFT, retirable=True)

        def lookup(request):
            return handle_version_lookup(stores.versions, request)

        exchange = LocalExchange(stores.versions, stores.warehouses)
        preview = prepare_seven(east, lookup, 'E-7')
        assert preview.lines[0].quantity == Fraction(7)
        assert read_current(east, 'east', DAY) == ()

        # Pause the retirement right after east's empty check: the old preview
        # must not be able to become a first posting in that window.
        paused = {'active': True}

        def pause_west(target, message):
            if target == 'west' and paused['active']:
                paused['active'] = False
                raise DeliveryUnavailable('west link down')

        exchange.before_delivery = pause_west
        try:
            retire_version(stores.versions, 'RET-E-7', DRAFT.number, exchange)
            raise AssertionError('retirement should have paused')
        except DeliveryUnavailable:
            pass
        exchange.before_delivery = None
        expect('retirement_pending', post_usage, east, 'east', 'POST-E-7', preview.number,
               exchange=exchange)
        assert east.facts.get_post_receipt('POST-E-7') is None

        retired = retire_version(stores.versions, 'RET-E-7', DRAFT.number, exchange)
        assert (retired.status, retired.blocker) == ('retired', None)
        expect('version_retired', post_usage, east, 'east', 'POST-E-7', preview.number,
               exchange=exchange)
        assert east.facts.get_post_receipt('POST-E-7') is None
        assert read_current(east, 'east', DAY) == ()
        # Replaying the same case changes nothing and does not touch a warehouse.
        assert get_retirement(stores.versions, 'RET-E-7') == retired
        return {'preview': preview, 'retired': retired}


def blocked_path(root: Path) -> dict:
    with open_stores(root, initialize=True) as stores:
        east, west = stores.warehouses['east'], stores.warehouses['west']
        publish_version(stores.versions, DRAFT, retirable=True)

        def lookup(request):
            return handle_version_lookup(stores.versions, request)

        exchange = LocalExchange(stores.versions, stores.warehouses)
        west_preview = prepare_seven(west, lookup, 'W-9', day=OTHER_DAY)
        west_receipt = post_usage(west, 'west', 'POST-W-9', west_preview.number, exchange=exchange)
        report = freeze_report(stores.reports, west, 'REPORT-W-9', 'west', OTHER_DAY)
        assert report.total == Fraction(7)

        east_preview = prepare_seven(east, lookup, 'E-7')
        blocked = retire_version(stores.versions, 'RET-W-9', DRAFT.number, exchange)
        assert blocked.status == 'blocked'
        blocker_region, blocker_fact = blocked.blocker
        assert blocker_region == 'west' and blocker_fact == west_receipt.fact.fact_number

        # East's still-unposted request is allowed once the case is blocked.
        east_receipt = post_usage(east, 'east', 'POST-E-7', east_preview.number, exchange=exchange)
        assert read_current(east, 'east', DAY) == (east_receipt.fact,)

        # Reversing both facts lets a fresh number succeed; the old case stays blocked.
        reverse_usage(east, 'east', 'REV-E-7', east_receipt.fact.fact_number)
        reverse_usage(west, 'west', 'REV-W-9', west_receipt.fact.fact_number)
        retired = retire_version(stores.versions, 'RET-2', DRAFT.number, exchange)
        assert retired.status == 'retired'
        assert get_retirement(stores.versions, 'RET-W-9').status == 'blocked'
        return {
            'west_receipt': west_receipt, 'east_receipt': east_receipt,
            'report': report, 'blocked': blocked, 'retired': retired,
        }


def main() -> None:
    # Keep the original V1/V7 sample in the demo run as well.
    with TemporaryDirectory() as base_directory:
        base_demo.run_day(Path(base_directory))
    with TemporaryDirectory() as directory:
        root = Path(directory)
        first = no_reference_path(root / 'retire-alone')
        assert first['retired'].status == 'retired'
        second = blocked_path(root / 'retire-blocked')

        # Reopen the blocked-path stores and confirm archived facts/reports replay.
        with open_stores(root / 'retire-blocked') as stores:
            east, west = stores.warehouses['east'], stores.warehouses['west']
            assert get_retirement(stores.versions, 'RET-W-9') == second['blocked']
            assert get_retirement(stores.versions, 'RET-2') == second['retired']
            assert east.facts.get_post_receipt('POST-E-7') == second['east_receipt']
            assert west.facts.get_post_receipt('POST-W-9') == second['west_receipt']
            restored = get_report(stores.reports, 'REPORT-W-9')
            assert restored == second['report']
            assert restored.total == Fraction(7)
            assert [fact.fact_number for fact in restored.facts] == [
                second['west_receipt'].fact.fact_number]

    print('V7 no-reference: east prepared 7 kWh with both accounts empty; pausing the '
          'case blocked the old preview (retirement_pending), and after RET-E-7 retired '
          'it was refused for good with version_retired (no fact, no receipt).')
    blocker = second['blocked'].blocker
    print(f"V7 blocked: RET-W-9 refused with {blocker[0]} fact {blocker[1]}; "
          f"east still posted {second['east_receipt'].fact.fact_number}.")
    print(f"V7 after reversal: RET-2 retired; RET-W-9 stays blocked; "
          f"REPORT-W-9 replays {second['report'].total} {second['report'].unit} "
          f"with fact {second['report'].facts[0].fact_number}.")


if __name__ == '__main__':
    main()
