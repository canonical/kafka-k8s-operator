#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm kafka-k8s and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    await ops_test.model.set_config({"update-status-hook-interval": "10s"})
    await ops_test.model.deploy("zookeeper-k8s", channel="edge", application_name="zookeeper-k8s")

    charm = await ops_test.build_charm(".")
    resources = {"kafka-image": METADATA["resources"]["kafka-image"]["upstream-source"]}
    await ops_test.model.deploy(
        charm, resources=resources, application_name="kafka-k8s", config={"metrics": False}
    )
    await ops_test.model.add_relation("kafka-k8s:zookeeper", "zookeeper-k8s:zookeeper")
    await ops_test.model.wait_for_idle(
        apps=["kafka-k8s", "zookeeper-k8s"], status="active", timeout=1000
    )
    assert ops_test.model.applications["kafka-k8s"].units[0].workload_status == "active"

    logger.debug("Setting update-status-hook-interval to 60m")
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})

    # Scale kafka
    await ops_test.model.applications["kafka-k8s"].scale(3)
    await ops_test.model.wait_for_idle(apps=["kafka-k8s"], status="active", timeout=1000)

async def test_rolling_restart(ops_test: OpsTest):
    """Verify that our rolling restart will work.

    It should kick units into a maintenance state, run replan, then move them back to active.

    """
    app = ops_test.model.applications["kafka-k8s"]
    for unit in app.units:
        await unit.run("JUJU_DISPATCH_PATH=hooks/config-changed ./dispatch")

    await ops_test.model.block_until(lambda: app.status in ("maintenance", "error"))
    assert app.status != "error"

    await ops_test.model.block_until(lambda: app.status in ("error", "blocked", "active"))
    assert app.status == "active"
