"""Balancer role core charm logic."""

import logging
from subprocess import CalledProcessError
from typing import TYPE_CHECKING

from ops import (
    ActiveStatus,
    EventBase,
    InstallEvent,
    Object,
    pebble,
)
from ops.pebble import Layer

from literals import (
    BALANCER,
    BALANCER_USER,
    BALANCER_WEBSERVER_PORT,
    CONTAINER,
    GROUP,
    USER,
    Status,
)
from managers.balancer import BalancerManager
from managers.config import BalancerConfigManager
from workload import BalancerWorkload

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class BalancerOperator(Object):
    """Implements the logic for the balancer."""

    def __init__(self, charm) -> None:
        super().__init__(charm, BALANCER.value)
        self.charm: "KafkaCharm" = charm

        self.workload = BalancerWorkload(container=self.charm.unit.get_container(CONTAINER))

        # Fast exit after workload instantiation, but before any event observer
        if BALANCER.value not in self.charm.config.roles or not self.charm.unit.is_leader():
            return

        self.config_manager = BalancerConfigManager(
            self.charm.state, self.workload, self.charm.config
        )
        self.balancer_manager = BalancerManager(self)

        self.framework.observe(self.charm.on.install, self._on_install)
        self.framework.observe(self.charm.on.start, self._on_start)
        self.framework.observe(
            getattr(self.charm.on, "kafka_pebble_ready"), self._on_kafka_pebble_ready
        )
        self.framework.observe(self.charm.on.leader_elected, self._on_start)

        # ensures data updates, eventually
        self.framework.observe(getattr(self.charm.on, "update_status"), self._on_config_changed)

    @property
    def _balancer_layer(self) -> Layer:
        """Returns a Pebble configuration layer for CruiseControl."""
        extra_opts = [
            # FIXME: Port already in use by the broker. To be fixed once we have CC_JMX_OPTS
            # f"-javaagent:{CharmedKafkaPaths(BROKER).jmx_prometheus_javaagent}={JMX_EXPORTER_PORT}:{CharmedKafkaPaths(BROKER).jmx_prometheus_config}",
            f"-Djava.security.auth.login.config={self.workload.paths.balancer_jaas}",
        ]
        command = f"{self.workload.paths.binaries_path}/bin/kafka-cruise-control-start.sh {self.workload.paths.cruise_control_properties}"

        layer_config: pebble.LayerDict = {
            "summary": "kafka layer",
            "description": "Pebble config layer for kafka",
            "services": {
                BALANCER.service: {
                    "override": "merge",
                    "summary": "balancer",
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

    def _on_install(self, event: InstallEvent) -> None:
        """Handler for `install` event."""
        if not self.charm.unit.get_container(CONTAINER).can_connect():
            event.defer()
            return

        self.config_manager.set_environment()

    def _on_start(self, event: EventBase) -> None:
        """Handler for `start` event."""
        self._on_kafka_pebble_ready(event)

    def _on_kafka_pebble_ready(self, event):
        self.charm._set_status(self.charm.state.ready_to_start)
        if not isinstance(self.charm.unit.status, ActiveStatus):
            event.defer()
            return

        if not self.charm.state.cluster.balancer_username:
            external_cluster = next(iter(self.charm.state.peer_clusters), None)
            payload = {
                "balancer-username": BALANCER_USER,
                "balancer-password": self.charm.workload.generate_password(),
                "balancer-uris": f"{self.charm.state.unit_broker.host}:{BALANCER_WEBSERVER_PORT}",
            }
            # Update relation data intra & extra cluster (if it exists)
            self.charm.state.cluster.update(payload)
            if external_cluster:
                external_cluster.update(payload)

        self.config_manager.set_cruise_control_properties()
        self.config_manager.set_broker_capacities()
        self.config_manager.set_zk_jaas_config()
        self.config_manager.set_cruise_control_auth()

        try:
            self.balancer_manager.create_internal_topics()
        except CalledProcessError as e:
            logger.warning(e.stdout)
            event.defer()
            return

        self.workload.start(layer=self._balancer_layer)
        logger.info("CruiseControl service started")

    def _on_config_changed(self, event: EventBase) -> None:
        """Generic handler for 'something changed' events."""
        if not self.healthy:
            event.defer()
            return

        properties = self.workload.read(self.workload.paths.cruise_control_properties)
        properties_changed = set(properties) ^ set(self.config_manager.cruise_control_properties)

        if properties_changed:
            logger.info(
                (
                    f'Balancer {self.charm.unit.name.split("/")[1]} updating config - '
                    f"OLD PROPERTIES = {set(properties) - set(self.config_manager.cruise_control_properties)}, "
                    f"NEW PROPERTIES = {set(self.config_manager.cruise_control_properties) - set(properties)}"
                )
            )
            self.config_manager.set_cruise_control_properties()

        if properties_changed:
            self._on_start(event)

    @property
    def healthy(self) -> bool:
        """Checks and updates various charm lifecycle states.

        Returns:
            True if service is alive and active. Otherwise False
        """
        self.charm._set_status(self.charm.state.ready_to_start)
        if not isinstance(self.charm.unit.status, ActiveStatus):
            return False

        if not self.workload.active() and self.charm.unit.is_leader():
            self.charm._set_status(Status.CC_NOT_RUNNING)
            return False

        return True
