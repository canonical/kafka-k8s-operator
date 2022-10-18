#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging
from typing import MutableMapping, Optional

from charms.rolling_ops.v0.rollingops import RollingOpsManager
from ops.charm import (
    ActionEvent,
    CharmBase,
    ConfigChangedEvent,
    PebbleReadyEvent,
    RelationEvent,
    RelationJoinedEvent,
)
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Container, Relation, WaitingStatus
from ops.pebble import ExecError, Layer, PathError, ProtocolError
from ops import pebble

from auth import KafkaAuth
from config import KafkaConfig
from literals import CHARM_KEY, CHARM_USERS, PEER, REL_NAME, ZOOKEEPER_REL_NAME
from provider import KafkaProvider
from tls import KafkaTLS
from utils import broker_active, generate_password

logger = logging.getLogger(__name__)


class KafkaK8sCharm(CharmBase):
    """Charmed Operator for Kafka K8s."""

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY
        self.kafka_config = KafkaConfig(self)
        self.client_relations = KafkaProvider(self)
        self.tls = KafkaTLS(self)
        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart)

        self.framework.observe(getattr(self.on, "kafka_pebble_ready"), self._on_kafka_pebble_ready)
        self.framework.observe(getattr(self.on, "leader_elected"), self._on_leader_elected)
        self.framework.observe(getattr(self.on, "config_changed"), self._on_config_changed)
        self.framework.observe(self.on[PEER].relation_changed, self._on_config_changed)

        self.framework.observe(
            self.on[ZOOKEEPER_REL_NAME].relation_joined, self._on_zookeeper_joined
        )
        self.framework.observe(
            self.on[ZOOKEEPER_REL_NAME].relation_changed, self._on_config_changed
        )
        self.framework.observe(
            self.on[ZOOKEEPER_REL_NAME].relation_broken, self._on_zookeeper_broken
        )

        self.framework.observe(getattr(self.on, "set_password_action"), self._set_password_action)

    @property
    def container(self) -> Container:
        """Grabs the current Kafka container."""
        return self.unit.get_container(CHARM_KEY)

    @property
    def _kafka_layer(self) -> Layer:
        """Returns a Pebble configuration layer for Kafka."""
        layer_config: pebble.LayerDict = {
            "summary": "kafka layer",
            "description": "Pebble config layer for kafka",
            "services": {
                CHARM_KEY: {
                    "override": "replace",
                    "summary": "kafka",
                    "command": self.kafka_config.kafka_command,
                    "startup": "enabled",
                    "environment": {"KAFKA_OPTS": self.kafka_config.extra_args},
                }
            },
        }
        return Layer(layer_config)

    @property
    def peer_relation(self) -> Optional[Relation]:
        """The cluster peer relation."""
        return self.model.get_relation(PEER)

    @property
    def app_peer_data(self) -> MutableMapping[str, str]:
        """Application peer relation data object."""
        if not self.peer_relation:
            return {}

        return self.peer_relation.data[self.app]

    @property
    def unit_peer_data(self) -> MutableMapping[str, str]:
        """Unit peer relation data object."""
        if not self.peer_relation:
            return {}

        return self.peer_relation.data[self.unit]

    def _on_kafka_pebble_ready(self, event: PebbleReadyEvent) -> None:
        """Handler for `kafka_pebble_ready` event."""
        if not self.container.can_connect():
            event.defer()
            return

        if not self.kafka_config.zookeeper_connected:
            self.unit.status = WaitingStatus("waiting for zookeeper relation")
            event.defer()
            return

        # required settings given zookeeper connection config has been created
        self.kafka_config.set_server_properties()
        self.kafka_config.set_jaas_config()

        # do not start units until SCRAM users have been added to ZooKeeper for server-server auth
        if self.unit.is_leader() and self.kafka_config.sync_password:
            kafka_auth = KafkaAuth(
                charm=self,
                opts=[self.kafka_config.extra_args],
                zookeeper=self.kafka_config.zookeeper_config.get("connect", ""),
                container=self.container,
            )
            try:
                kafka_auth.add_user(username="sync", password=self.kafka_config.sync_password)
                self.app_peer_data.update({"broker-creds": "added"})
            except ExecError as e:
                logger.debug(str(e))
                event.defer()
                return

        # for non-leader units
        if not self.ready_to_start:
            event.defer()
            return

        # start kafka service
        self.container.add_layer(CHARM_KEY, self._kafka_layer, combine=True)
        self.container.replan()

        # start_snap_service can fail silently, confirm with ZK if kafka is actually connected
        if broker_active(
            unit=self.unit,
            zookeeper_config=self.kafka_config.zookeeper_config,
        ):
            logger.info(f'Broker {self.unit.name.split("/")[1]} connected')
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = BlockedStatus("kafka unit not connected to ZooKeeper")
            return

    def _on_config_changed(self, event: ConfigChangedEvent) -> None:
        """Generic handler for most `config_changed` events across relations."""
        if not self.ready_to_start:
            event.defer()
            return

        # Load current properties set in the charm workload
        raw_properties = None
        try:
            raw_properties = str(self.container.pull(self.kafka_config.properties_filepath).read())
            properties = raw_properties.splitlines()
        except (ProtocolError, PathError) as e:
            logger.debug(str(e))
            event.defer()
            return
        if not raw_properties:
            # Event fired before charm has properly started
            event.defer()
            return

        if set(properties) ^ set(self.kafka_config.server_properties):
            logger.info(
                (
                    f'Broker {self.unit.name.split("/")[1]} updating config - '
                    f"OLD PROPERTIES = {set(properties) - set(self.kafka_config.server_properties)}, "
                    f"NEW PROPERTIES = {set(self.kafka_config.server_properties) - set(properties)}"
                )
            )
            self.kafka_config.set_server_properties()

            self.on[f"{self.restart.name}"].acquire_lock.emit()

        # If Kafka is related to client charms, update their information.
        if self.model.relations.get(REL_NAME, None) and self.unit.is_leader():
            self.client_relations.update_connection_info()

    def _on_leader_elected(self, _) -> None:
        """Handler for `leader_elected` event, ensuring sync_passwords gets set."""
        sync_password = self.kafka_config.sync_password
        self.set_secret(
            scope="app", key="sync_password", value=(sync_password or generate_password())
        )

    def _on_zookeeper_joined(self, event: RelationJoinedEvent) -> None:
        """Handler for `zookeeper_relation_joined` event, ensuring chroot gets set."""
        if self.unit.is_leader():
            event.relation.data[self.app].update({"chroot": "/" + self.app.name})

    def _on_zookeeper_broken(self, event: RelationEvent) -> None:
        """Handler for `zookeeper_relation_departed/broken` events."""
        if not self.container.can_connect():
            event.defer()
            return

        logger.info("stopping kafka service")
        self.container.stop(CHARM_KEY)
        self.unit.status = BlockedStatus("missing required zookeeper relation")

    def _set_password_action(self, event: ActionEvent) -> None:
        """Handler for set-password action.

        Set the password for a specific user, if no passwords are passed, generate them.
        """
        if not self.unit.is_leader():
            msg = "Password rotation must be called on leader unit"
            logger.error(msg)
            event.fail(msg)
            return

        username = event.params.get("username", "sync")
        if username not in CHARM_USERS:
            msg = f"The action can be run only for users used by the charm: {CHARM_USERS} not {username}."
            logger.error(msg)
            event.fail(msg)
            return

        new_password = event.params.get("password", generate_password())

        if new_password == self.kafka_config.sync_password:
            event.log("The old and new passwords are equal.")
            event.set_results({f"{username}-password": new_password})
            return

        # Update the user
        kafka_auth = KafkaAuth(
            charm=self,
            opts=[self.kafka_config.extra_args],
            zookeeper=self.kafka_config.zookeeper_config.get("connect", ""),
            container=self.container,
        )
        try:
            kafka_auth.add_user(username="sync", password=new_password)
        except ExecError as e:
            logger.error(str(e))
            event.fail(str(e))
            return

        # Store the password on application databag
        self.set_secret(scope="app", key=f"{username}_password", value=new_password)
        event.set_results({f"{username}-password": new_password})

    def _restart(self, event: EventBase) -> None:
        """Handler for `rolling_ops` restart events."""
        if not self.ready_to_start:
            event.defer()
            return

        self.container.restart(CHARM_KEY)

    @property
    def ready_to_start(self) -> bool:
        """Check for active ZooKeeper relation and adding of inter-broker auth username.

        Returns:
            True if ZK is related and `sync` user has been added. False otherwise.
        """
        # SSL must be enabled for Kafka and ZK or disabled for both
        if self.tls.enabled ^ (
            self.kafka_config.zookeeper_config.get("tls", "disabled") == "enabled"
        ):
            msg = "TLS needs to be active for Zookeeper and Kafka"
            logger.debug(msg)
            self.unit.status = BlockedStatus(msg)
            return False

        if not self.kafka_config.zookeeper_connected or not self.app_peer_data.get(
            "broker-creds", None
        ):
            return False

        return True

    def get_secret(self, scope: str, key: str) -> Optional[str]:
        """Get TLS secret from the secret storage.

        Args:
            scope: whether this secret is for a `unit` or `app`
            key: the secret key name

        Returns:
            String of key value.
            None if non-existent key
        """
        if not self.app_peer_data or not self.unit_peer_data:
            return None

        if scope == "unit":
            return self.unit_peer_data.get(key, None)
        elif scope == "app":
            return self.app_peer_data.get(key, None)
        else:
            raise RuntimeError("Unknown secret scope.")

    def set_secret(self, scope: str, key: str, value: Optional[str]) -> None:
        """Get TLS secret from the secret storage.

        Args:
            scope: whether this secret is for a `unit` or `app`
            key: the secret key name
            value: the value for the secret key
        """
        if scope == "unit":
            if not value:
                self.unit_peer_data.update({key: ""})
                return
            self.unit_peer_data.update({key: value})
        elif scope == "app":
            if not value:
                self.unit_peer_data.update({key: ""})
                return
            self.app_peer_data.update({key: value})
        else:
            raise RuntimeError("Unknown secret scope.")


if __name__ == "__main__":
    main(KafkaK8sCharm)
