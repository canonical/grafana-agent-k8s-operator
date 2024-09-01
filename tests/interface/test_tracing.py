# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from interface_tester import InterfaceTester


def test_tracing_v2_interface(interface_tester: InterfaceTester):
    interface_tester.configure(
        interface_name="tracing",
        interface_version=2,
    )
    interface_tester.run()
