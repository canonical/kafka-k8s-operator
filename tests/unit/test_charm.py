# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness
from pytest_mock import MockerFixture

from charm import CharmError, KafkaK8sCharm


@pytest.fixture
def harness(mocker: MockerFixture):
    mocker.patch("charm.KubernetesServicePatch", lambda x, y: None)
    kafka_harness = Harness(KafkaK8sCharm)
    kafka_harness.begin()
    kafka_harness.charm.unit.get_container("kafka").push("/entrypoint", "")
    yield kafka_harness
    kafka_harness.cleanup()


def test_on_config_changed(mocker: MockerFixture, harness: Harness):
    # test config validation
    _validate_config_original = harness.charm._validate_config
    harness.charm._validate_config = mocker.Mock()
    harness.charm._validate_config.side_effect = [CharmError("invalid configuration")]
    harness.charm.on.config_changed.emit()
    assert harness.charm.unit.status == BlockedStatus("invalid configuration")
    harness.charm._validate_config = _validate_config_original
    # zookeeper not ready
    harness.charm.on.config_changed.emit()
    assert harness.charm.unit.status == BlockedStatus("need zookeeper relation")
    # zookeeker ready
    relation_id = harness.add_relation("zookeeper", "zookeeper")
    harness.add_relation_unit(relation_id, "zookeeper/0")
    harness.update_relation_data(relation_id, "zookeeper", {"hosts": "zk-1"})
    # test pebble not ready
    harness.charm.unit.get_container("kafka").can_connect = mocker.Mock()
    harness.charm.unit.get_container("kafka").can_connect.side_effect = [False]
    harness.charm.on.config_changed.emit()
    assert harness.charm.unit.status == MaintenanceStatus("waiting for pebble to start")
    harness.charm.unit.get_container("kafka").can_connect.side_effect = None
    # test pebble ready - not jmx resource
    harness.charm.on.kafka_pebble_ready.emit("kafka")
    assert harness.charm.unit.status == BlockedStatus("Missing 'jmx-prometheus-jar' resource")
    # jmx resource added
    mocker.patch("charm.KafkaK8sCharm._setup_metrics")
    kafka_properties = """clientPort=2181
    broker.id.generation.enable=true

    # comment
    invalid-line
    """
    harness.update_config({"kafka-properties": kafka_properties})
    assert harness.charm.unit.status == ActiveStatus()
    assert harness.charm.kafka_properties == {
        "KAFKA_CLIENT_PORT": "2181",
        "KAFKA_BROKER_ID_GENERATION_ENABLE": "true",
    }


def test_on_update_status(mocker: MockerFixture, harness: Harness):
    mocker.patch("charm.KafkaK8sCharm._setup_metrics")
    # ZooKeeper not ready
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == BlockedStatus("need zookeeper relation")
    # ZooKeeper ready
    mocker.patch(
        "charms.zookeeper_k8s.v0.zookeeper.ZooKeeperRequires.hosts",
        return_value="zk-1",
        new_callable=mocker.PropertyMock,
    )
    # test service not ready
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == WaitingStatus("kafka service not configured yet")
    # test service ready
    harness.charm.on.kafka_pebble_ready.emit("kafka")
    assert harness.charm.unit.status == ActiveStatus()
    # test service not running
    harness.charm.unit.get_container("kafka").stop("kafka")
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == BlockedStatus("kafka service is not running")


def test_on_zookeeper_clients_broken(harness: Harness):
    harness.charm.on.kafka_pebble_ready.emit("kafka")
    harness.charm.on.zookeeper_clients_broken.emit()
    assert harness.charm.unit.status == BlockedStatus("need zookeeper relation")


def test_kafka_relation(mocker: MockerFixture, harness: Harness):
    test_on_config_changed(mocker, harness)
    harness.set_leader(True)
    relation_id = harness.add_relation("kafka", "kafka-client")
    harness.add_relation_unit(relation_id, "kafka-client/0")
    relation_data = harness.get_relation_data(relation_id, harness.charm.app.name)
    assert relation_data == {"host": "kafka-k8s", "port": "9092"}
