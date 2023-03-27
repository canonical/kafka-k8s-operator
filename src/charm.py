#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging
from typing import MutableMapping, Optional

from charms.data_platform_libs.v0.data_models import TypedCharmBase
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.rolling_ops.v0.rollingops import RollingOpsManager
from ops import pebble
from ops.charm import (
    ActionEvent,
    LeaderElectedEvent,
    PebbleReadyEvent,
    RelationEvent,
    RelationJoinedEvent,
    StorageAttachedEvent,
    StorageDetachingEvent,
)
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Container, Relation, WaitingStatus
from ops.pebble import Layer, PathError, ProtocolError

from auth import KafkaAuth
from config import KafkaConfig
from literals import (
    ADMIN_USER,
    CHARM_KEY,
    CONTAINER,
    INTER_BROKER_USER,
    JMX_EXPORTER_PORT,
    PEER,
    REL_NAME,
    ZOOKEEPER_REL_NAME,
)
from provider import KafkaProvider
from structured_config import CharmConfig
from tls import KafkaTLS
from utils import broker_active, generate_password

logger = logging.getLogger(__name__)


class KafkaK8sCharm(TypedCharmBase[CharmConfig]):
    """Charmed Operator for Kafka K8s."""

    config_type = CharmConfig

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY
        self.kafka_config = KafkaConfig(self)
        self.client_relations = KafkaProvider(self)
        self.tls = KafkaTLS(self)
        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart)
        self.metrics_endpoint = MetricsEndpointProvider(
            self,
            jobs=[{"static_configs": [{"targets": [f"*:{JMX_EXPORTER_PORT}"]}]}],
        )
        self.grafana_dashboards = GrafanaDashboardProvider(self)
        self.loki_push = LogProxyConsumer(
            self,
            log_files=["/opt/kafka/logs/server.log"],
            relation_name="logging",
            container_name="kafka",
        )

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
        self.framework.observe(getattr(self.on, "rolling_restart_unit_action"), self._restart)
        self.framework.observe(
            getattr(self.on, "get_admin_credentials_action"), self._get_admin_credentials_action
        )

        self.framework.observe(
            getattr(self.on, "log_data_storage_attached"), self._on_storage_attached
        )
        self.framework.observe(
            getattr(self.on, "log_data_storage_detaching"), self._on_storage_detaching
        )

    @property
    def container(self) -> Container:
        """Grabs the current Kafka container."""
        return self.unit.get_container(CONTAINER)

    @property
    def _kafka_layer(self) -> Layer:
        """Returns a Pebble configuration layer for Kafka."""
        layer_config: pebble.LayerDict = {
            "summary": "kafka layer",
            "description": "Pebble config layer for kafka",
            "services": {
                CONTAINER: {
                    "override": "replace",
                    "summary": "kafka",
                    "command": self.kafka_config.kafka_command,
                    "startup": "enabled",
                    "environment": {"KAFKA_OPTS": " ".join(self.kafka_config.extra_args)},
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

    def _on_storage_attached(self, event: StorageAttachedEvent) -> None:
        """Handler for `storage_attached` events."""
        # checks first whether the broker is active before warning
        if not self.kafka_config.zookeeper_connected or not broker_active(
            unit=self.unit, zookeeper_config=self.kafka_config.zookeeper_config
        ):
            return

        # new dirs won't be used until topic partitions are assigned to it
        # either automatically for new topics, or manually for existing
        message = (
            "manual partition reassignment may be needed for Kafka to utilize new storage volumes"
        )
        logger.warning(f"attaching storage - {message}")
        self.unit.status = ActiveStatus(message)

        self._on_config_changed(event)

    def _on_storage_detaching(self, event: StorageDetachingEvent) -> None:
        """Handler for `storage_detaching` events."""
        # checks first whether the broker is active before warning
        if not self.kafka_config.zookeeper_connected or not broker_active(
            unit=self.unit, zookeeper_config=self.kafka_config.zookeeper_config
        ):
            return

        # in the case where there may be replication recovery may be possible
        if self.peer_relation and len(self.peer_relation.units):
            message = "manual partition reassignment from replicated brokers recommended due to lost partitions on removed storage volumes"
            logger.warning(f"removing storage - {message}")
            self.unit.status = BlockedStatus(message)
        else:
            message = "potential log-data loss due to storage removal without replication"
            logger.error(f"removing storage - {message}")
            self.unit.status = BlockedStatus(message)

        self._on_config_changed(event)

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
        self.kafka_config.set_zk_jaas_config()
        self.kafka_config.set_client_properties()

        # do not start units until SCRAM users have been added to ZooKeeper for server-server auth
        # set internal passwords
        if self.unit.is_leader():
            for username, password in self.kafka_config.internal_user_credentials.items():
                updated_user = self.update_internal_user(username=username, password=password)
                # do not continue until both internal users are updated
                if not updated_user:
                    event.defer()
                    return

            # updating non-leader units of creation of internal users
            self.peer_relation.data[self.app].update({"broker-creds": "added"})

        # for non-leader units
        if not self.ready_to_start:
            event.defer()
            return

        # start kafka service
        self.container.add_layer(CONTAINER, self._kafka_layer, combine=True)
        self.container.replan()

        # service_start might fail silently, confirm with ZK if kafka is actually connected
        if broker_active(
            unit=self.unit,
            zookeeper_config=self.kafka_config.zookeeper_config,
        ):
            logger.info(f'Broker {self.unit.name.split("/")[1]} connected')
            self.unit_peer_data.update({"state": "started"})
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = BlockedStatus("kafka unit not connected to ZooKeeper")
            return

    def _on_config_changed(self, event: EventBase) -> None:
        """Generic handler for most `config_changed` events across relations."""
        if not self.ready_to_start:
            event.defer()
            return

        # Load current properties set in the charm workload
        raw_properties = None
        try:
            raw_properties = str(
                self.container.pull(self.kafka_config.server_properties_filepath).read()
            )
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
            self.kafka_config.set_client_properties()

            self.on[f"{self.restart.name}"].acquire_lock.emit()

        # If Kafka is related to client charms, update their information.
        if self.model.relations.get(REL_NAME, None) and self.unit.is_leader():
            self.client_relations.update_connection_info()

    def _on_leader_elected(self, event: LeaderElectedEvent) -> None:
        """Handler for `leader_elected` event, ensuring internal user passwords get set."""
        if not self.peer_relation:
            logger.debug("no peer relation")
            event.defer()
            return

        self.set_internal_passwords()

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
        self.container.stop(CONTAINER)
        self.unit.status = BlockedStatus("missing required zookeeper relation")

    def _set_password_action(self, event: ActionEvent) -> None:
        """Handler for set-password action.

        Set the password for a specific user, if no passwords are passed, generate them.
        """
        if not self.peer_relation:
            logger.debug("no peer relation")
            event.defer()
            return

        if not self.unit.is_leader():
            msg = "Password rotation must be called on leader unit"
            logger.error(msg)
            event.fail(msg)
            return

        username = event.params["username"]
        new_password = event.params.get("password", generate_password())

        if new_password in self.kafka_config.internal_user_credentials.values():
            msg = "Password already exists, please choose a different password."
            logger.error(msg)
            event.fail(msg)
            return

        user_updated = self.update_internal_user(username=username, password=new_password)
        if not user_updated:
            event.fail("Unable to update user.")
            return

        # Store the password on application databag
        self.set_secret(scope="app", key=f"{username}-password", value=new_password)
        event.set_results({f"{username}-password": new_password})

    def _restart(self, event: EventBase) -> None:
        """Handler for `rolling_ops` restart events."""
        # ensures service isn't referenced before pebble ready
        if not self.unit_peer_data.get("state", None) == "started":
            event.defer()
            return

        self.container.restart(CONTAINER)

        if broker_active(
            unit=self.unit,
            zookeeper_config=self.kafka_config.zookeeper_config,
        ):
            logger.info(f'Broker {self.unit.name.split("/")[1]} restarted')
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = BlockedStatus(
                f"Broker {self.unit.name.split('/')[1]} failed to restart"
            )
            return

    @property
    def ready_to_start(self) -> bool:
        """Check for active ZooKeeper relation and adding of inter-broker auth username.

        Returns:
            True if ZK is related and `sync` user has been added. False otherwise.
        """
        if not self.peer_relation:
            logger.debug("no peer relation")
            return False

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.tls.enabled ^ (
            self.kafka_config.zookeeper_config.get("tls", "disabled") == "enabled"
        ):
            msg = "TLS must be enabled for Zookeeper and Kafka"
            logger.error(msg)
            self.unit.status = BlockedStatus(msg)
            return False

        if not self.kafka_config.zookeeper_connected or not self.peer_relation.data[self.app].get(
            "broker-creds", None
        ):
            return False

        return True

    def _get_admin_credentials_action(self, event: ActionEvent) -> None:
        raw_properties = str(
            self.container.pull(self.kafka_config.client_properties_filepath).read()
        )
        client_properties = raw_properties.splitlines()

        if not client_properties:
            msg = "client.properties file not found on target unit."
            logger.error(msg)
            event.fail(msg)
            return

        admin_properties = set(client_properties) - set(self.kafka_config.tls_properties)

        event.set_results(
            {
                "username": ADMIN_USER,
                "password": self.kafka_config.internal_user_credentials[ADMIN_USER],
                "client-properties": "\n".join(admin_properties),
            }
        )

    def update_internal_user(self, username: str, password: str) -> bool:
        """Updates internal SCRAM usernames and passwords."""
        if not self.unit.is_leader():
            logger.debug("Cannot update internal user from non-leader unit.")
            return False

        if username not in [INTER_BROKER_USER, ADMIN_USER]:
            msg = f"Can only update internal charm users: {INTER_BROKER_USER} or {ADMIN_USER}, not {username}."
            logger.error(msg)
            return False

        # do not start units until SCRAM users have been added to ZooKeeper for server-server auth
        kafka_auth = KafkaAuth(
            self,
            opts=self.kafka_config.auth_args,
            zookeeper=self.kafka_config.zookeeper_config.get("connect", ""),
            container=self.container,
        )
        try:
            kafka_auth.add_user(
                username=username,
                password=password,
            )
            return True

        except Exception as e:
            # command to add users fails if attempted too early
            logger.info(f"Exception: {str(e)}")
            return False

    def set_internal_passwords(self) -> None:
        """Sets inter-broker and admin user passwords to app relation data."""
        if not self.unit.is_leader():
            return

        for password in [f"{INTER_BROKER_USER}-password", f"{ADMIN_USER}-password"]:
            current_password = self.get_secret(scope="app", key=password)
            self.set_secret(
                scope="app", key=password, value=(current_password or generate_password())
            )

    def get_secret(self, scope: str, key: str) -> Optional[str]:
        """Get TLS secret from the secret storage.

        Args:
            scope: whether this secret is for a `unit` or `app`
            key: the secret key name

        Returns:
            String of key value.
            None if non-existent key
        """
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
