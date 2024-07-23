"""Balancer role core charm logic."""

import logging
from subprocess import CalledProcessError
from typing import TYPE_CHECKING

from ops import (
    ActiveStatus,
    EventBase,
    Object,
)

from literals import (
    BALANCER,
    BALANCER_WEBSERVER_PORT,
    BALANCER_WEBSERVER_USER,
    CONTAINER,
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
        self.framework.observe(self.charm.on.leader_elected, self._on_start)

        # ensures data updates, eventually
        self.framework.observe(getattr(self.charm.on, "update_status"), self._on_config_changed)

    def _on_install(self, _) -> None:
        """Handler for `install` event."""
        self.config_manager.set_environment()

    def _on_start(self, event: EventBase) -> None:
        """Handler for `start` event."""
        self.charm._set_status(self.charm.state.ready_to_start)
        if not isinstance(self.charm.unit.status, ActiveStatus):
            event.defer()
            return

        if not self.charm.state.cluster.balancer_username:
            external_cluster = next(iter(self.charm.state.peer_clusters), None)
            payload = {
                "balancer-username": BALANCER_WEBSERVER_USER,
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

        self.workload.restart()

        logger.info("Cruise-control started")

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
