"""Kafka library.

This [library](https://juju.is/docs/sdk/libraries) implements both sides of the
`kafka` [interface](https://juju.is/docs/sdk/relations).

The *provider* side of this interface is implemented by the
[kafka-k8s Charmed Operator](https://charmhub.io/kafka-k8s).

Any Charmed Operator that *requires* Kafka for providing its
service should implement the *requirer* side of this interface.

In a nutshell using this library to implement a Charmed Operator *requiring*
Kafka would look like

```
$ charmcraft fetch-lib charms.kafka_k8s.v0.kafka
```

`metadata.yaml`:

```
requires:
  kafka:
    interface: kafka
    limit: 1
```

`src/charm.py`:

```
from charms.kafka_k8s.v0.kafka import KafkaEvents, KafkaRequires
from ops.charm import CharmBase


class MyCharm(CharmBase):

    on = KafkaEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self.kafka = KafkaRequires(self)
        self.framework.observe(
            self.on.kafka_available,
            self._on_kafka_available,
        )
        self.framework.observe(
            self.on.kafka_broken,
            self._on_kafka_broken,
        )

    def _on_kafka_available(self, event):
        # Get Kafka host and port
        host: str = self.kafka.host
        port: int = self.kafka.port
        # host => "kafka-k8s"
        # port => 9092

    def _on_kafka_broken(self, event):
        # Stop service
        # ...
        self.unit.status = BlockedStatus("need kafka relation")
```

You can file bugs
[here](https://github.com/charmed-osm/kafka-k8s-operator/issues)!
"""

# The unique Charmhub library identifier, never change it
LIBID = "eacc8c85082347c9aae740e0220b8376"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1


from typing import Optional

from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource, Object
from ops.model import Relation

KAFKA_HOST_APP_KEY = "host"
KAFKA_PORT_APP_KEY = "port"


class _KafkaAvailableEvent(EventBase):
    """Event emitted when Kafka is available."""


class _KafkaBrokenEvent(EventBase):
    """Event emitted when Kafka relation is broken."""


class KafkaEvents(CharmEvents):
    """Kafka events.

    This class defines the events that Kafka can emit.

    Events:
        kafka_available (_KafkaAvailableEvent)
    """

    kafka_available = EventSource(_KafkaAvailableEvent)
    kafka_broken = EventSource(_KafkaBrokenEvent)


class KafkaRequires(Object):
    """Requires-side of the Kafka relation."""

    def __init__(self, charm: CharmBase, endpoint_name: str = "kafka") -> None:
        super().__init__(charm, endpoint_name)
        self.charm = charm
        self._endpoint_name = endpoint_name

        # Observe relation events
        event_observe_mapping = {
            charm.on[self._endpoint_name].relation_changed: self._on_relation_changed,
            charm.on[self._endpoint_name].relation_broken: self._on_relation_broken,
        }
        for event, observer in event_observe_mapping.items():
            self.framework.observe(event, observer)

    def _on_relation_changed(self, event) -> None:
        if all(
            key in event.relation.data[event.relation.app]
            for key in (KAFKA_HOST_APP_KEY, KAFKA_PORT_APP_KEY)
        ):
            self.charm.on.kafka_available.emit()

    def _on_relation_broken(self, _) -> None:
        self.charm.on.kafka_broken.emit()

    @property
    def host(self) -> str:
        relation: Relation = self.model.get_relation(self._relation_name)
        return relation.data[relation.app].get(KAFKA_HOST_APP_KEY) if relation else None

    @property
    def port(self) -> int:
        relation: Relation = self.model.get_relation(self._relation_name)
        return int(relation.data[relation.app].get(KAFKA_PORT_APP_KEY)) if relation else None


class KafkaProvides(Object):
    """Provides-side of the Kafka relation."""

    def __init__(self, charm: CharmBase, endpoint_name: str = "kafka") -> None:
        super().__init__(charm, endpoint_name)
        self._endpoint_name = endpoint_name

    def set_host_info(self, host: str, port: int, relation: Optional[Relation] = None) -> None:
        """Set Kafka host and port.

        This function writes in the application data of the relation, therefore,
        only the unit leader can call it.

        Args:
            host (str): Kafka hostname or IP address.
            port (int): Kafka port.
            relation (Optional[Relation]): Relation to update.
                                           If not specified, all relations will be updated.

        Raises:
            Exception: if a non-leader unit calls this function.
        """
        if not self.model.unit.is_leader():
            raise Exception("only the leader set host information.")

        if relation:
            self._update_relation_data(host, port, relation)
            return

        for relation in self.model.relations[self._endpoint_name]:
            self._update_relation_data(host, port, relation)

    def _update_relation_data(self, host: str, port: int, relation: Relation) -> None:
        """Update data in relation if needed."""
        relation.data[self.model.app][KAFKA_HOST_APP_KEY] = host
        relation.data[self.model.app][KAFKA_PORT_APP_KEY] = str(port)
