#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kafka K8s charm module."""

import logging
from typing import Any, Dict

from charms.kafka_k8s.v0.kafka import KafkaProvides
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from charms.zookeeper_k8s.v0.zookeeper import ZooKeeperEvents, ZooKeeperRequires
from lightkube.models.core_v1 import ServicePort
from ops.charm import CharmBase, ConfigChangedEvent, RelationJoinedEvent
from ops.framework import StoredState
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    Container,
    MaintenanceStatus,
    WaitingStatus,
)
from ops.pebble import ServiceStatus

logger = logging.getLogger(__name__)

KAFKA_PORT = 9092


def _convert_key_to_confluent_syntax(key: str) -> str:
    new_key = key.replace("_", "___").replace("-", "__").replace(".", "_")
    new_key = "".join([f"_{char}" if char.isupper() else char for char in new_key])
    return f"KAFKA_{new_key.upper()}"


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

        # Stored State
        self._stored.set_default(entrypoint_patched=False, kafka_started=False)

        # Patch K8s service port
        port = ServicePort(KAFKA_PORT, name=f"{self.app.name}")
        self.service_patcher = KubernetesServicePatch(self, [port])

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
            key, value = kafka_property.split("=")
            key = _convert_key_to_confluent_syntax(key)
            envs[key] = value
        return envs

    # ---------------------------------------------------------------------------
    #   Handlers for Charm Events
    # ---------------------------------------------------------------------------

    def _on_config_changed(self, event: ConfigChangedEvent) -> None:
        """Handler for the config-changed event."""
        # Validate charm configuration
        try:
            self._validate_config()
        except Exception as e:
            self.unit.status = BlockedStatus(f"{e}")
            return

        # Check Pebble has started in the container
        container: Container = self.unit.get_container("kafka")
        if not container.can_connect():
            logger.debug("waiting for pebble to start")
            self.unit.status = MaintenanceStatus("waiting for pebble to start")
            return

        # Check zookeeper
        if not self.zookeeper.hosts:
            self.unit.status = BlockedStatus("need zookeeper relation")
            return

        # Add Pebble layer with the kafka service
        self._patch_entrypoint(container)
        container.add_layer("kafka", self._get_kafka_layer(), combine=True)
        container.replan()

        # Update kafka information
        if not self._stored.kafka_started and self.unit.is_leader():
            self.kafka.set_host_info(self.app.name, KAFKA_PORT)
        self._stored.kafka_started = True

        # Update charm status
        self._on_update_status()

    def _on_update_status(self, _=None) -> None:
        """Handler for the update-status event."""
        # Check zookeeper
        if not self.zookeeper.hosts:
            self.unit.status = BlockedStatus("need zookeeper relation")
            return

        # Check if the kafka service is configured
        container: Container = self.unit.get_container("kafka")
        if not container.can_connect() or "kafka" not in container.get_plan().services:
            self.unit.status = WaitingStatus("kafka service not configured yet")
            return

        # Check if the kafka service is running
        if container.get_service("kafka").current == ServiceStatus.ACTIVE:
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = BlockedStatus("kafka service is not running")

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
            Exception: if charm configuration is invalid.
        """
        pass

    def _patch_entrypoint(self, container: Container) -> None:
        """Patch entrypoint.

        This function pushes what will be the main entrypoint for the kafka service.
        The pushed entrypoint is a wrapper to the default one, that unsets the environment
        variables that Kubernetes autommatically creates that conflict with the expected
        environment variables by the container.

        Args:
            container (Container): Container where the entrypoint will be pushed.
        """
        if self._stored.entrypoint_patched:
            return
        with open("templates/entrypoint", "r") as f:
            container.push(
                "/entrypoint",
                f.read(),
                permissions=0o777,
            )
        self._stored.entrypoint_patched = True

    def _get_kafka_layer(self) -> Dict[str, Any]:
        """Get Kafka layer for Pebble."""
        return {
            "summary": "kafka layer",
            "description": "pebble config layer for kafka",
            "services": {
                "kafka": {
                    "override": "replace",
                    "summary": "kafka service",
                    "command": "/entrypoint",
                    "startup": "enabled",
                    "environment": {
                        "CHARM_NAME": self.app.name.upper().replace("-", "_"),
                        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                        "LANG": "C.UTF-8",
                        "CUB_CLASSPATH": '"/usr/share/java/cp-base-new/*"',
                        "container": "oci",
                        "COMPONENT": "kafka",
                        "KAFKA_ZOOKEEPER_CONNECT": self.zookeeper.hosts,
                        **self.kafka_properties,
                    },
                }
            },
        }


if __name__ == "__main__":  # pragma: no cover
    main(KafkaK8sCharm)
