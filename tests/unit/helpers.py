# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


class FakeProcessVersionCheck:
    def __init__(self, args):
        pass

    def wait_output(self):
        return ("v0.1.0", "")
