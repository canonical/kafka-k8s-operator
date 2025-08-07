#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import jubilant
import pytest

from integration.ha.continuous_writes import ContinuousWrites
from integration.helpers.ha import (
    add_k8s_hosts,
    deploy_chaos_mesh,
    destroy_chaos_mesh,
    modify_pebble_restart_delay,
    remove_instance_isolation,
    remove_k8s_hosts,
)
from integration.helpers.pytest_operator import (
    APP_NAME,
)

logger = logging.getLogger(__name__)


@pytest.fixture()
def c_writes(juju: jubilant.Juju):
    """Creates instance of the ContinuousWrites."""
    app = APP_NAME
    assert juju.model
    return ContinuousWrites(juju.model, app)


@pytest.fixture()
def c_writes_runner(juju: jubilant.Juju, c_writes: ContinuousWrites):
    """Starts continuous write operations and clears writes at the end of the test."""
    add_k8s_hosts(juju=juju)
    c_writes.start()
    yield
    c_writes.clear()
    remove_k8s_hosts(juju=juju)
    logger.info("\n\n\n\nThe writes have been cleared.\n\n\n\n")


@pytest.fixture()
def restart_delay(juju: jubilant.Juju):
    modify_pebble_restart_delay(juju=juju, policy="extend")
    yield
    modify_pebble_restart_delay(juju=juju, policy="restore")


@pytest.fixture()
def chaos_mesh(juju: jubilant.Juju):
    """Deploys chaos mesh to the namespace and uninstalls it at the end."""
    deploy_chaos_mesh(juju.model)

    yield

    remove_instance_isolation(juju)
    destroy_chaos_mesh(juju.model)
