#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Application charm that connects to database charms.

This charm is meant to be used only for testing
of the libraries in this repository.
"""

import logging

from charms.data_platform_libs.v0.data_interfaces import KafkaRequires, TopicCreatedEvent
from client import KafkaClient
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus

logger = logging.getLogger(__name__)


CHARM_KEY = "app"
PEER = "cluster"
REL_NAME_CONSUMER = "kafka-client-consumer"
REL_NAME_PRODUCER = "kafka-client-producer"
REL_NAME_ADMIN = "kafka-client-admin"
ZK = "zookeeper"
CONSUMER_GROUP_PREFIX = "test-prefix"


class ApplicationCharm(CharmBase):
    """Application charm that connects to database charms."""

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY

        self.framework.observe(getattr(self.on, "start"), self._on_start)
        self.kafka_requirer_consumer = KafkaRequires(
            self,
            relation_name=REL_NAME_CONSUMER,
            topic="test-topic",
            extra_user_roles="consumer",
            consumer_group_prefix=CONSUMER_GROUP_PREFIX,
        )
        self.kafka_requirer_producer = KafkaRequires(
            self, relation_name=REL_NAME_PRODUCER, topic="test-topic", extra_user_roles="producer"
        )
        self.kafka_requirer_admin = KafkaRequires(
            self, relation_name=REL_NAME_ADMIN, topic="test-topic", extra_user_roles="admin"
        )
        self.framework.observe(
            self.kafka_requirer_consumer.on.topic_created, self.on_topic_created_consumer
        )
        self.framework.observe(
            self.kafka_requirer_producer.on.topic_created, self.on_topic_created_producer
        )
        self.framework.observe(
            self.kafka_requirer_admin.on.topic_created, self.on_topic_created_admin
        )

        # this action is needed because hostnames cannot be resolved outside K8s
        self.framework.observe(getattr(self.on, "produce_action"), self._produce)

    def _on_start(self, _) -> None:
        self.unit.status = ActiveStatus()

    def on_topic_created_consumer(self, event: TopicCreatedEvent) -> None:
        logger.info(f"{event.username} {event.password} {event.bootstrap_server} {event.tls}")
        return

    def on_topic_created_producer(self, event: TopicCreatedEvent) -> None:
        logger.info(f"{event.username} {event.password} {event.bootstrap_server} {event.tls}")
        return

    def on_topic_created_admin(self, event: TopicCreatedEvent) -> None:
        logger.info(f"{event.username} {event.password} {event.bootstrap_server} {event.tls}")
        return

    def _produce(self, _) -> None:
        username = None
        password = None
        uris = None
        security_protocol = "SASL_PLAINTEXT"
        for relation in self.model.relations[REL_NAME_ADMIN]:
            if not relation.app:
                continue

            username = relation.data[relation.app].get("username", "")
            password = relation.data[relation.app].get("password", "")
            uris = relation.data[relation.app].get("endpoints", "").split(",")

        if not (username and password and uris):
            raise KeyError("missing relation data from app charm")

        client = KafkaClient(
            servers=uris,
            username=username,
            password=password,
            topic="test-topic",
            consumer_group_prefix=None,
            security_protocol=security_protocol,
        )

        client.create_topic()
        client.run_producer()


if __name__ == "__main__":
    main(ApplicationCharm)
