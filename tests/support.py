from contextlib import ExitStack, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from energy.conversion.prepare import prepare_usage
from energy.facts.current import read_current
from energy.facts.exchange import LocalExchange
from energy.facts.posting import post_usage
from energy.facts.warehouse import initialize_warehouse, open_warehouse
from energy.intake.register import receive_batch
from energy.intake.rows import SourceRow
from energy.reports.build import freeze_report
from energy.reports.repository import ReportRepository
from energy.storage import DomainError
from energy.versions.messages import handle_version_lookup
from energy.versions.publish import publish_version
from energy.versions.repository import VersionRepository
from energy.versions.retirement import get_retirement, retire_version
from energy.versions.rules import DeviceRule, VersionDraft


DAY = '2026-11-24'
OTHER_DAY = '2026-11-25'


class InjectedCommitFailure(RuntimeError):
    pass


class ReplyLost(RuntimeError):
    pass


class CommitControl:
    def __init__(self):
        self.armed = set()

    def fail_once(self, operation):
        self.armed.add(operation)

    def before_commit(self, operation):
        if operation in self.armed:
            self.armed.remove(operation)
            raise InjectedCommitFailure(operation)


class LocalMessages:
    def __init__(self):
        self.before_delivery = None
        self.before_reply = None

    def call(self, handler, *args):
        if self.before_delivery is not None:
            self.before_delivery(args)
        result = handler(*args)
        if self.before_reply is not None:
            self.before_reply(result)
        return result


def row(number, reading, *, device='M1', unit='kWh', source=None):
    return SourceRow(number, device, unit, reading, source or f'log/{number}')


class WarehouseCase(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.catalog_path = self.root / 'catalog.sqlite3'
        self.east_path = self.root / 'east.sqlite3'
        self.west_path = self.root / 'west.sqlite3'
        self.commits = CommitControl()
        self.messages = LocalMessages()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self._connect(initialize=True)
        self.publish()
        self.exchange = LocalExchange(
            self.versions, {'east': self.east, 'west': self.west})

    def _connect(self, *, initialize):
        self.versions = VersionRepository(self.catalog_path)
        self.stack.callback(self.versions.close)
        self.reports = ReportRepository(self.catalog_path, before_commit=self.commits.before_commit)
        self.stack.callback(self.reports.close)
        if initialize:
            self.versions.initialize()
            self.reports.initialize()
        open_region = initialize_warehouse if initialize else open_warehouse
        self.east = open_region(self.east_path, 'east', before_commit=self.commits.before_commit)
        self.stack.callback(self.east.close)
        self.west = open_region(self.west_path, 'west', before_commit=self.commits.before_commit)
        self.stack.callback(self.west.close)

    def reopen(self, *, initialize=False):
        self.stack.close()
        self._connect(initialize=initialize)
        self.exchange = LocalExchange(
            self.versions, {'east': self.east, 'west': self.west})

    def publish(self, version='V1-A', numerator=7, denominator=2, *,
                unit='kWh', source='C-17', retirable=False):
        return publish_version(self.versions, VersionDraft(version, (
            DeviceRule('M1', unit, numerator, denominator, source),
        )), retirable=retirable)

    def lookup(self, request):
        return self.messages.call(handle_version_lookup, self.versions, request)

    def receive(self, warehouse, batch, rows, day=DAY):
        return receive_batch(warehouse, warehouse.scope.region, day, batch, rows)

    def prepare(self, warehouse, receipt, version='V1-A'):
        return prepare_usage(warehouse, receipt.receipt_number, version, self.lookup)

    def prepared(self, warehouse, batch, rows, day=DAY, version='V1-A'):
        return self.prepare(warehouse, self.receive(warehouse, batch, rows, day), version)

    def post(self, warehouse, request, preview, **kwargs):
        return post_usage(warehouse, warehouse.scope.region, request, preview.number, **kwargs)

    def current(self, warehouse, day=DAY):
        return read_current(warehouse, warehouse.scope.region, day)

    def freeze(self, warehouse, number, day=DAY):
        return freeze_report(self.reports, warehouse, number, warehouse.scope.region, day)

    def retire(self, number, version, exchange=None):
        return retire_version(self.versions, number, version,
                              self.exchange if exchange is None else exchange)

    def retirement(self, number):
        return get_retirement(self.versions, number)

    @contextmanager
    def error(self, code):
        with self.assertRaises(DomainError) as caught:
            yield
        self.assertEqual(caught.exception.code, code)
