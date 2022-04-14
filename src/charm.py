#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kafka K8s charm module."""

import logging
from typing import Any, Dict

from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.kafka_k8s.v0.kafka import KafkaProvides
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.rolling_ops.v0.rollingops import RollingOpsManager
from charms.zookeeper_k8s.v0.zookeeper import ZooKeeperEvents, ZooKeeperRequires
from lightkube.models.core_v1 import ServicePort
from ops.charm import CharmBase, RelationJoinedEvent
from ops.framework import StoredState
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    Container,
    MaintenanceStatus,
    ModelError,
    StatusBase,
    WaitingStatus,
)
from ops.pebble import PathError, ServiceStatus

logger = logging.getLogger(__name__)

KAFKA_PORT = 9092


def _convert_key_to_confluent_syntax(key: str) -> str:
    new_key = key.replace("_", "___").replace("-", "__").replace(".", "_")
    new_key = "".join([f"_{char}" if char.isupper() else char for char in new_key])
    return f"KAFKA_{new_key.upper()}"


class CharmError(Exception):
    """Charm Error Exception."""

    def __init__(self, message: str, status: StatusBase = BlockedStatus) -> None:
        self.message = message
        self.status = status


class KafkaK8sCharm(CharmBase):
    """Kafka K8s Charm operator."""

    on = ZooKeeperEvents()
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self.kafka = KafkaProvides(self)
        self.zookeeper = ZooKeeperRequires(self)

        # Observe charm events
        event_observe_mapping = {
            self.on.kafka_pebble_ready: self._on_config_changed,
            self.on.config_changed: self._on_config_changed,
            self.on.update_status: self._on_update_status,
            self.on.zookeeper_clients_changed: self._on_config_changed,
            self.on.zookeeper_clients_broken: self._on_zookeeper_clients_broken,
            self.on.kafka_relation_joined: self._on_kafka_relation_joined,
        }
        for event, observer in event_observe_mapping.items():
            self.framework.observe(event, observer)

        self.replan_manager = RollingOpsManager(
            charm=self, relation="replan", callback=self._replan
        )

        # Stored State
        self._stored.set_default(kafka_started=False)

        # Patch K8s service port
        port = ServicePort(KAFKA_PORT, name=f"{self.app.name}")
        self.service_patcher = KubernetesServicePatch(self, [port])

        # Prometheus and Grafana integration
        self.metrics_endpoint = MetricsEndpointProvider(
            self, jobs=[{"static_configs": [{"targets": ["*:1234"]}]}]
        )
        self.grafana_dashboard_provider = GrafanaDashboardProvider(self)

    # ---------------------------------------------------------------------------
    #   Properties
    # ---------------------------------------------------------------------------

    @property
    def kafka_properties(self) -> Dict[str, Any]:
        """Get Kafka environment variables.

        This function uses the configuration kafka-properties to generate the
        environment variables needed to configure Kafka and in the format expected
        by the container.

        Returns:
            Dictionary with the environment variables needed for Kafka container.
        """
        envs = {}
        for kafka_property in self.config["kafka-properties"].splitlines():
            if "=" not in kafka_property:
                continue
            key, value = kafka_property.strip().split("=")
            key = _convert_key_to_confluent_syntax(key)
            envs[key] = value
        return envs

    # ---------------------------------------------------------------------------
    #   Handlers for Charm Events
    # ---------------------------------------------------------------------------

    def _on_config_changed(self, event) -> None:
        """If _replan has not yet been run, run it.

        If we are in the middle of a running environment, schedule a replan with the
        rolling ops manager.

        """
        if not self._stored.kafka_started:
            # On first start, let all the kafka instances come up together.
            return self._replan(event)

        # In a running cluster, coordinate replans so that only one unit does so at a
        # time.
        self.on[self.replan_manager.name].acquire_lock.emit()

    def _replan(self, event) -> None:
        """Process config and run replan."""
        try:
            self._validate_config()
            self._check_relations()
            container: Container = self.unit.get_container("kafka")
            self._check_container_ready(container)
            # Add Pebble layer with the kafka service
            self._patch_entrypoint(container)
            self._setup_metrics(container)
            container.add_layer("kafka", self._get_kafka_layer(), combine=True)
            container.replan()

            # Update kafka information
            if not self._stored.kafka_started and self.unit.is_leader():
                self.kafka.set_host_info(self.app.name, KAFKA_PORT)
            self._stored.kafka_started = True

            # Update charm status
            self._on_update_status()
        except CharmError as e:
            logger.debug(e.message)
            self.unit.status = e.status(e.message)

    def _on_update_status(self, _=None) -> None:
        """Handler for the update-status event."""
        try:
            self._check_relations()
            container: Container = self.unit.get_container("kafka")
            self._check_container_ready(container)
            self._check_service_configured(container)
            self._check_service_active(container)
            self.unit.status = ActiveStatus()
        except CharmError as e:
            logger.debug(e.message)
            self.unit.status = e.status(e.message)

    def _on_zookeeper_clients_broken(self, _) -> None:
        """Handler for the zookeeper-clients-broken event."""
        # Check Pebble has started in the container
        container: Container = self.unit.get_container("kafka")
        if (
            container.can_connect()
            and "kafka" in container.get_plan().services
            and container.get_service("kafka").current == ServiceStatus.ACTIVE
        ):
            logger.debug("Stopping kafka service")
            container.stop("kafka")

        # Update charm status
        self.unit.status = BlockedStatus("need zookeeper relation")

    def _on_kafka_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Handler for the kafka-relation-joined event."""
        if self._stored.kafka_started and self.unit.is_leader():
            self.kafka.set_host_info(self.app.name, KAFKA_PORT, event.relation)

    # ---------------------------------------------------------------------------
    #   Validation and configuration
    # ---------------------------------------------------------------------------

    def _validate_config(self) -> None:
        """Validate charm configuration.

        Raises:
            CharmError: if charm configuration is invalid.
        """
        pass

    def _check_relations(self) -> None:
        """Check required relations.

        Raises:
            CharmError: if relations are missing.
        """
        if not self.zookeeper.hosts:
            raise CharmError("need zookeeper relation")

    def _check_container_ready(self, container: Container) -> None:
        """Check Pebble has started in the container.

        Args:
            container (Container): Container to be checked.

        Raises:
            CharmError: if container is not ready.
        """
        if not container.can_connect():
            raise CharmError("waiting for pebble to start", MaintenanceStatus)

    def _check_service_configured(self, container: Container) -> None:
        """Check if kafka service has been successfully configured.

        Args:
            container (Container): Container to be checked.

        Raises:
            CharmError: if kafka service has not been configured.
        """
        if "kafka" not in container.get_plan().services:
            raise CharmError("kafka service not configured yet", WaitingStatus)

    def _check_service_active(self, container: Container) -> None:
        """Check if the kafka service is running.

        Raises:
            CharmError: if kafka service is not running.
        """
        if container.get_service("kafka").current != ServiceStatus.ACTIVE:
            raise CharmError("kafka service is not running")

    def _patch_entrypoint(self, container: Container) -> None:
        """Patch entrypoint.

        This function pushes what will be the main entrypoint for the kafka service.
        The pushed entrypoint is a wrapper to the default one, that unsets the environment
        variables that Kubernetes autommatically creates that conflict with the expected
        environment variables by the container.

        Args:
            container (Container): Container where the entrypoint will be pushed.
        """
        if self._file_exists(container, "/entrypoint"):
            return
        with open("templates/entrypoint", "r") as f:
            container.push(
                "/entrypoint",
                f.read(),
                permissions=0o777,
            )

    def _setup_metrics(self, container: Container) -> None:
        """Setup metrics.

        Args:
            container (Container): Container where the the metrics will be setup.
        """
        if self.config.get("metrics"):
            container.make_dir("/opt/prometheus", make_parents=True, permissions=0o555)
            with open("templates/kafka_broker.yml", "r") as f:
                container.push("/opt/prometheus/kafka_broker.yml", f)
            try:
                resource_path = self.model.resources.fetch("jmx-prometheus-jar")
                with open(resource_path, "rb") as f:
                    container.push("/opt/prometheus/jmx_prometheus_javaagent.jar", f)
            except ModelError:
                raise CharmError("Missing 'jmx-prometheus-jar' resource")

    def _get_kafka_layer(self) -> Dict[str, Any]:
        """Get Kafka layer for Pebble.

        Returns:
            Dict[str, Any]: Pebble layer.
        """
        env_variables = {
            "CHARM_NAME": self.app.name.upper().replace("-", "_"),
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            "CUB_CLASSPATH": '"/usr/share/java/cp-base-new/*"',
            "container": "oci",
            "COMPONENT": "kafka",
            "KAFKA_ZOOKEEPER_CONNECT": self.zookeeper.hosts,
            **self.kafka_properties,
        }
        if self.config.get("metrics"):
            env_variables[
                "KAFKA_OPTS"
            ] = "-javaagent:/opt/prometheus/jmx_prometheus_javaagent.jar=1234:/opt/prometheus/kafka_broker.yml"

        return {
            "summary": "kafka layer",
            "description": "pebble config layer for kafka",
            "services": {
                "kafka": {
                    "override": "replace",
                    "summary": "kafka service",
                    "command": "/entrypoint",
                    "startup": "enabled",
                    "environment": env_variables,
                }
            },
        }

    def _file_exists(self, container: Container, path: str) -> bool:
        """Check if a file exists in the container.

        Args:
            path (str): Path of the file to be checked.

        Returns:
            bool: True if the file exists, else False.
        """
        file_exists = None
        try:
            _ = container.pull(path)
            file_exists = True
        except PathError:
            file_exists = False
        exist_str = "exists" if file_exists else 'doesn"t exist'
        logger.debug(f"File {path} {exist_str}.")
        return file_exists


if __name__ == "__main__":  # pragma: no cover
    main(KafkaK8sCharm)
