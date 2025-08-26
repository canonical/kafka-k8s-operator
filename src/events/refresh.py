#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Apache Kafka in-place upgrades."""

import abc
import dataclasses
import logging
from typing import TYPE_CHECKING

import charm_refresh
from lightkube.core.client import Client
from lightkube.core.exceptions import ApiError
from lightkube.resources.apps_v1 import StatefulSet

if TYPE_CHECKING:
    from charm import KafkaCharm

logger = logging.getLogger(__name__)


class KafkaUpgradeError(Exception):
    """Exception raised when Apache Kafka upgrade fails."""


@dataclasses.dataclass(eq=False)
class KafkaRefresh(charm_refresh.CharmSpecificCommon, abc.ABC):
    """Base class for Apache Kafka refresh operations."""

    _charm: "KafkaCharm"

    @classmethod
    def is_compatible(
        cls,
        *,
        old_charm_version: charm_refresh.CharmVersion,
        new_charm_version: charm_refresh.CharmVersion,
        old_workload_version: str,
        new_workload_version: str,
    ) -> bool:
        """Checks charm version compatibility."""
        if not super().is_compatible(
            old_charm_version=old_charm_version,
            new_charm_version=new_charm_version,
            old_workload_version=old_workload_version,
            new_workload_version=new_workload_version,
        ):
            return False

        return is_workload_compatible(
            old_workload_version=old_workload_version,
            new_workload_version=new_workload_version,
        )

    def run_pre_refresh_checks_after_1_unit_refreshed(self) -> None:
        """Implement pre-refresh checks after 1 unit refreshed."""
        logger.debug("Running pre-refresh checks")
        if (
            self._charm.state.runs_balancer
            and not self._charm.state.runs_broker
            and not self._charm.state.runs_controller
        ):
            raise charm_refresh.PrecheckFailed("Refresh not supported on balancer-only nodes.")
        if not self._charm.broker.healthy:
            raise charm_refresh.PrecheckFailed("Cluster is not healthy")


@dataclasses.dataclass(eq=False)
class KubernetesKafkaRefresh(KafkaRefresh, charm_refresh.CharmSpecificKubernetes):
    """Refresh handler for Kafka charm on Kubernetes substrate."""

    def run_pre_refresh_checks_after_1_unit_refreshed(self) -> None:
        """Implement pre-refresh checks after 1 unit refreshed."""
        super().run_pre_refresh_checks_after_1_unit_refreshed()
        if self._charm.unit.is_leader():
            self._set_rolling_update_partition(partition=len(self._charm.state.brokers) - 1)

    def _set_rolling_update_partition(self, partition: int) -> None:
        """Set the rolling update partition to a specific value."""
        try:
            patch = {"spec": {"updateStrategy": {"rollingUpdate": {"partition": partition}}}}
            Client().patch(  # pyright: ignore [reportArgumentType]
                StatefulSet,
                name=self._charm.model.app.name,
                namespace=self._charm.model.name,
                obj=patch,
            )
            logger.debug(f"Kubernetes StatefulSet partition set to {partition}")
        except ApiError as e:
            raise KafkaUpgradeError("Kubernetes StatefulSet patch failed", str(e))


def is_workload_compatible(
    old_workload_version: str,
    new_workload_version: str,
) -> bool:
    """Check if the workload versions are compatible."""
    try:
        old_major, old_minor, *_ = (
            int(component) for component in old_workload_version.split(".")
        )
        new_major, new_minor, *_ = (
            int(component) for component in new_workload_version.split(".")
        )
    except ValueError:
        # Not enough values to unpack or cannot convert
        logger.info(
            "Unable to parse workload versions."
            f"Got {old_workload_version} to {new_workload_version}"
        )
        return False

    if old_major != new_major:
        logger.info(
            "Refreshing to a different major workload is not supported. "
            f"Got {old_major} to {new_major}"
        )
        return False

    if not new_minor >= old_minor:
        logger.info(
            "Downgrading to a previous minor workload is not supported. "
            f"Got {old_major}.{old_minor} to {new_major}.{new_minor}"
        )
        return False

    # TODO: Once more releases are made, MetadataVersion.java on upstream needs to be checked.
    # Rollback is not supported when metadata version has changes. The last field on the version
    # lets us know if there are rollback incompatible changes.
    # Examples:
    # Valid refresh and rollback path
    # IBP_3_9_IV0(21, "3.9", "IV0", false) --> IBP_4_0_IV0(22, "4.0", "IV0", false)
    # Valid refresh, but not rollback path
    # IBP_4_0_IV0(22, "4.0", "IV0", false) --> IBP_4_0_IV1(23, "4.0", "IV1", true)
    #
    # IBP_4_0_IV1 is the latest version as of this writing that breaks rollback compatibility.

    return True
