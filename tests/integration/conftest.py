#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import glob
import typing

import jubilant
import pytest

from .helpers import APP_NAME, CONTROLLER_NAME, KRaftMode


def pytest_addoption(parser):
    """Defines pytest parsers."""
    parser.addoption(
        "--model",
        action="store",
        help="Juju model to use; if not provided, a new model "
        "will be created for each test which requires one",
    )
    parser.addoption(
        "--keep-models",
        action="store_true",
        help="Keep models handled by opstest, can be overridden in track_model",
    )
    parser.addoption(
        "--kraft-mode", action="store", help="KRaft mode to run the tests", default="single"
    )


@pytest.fixture(scope="module")
def kraft_mode(request: pytest.FixtureRequest) -> KRaftMode:
    """Returns the KRaft mode which is used to run the tests, should be either `single` or `multi`."""
    mode = f'{request.config.getoption("--kraft-mode")}' or "single"
    if mode not in ("single", "multi"):
        raise Exception("Unknown --kraft-mode, valid options are 'single' and 'multi'")

    return mode


@pytest.fixture(scope="module")
def controller_app(kraft_mode) -> str:
    """Returns the name of the controller application."""
    return APP_NAME if kraft_mode == "single" else CONTROLLER_NAME


@pytest.fixture(scope="module")
def kafka_apps(kraft_mode) -> list[str]:
    """Returns a list of applications used to deploy the Apache Kafka cluster, depending on KRaft mode.

    This would be either [broker_app] for single mode,  or [broker_app, controller_app] for multi mode.
    This fixture is useful for wait calls for example.
    """
    return [APP_NAME] if kraft_mode == "single" else [APP_NAME, CONTROLLER_NAME]


@pytest.fixture(scope="module")
def usernames():
    return set()


@pytest.fixture(scope="module")
def kafka_charm():
    """Kafka charm used for integration testing."""
    charms = glob.glob("./*.charm")
    if not charms:
        raise RuntimeError("Can not find Kafka charm, did you run charmcraft pack?")
    return charms[0]


@pytest.fixture(scope="module")
def app_charm():
    """Build the application charm."""
    charm_path = "tests/integration/app-charm"
    charms = glob.glob(f"{charm_path}/*.charm")
    if not charms:
        raise RuntimeError("Can not find Kafka charm, did you run charmcraft pack?")
    return charms[0]


# -- Jubilant --


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    model = request.config.getoption("--model")
    keep_models = typing.cast(bool, request.config.getoption("--keep-models"))

    if model is None:
        with jubilant.temp_model(keep=keep_models) as juju:
            juju.wait_timeout = 10 * 60
            juju.model_config({"update-status-hook-interval": "180s"})
            yield juju

            log = juju.debug_log(limit=1000)
    else:
        juju = jubilant.Juju(model=model)
        yield juju
        log = juju.debug_log(limit=1000)

    if request.session.testsfailed:
        print(log, end="")
