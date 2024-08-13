#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Balancer role core charm logic."""

import logging
from subprocess import CalledProcessError
from typing import TYPE_CHECKING

from ops import (
    ActionEvent,
    ActiveStatus,
    EventBase,
    InstallEvent,
    Object,
    pebble,
)
from ops.pebble import ExecError, Layer

from literals import (
    BALANCER,
    BALANCER_WEBSERVER_PORT,
    BALANCER_WEBSERVER_USER,
    CONTAINER,
    GROUP,
    MODE_ADD,
    MODE_REMOVE,
    USER,
    Status,
)
from managers.balancer import BalancerManager
from managers.config import BalancerConfigManager
from managers.tls import TLSManager
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

        self.tls_manager = TLSManager(
            state=self.charm.state,
            workload=self.workload,
            substrate=self.charm.substrate,
            config=self.charm.config,
        )

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
        self.framework.observe(self.charm.on.update_status, self._on_config_changed)
        self.framework.observe(self.charm.on.config_changed, self._on_config_changed)

        self.framework.observe(getattr(self.charm.on, "rebalance_action"), self.rebalance)

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

        if not self.charm.state.cluster.balancer_password:
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
        except (CalledProcessError, ExecError) as e:
            logger.warning(e.stdout)
            event.defer()
            return

        self.workload.start(layer=self._balancer_layer)
        logger.info("CruiseControl service started")

    def _on_config_changed(self, event: EventBase) -> None:
        """Generic handler for 'something changed' events."""
        if not self.healthy:
            return

        changed_map = [
            (
                "properties",
                self.workload.paths.cruise_control_properties,
                self.config_manager.cruise_control_properties,
            ),
            (
                "jass",
                self.workload.paths.balancer_jaas,
                self.config_manager.jaas_config.splitlines(),
            ),
        ]

        content_changed = False
        for kind, path, state_content in changed_map:
            file_content = self.workload.read(path)
            if set(file_content) ^ set(state_content):
                logger.info(
                    (
                        f"Balancer {self.charm.unit.name.split('/')[1]} updating config - "
                        f"OLD {kind.upper()} = {set(map(str.strip, file_content)) - set(map(str.strip, state_content))}"
                        f"NEW {kind.upper()} = {set(map(str.strip, state_content)) - set(map(str.strip, file_content))}"
                    )
                )
                content_changed = True

        if content_changed:
            # safe to update everything even if it hasn't changed, service will restart anyway
            self.config_manager.set_cruise_control_properties()
            self.config_manager.set_broker_capacities()
            self.config_manager.set_zk_jaas_config()

            self._on_start(event)

    def rebalance(self, event: ActionEvent) -> None:
        """Handles the `rebalance` Juju Action."""
        failure_conditions = [
            (not self.charm.unit.is_leader(), "Action must be ran on the application leader"),
            (
                not self.balancer_manager.cruise_control.monitoring,
                "CruiseControl balancer service is not yet ready",
            ),
            (
                self.balancer_manager.cruise_control.executing,
                "CruiseControl balancer service is currently executing a task, please try again later",
            ),
            (
                not self.balancer_manager.cruise_control.ready,
                "CruiseControl balancer service has not yet collected enough data to provide a partition reallocation proposal",
            ),
            (
                event.params.get("brokerid", None) is None
                and event.params["mode"] in (MODE_ADD, MODE_REMOVE),
                "'add' and 'remove' rebalance action require passing the 'brokerid' parameter",
            ),
            (
                event.params["mode"] in (MODE_ADD, MODE_REMOVE)
                and event.params.get("brokerid")
                not in [broker.unit_id for broker in self.charm.state.brokers],
                "invalid brokerid",
            ),
        ]

        for check, msg in failure_conditions:
            if check:
                event.fail(msg)
                return

        response, user_task_id = self.balancer_manager.rebalance(**event.params)
        logger.debug(f"rebalance - {vars(response)=}")

        if response.status_code != 200:
            event.fail(
                f"'{event.params['mode']}' rebalance failed with status code {response.status_code}"
            )
            return

        self.charm._set_status(Status.WAITING_FOR_REBALANCE)

        self.balancer_manager.wait_for_task(user_task_id)

        sanitised_response = self.balancer_manager.clean_results(response.json())
        if not isinstance(sanitised_response, dict):
            event.fail("Unknown error")
            return

        event.set_results(sanitised_response)

        self.charm._set_status(Status.ACTIVE)

    @property
    def healthy(self) -> bool:
        """Checks and updates various charm lifecycle states.

        Returns:
            True if service is alive and active. Otherwise False
        """
        if not self.charm.state.runs_balancer:
            return True

        self.charm._set_status(self.charm.state.ready_to_start)
        if not isinstance(self.charm.unit.status, ActiveStatus):
            return False

        if not self.workload.active() and self.charm.unit.is_leader():
            self.charm._set_status(Status.CC_NOT_RUNNING)
            return False

        return True
