#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging

from charms.data_platform_libs.v0.data_models import TypedCharmBase
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.rolling_ops.v0.rollingops import RollingOpsManager
from ops import pebble
from ops.charm import (
    ActionEvent,
    StorageAttachedEvent,
    StorageDetachingEvent,
)
from ops.framework import EventBase
from ops.main import main
from ops.model import StatusBase
from ops.pebble import Layer, PathError, ProtocolError

from core.cluster import ClusterState
from core.literals import (
    ADMIN_USER,
    CHARM_KEY,
    CONTAINER,
    INTERNAL_USERS,
    JMX_EXPORTER_PORT,
    LOGS_RULES_DIR,
    METRICS_RULES_DIR,
    PEER,
    REL_NAME,
    DebugLevel,
    Status,
    Substrate,
)
from core.structured_config import CharmConfig
from events.provider import KafkaProvider
from events.tls import TLSHandler
from events.zookeeper import ZooKeeperHandler
from k8s_workload import KafkaWorkload
from managers.auth import AuthManager
from managers.config import KafkaConfigManager
from managers.tls import TLSManager

logger = logging.getLogger(__name__)


class KafkaK8sCharm(TypedCharmBase[CharmConfig]):
    """Charmed Operator for Kafka K8s."""

    config_type = CharmConfig

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY
        self.substrate: Substrate = "k8s"
        self.workload = KafkaWorkload(container=self.unit.get_container(CONTAINER))
        self.state = ClusterState(self, substrate=self.substrate)

        # HANDLERS

        self.zookeeper = ZooKeeperHandler(self)
        self.tls = TLSHandler(self)
        self.provider = KafkaProvider(self)

        # MANAGERS

        self.config_manager = KafkaConfigManager(self.state, self.workload, self.config)
        self.tls_manager = TLSManager(self.state, self.workload)
        self.auth_manager = AuthManager(self.state, self.workload, self.config_manager.kafka_opts)

        self.restart = RollingOpsManager(self, relation="restart", callback=self._restart)
        self.metrics_endpoint = MetricsEndpointProvider(
            self,
            jobs=[{"static_configs": [{"targets": [f"*:{JMX_EXPORTER_PORT}"]}]}],
            alert_rules_path=METRICS_RULES_DIR,
        )
        self.grafana_dashboards = GrafanaDashboardProvider(self)
        self.loki_push = LogProxyConsumer(
            self,
            log_files=[f"{self.workload.paths.logs_path}/server.log"],
            alert_rules_path=LOGS_RULES_DIR,
            relation_name="logging",
            container_name="kafka",
        )

        self.framework.observe(getattr(self.on, "kafka_pebble_ready"), self._on_kafka_pebble_ready)
        self.framework.observe(getattr(self.on, "config_changed"), self._on_config_changed)
        self.framework.observe(getattr(self.on, "update_status"), self._on_update_status)

        self.framework.observe(self.on[PEER].relation_changed, self._on_config_changed)

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
    def _kafka_layer(self) -> Layer:
        """Returns a Pebble configuration layer for Kafka."""
        layer_config: pebble.LayerDict = {
            "summary": "kafka layer",
            "description": "Pebble config layer for kafka",
            "services": {
                CONTAINER: {
                    "override": "replace",
                    "summary": "kafka",
                    "command": f"{self.workload.paths.binaries_path}/bin/kafka-server-start.sh {self.workload.paths.server_properties}",
                    "startup": "enabled",
                    "user": "kafka",
                    "group": "kafka",
                    "environment": {
                        "KAFKA_OPTS": " ".join(self.config_manager.kafka_opts),
                        "KAFKA_JMX_OPTS": " ".join(self.config_manager.jmx_opts),
                        "JAVA_HOME": self.workload.paths.java_home,
                        "LOG_DIR": self.workload.paths.logs_path,
                    },
                }
            },
        }
        return Layer(layer_config)

    def _on_kafka_pebble_ready(self, event: EventBase) -> None:
        """Handler for `start` event."""
        if not self.state.ready_to_start:
            event.defer()
            return

        # required settings given zookeeper connection config has been created
        self.config_manager.set_environment()
        self.config_manager.set_server_properties()
        self.config_manager.set_zk_jaas_config()
        self.config_manager.set_client_properties()

        # start kafka service
        self.workload.start(layer=self._kafka_layer)

        # service_start might fail silently, confirm with ZK if kafka is actually connected
        self._on_update_status(event)

    def _on_config_changed(self, event: EventBase) -> None:
        """Generic handler for most `config_changed` events across relations."""
        if not self.healthy:
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

    def _on_update_status(self, event: EventBase) -> None:
        """Handler for `update-status` events."""
        if not self.healthy:
            return

        if not self.state.zookeeper.broker_active():
            self._set_status(Status.ZK_NOT_CONNECTED)
            return

        # NOTE for situations like IP change and late integration with rack-awareness charm.
        # If properties have changed, the broker will restart.
        self._on_config_changed(event)

        self._set_status(Status.ACTIVE)

    def _on_storage_attached(self, event: StorageAttachedEvent) -> None:
        """Handler for `storage_attached` events."""
        # checks first whether the broker is active before warning
        if not self.state.ready_to_start:
            return

        # new dirs won't be used until topic partitions are assigned to it
        # either automatically for new topics, or manually for existing
        self._set_status(Status.ADDED_STORAGE)
        self._on_config_changed(event)

    def _on_storage_detaching(self, event: StorageDetachingEvent) -> None:
        """Handler for `storage_detaching` events."""
        # in the case where there may be replication recovery may be possible
        if self.state.peer_relation and len(self.state.peer_relation.units):
            self._set_status(Status.REMOVED_STORAGE)
        else:
            self._set_status(Status.REMOVED_STORAGE_NO_REPL)

        self._on_config_changed(event)

    def _restart(self, event: EventBase) -> None:
        """Handler for `rolling_ops` restart events."""
        # only attempt restart if service is already active
        if not self.healthy:
            event.defer()
            return

        self.workload.restart()

        if self.healthy:
            logger.info(f'Broker {self.unit.name.split("/")[1]} restarted')
        else:
            logger.error(f"Broker {self.unit.name.split('/')[1]} failed to restart")

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
            msg = "Unit is not healthy"
            logger.error(msg)
            event.fail(msg)
            return

        username = event.params["username"]
        new_password = event.params.get("password", self.workload.generate_password())

        if new_password in self.state.cluster.internal_user_credentials.values():
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
        self.state.cluster.relation_data.update({f"{username}-password": new_password})
        event.set_results({f"{username}-password": new_password})

    def _get_admin_credentials_action(self, event: ActionEvent) -> None:
        client_properties = self.workload.read(self.workload.paths.client_properties)

        if not client_properties:
            msg = "client.properties file not found on target unit."
            logger.error(msg)
            event.fail(msg)
            return

        admin_properties = set(client_properties) - set(self.config_manager.tls_properties)

        event.set_results(
            {
                "username": ADMIN_USER,
                "password": self.state.cluster.internal_user_credentials[ADMIN_USER],
                "client-properties": "\n".join(admin_properties),
            }
        )

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
        self.auth_manager.add_user(
            username=username,
            password=password,
            zk_auth=True,
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
        credentials = [
            (username, self.workload.generate_password()) for username in INTERNAL_USERS
        ]
        for username, password in credentials:
            self._update_internal_user(username=username, password=password)

        return credentials

    @property
    def healthy(self) -> bool:
        """Checks and updates various charm lifecycle states.

        Is slow to fail due to retries, to be used sparingly.

        Returns:
            True if service is alive and active. Otherwise False
        """
        if not self.state.ready_to_start:
            return False

        if not self.workload.active():
            self._set_status(Status.SERVICE_NOT_RUNNING)
            return False

        return True

    def _set_status(self, key: Status) -> None:
        """Sets charm status."""
        status: StatusBase = key.value.status
        log_level: DebugLevel = key.value.log_level

        getattr(logger, log_level.lower())(status.message)
        self.unit.status = status


if __name__ == "__main__":
    main(KafkaK8sCharm)
