#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""ZooKeeper Library.

This [library](https://juju.is/docs/sdk/libraries) implements both sides of the
`zookeeper` [interface](https://juju.is/docs/sdk/relations).

The *provider* side of this interface is implemented by the
[zookeeper-k8s Charmed Operator](https://charmhub.io/zookeeper-k8s).

Any Charmed Operator that *requires* a ZooKeeper database for providing its
service should implement the *requirer* side of this interface.
[kafka-k8s](https://charmhub.io/kafka-k8s) is an example.

In a nutshell using this library to implement a Charmed Operator *requiring* a
ZooKeeper database (and talking to it as a ZooKeeper client) would look like

```
$ charmcraft fetch-lib charms.zookeeper_k8s.v0.zookeeper
```

`metadata.yaml`:

```
requires:
  zookeeper:
    interface: zookeeper
```

`src/charm.py`:

```
from charms.zookeeper_k8s.v0.zookeeper import ZooKeeperEvents, ZooKeeperRequires
from ops.charm import CharmBase


class MyCharm(CharmBase):

    on = ZooKeeperEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self.zookeeper = ZooKeeperRequires(self)
        self.framework.observe(
            self.on.zookeeper_clients_changed,
            self._on_zookeeper_clients_changed,
        )
        self.framework.observe(
            self.on.zookeeper_clients_broken,
            self._on_zookeeper_clients_broken,
        )

    def _on_zookeeper_clients_changed(self, event):
        # Get zookeeper client addresses
        client_addresses: str = self.zookeeper.hosts
        # client_addresses => "zk-0:2181,zk-1:2181"

    def _on_zookeeper_clients_broken(self, event):
        # Stop service
        # ...
        self.unit.status = BlockedStatus("need zookeeper relation")
```

You can file bugs
[here](https://github.com/charmed-osm/zookeeper-k8s-operator/issues)!
"""

import logging
from typing import Optional

from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource, Object
from ops.model import Relation

# The unique Charmhub library identifier, never change it
LIBID = "0d1db716e5cf45aa9177f4df6ad969ff"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 13


logger = logging.getLogger(__name__)

# Relation app data keys
HOSTS_APP_KEY = "hosts"


class _ClientsChangedEvent(EventBase):
    """Event emitted whenever there is a change in the zookeeper clients."""


class _ClientsBrokenEvent(EventBase):
    """Event emitted when the zookeeper clients are not available anymore."""


class ZooKeeperEvents(CharmEvents):
    """ZooKeeper events.

    This class defines the events that ZooKeeper can emit.

    Events:
        zookeeper_clients_changed (_ClientsBrokenEvent)
    """

    zookeeper_clients_changed = EventSource(_ClientsChangedEvent)
    zookeeper_clients_broken = EventSource(_ClientsBrokenEvent)


class ZooKeeperRequires(Object):
    """ZooKeeper requires relation."""

    def __init__(self, charm: CharmBase, endpoint_name: str = "zookeeper") -> None:
        """Constructor.

        Args:
            charm (CharmBase): The charm that implements the relation.
            endpoint_name (str): Endpoint name of the relation.
        """
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

    @property
    def hosts(self) -> Optional[str]:
        """Get zookeeper hosts.

        Returns:
            Optional[str]: Comma-listed zookeeper client hosts.
        """
        hosts = None
        relation: Relation = self.framework.model.get_relation(self._endpoint_name)
        if relation and relation.app and relation.data and relation.app in relation.data:
            hosts = relation.data[relation.app].get(HOSTS_APP_KEY)
        return hosts

    def _on_relation_changed(self, _):
        self.charm.on.zookeeper_clients_changed.emit()

    def _on_relation_broken(self, _):
        self.charm.on.zookeeper_clients_broken.emit()


class ZooKeeperProvides(Object):
    """ZooKeeper provides relation.

    Example:
        class ZooKeeperK8sCharm(CharmBase):
            on = ZooKeeperClusterEvents()

            def __init__(self, *args):
                super().__init__(*args)
                self.cluster = ZooKeeperCluster(self)
                self.zookeeper = ZooKeeperProvides(self)
                self.framework.observe(
                    self.on.zookeeper_relation_changed,
                    self._update_hosts
                )
                self.framework.observe(self.on.servers_changed, self._on_servers_changed)

            def _update_hosts(self, _=None):
                if self.unit.is_leader():
                    self.zookeeper.update_hosts(self.cluster.client_addresses)

            def _on_servers_changed(self, event):
                # Reload the service...
                self._update_hosts()
    """

    def __init__(self, charm: CharmBase, endpoint_name: str = "zookeeper") -> None:
        """Constructor.

        Args:
            charm (CharmBase): The charm that implements the relation.
            endpoint_name (str): Endpoint name of the relation.
        """
        super().__init__(charm, endpoint_name)
        self._endpoint_name = endpoint_name

    def update_hosts(self, client_addresses: str, relation_id: Optional[int] = None) -> None:
        """Update hosts in the zookeeper relation.

        This method will cause a relation-changed event in the requirer units
        of the relation.

        Args:
            client_addresses (str): Comma-listed addresses of zookeeper clients.
            relation_id (Optional[int]): Id of the relation. If set, it will be used to update
                                         the relation data of the specified relation. If not set,
                                         the data for all the relations will be updated.
        """
        relation: Relation
        if relation_id:
            relation = self.model.get_relation(self._endpoint_name, relation_id)
            self._update_hosts_in_relation(relation, client_addresses)
            relation.data[self.model.app][HOSTS_APP_KEY] = client_addresses
        else:
            for relation in self.model.relations[self._endpoint_name]:
                self._update_hosts_in_relation(relation, client_addresses)

    def _update_hosts_in_relation(self, relation: Relation, hosts: str) -> None:
        """Update hosts relation data if needed.

        Args:
            relation (Relation): Relation to be updated.
            hosts (str): String with the zookeeper hosts.
        """
        if relation.data[self.model.app].get(HOSTS_APP_KEY) != hosts:
            relation.data[self.model.app][HOSTS_APP_KEY] = hosts
