#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


class DummyExec:
    def wait_output(self):
        return ("", None)
