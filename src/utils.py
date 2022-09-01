# !/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of helper methods for checking active connections between ZK and Kafka."""

import logging
import secrets
import string

logger = logging.getLogger(__name__)


def generate_password() -> str:
    """Creates randomized string for use as app passwords.

    Returns:
        String of 32 randomized letter+digit characters
    """
    return "".join([secrets.choice(string.ascii_letters + string.digits) for _ in range(32)])
