# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
from pathlib import Path

from ops import pebble
from ops.testing import Container, Context, Exec, State, UnknownStatus

from charm import GrafanaAgentK8sCharm


@dataclasses.dataclass
class _MockProc:
    returncode: int = 0
    stdout: str = ""


def _subp_run_mock(*a, **kw):
    return _MockProc(0)


def test_install(ctx):
    out = ctx.run(ctx.on.install(), state=State())
    assert out.unit_status == UnknownStatus()


def test_start(ctx):
    out = ctx.run(ctx.on.start(), state=State())
    assert out.unit_status.name == "unknown"


def test_charm_start_with_container(ctx):
    agent = Container(
        name="agent",
        can_connect=True,
        execs={Exec(["/bin/agent", "-version"], return_code=0, stdout="42.42")},
    )

    out = ctx.run(ctx.on.pebble_ready(agent), state=State(containers=[agent]))

    assert out.unit_status.name == "blocked"
    agent_out = out.get_container("agent")
    assert agent_out.services["agent"].current == pebble.ServiceStatus.ACTIVE
