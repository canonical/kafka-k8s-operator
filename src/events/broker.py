"""Broker role core charm logic."""

import logging
from typing import TYPE_CHECKING

from ops import (
    ActiveStatus,
    EventBase,
    InstallEvent,
    Object,
    SecretChangedEvent,
    StartEvent,
    StatusBase,
    StorageAttachedEvent,
    StorageDetachingEvent,
    UpdateStatusEvent,
    pebble,
)
from ops.pebble import Layer

from events.oauth import OAuthHandler
from events.password_actions import PasswordActionEvents
from events.provider import KafkaProvider
from events.tls import TLSHandler
from events.upgrade import KafkaDependencyModel, KafkaUpgrade
from events.zookeeper import ZooKeeperHandler
from literals import (
    BROKER,
    CONTAINER,
    DEPENDENCIES,
    GROUP,
    JMX_EXPORTER_PORT,
    PEER,
    REL_NAME,
    USER,
    DebugLevel,
    Status,
)
from managers.auth import AuthManager
from managers.balancer import BalancerManager
from managers.config import ConfigManager
from managers.tls import TLSManager
from workload import KafkaWorkload

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class BrokerOperator(Object):
    """Charmed Operator for Kafka."""

    def __init__(self, charm) -> None:
        super().__init__(charm, BROKER.value)
        self.charm: "KafkaCharm" = charm

        self.workload = KafkaWorkload(container=self.charm.unit.get_container(CONTAINER))

        # Fast exit after workload instantiation, but before any event observer
        if BROKER.value not in self.charm.config.roles:
            return

        self.upgrade = KafkaUpgrade(
            self,
            substrate=self.charm.substrate,
            dependency_model=KafkaDependencyModel(
                **DEPENDENCIES  # pyright: ignore[reportArgumentType]
            ),
        )
        self.password_action_events = PasswordActionEvents(self)
        self.zookeeper = ZooKeeperHandler(self)
        self.tls = TLSHandler(self)
        self.provider = KafkaProvider(self)
        self.oauth = OAuthHandler(self)

        # MANAGERS

        self.config_manager = ConfigManager(
            state=self.charm.state,
            workload=self.workload,
            config=self.charm.config,
            current_version=self.upgrade.current_version,
        )
        self.tls_manager = TLSManager(
            state=self.charm.state, workload=self.workload, substrate=self.charm.substrate
        )
        self.auth_manager = AuthManager(
            state=self.charm.state,
            workload=self.workload,
            kafka_opts=self.config_manager.kafka_opts,
            log4j_opts=self.config_manager.tools_log4j_opts,
        )

        self.balancer_manager = BalancerManager(self)

        # ---

        self.framework.observe(getattr(self.charm.on, "install"), self._on_install)
        self.framework.observe(getattr(self.charm.on, "start"), self._on_start)
        self.framework.observe(
            getattr(self.charm.on, "kafka_pebble_ready"), self._on_kafka_pebble_ready
        )
        self.framework.observe(getattr(self.charm.on, "config_changed"), self._on_config_changed)
        self.framework.observe(getattr(self.charm.on, "update_status"), self._on_update_status)
        self.framework.observe(getattr(self.charm.on, "secret_changed"), self._on_secret_changed)

        self.framework.observe(self.charm.on[PEER].relation_changed, self._on_config_changed)

        self.framework.observe(
            getattr(self.charm.on, "data_storage_attached"), self._on_storage_attached
        )
        self.framework.observe(
            getattr(self.charm.on, "data_storage_detaching"), self._on_storage_detaching
        )

    @property
    def _kafka_layer(self) -> Layer:
        """Returns a Pebble configuration layer for Kafka."""
        extra_opts = [
            f"-javaagent:{self.workload.paths.jmx_prometheus_javaagent}={JMX_EXPORTER_PORT}:{self.workload.paths.jmx_prometheus_config}",
            f"-Djava.security.auth.login.config={self.workload.paths.zk_jaas}",
        ]
        command = f"{self.workload.paths.binaries_path}/bin/kafka-server-start.sh {self.workload.paths.server_properties}"

        layer_config: pebble.LayerDict = {
            "summary": "kafka layer",
            "description": "Pebble config layer for kafka",
            "services": {
                BROKER.service: {
                    "override": "replace",
                    "summary": "kafka",
                    "command": command,
                    "startup": "enabled",
                    "user": USER,
                    "group": GROUP,
                    "environment": {
                        "KAFKA_OPTS": " ".join(extra_opts),
                        # FIXME https://github.com/canonical/kafka-k8s-operator/issues/80
                        "JAVA_HOME": "/usr/lib/jvm/java-18-openjdk-amd64",
                        "LOG_DIR": self.workload.paths.logs_path,
                    },
                }
            },
        }
        return Layer(layer_config)

    def _on_kafka_pebble_ready(self, event: EventBase) -> None:
        """Handler for `start` event."""
        # don't want to run default pebble ready during upgrades
        if not self.upgrade.idle:
            return

        self._set_status(self.charm.state.ready_to_start)
        if not isinstance(self.charm.unit.status, ActiveStatus):
            event.defer()
            return

        # required settings given zookeeper connection config has been created
        self.config_manager.set_server_properties()
        self.config_manager.set_zk_jaas_config()
        self.config_manager.set_client_properties()

        # during pod-reschedules (e.g upgrades or otherwise) we lose all files
        # need to manually add-back key/truststores
        if (
            self.charm.state.cluster.tls_enabled
            and self.charm.state.unit_broker.certificate
            and self.charm.state.unit_broker.ca
        ):  # TLS is probably completed
            self.tls_manager.set_server_key()
            self.tls_manager.set_ca()
            self.tls_manager.set_certificate()
            self.tls_manager.set_truststore()
            self.tls_manager.set_keystore()

        # start kafka service
        self.workload.start(layer=self._kafka_layer)
        logger.info("Kafka service started")

        # service_start might fail silently, confirm with ZK if kafka is actually connected
        self.charm.on.update_status.emit()

    def _on_start(self, event: StartEvent) -> None:
        """Wrapper for start event."""
        if self.charm.state.peer_relation:
            self.charm.state.unit_broker.update(
                {"cores": str(self.balancer_manager.cores), "rack": self.config_manager.rack}
            )
        self._on_kafka_pebble_ready(event)

    def _on_install(self, event: InstallEvent) -> None:
        """Handler for `install` event."""
        if not self.charm.unit.get_container(CONTAINER).can_connect():
            event.defer()
            return

        self.charm.unit.set_workload_version(self.workload.get_version())
        self.config_manager.set_environment()

    def _on_config_changed(self, event: EventBase) -> None:
        """Generic handler for most `config_changed` events across relations."""
        if not self.upgrade.idle or not self.healthy:
            event.defer()
            return

        # Load current properties set in the charm workload
        properties = self.workload.read(self.workload.paths.server_properties)
        properties_changed = set(properties) ^ set(self.config_manager.server_properties)

        zk_jaas = self.workload.read(self.workload.paths.zk_jaas)
        zk_jaas_changed = set(zk_jaas) ^ set(self.config_manager.jaas_config.splitlines())

        if not properties or not zk_jaas:
            # Event fired before charm has properly started
            event.defer()
            return

        # update environment
        self.config_manager.set_environment()
        self.charm.unit.set_workload_version(self.workload.get_version())

        if zk_jaas_changed:
            clean_broker_jaas = [conf.strip() for conf in zk_jaas]
            clean_config_jaas = [
                conf.strip() for conf in self.config_manager.jaas_config.splitlines()
            ]
            logger.info(
                (
                    f'Broker {self.charm.unit.name.split("/")[1]} updating JAAS config - '
                    f"OLD JAAS = {set(clean_broker_jaas) - set(clean_config_jaas)}, "
                    f"NEW JAAS = {set(clean_config_jaas) - set(clean_broker_jaas)}"
                )
            )
            self.config_manager.set_zk_jaas_config()

        if properties_changed:
            logger.info(
                (
                    f'Broker {self.charm.unit.name.split("/")[1]} updating config - '
                    f"OLD PROPERTIES = {set(properties) - set(self.config_manager.server_properties)}, "
                    f"NEW PROPERTIES = {set(self.config_manager.server_properties) - set(properties)}"
                )
            )
            self.config_manager.set_server_properties()

        if zk_jaas_changed or properties_changed:
            self.charm.on[f"{self.charm.restart.name}"].acquire_lock.emit()

        # update client_properties whenever possible
        self.config_manager.set_client_properties()

        # If Kafka is related to client charms, update their information.
        if self.model.relations.get(REL_NAME, None) and self.charm.unit.is_leader():
            self.update_client_data()

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Handler for `update-status` events."""
        if not self.upgrade.idle or not self.healthy:
            return

        if not self.charm.state.zookeeper.broker_active():
            self._set_status(Status.ZK_NOT_CONNECTED)
            return

        # NOTE for situations like IP change and late integration with rack-awareness charm.
        # If properties have changed, the broker will restart.
        self.charm.on.config_changed.emit()

        self._set_status(Status.ACTIVE)

    def _on_secret_changed(self, event: SecretChangedEvent) -> None:
        """Handler for `secret_changed` events."""
        if not event.secret.label or not self.charm.state.cluster.relation:
            return

        if event.secret.label == self.charm.state.cluster.data_interface._generate_secret_label(
            PEER,
            self.charm.state.cluster.relation.id,
            "extra",  # pyright: ignore[reportArgumentType] -- Changes with the https://github.com/canonical/data-platform-libs/issues/124
        ):
            # TODO: figure out why creating internal credentials setting doesn't trigger changed event here
            self.charm.on.config_changed.emit()

    def _on_storage_attached(self, event: StorageAttachedEvent) -> None:
        """Handler for `storage_attached` events."""
        if (
            not self.charm.unit.get_container(CONTAINER).can_connect()
            or not self.charm.state.peer_relation
        ):
            event.defer()
            return

        self.charm.state.unit_broker.update({"storages": self.balancer_manager.storages})
        # checks first whether the broker is active before warning
        if self.workload.active():
            # new dirs won't be used until topic partitions are assigned to it
            # either automatically for new topics, or manually for existing
            self._set_status(Status.ADDED_STORAGE)
            self._on_config_changed(event)

    def _on_storage_detaching(self, _: StorageDetachingEvent) -> None:
        """Handler for `storage_detaching` events."""
        # in the case where there may be replication recovery may be possible
        if self.charm.state.peer_relation and len(self.charm.state.peer_relation.units):
            self._set_status(Status.REMOVED_STORAGE)
        else:
            self._set_status(Status.REMOVED_STORAGE_NO_REPL)

        self.charm.on.config_changed.emit()

    def _restart(self, event: EventBase) -> None:
        """Handler for `rolling_ops` restart events."""
        # only attempt restart if service is already active
        if not self.healthy:
            event.defer()
            return

        self.workload.restart()

        if self.healthy:
            logger.info(f'Broker {self.charm.unit.name.split("/")[1]} restarted')
        else:
            logger.error(f"Broker {self.charm.unit.name.split('/')[1]} failed to restart")

    @property
    def healthy(self) -> bool:
        """Checks and updates various charm lifecycle states.

        Is slow to fail due to retries, to be used sparingly.

        Returns:
            True if service is alive and active. Otherwise False
        """
        self._set_status(self.charm.state.ready_to_start)
        if not isinstance(self.charm.unit.status, ActiveStatus):
            return False

        if not self.workload.active():
            self._set_status(Status.BROKER_NOT_RUNNING)
            return False

        return True

    def update_client_data(self) -> None:
        """Writes necessary relation data to all related client applications."""
        if not self.charm.unit.is_leader() or not self.healthy:
            return

        for client in self.charm.state.clients:
            if not client.password:
                logger.debug(
                    f"Skipping update of {client.app.name}, user has not yet been added..."
                )
                continue

            client.update(
                {
                    "endpoints": client.bootstrap_server,
                    "zookeeper-uris": client.zookeeper_uris,
                    "consumer-group-prefix": client.consumer_group_prefix,
                    "topic": client.topic,
                    "username": client.username,
                    "password": client.password,
                    "tls": client.tls,
                    "tls-ca": client.tls,  # TODO: fix tls-ca
                }
            )

    def _set_status(self, key: Status) -> None:
        """Sets charm status."""
        status: StatusBase = key.value.status
        log_level: DebugLevel = key.value.log_level

        getattr(logger, log_level.lower())(status.message)
        self.charm.unit.status = status
