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
    RelationChangedEvent,
    RelationCreatedEvent,
    RelationEvent,
    StorageAttachedEvent,
    StorageDetachingEvent,
)
from ops.framework import EventBase
from ops.main import main
from ops.model import Container, Relation, StatusBase
from ops.pebble import ExecError, Layer, PathError, ProtocolError

from auth import KafkaAuth
from config import KafkaConfig
from literals import (
    ADMIN_USER,
    CHARM_KEY,
    CONTAINER,
    INTERNAL_USERS,
    JAVA_HOME,
    JMX_EXPORTER_PORT,
    LOGS_PATH,
    PEER,
    REL_NAME,
    ZOOKEEPER_REL_NAME,
    METRICS_RULES_DIR,
    LOGS_RULES_DIR,
    DebugLevel,
    Status,
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
            alert_rules_path=METRICS_RULES_DIR,
        )
        self.grafana_dashboards = GrafanaDashboardProvider(self)
        self.loki_push = LogProxyConsumer(
            self,
            log_files=[f"{LOGS_PATH}/server.log"],
            alert_rules_path=LOGS_RULES_DIR,
            relation_name="logging",
            container_name="kafka",
        )

        self.framework.observe(getattr(self.on, "kafka_pebble_ready"), self._on_kafka_pebble_ready)
        self.framework.observe(getattr(self.on, "config_changed"), self._on_config_changed)
        self.framework.observe(getattr(self.on, "update_status"), self._on_update_status)

        self.framework.observe(self.on[PEER].relation_changed, self._on_config_changed)

        self.framework.observe(
            self.on[ZOOKEEPER_REL_NAME].relation_created, self._on_zookeeper_created
        )
        self.framework.observe(
            self.on[ZOOKEEPER_REL_NAME].relation_joined, self._on_zookeeper_changed
        )
        self.framework.observe(
            self.on[ZOOKEEPER_REL_NAME].relation_changed, self._on_zookeeper_changed
        )
        self.framework.observe(
            self.on[ZOOKEEPER_REL_NAME].relation_broken, self._on_zookeeper_broken
        )

        self.framework.observe(getattr(self.on, "set_password_action"), self._set_password_action)
        self.framework.observe(
            getattr(self.on, "get_admin_credentials_action"), self._get_admin_credentials_action
        )

        self.framework.observe(
            getattr(self.on, "data_storage_attached"), self._on_storage_attached
        )
        self.framework.observe(
            getattr(self.on, "data_storage_detaching"), self._on_storage_detaching
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
                    "user": "kafka",
                    "group": "kafka",
                    "environment": {
                        "KAFKA_OPTS": " ".join(self.kafka_config.extra_args),
                        "JAVA_HOME": JAVA_HOME,
                        "LOG_DIR": LOGS_PATH,
                    },
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

    @property
    def ready_to_start(self) -> bool:
        """Check for active ZooKeeper relation and adding of inter-broker auth username.

        Returns:
            True if ZK is related and `sync` user has been added. False otherwise.
        """
        if not self.peer_relation:
            self._set_status(Status.NO_PEER_RELATION)
            return False

        if not self.kafka_config.zookeeper_related:
            self._set_status(Status.ZK_NOT_RELATED)
            return False

        if not self.kafka_config.zookeeper_connected:
            self._set_status(Status.ZK_NO_DATA)
            return False

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.tls.enabled ^ (
            self.kafka_config.zookeeper_config.get("tls", "disabled") == "enabled"
        ):
            self._set_status(Status.ZK_TLS_MISMATCH)
            return False

        if not self.kafka_config.internal_user_credentials:
            self._set_status(Status.NO_BROKER_CREDS)
            return False

        return True

    @property
    def healthy(self) -> bool:
        """Checks and updates various charm lifecycle states.

        Is slow to fail due to retries, to be used sparingly.

        Returns:
            True if service is alive and active. Otherwise False
        """
        if not self.ready_to_start:
            return False

        if not self.container.get_service("kafka").is_running():
            self._set_status(Status.SERVICE_NOT_RUNNING)
            return False

        return True

    def _on_update_status(self, _: EventBase) -> None:
        """Handler for `update-status` events."""
        if not self.healthy:
            return

        if not broker_active(
            unit=self.unit,
            zookeeper_config=self.kafka_config.zookeeper_config,
        ):
            self._set_status(Status.ZK_NOT_CONNECTED)
            return

        self._set_status(Status.ACTIVE)

    def _on_storage_attached(self, event: StorageAttachedEvent) -> None:
        """Handler for `storage_attached` events."""
        # checks first whether the broker is active before warning
        if not self.ready_to_start:
            return

        # new dirs won't be used until topic partitions are assigned to it
        # either automatically for new topics, or manually for existing
        self._set_status(Status.ADDED_STORAGE)
        self._on_config_changed(event)

    def _on_storage_detaching(self, event: StorageDetachingEvent) -> None:
        """Handler for `storage_detaching` events."""
        # in the case where there may be replication recovery may be possible
        if self.peer_relation and len(self.peer_relation.units):
            self._set_status(Status.REMOVED_STORAGE)
        else:
            self._set_status(Status.REMOVED_STORAGE_NO_REPL)

        self._on_config_changed(event)

    def _on_zookeeper_created(self, event: RelationCreatedEvent) -> None:
        """Handler for `zookeeper_relation_created` events."""
        if self.unit.is_leader():
            event.relation.data[self.app].update({"chroot": "/" + self.app.name})

    def _on_zookeeper_changed(self, event: RelationChangedEvent) -> None:
        """Handler for `zookeeper_relation_created/joined/changed` events, ensuring internal users get created."""
        if not self.container.can_connect():
            event.defer()
            return

        if not self.kafka_config.zookeeper_connected:
            self._set_status(Status.ZK_NO_DATA)
            event.defer()
            return

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.tls.enabled ^ (
            self.kafka_config.zookeeper_config.get("tls", "disabled") == "enabled"
        ):
            event.defer()
            self._set_status(Status.ZK_TLS_MISMATCH)
            return

        # do not create users until certificate + keystores created
        # otherwise unable to authenticate to ZK
        if self.tls.enabled and not self.tls.certificate:
            event.defer()
            self._set_status(Status.NO_CERT)
            return

        if not self.kafka_config.internal_user_credentials and self.unit.is_leader():
            # loading the minimum config needed to authenticate to zookeeper
            self.kafka_config.set_environment()
            self.kafka_config.set_zk_jaas_config()
            self.kafka_config.set_server_properties()

            try:
                internal_user_credentials = self._create_internal_credentials()
            except (KeyError, RuntimeError, ExecError) as e:
                logger.warning(str(e))
                event.defer()
                return

            # only set to relation data when all set
            for username, password in internal_user_credentials:
                self.set_secret(scope="app", key=f"{username}-password", value=password)

        self._on_config_changed(event)

    def _on_zookeeper_broken(self, event: RelationEvent) -> None:
        """Handler for `zookeeper_relation_departed/broken` events."""
        if not self.container.can_connect():
            event.defer()
            return

        logger.info("stopping kafka service")
        self.container.stop(CONTAINER)
        self._set_status(Status.ZK_NOT_RELATED)

    def _on_kafka_pebble_ready(self, event: EventBase) -> None:
        """Handler for `start` event."""
        if not self.ready_to_start:
            event.defer()
            return

        # required settings given zookeeper connection config has been created
        self.kafka_config.set_environment()
        self.kafka_config.set_server_properties()
        self.kafka_config.set_zk_jaas_config()
        self.kafka_config.set_client_properties()

        # start kafka service
        self.container.add_layer(CONTAINER, self._kafka_layer, combine=True)
        self.container.replan()

        # flag that the unit has actually started the new layer service, not default
        self.unit_peer_data.update({"started": "True"})

        # service_start might fail silently, confirm with ZK if kafka is actually connected
        self._on_update_status(event)

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

    def _restart(self, event: EventBase) -> None:
        """Handler for `rolling_ops` restart events."""
        # only attempt restart if service is already active
        if not self.healthy or not self.unit_peer_data.get("started", ""):
            event.defer()
            return

        self.container.restart(CONTAINER)

        if self.healthy:
            logger.info(f'Broker {self.unit.name.split("/")[1]} restarted')
        else:
            logger.error(f"Broker {self.unit.name.split('/')[1]} failed to restart")

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

    def _set_password_action(self, event: ActionEvent) -> None:
        """Handler for set-password action.

        Set the password for a specific user, if no passwords are passed, generate them.
        """
        if not self.unit.is_leader():
            msg = "Password rotation must be called on leader unit"
            logger.error(msg)
            event.fail(msg)
            return

        if not self.healthy:
            event.defer()
            return

        username = event.params["username"]
        new_password = event.params.get("password", generate_password())

        if new_password in self.kafka_config.internal_user_credentials.values():
            msg = "Password already exists, please choose a different password."
            logger.error(msg)
            event.fail(msg)
            return

        try:
            self._update_internal_user(username=username, password=new_password)
        except Exception as e:
            logger.error(str(e))
            event.fail(f"unable to set password for {username}")

        # Store the password on application databag
        self.set_secret(scope="app", key=f"{username}-password", value=new_password)
        event.set_results({f"{username}-password": new_password})

    def _update_internal_user(self, username: str, password: str) -> None:
        """Updates internal SCRAM usernames and passwords.

        Raises:
            RuntimeError if called from non-leader unit
            KeyError if attempted to update non-leader unit
            ExecError if command to ZooKeeper failed
        """
        if not self.unit.is_leader():
            raise RuntimeError("Cannot update internal user from non-leader unit.")

        if username not in INTERNAL_USERS:
            raise KeyError(
                f"Can only update internal charm users: {INTERNAL_USERS}, not {username}."
            )

        # do not start units until SCRAM users have been added to ZooKeeper for server-server auth
        kafka_auth = KafkaAuth(self)
        kafka_auth.add_user(
            username=username,
            password=password,
        )

    def _create_internal_credentials(self) -> list[tuple[str, str]]:
        """Creates internal SCRAM users during cluster start.

        Returns:
            List of (username, password) for all internal users

        Raises:
            RuntimeError if called from non-leader unit
            KeyError if attempted to update non-leader unit
            subprocess.CalledProcessError if command to ZooKeeper failed
        """
        credentials = [(username, generate_password()) for username in INTERNAL_USERS]
        for username, password in credentials:
            self._update_internal_user(username=username, password=password)

        return credentials

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

    def _set_status(self, key: Status) -> None:
        """Sets charm status."""
        status: StatusBase = key.value.status
        log_level: DebugLevel = key.value.log_level

        getattr(logger, log_level.lower())(status.message)
        self.unit.status = status


if __name__ == "__main__":
    main(KafkaK8sCharm)
