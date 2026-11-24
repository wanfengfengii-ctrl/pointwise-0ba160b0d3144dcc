from tempfile import TemporaryDirectory
from pathlib import Path

from energy.conversion.prepare import prepare_usage
from energy.facts.current import read_current
from energy.facts.posting import post_usage
from energy.facts.reversal import reverse_usage
from energy.intake.register import receive_batch
from energy.intake.rows import SourceRow
from energy.reports.build import freeze_report
from energy.reports.read import get_report
from energy.versions.messages import handle_version_lookup
from energy.versions.publish import publish_version
from energy.versions.rules import DeviceRule, VersionDraft
from samples.init_sample import open_stores


DAY = "2026-11-24"
OTHER_DAY = "2026-11-25"
DRAFT = VersionDraft("V7", (DeviceRule("M1", "kWh", 7, 1, "C-70"),))


def prepare_one(warehouse, lookup, batch_number, *, day=DAY, reading=1):
    region = warehouse.scope.region
    rows = (SourceRow(9, "M1", "kWh", reading, f"{batch_number}/9"),)
    batch = receive_batch(warehouse, region, day, batch_number, rows)
    return prepare_usage(warehouse, batch.receipt_number, DRAFT.number, lookup)


def observe_v1(versions, east, west):
    publish_version(versions, DRAFT)

    def lookup(request):
        return handle_version_lookup(versions, request)

    preview = prepare_one(east, lookup, "E-7")
    assert preview.lines[0].quantity == 7
    assert read_current(east, "east", DAY) == ()
    assert read_current(west, "west", DAY) == ()
    receipt = post_usage(east, "east", "POST-E-7", preview.number)
    assert read_current(east, "east", DAY) == (receipt.fact,)
    assert read_current(west, "west", DAY) == ()
    assert receipt.fact.preview.lines[0].quantity == 7
    return receipt


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        with open_stores(root, initialize=True) as stores:
            east = stores.warehouses["east"]
            receipt = observe_v1(stores.versions, east, stores.warehouses["west"])
            report = freeze_report(stores.reports, east, "REPORT-E-7", "east", DAY)
            assert (report.total, report.lines[0].source.source) == (7, "E-7/9")
            reverse_usage(east, "east", "REVERSE-E-7", receipt.fact.fact_number)
        with open_stores(root) as stores:
            east = stores.warehouses["east"]
            assert read_current(east, "east", DAY) == ()
            assert east.facts.get_post_receipt("POST-E-7") == receipt
            assert get_report(stores.reports, "REPORT-E-7") == report
    print(f"V1 {DRAFT.number}: east=0 west=0 facts before posting, then {receipt.fact.fact_number} added {report.total} {report.unit}")
    print(f"V1 after reversal and reopen: east has no effective facts, {report.number} retains {report.total} {report.unit}")


if __name__ == "__main__":
    main()
