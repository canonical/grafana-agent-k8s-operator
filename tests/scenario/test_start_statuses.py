# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
from pathlib import Path

from ops import pebble
from scenario import Container, Context, ExecOutput, State

from charm import GrafanaAgentK8sCharm

CHARM_ROOT = Path(__file__).parent.parent.parent


@dataclasses.dataclass
class _MockProc:
    returncode: int = 0
    stdout: str = ""


def _subp_run_mock(*a, **kw):
    return _MockProc(0)


def test_install(vroot):
    ctx = Context(
        charm_type=GrafanaAgentK8sCharm,
        charm_root=vroot,
    )
    out = ctx.run(state=State(), event="install")
    assert out.unit_status == ("unknown", "")


def test_start(vroot):
    ctx = Context(
        charm_type=GrafanaAgentK8sCharm,
        charm_root=vroot,
    )
    out = ctx.run(state=State(), event="start")
    assert out.unit_status.name == "unknown"


def test_charm_start_with_container(vroot):
    agent = Container(
        name="agent",
        can_connect=True,
        exec_mock={("/bin/agent", "-version"): ExecOutput(stdout="42.42")},
    )

    ctx = Context(
        charm_type=GrafanaAgentK8sCharm,
        charm_root=vroot,
    )
    out = ctx.run(state=State(containers=[agent]), event=agent.pebble_ready_event)

    assert out.unit_status.name == "blocked"
    agent_out = out.get_container("agent")
    assert agent_out.services["agent"].current == pebble.ServiceStatus.ACTIVE
