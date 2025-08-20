#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import os

import pytest
from pytest_operator.plugin import OpsTest

from integration.helpers.pytest_operator import (
    APP_NAME,
    KAFKA_CONTAINER,
    KRaftMode,
    KRaftUnitStatus,
    create_test_topic,
    get_address,
    kraft_quorum_status,
    netcat,
    search_secrets,
)
from literals import (
    INTERNAL_TLS_RELATION,
    KRAFT_NODE_ID_OFFSET,
    PEER_CLUSTER_ORCHESTRATOR_RELATION,
    PEER_CLUSTER_RELATION,
    SECURITY_PROTOCOL_PORTS,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.kraft

CONTROLLER_APP = "controller"
CONTROLLER_PORT = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].controller
PRODUCER_APP = "producer"
TLS_NAME = "self-signed-certificates"


class TestKRaft:

    deployment_strat: str
    controller_app: str
    tls_enabled: bool = os.environ.get("TLS", "disabled") == "enabled"

    @pytest.fixture(autouse=True)
    def setup_method_fixture(self, kraft_mode: KRaftMode):
        self.deployment_strat = kraft_mode
        self.controller_app = {"single": APP_NAME, "multi": CONTROLLER_APP}[self.deployment_strat]

    async def _assert_broker_listeners_accessible(self, ops_test: OpsTest, broker_unit_num=0):
        logger.info(f"Asserting broker listeners are up: {APP_NAME}/{broker_unit_num}")
        address = await get_address(ops_test=ops_test, app_name=APP_NAME, unit_num=broker_unit_num)
        assert netcat(
            address, SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal
        )  # Internal listener

        # Client listener should not be enabled if there is no relations
        assert not netcat(
            address, SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT", "SCRAM-SHA-512"].client
        )

    async def _assert_controller_listeners_accessible(
        self, ops_test: OpsTest, controller_unit_num=0
    ):
        # Check controller socket
        logger.info(
            f"Asserting controller listeners are up: {self.controller_app}/{controller_unit_num}"
        )
        address = await get_address(
            ops_test=ops_test, app_name=self.controller_app, unit_num=controller_unit_num
        )

        assert netcat(address, CONTROLLER_PORT)

    async def _assert_quorum_healthy(self, ops_test: OpsTest):
        address = await get_address(ops_test=ops_test, app_name=self.controller_app)
        controller_port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].controller
        bootstrap_controller = f"{address}:{controller_port}"

        unit_status = kraft_quorum_status(
            ops_test, f"{self.controller_app}/0", bootstrap_controller
        )

        offset = KRAFT_NODE_ID_OFFSET if self.deployment_strat == "single" else 0

        for unit_id, status in unit_status.items():
            if unit_id < offset + 100:
                assert status in (KRaftUnitStatus.FOLLOWER, KRaftUnitStatus.LEADER)
            else:
                assert status == KRaftUnitStatus.OBSERVER

    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(self, ops_test: OpsTest, kafka_charm):
        await asyncio.gather(
            ops_test.model.deploy(
                kafka_charm,
                application_name=APP_NAME,
                num_units=1,
                config={
                    "roles": "broker,controller" if self.controller_app == APP_NAME else "broker",
                    "profile": "testing",
                },
                resources={"kafka-image": KAFKA_CONTAINER},
                trust=True,
            ),
            ops_test.model.deploy(
                "kafka-test-app",
                application_name=PRODUCER_APP,
                channel="edge",
                num_units=1,
                series="jammy",
                config={
                    "topic_name": "HOT-TOPIC",
                    "num_messages": 100000,
                    "role": "producer",
                    "partitions": 20,
                    "replication_factor": "1",
                },
                trust=True,
            ),
        )

        if self.controller_app != APP_NAME:
            await ops_test.model.deploy(
                kafka_charm,
                application_name=self.controller_app,
                num_units=1,
                config={
                    "roles": self.controller_app,
                    "profile": "testing",
                },
                resources={"kafka-image": KAFKA_CONTAINER},
                trust=True,
            )

        status = "active" if self.controller_app == APP_NAME else "blocked"
        async with ops_test.fast_forward(fast_interval="60s"):
            await ops_test.model.wait_for_idle(
                apps=list({APP_NAME, self.controller_app}),
                idle_period=30,
                timeout=1800,
                raise_on_error=False,
                status=status,
            )

        # ensuring update-status fires
        async with ops_test.fast_forward(fast_interval="10s"):
            await asyncio.sleep(30)

    @pytest.mark.abort_on_fail
    async def test_integrate(self, ops_test: OpsTest):
        if self.controller_app != APP_NAME:
            await ops_test.model.add_relation(
                f"{APP_NAME}:{PEER_CLUSTER_ORCHESTRATOR_RELATION}",
                f"{CONTROLLER_APP}:{PEER_CLUSTER_RELATION}",
            )

        await ops_test.model.wait_for_idle(
            apps=list({APP_NAME, self.controller_app}), idle_period=30
        )

        async with ops_test.fast_forward(fast_interval="40s"):
            await asyncio.sleep(120)

        assert ops_test.model.applications[APP_NAME].status == "active"
        assert ops_test.model.applications[self.controller_app].status == "active"

    @pytest.mark.abort_on_fail
    async def test_listeners(self, ops_test: OpsTest):
        print("SLEEPING")
        logger.info("SLEEPING")
        await asyncio.sleep(300)
        await self._assert_broker_listeners_accessible(ops_test)
        await self._assert_controller_listeners_accessible(ops_test)

    @pytest.mark.abort_on_fail
    async def test_authorizer(self, ops_test: OpsTest):

        address = await get_address(ops_test=ops_test)
        port = SECURITY_PROTOCOL_PORTS["SASL_SSL", "SCRAM-SHA-512"].internal

        await create_test_topic(ops_test, f"{address}:{port}")

    @pytest.mark.abort_on_fail
    async def test_scale_out(self, ops_test: OpsTest):
        await ops_test.model.applications[self.controller_app].add_units(count=4)

        if self.deployment_strat == "multi":
            await ops_test.model.applications[APP_NAME].add_units(count=2)

        async with ops_test.fast_forward(fast_interval="60s"):
            await ops_test.model.wait_for_idle(
                apps=list({APP_NAME, self.controller_app}),
                status="active",
                timeout=2000,
                idle_period=40,
            )

        address = await get_address(ops_test=ops_test, app_name=self.controller_app)
        bootstrap_controller = f"{address}:{CONTROLLER_PORT}"

        unit_status = kraft_quorum_status(
            ops_test, f"{self.controller_app}/0", bootstrap_controller
        )

        offset = KRAFT_NODE_ID_OFFSET if self.controller_app == APP_NAME else 0

        for unit_id, status in unit_status.items():
            if unit_id < offset + 100:
                assert status in (KRaftUnitStatus.FOLLOWER, KRaftUnitStatus.LEADER)
            else:
                assert status == KRaftUnitStatus.OBSERVER

        for unit_num in range(3):
            await self._assert_broker_listeners_accessible(ops_test, broker_unit_num=unit_num)

        for unit_num in range(5):
            await self._assert_controller_listeners_accessible(
                ops_test, controller_unit_num=unit_num
            )

    @pytest.mark.abort_on_fail
    @pytest.mark.skipif(tls_enabled, reason="Not required with TLS test.")
    async def test_scale_in(self, ops_test: OpsTest):
        await ops_test.model.applications[self.controller_app].scale(scale=3)

        await asyncio.sleep(120)

        async with ops_test.fast_forward(fast_interval="60s"):
            await ops_test.model.wait_for_idle(
                apps=[self.controller_app],
                status="active",
                timeout=1200,
                idle_period=40,
                wait_for_exact_units=3,
            )

        address = await get_address(ops_test=ops_test, app_name=self.controller_app, unit_num=0)
        bootstrap_controller = f"{address}:{CONTROLLER_PORT}"

        unit_status = kraft_quorum_status(
            ops_test, f"{self.controller_app}/0", bootstrap_controller
        )

        assert KRaftUnitStatus.LEADER in unit_status.values()

        for unit_num in range(3):
            await self._assert_broker_listeners_accessible(ops_test, broker_unit_num=unit_num)
            await self._assert_controller_listeners_accessible(
                ops_test, controller_unit_num=unit_num
            )

    @pytest.mark.skipif(not tls_enabled, reason="only required when TLS is on.")
    @pytest.mark.abort_on_fail
    async def test_relate_peer_tls(self, ops_test: OpsTest):
        await ops_test.model.deploy(TLS_NAME, application_name=TLS_NAME, channel="1/stable")
        await ops_test.model.wait_for_idle(
            apps=[TLS_NAME], idle_period=30, timeout=600, status="active"
        )

        await ops_test.model.add_relation(
            f"{self.controller_app}:{INTERNAL_TLS_RELATION}", TLS_NAME
        )
        await ops_test.model.wait_for_idle(
            apps=[self.controller_app, TLS_NAME], idle_period=60, timeout=1200
        )

        async with ops_test.fast_forward(fast_interval="90s"):
            await asyncio.sleep(180)
            await ops_test.model.wait_for_idle(
                apps={self.controller_app, APP_NAME, TLS_NAME},
                idle_period=45,
                timeout=1800,
                status="active",
            )

        for unit_num in range(3):
            await self._assert_broker_listeners_accessible(ops_test, broker_unit_num=unit_num)
            await self._assert_controller_listeners_accessible(
                ops_test, controller_unit_num=unit_num
            )

        # Check quorum is healthy
        await self._assert_quorum_healthy(ops_test)

        internal_ca = search_secrets(ops_test, owner=self.controller_app, search_key="internal-ca")
        controller_ca = search_secrets(
            ops_test, owner=f"{self.controller_app}/0", search_key="peer-ca-cert"
        )

        assert internal_ca
        assert controller_ca
        # ensure we're not using internal CA
        assert internal_ca != controller_ca

    @pytest.mark.skipif(not tls_enabled, reason="only required when TLS is on.")
    @pytest.mark.abort_on_fail
    async def test_remove_peer_tls_relation(self, ops_test: OpsTest):
        await ops_test.juju("remove-relation", self.controller_app, TLS_NAME)

        async with ops_test.fast_forward(fast_interval="90s"):
            await asyncio.sleep(180)
            await ops_test.model.wait_for_idle(
                apps={self.controller_app, APP_NAME, TLS_NAME},
                idle_period=60,
                timeout=1800,
                status="active",
            )

        for unit_num in range(3):
            await self._assert_broker_listeners_accessible(ops_test, broker_unit_num=unit_num)
            await self._assert_controller_listeners_accessible(
                ops_test, controller_unit_num=unit_num
            )

        # Check quorum is healthy
        await self._assert_quorum_healthy(ops_test)

        internal_ca = search_secrets(ops_test, owner=self.controller_app, search_key="internal-ca")
        controller_ca = search_secrets(
            ops_test, owner=f"{self.controller_app}/0", search_key="peer-ca-cert"
        )

        assert internal_ca
        assert controller_ca
        # Now we should be using internal CA
        assert internal_ca == controller_ca
