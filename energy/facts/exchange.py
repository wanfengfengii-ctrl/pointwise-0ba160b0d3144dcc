"""In-process trusted message exchange for demos and tests.

The three stores never read each other's files.  A caller supplies an
``exchange(target, message)`` callable that delivers a message to ``catalog``,
``east`` or ``west`` and returns that side's reply.  This class implements such
an exchange for serial use, with hooks to simulate an undelivered request
(``before_delivery``) or a delivered request whose reply is lost
(``before_reply``), plus ``deliver`` for replaying a message later.
"""

from energy.facts.posting import handle_warehouse_message
from energy.versions.handoff import DeliveryUnavailable
from energy.versions.retirement import handle_catalog_message


class LocalExchange:
    def __init__(self, versions, warehouses, *, before_delivery=None, before_reply=None):
        self.versions = versions
        self.warehouses = warehouses
        self.before_delivery = before_delivery
        self.before_reply = before_reply

    def handler(self, target):
        if target == 'catalog':
            return lambda message: handle_catalog_message(self.versions, message)
        if target in self.warehouses:
            warehouse = self.warehouses[target]
            return lambda message: handle_warehouse_message(warehouse, message)
        raise DeliveryUnavailable(f'unknown target {target!r}')

    def deliver(self, target, message):
        """Deliver one message without running the interleaving hooks."""
        return self.handler(target)(message)

    def __call__(self, target, message):
        if self.before_delivery is not None:
            self.before_delivery(target, message)
        reply = self.deliver(target, message)
        if self.before_reply is not None:
            self.before_reply(target, message, reply)
        return reply
