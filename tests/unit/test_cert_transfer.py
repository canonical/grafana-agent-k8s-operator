

import json
import pathlib
import tempfile
import uuid
from pathlib import Path

import yaml
from helpers import k8s_resource_multipatch, patch_lightkube_client
from ops import pebble
from ops.testing import Container, Exec, Model, Mount, Relation, State


@patch_lightkube_client
@k8s_resource_multipatch
def test_ca_cert_saved_to_disk(ctx):
    model_uuid = uuid.uuid4()
    ca_cert_path = "/usr/local/share/ca-certificates"
    fake_cert = "-----BEGIN CERTIFICATE-----123-----END CERTIFICATE-----"
    remote_app_data = {
        "certificates": json.dumps([
            fake_cert
        ]),
        "version": "1"
    }
    # GIVEN a receive-ca-cert relation over certificates_transfer
    rel_id = 1
    certificate_transfer_relation = Relation(
        "receive-ca-cert",
        remote_app_data=remote_app_data,
        id=rel_id,
    )
    state = State(
        leader=True,
        containers=[
            Container(
                "agent",
                can_connect=True,
                execs=[Exec(['update-ca-certificates', '--fresh'])],
                # Setting the service to inactive. After relation change, it must be active.
                service_statuses={"agent": pebble.ServiceStatus.INACTIVE},
            ),
        ],
        relations=[
            certificate_transfer_relation
        ],
        model=Model(uuid=str(model_uuid))
    )
    # WHEN a relation is joined
    state_out = ctx.run(ctx.on.relation_changed(certificate_transfer_relation), state)

    agent = state_out.get_container("agent")

    # THEN the agent service has started
    assert agent.services["agent"].is_running()

    fs = agent.get_filesystem(ctx)
    ca_cert = fs.joinpath(*ca_cert_path.strip("/").split("/"))

    # Get the files inside the /usr/local/share/ca-certificates folder
    files = [str(f) for f in ca_cert.iterdir() if f.is_file()]

    # The path to the cert file has the naming convention {path to the folder}/receive-ca-cert-model_uuid-relation_id-index_to_certificate-ca.crt
    cert_path = f"{ca_cert}/receive-ca-cert-{model_uuid}-{rel_id}-0-ca.crt"

    # AND the CA cert gets written to disk
    assert cert_path in files

    # AND the content of the cert file is equal to the certificate in relation data
    cert = yaml.safe_load(Path(cert_path).read_text())
    assert cert == fake_cert

@patch_lightkube_client
@k8s_resource_multipatch
def test_ca_cert_removed_from_disk_on_relation_broken(ctx):
    model_uuid = uuid.uuid4()
    ca_cert_path = "/usr/local/share/ca-certificates"
    fake_cert = "-----BEGIN CERTIFICATE-----123-----END CERTIFICATE-----"
    remote_app_data = {
        "certificates": json.dumps([
            fake_cert
        ]),
        "version": "1"
    }
    # GIVEN a receive-ca-cert relation over certificates_transfer
    rel_id = 1
    certificate_transfer_relation = Relation(
        "receive-ca-cert",
        remote_app_data=remote_app_data,
        id=rel_id,
    )

    # Creating a fake CA cert file
    # This file will need to be mounted into the container. When the relation is broken, we'll check that the file has been deleted.

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        fake_path = pathlib.Path(tmp.name)
    cert_path = f"{ca_cert_path}/receive-ca-cert-{model_uuid}-{rel_id}-0-ca.crt"
    mounts = {
        'fake-ca-cert': Mount(location=cert_path, source=fake_path),
    }

    state = State(
        leader=True,
        containers=[
            Container(
                "agent",
                can_connect=True,
                execs=[Exec(['update-ca-certificates', '--fresh'])],
                mounts=mounts,
            ),
        ],
        relations=[certificate_transfer_relation],
        model=Model(uuid=str(model_uuid)),
    )
    # WHEN a relation is broken
    state_out = ctx.run(ctx.on.relation_broken(certificate_transfer_relation), state)

    # THEN the fake CA cert file should be deleted
    agent = state_out.get_container("agent")

    fs = agent.get_filesystem(ctx)
    ca_cert_path = fs.joinpath(*ca_cert_path.strip("/").split("/"))
    assert list(ca_cert_path.iterdir()) == []
