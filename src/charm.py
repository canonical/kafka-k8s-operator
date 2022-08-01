#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed Machine Operator for Apache Kafka."""

import logging
import secrets
import string
import subprocess
from typing import List

from ops.charm import CharmBase, RelationEvent, RelationJoinedEvent
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Container, Relation, WaitingStatus
from ops.pebble import ExecError, Layer

from config import KafkaConfig
from connection_check import broker_active, zookeeper_connected
from literals import CHARM_KEY, PEER, REL_NAME
from provider import KafkaProvider

logger = logging.getLogger(__name__)


class KafkaCharm(CharmBase):
    """Charmed Operator for Kafka."""

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY
        self.kafka_config = KafkaConfig(self)
        self.client_relations = KafkaProvider(self)

        self.framework.observe(getattr(self.on, "kafka_pebble_ready"), self._on_kafka_pebble_ready)
        self.framework.observe(getattr(self.on, "leader_elected"), self._on_leader_elected)
        self.framework.observe(self.on[REL_NAME].relation_created, self._on_zookeeper_created)
        self.framework.observe(self.on[REL_NAME].relation_joined, self._on_zookeeper_joined)
        self.framework.observe(self.on[REL_NAME].relation_departed, self._on_zookeeper_broken)
        self.framework.observe(self.on[REL_NAME].relation_broken, self._on_zookeeper_broken)

    # TODO: possibly add a 'zookeeper units changed, do something' handler
    # this is because we don't want to restart all Kafka units every time ZK changes units
    # but we do want to ensure Kafka has sufficient ZK connections in config in case of a failure
    # maybe manual action?

    @property
    def container(self) -> Container:
        """Grabs the current ZooKeeper container."""
        return self.unit.get_container("zookeeper")

    @property
    def _kafka_layer(self) -> Layer:
        """Returns a Pebble configuration layer for Kafka."""
        layer_config = {
            "summary": "kafka layer",
            "description": "Pebble config layer for kafka",
            "services": {
                "zookeeper": {
                    "override": "replace",
                    "summary": "kafka",
                    "command": self.kafka_config.kafka_command,
                    "startup": "enabled",
                    "environment": {"EXTRA_ARGS": self.kafka_config.extra_args},
                }
            },
        }
        return Layer(layer_config)

    @property
    def peer_relation(self) -> Relation:
        """The Kafka peer relation."""
        return self.model.get_relation(PEER)

    def run_bin_command(self, bin_keyword: str, bin_args: List[str], extra_args: str) -> str:
        """Runs kafka bin command with desired args.

        Args:
            bin_keyword: the kafka shell script to run
                e.g `configs`, `topics` etc
            bin_args: the shell command args
            extra_args (optional): the desired `EXTRA_ARGS` env var values for the command

        Returns:
            String of kafka bin command output
        """
        environment = {"EXTRA_ARGS": " ".join(extra_args)}
        command = [f"/opt/kafka/bin/kafka-{bin_keyword}.sh"] + bin_args

        try:
            process = self.container.exec(command=command, environment=environment)
            output, _ = process.wait_output()
            logger.info(f"{output=}")
            return output
        except (ExecError) as e:
            logger.info(f"cmd failed - command={e.command}, stdout={e.stdout}, stderr={e.stderr}")
            raise e

    def _on_kafka_pebble_ready(self, event: EventBase) -> None:
        """Handler for `kafka_pebble_ready` event."""
        if not self.container.can_connect():
            event.defer()
            return

        if not zookeeper_connected(charm=self):
            self.unit.status = WaitingStatus("waiting for zookeeper relation")
            return

        # required settings given zookeeper connection config has been created
        self.kafka_config.set_server_properties()
        self.kafka_config.set_jaas_config()

        # do not start units until SCRAM users have been added to ZooKeeper for server-server auth
        if self.unit.is_leader() and self.kafka_config.sync_password:
            try:
                self.kafka_config.add_user_to_zookeeper(
                    username="sync", password=self.kafka_config.sync_password
                )
                self.peer_relation.data[self.app].update({"broker-creds": "added"})
            except subprocess.CalledProcessError:
                # command to add users fails sometimes for unknown reasons. Retry seems to fix it.
                event.defer()
                return

        # for non-leader units
        if not self.peer_relation.data[self.app].get("broker-creds", None):
            logger.debug("broker-creds not yet added to zookeeper")
            event.defer()
            return

        # start kafka service
        self.container.add_layer("zookeeper", self._kafka_layer, combine=True)
        self.container.replan()

        # start_snap_service can fail silently, confirm with ZK if kafka is actually connected
        if broker_active(
            unit=self.unit,
            zookeeper_config=self.kafka_config.zookeeper_config,
        ):
            logger.info(f'Broker {self.unit.name.split("/")[1]} connected')
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = BlockedStatus("kafka unit not connected to ZooKeeper")
            return

    def _on_leader_elected(self, _) -> None:
        """Handler for `leader_elected` event, ensuring sync_passwords gets set."""
        sync_password = self.kafka_config.sync_password
        if not sync_password:
            self.peer_relation.data[self.app].update(
                {
                    "sync_password": "".join(
                        [secrets.choice(string.ascii_letters + string.digits) for _ in range(32)]
                    )
                }
            )

    def _on_zookeeper_joined(self, event: RelationJoinedEvent) -> None:
        """Handler for `zookeeper_relation_joined` event, ensuring chroot gets set."""
        if self.unit.is_leader():
            event.relation.data[self.app].update({"chroot": "/" + self.app.name})

    def _on_zookeeper_created(self, event: EventBase) -> None:
        """Handler for `zookeeper_relation_created` event."""
        # if missing zookeeper_config, required data might not be set yet
        if not zookeeper_connected(charm=self):
            event.defer()
            return

        # for every new ZK relation, start kafka service
        self._on_kafka_pebble_ready(event=event)

    def _on_zookeeper_broken(self, _: RelationEvent) -> None:
        """Handler for `zookeeper_relation_departed/broken` events."""
        # if missing zookeeper_config, there is no required ZooKeeper relation, block
        if not zookeeper_connected(charm=self):
            logger.info("stopping snap service")
            self.container.stop("kafka")
            self.unit.status = BlockedStatus("missing required zookeeper relation")


if __name__ == "__main__":
    main(KafkaCharm)
