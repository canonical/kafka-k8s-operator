#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Supporting objects for Kafka-Zookeeper relation."""

import logging
import subprocess
from typing import TYPE_CHECKING

from ops import Object, RelationChangedEvent, RelationEvent
from ops.pebble import ExecError

from core.literals import ZK, Status

if TYPE_CHECKING:
    from charm import KafkaK8sCharm

logger = logging.getLogger(__name__)


class ZooKeeperHandler(Object):
    """Implements the provider-side logic for client applications relating to Kafka."""

    def __init__(self, charm) -> None:
        super().__init__(charm, "zookeeper_client")
        self.charm: "KafkaK8sCharm" = charm

        self.framework.observe(self.charm.on[ZK].relation_created, self._on_zookeeper_created)
        self.framework.observe(self.charm.on[ZK].relation_joined, self._on_zookeeper_changed)
        self.framework.observe(self.charm.on[ZK].relation_changed, self._on_zookeeper_changed)
        self.framework.observe(self.charm.on[ZK].relation_broken, self._on_zookeeper_broken)

    def _on_zookeeper_created(self, _) -> None:
        """Handler for `zookeeper_relation_created` events."""
        if self.model.unit.is_leader():
            self.charm.state.zookeeper.update({"chroot": "/" + self.model.app.name})

    def _on_zookeeper_changed(self, event: RelationChangedEvent) -> None:
        """Handler for `zookeeper_relation_created/joined/changed` events, ensuring internal users get created."""
        if not self.charm.state.zookeeper.zookeeper_connected:
            logger.debug("No information found from ZooKeeper relation")
            self.charm._set_status(Status.ZK_NO_DATA)
            return

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.charm.state.cluster.tls_enabled ^ self.charm.state.zookeeper.tls:
            event.defer()
            self.charm._set_status(Status.ZK_TLS_MISMATCH)
            return

        # do not create users until certificate + keystores created
        # otherwise unable to authenticate to ZK
        if self.charm.state.cluster.tls_enabled and not self.charm.state.broker.certificate:
            event.defer()
            self.charm._set_status(Status.NO_CERT)
            return

        if not self.charm.state.cluster.internal_user_credentials and self.model.unit.is_leader():
            # loading the minimum config needed to authenticate to zookeeper
            self.charm.config_manager.set_zk_jaas_config()
            self.charm.config_manager.set_server_properties()

            try:
                internal_user_credentials = self.charm.create_internal_credentials()
            except (KeyError, RuntimeError, subprocess.CalledProcessError, ExecError) as e:
                logger.warning(str(e))
                event.defer()
                return

            # only set to relation data when all set
            for username, password in internal_user_credentials:
                self.charm.state.cluster.update({f"{username}-password": password})

        self.charm._on_config_changed(event)

    def _on_zookeeper_broken(self, _: RelationEvent) -> None:
        """Handler for `zookeeper_relation_broken` event, ensuring charm blocks."""
        self.charm.workload.stop()

        logger.info(f'Broker {self.model.unit.name.split("/")[1]} disconnected')
        self.charm._set_status(Status.ZK_NOT_RELATED)
