#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from time import sleep

import pytest
from jubilant_adapters import JujuFixture, gather

from integration.ha.continuous_writes import ContinuousWrites
from integration.ha.ha_helpers import (
    add_k8s_hosts,
    assert_continuous_writes_consistency,
    delete_pod,
    deploy_chaos_mesh,
    destroy_chaos_mesh,
    get_topic_description,
    get_topic_offsets,
    isolate_instance_from_cluster,
    modify_pebble_restart_delay,
    remove_instance_isolation,
    remove_k8s_hosts,
    send_control_signal,
)
from integration.helpers import (
    APP_NAME,
    DUMMY_NAME,
    KAFKA_CONTAINER,
    REL_NAME_ADMIN,
    ZK_NAME,
    check_logs,
)

RESTART_DELAY = 60
CLIENT_TIMEOUT = 30
REELECTION_TIME = 25

logger = logging.getLogger(__name__)


@pytest.fixture()
def c_writes(juju: JujuFixture):
    """Creates instance of the ContinuousWrites."""
    app = APP_NAME
    return ContinuousWrites(juju, app)


@pytest.fixture()
def c_writes_runner(juju: JujuFixture, c_writes: ContinuousWrites):
    """Starts continuous write operations and clears writes at the end of the test."""
    add_k8s_hosts(juju=juju)
    c_writes.start()
    yield
    c_writes.clear()
    remove_k8s_hosts(juju=juju)
    logger.info("\n\n\n\nThe writes have been cleared.\n\n\n\n")


@pytest.fixture()
def restart_delay(juju: JujuFixture):
    modify_pebble_restart_delay(juju=juju, policy="extend")
    yield
    modify_pebble_restart_delay(juju=juju, policy="restore")


@pytest.fixture()
def chaos_mesh(juju: JujuFixture):
    """Deploys chaos mesh to the namespace and uninstalls it at the end."""
    deploy_chaos_mesh(juju.model)

    yield

    remove_instance_isolation(juju)
    destroy_chaos_mesh(juju.model)


def test_build_and_deploy(juju: JujuFixture, kafka_charm, app_charm):
    gather(
        juju.ext.model.deploy(
            kafka_charm,
            application_name=APP_NAME,
            num_units=1,
            resources={"kafka-image": KAFKA_CONTAINER},
            trust=True,
            config={"expose_external": "nodeport"},
        ),
        juju.ext.model.deploy(ZK_NAME, channel="3/edge", num_units=1, trust=True),
        juju.ext.model.deploy(app_charm, application_name=DUMMY_NAME, trust=True),
    )
    juju.ext.model.wait_for_idle(apps=[APP_NAME, ZK_NAME], timeout=2000)

    juju.ext.model.add_relation(APP_NAME, ZK_NAME)
    with juju.ext.fast_forward(fast_interval="20s"):
        sleep(90)

    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME],
        idle_period=30,
        status="active",
        timeout=2000,
        raise_on_error=False,
    )

    juju.ext.model.add_relation(APP_NAME, f"{DUMMY_NAME}:{REL_NAME_ADMIN}")

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME, DUMMY_NAME, ZK_NAME], idle_period=30, status="active", timeout=2000
        )


# run this test early, in case of resource limits on runners with too many units
def test_multi_cluster_isolation(juju: JujuFixture, kafka_charm):
    second_kafka_name = f"{APP_NAME}-two"
    second_zk_name = f"{ZK_NAME}-two"

    gather(
        juju.ext.model.deploy(
            kafka_charm,
            application_name=second_kafka_name,
            num_units=1,
            resources={"kafka-image": KAFKA_CONTAINER},
            trust=True,
            config={"expose_external": "nodeport"},
        ),
        juju.ext.model.deploy(
            ZK_NAME, application_name=second_zk_name, channel="3/edge", trust=True
        ),
    )
    juju.ext.model.add_relation(second_kafka_name, second_zk_name)

    with juju.ext.fast_forward(fast_interval="60s"):
        juju.ext.model.wait_for_idle(
            apps=[second_kafka_name, second_zk_name],
            idle_period=30,
            status="active",
            timeout=2000,
            raise_on_error=False,
        )

    assert juju.ext.model.applications[second_kafka_name].status == "active"
    assert juju.ext.model.applications[second_zk_name].status == "active"

    # produce to first cluster
    action = juju.ext.model.units.get(f"{DUMMY_NAME}/0").run_action("produce")
    action.wait()
    sleep(10)
    juju.ext.model.wait_for_idle(apps=[APP_NAME, DUMMY_NAME], timeout=1000, idle_period=30)
    assert juju.ext.model.applications[APP_NAME].status == "active"
    assert juju.ext.model.applications[DUMMY_NAME].status == "active"

    # logs exist on first cluster
    check_logs(
        juju=juju,
        kafka_unit_name=f"{APP_NAME}/0",
        topic="test-topic",
    )

    # Check that logs are not found on the second cluster
    with pytest.raises(AssertionError):
        check_logs(
            juju=juju,
            kafka_unit_name=f"{second_kafka_name}/0",
            topic="test-topic",
        )

    # fast removal of second cluster
    remove_apps = f"remove-application --force --destroy-storage --no-wait --no-prompt {second_kafka_name} {second_zk_name}"
    juju.juju(*remove_apps.split(), check=True)


def test_scale_up_zk_kafka(juju: JujuFixture):
    juju.ext.model.applications[APP_NAME].add_units(count=2)
    juju.ext.model.applications[ZK_NAME].add_units(count=2)
    juju.ext.model.block_until(lambda: len(juju.ext.model.applications[APP_NAME].units) == 3)
    juju.ext.model.block_until(lambda: len(juju.ext.model.applications[ZK_NAME].units) == 3)
    juju.ext.model.wait_for_idle(
        apps=[APP_NAME, ZK_NAME], status="active", timeout=1000, idle_period=30
    )


def test_kill_broker_with_topic_leader(
    juju: JujuFixture,
    restart_delay,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass to create messages
    sleep(5)
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader

    logger.info(
        f"Killing broker of leader for topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    send_control_signal(juju=juju, unit_name=f"{APP_NAME}/{initial_leader_num}", signal="SIGKILL")

    # Give time for the remaining units to notice leader going down
    sleep(REELECTION_TIME)

    # Check offsets after killing leader
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    # verify replica is not in sync and check that leader changed
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert initial_leader_num != topic_description.leader
    assert topic_description.in_sync_replicas == {0, 1, 2} - {initial_leader_num}

    # Give time for the service to restart
    sleep(RESTART_DELAY * 2)

    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    assert topic_description.in_sync_replicas == {0, 1, 2}
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


def test_restart_broker_with_topic_leader(
    juju: JujuFixture,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    leader_num = topic_description.leader

    logger.info(
        f"Restarting broker of leader for topic '{ContinuousWrites.TOPIC_NAME}': {leader_num}"
    )
    send_control_signal(juju=juju, unit_name=f"{APP_NAME}/{leader_num}", signal="SIGTERM")
    # Give time for the service to restart
    sleep(REELECTION_TIME * 2)

    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    sleep(CLIENT_TIMEOUT)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert topic_description.in_sync_replicas == {0, 1, 2}
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


def test_freeze_broker_with_topic_leader(
    juju: JujuFixture,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader

    logger.info(
        f"Freezing broker of leader for topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    send_control_signal(juju=juju, unit_name=f"{APP_NAME}/{initial_leader_num}", signal="SIGSTOP")
    sleep(REELECTION_TIME * 2)

    # verify replica is not in sync
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert topic_description.in_sync_replicas == {0, 1, 2} - {initial_leader_num}
    assert initial_leader_num != topic_description.leader

    # verify new writes are continuing. Also, check that leader changed
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    # Un-freeze the process
    logger.info(f"Un-freezing broker: {initial_leader_num}")
    send_control_signal(juju=juju, unit_name=f"{APP_NAME}/{initial_leader_num}", signal="SIGCONT")
    sleep(REELECTION_TIME)
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    # verify the unit is now rejoined the cluster
    assert topic_description.in_sync_replicas == {0, 1, 2}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


def test_full_cluster_crash(
    juju: JujuFixture,
    restart_delay,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass for messages to be produced
    sleep(10)

    logger.info("Killing all brokers...")
    # kill all units "simultaneously"
    gather(
        *[
            send_control_signal(juju, unit.name, signal="SIGKILL")
            for unit in juju.ext.model.applications[APP_NAME].units
        ]
    )
    # Give time for the service to restart
    sleep(RESTART_DELAY * 2)

    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    assert int(next_offsets[-1]) > int(initial_offsets[-1])
    assert topic_description.in_sync_replicas == {0, 1, 2}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


def test_full_cluster_restart(
    juju: JujuFixture,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass for messages to be produced
    sleep(10)

    logger.info("Restarting all brokers...")
    # Restart all units "simultaneously"
    gather(
        *[
            send_control_signal(juju, unit.name, signal="SIGTERM")
            for unit in juju.ext.model.applications[APP_NAME].units
        ]
    )
    # Give time for the service to restart
    sleep(REELECTION_TIME * 2)

    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)

    assert int(next_offsets[-1]) > int(initial_offsets[-1])
    assert topic_description.in_sync_replicas == {0, 1, 2}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


def test_pod_reschedule(
    juju: JujuFixture,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
):
    # Let some time pass to create messages
    sleep(5)
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader

    logger.info(
        f"Killing pod of leader for topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    delete_pod(juju, unit_name=f"{APP_NAME}/{initial_leader_num}")

    # let pod reschedule process be noticed up by juju
    with juju.ext.fast_forward("60s"):
        juju.ext.model.wait_for_idle(
            apps=[APP_NAME], idle_period=30, status="active", timeout=1000
        )

    # refresh hosts with the new ip
    remove_k8s_hosts(juju=juju)
    add_k8s_hosts(juju=juju)

    # Check offsets after killing leader
    initial_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert initial_leader_num != topic_description.leader
    assert topic_description.in_sync_replicas == {0, 1, 2}

    result = c_writes.stop()
    assert_continuous_writes_consistency(result=result)


@pytest.mark.unstable
def test_network_cut_without_ip_change(
    juju: JujuFixture,
    c_writes: ContinuousWrites,
    c_writes_runner: ContinuousWrites,
    chaos_mesh,
):
    # Let some time pass for messages to be produced
    sleep(5)

    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    initial_leader_num = topic_description.leader

    logger.info(
        f"Cutting network for leader of topic '{ContinuousWrites.TOPIC_NAME}': {initial_leader_num}"
    )
    isolate_instance_from_cluster(juju=juju, unit_name=f"{APP_NAME}/{initial_leader_num}")
    sleep(REELECTION_TIME * 2)

    available_unit = f"{APP_NAME}/{next(iter({0, 1, 2} - {initial_leader_num}))}"
    # verify replica is not in sync
    topic_description = get_topic_description(
        juju=juju, topic=ContinuousWrites.TOPIC_NAME, unit_name=available_unit
    )
    assert topic_description.in_sync_replicas == {0, 1, 2} - {initial_leader_num}
    assert initial_leader_num != topic_description.leader

    # verify new writes are continuing. Also, check that leader changed
    topic_description = get_topic_description(
        juju=juju, topic=ContinuousWrites.TOPIC_NAME, unit_name=available_unit
    )
    initial_offsets = get_topic_offsets(
        juju=juju, topic=ContinuousWrites.TOPIC_NAME, unit_name=available_unit
    )
    sleep(CLIENT_TIMEOUT * 2)
    next_offsets = get_topic_offsets(
        juju=juju, topic=ContinuousWrites.TOPIC_NAME, unit_name=available_unit
    )

    assert int(next_offsets[-1]) > int(initial_offsets[-1])

    # Release the network
    logger.info(f"Releasing network of broker: {initial_leader_num}")
    remove_instance_isolation(juju)

    sleep(REELECTION_TIME * 2)

    with juju.ext.fast_forward(fast_interval="15s"):
        result = c_writes.stop()
        sleep(CLIENT_TIMEOUT * 8)

    # verify the unit is now rejoined the cluster
    topic_description = get_topic_description(juju=juju, topic=ContinuousWrites.TOPIC_NAME)
    assert topic_description.in_sync_replicas == {0, 1, 2}

    assert_continuous_writes_consistency(result=result)
