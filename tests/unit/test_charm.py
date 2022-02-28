# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import ServiceStatus
from ops.testing import Harness
from pytest_mock import MockerFixture

from charm import KafkaK8sCharm


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
    harness.charm._validate_config.side_effect = [Exception("invalid configuration")]
    harness.charm.on.config_changed.emit()
    assert harness.charm.unit.status == BlockedStatus("invalid configuration")
    harness.charm._validate_config = _validate_config_original
    # test pebble not ready
    harness.charm.unit.get_container("kafka").can_connect = mocker.Mock()
    harness.charm.unit.get_container("kafka").can_connect.side_effect = [False]
    harness.charm.on.config_changed.emit()
    assert harness.charm.unit.status == MaintenanceStatus("waiting for pebble to start")
    harness.charm.unit.get_container("kafka").can_connect.side_effect = None
    # test pebble ready - zookeeper not ready
    spy = mocker.spy(harness.charm.unit.get_container("kafka"), "replan")
    harness.charm.on.kafka_pebble_ready.emit("kafka")
    assert harness.charm.unit.status == BlockedStatus("need zookeeper relation")
    assert spy.call_count == 0
    # test pebble ready - zookeeper ready
    relation_id = harness.add_relation("zookeeper", "zookeeper")
    harness.add_relation_unit(relation_id, "zookeeper/0")
    harness.update_relation_data(relation_id, "zookeeper", {"hosts": "zk-1"})
    assert harness.charm.unit.status == ActiveStatus()
    assert spy.call_count == 1


def test_on_update_status(mocker: MockerFixture, harness: Harness):
    # ZooKeeper not ready
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == BlockedStatus("need zookeeper relation")
    # ZooKeeper ready
    mocker.patch(
        "charms.zookeeper_k8s.v0.zookeeper.ZooKeeperRequires.hosts",
        return_value="zk-1",
        new_callable=mocker.PropertyMock,
    )
    # Make sure the service kafka is set
    harness.charm.on.kafka_pebble_ready.emit("kafka")
    harness.charm.unit.get_container("kafka").can_connect = mocker.Mock()
    harness.charm.unit.get_container("kafka").can_connect.side_effect = [False]
    # test service not ready
    original_get_plan = harness.charm.unit.get_container("kafka").get_plan
    harness.charm.unit.get_container("kafka").get_plan = mocker.Mock()
    harness.charm.unit.get_container("kafka").get_plan().services = {}
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == WaitingStatus("kafka service not configured yet")
    harness.charm.unit.get_container("kafka").get_plan = original_get_plan
    # test service not running
    harness.charm.unit.get_container("kafka").can_connect.side_effect = None
    harness.charm.unit.get_container("kafka").stop("kafka")
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == BlockedStatus("kafka service is not running")
    # test service running
    harness.charm.unit.get_container("kafka").start("kafka")
    harness.charm.on.kafka_pebble_ready.emit("kafka")
    assert harness.charm.unit.status == ActiveStatus()


def test_on_zookeeper_clients_broken(mocker: MockerFixture, harness: Harness):
    harness.charm.unit.get_container("kafka").can_connect = mocker.Mock()
    harness.charm.unit.get_container("kafka").get_plan = mocker.Mock()
    harness.charm.unit.get_container("kafka").get_plan().services = {"kafka": {}}
    harness.charm.unit.get_container("kafka").get_service = mocker.Mock()
    harness.charm.unit.get_container("kafka").get_service("kafka").current = ServiceStatus.ACTIVE
    harness.charm.unit.get_container("kafka").stop = mocker.Mock()
    harness.charm.on.zookeeper_clients_broken.emit()
    assert harness.charm.unit.get_container("kafka").stop.call_count == 1
    assert harness.charm.unit.status == BlockedStatus("need zookeeper relation")


def test_kafka_relation(mocker: MockerFixture, harness: Harness):
    test_on_config_changed(mocker, harness)
    harness.set_leader(True)
    relation_id = harness.add_relation("kafka", "kafka-client")
    harness.add_relation_unit(relation_id, "kafka-client/0")
    relation_data = harness.get_relation_data(relation_id, harness.charm.app.name)
    assert relation_data == {"host": "kafka-k8s", "port": "9092"}
