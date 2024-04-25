# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka in-place upgrades."""

import logging
from typing import TYPE_CHECKING

from charms.data_platform_libs.v0.upgrade import (
    ClusterNotReadyError,
    DataUpgrade,
    DependencyModel,
    EventBase,
    KubernetesClientError,
    verify_requirements,
)
from lightkube.core.client import Client
from lightkube.core.exceptions import ApiError
from lightkube.resources.apps_v1 import StatefulSet
from pydantic import BaseModel
from typing_extensions import override

from literals import Status

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)

ROLLBACK_INSTRUCTIONS = """Unit failed to upgrade and requires manual rollback to previous stable version.
    1. Re-run `pre-upgrade-check` action on the leader unit to enter 'recovery' state
    2. Run `juju refresh` to the previously deployed charm revision
"""


class KafkaDependencyModel(BaseModel):
    """Model for Kafka Operator dependencies."""

    kafka_service: DependencyModel


class KafkaUpgrade(DataUpgrade):
    """Implementation of :class:`DataUpgrade` overrides for in-place upgrades."""

    def __init__(self, charm: "KafkaCharm", **kwargs):
        super().__init__(charm, **kwargs)
        self.charm = charm

        self.framework.observe(
            getattr(self.charm.on, "upgrade_charm"), self._on_kafka_pebble_ready_upgrade
        )

    def _on_kafka_pebble_ready_upgrade(self, event: EventBase) -> None:
        """Handler for the `upgrade-charm` events handled during in-place upgrades."""
        # ensure pebble-ready only fires after normal peer-relation-driven server init
        if not self.charm.state.ready_to_start or self.idle:
            return

        dependency_model: DependencyModel = getattr(self.dependency_model, "kafka_service")
        if not verify_requirements(
            version=self.charm.state.zookeeper.zookeeper_version,
            requirement=dependency_model.dependencies["zookeeper"],
        ):
            logger.error(
                "Current ZooKeeper version %s does not meet requirement %s",
                self.charm.state.zookeeper.zookeeper_version,
                dependency_model.dependencies["zookeeper"],
            )
            self.set_unit_failed()
            return

        # required settings given zookeeper connection config has been created
        self.charm.config_manager.set_environment()
        self.charm.config_manager.set_server_properties()
        self.charm.config_manager.set_zk_jaas_config()
        self.charm.config_manager.set_client_properties()

        # during pod-reschedules (e.g upgrades or otherwise) we lose all files
        # need to manually add-back key/truststores
        if (
            self.charm.state.cluster.tls_enabled
            and self.charm.state.unit_broker.certificate
            and self.charm.state.unit_broker.ca
        ):  # TLS is probably completed
            self.charm.tls_manager.set_server_key()
            self.charm.tls_manager.set_ca()
            self.charm.tls_manager.set_certificate()
            self.charm.tls_manager.set_truststore()
            self.charm.tls_manager.set_keystore()

        # start kafka service
        self.charm.workload.start(layer=self.charm._kafka_layer)

        try:
            self.post_upgrade_check()
        except ClusterNotReadyError as e:
            logger.error(e.cause)
            self.set_unit_failed()
            return

        if not self.charm.state.zookeeper.broker_active():
            logger.error(Status.ZK_NOT_CONNECTED)
            self.set_unit_failed()
            return

        self.set_unit_completed()

    @property
    def idle(self) -> bool:
        """Checks if cluster state is idle.

        Returns:
            True if cluster state is idle. Otherwise False
        """
        return not bool(self.upgrade_stack)

    @property
    def current_version(self) -> str:
        """Get current Kafka version."""
        dependency_model: DependencyModel = getattr(self.dependency_model, "kafka_service")
        return dependency_model.version

    @override
    def pre_upgrade_check(self) -> None:
        default_message = "Pre-upgrade check failed and cannot safely upgrade"
        if not self.charm.healthy:
            raise ClusterNotReadyError(message=default_message, cause="Cluster is not healthy")

        if self.idle:
            self._set_rolling_update_partition(partition=len(self.charm.state.brokers) - 1)

    def post_upgrade_check(self) -> None:
        """Runs necessary checks validating the unit is in a healthy state after upgrade."""
        self.pre_upgrade_check()

        if not self.charm.workload.active:
            raise ClusterNotReadyError(
                message="Post-upgrade check failed and cannot safely upgrade",
                cause="Container service not ruunning",
            )

    @override
    def log_rollback_instructions(self) -> None:
        logger.critical(ROLLBACK_INSTRUCTIONS)

    @override
    def _set_rolling_update_partition(self, partition: int) -> None:
        """Set the rolling update partition to a specific value."""
        try:
            patch = {"spec": {"updateStrategy": {"rollingUpdate": {"partition": partition}}}}
            Client().patch(  # pyright: ignore [reportArgumentType]
                StatefulSet,
                name=self.charm.model.app.name,
                namespace=self.charm.model.name,
                obj=patch,
            )
            logger.debug(f"Kubernetes StatefulSet partition set to {partition}")
        except ApiError as e:
            if e.status.code == 403:
                cause = "`juju trust` needed"
            else:
                cause = str(e)
            raise KubernetesClientError("Kubernetes StatefulSet patch failed", cause)
