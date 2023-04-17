# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from pathlib import Path

from fs.tempfs import TempFS

from charm import SnapFstab


class TestFstabParsing(unittest.TestCase):
    """Verify that fstab handling behaves appropriately."""

    def setUp(self):
        self.sandbox = TempFS("fstab_samples", auto_clean=True)
        self.sandbox_root = self.sandbox.getsyspath("/")
        self.addCleanup(self.sandbox.close)

    def test_single_plug_parses(self):
        fstab = "/var/snap/charmed-kafka/common/log /snap/grafana-agent/7/shared-logs/log none bind,ro 0 0\n"
        fstab_file = Path(self.sandbox_root) / "single-plug-fstab"
        fstab_file.write_text(fstab)

        fstab = SnapFstab(fstab_file)
        entry = fstab.entry("charmed-kafka", "logs")
        self.assertEqual(entry.owner, "charmed-kafka")
        self.assertEqual(entry.endpoint_source, "common/log")
        self.assertEqual(entry.target, "/snap/grafana-agent/7/shared-logs/log")
        self.assertEqual(entry.relative_target, "/log")

    def test_multiple_owners_parses(self):
        fstab = """
        /var/snap/charmed-kafka/common/aei /snap/grafana-agent/7/shared-logs/aei none bind,ro 0 0\n
        /var/snap/charmed-kafka/common/log /snap/grafana-agent/7/shared-logs/log none bind,ro 0 0\n
        /var/snap/other-snap/logs/shared /snap/grafana-agent/7/shared-logs/shared none bind,ro 0 0\n
        """
        fstab_file = Path(self.sandbox_root) / "single-plug-fstab"
        fstab_file.write_text(fstab)

        fstab = SnapFstab(fstab_file)
        entry = fstab.entry("charmed-kafka", "logs")
        self.assertEqual(entry.owner, "charmed-kafka")
        self.assertEqual(entry.endpoint_source, "common/log")
        self.assertEqual(entry.target, "/snap/grafana-agent/7/shared-logs/log")
        self.assertEqual(entry.relative_target, "/log")

    def test_multiple_entries(self):
        fstab = """
        /var/snap/charmed-kafka/common/aei /snap/grafana-agent/7/shared-logs/aei none bind,ro 0 0\n
        /var/snap/charmed-kafka/common/log /snap/grafana-agent/7/shared-logs/log none bind,ro 0 0\n
        /var/snap/other-snap/logs/shared /snap/grafana-agent/8/shared-logs/shared-aei none bind,ro 0 0\n
        """
        fstab_file = Path(self.sandbox_root) / "single-plug-fstab"
        fstab_file.write_text(fstab)

        fstab = SnapFstab(fstab_file)
        entry = fstab.entry("charmed-kafka", "logs")
        self.assertEqual(entry.owner, "charmed-kafka")
        self.assertEqual(entry.endpoint_source, "common/log")
        self.assertEqual(entry.target, "/snap/grafana-agent/7/shared-logs/log")
        self.assertEqual(entry.relative_target, "/log")

        entry = fstab.entry("charmed-kafka", "aei")
        self.assertEqual(entry.owner, "charmed-kafka")
        self.assertEqual(entry.endpoint_source, "common/aei")
        self.assertEqual(entry.target, "/snap/grafana-agent/7/shared-logs/aei")
        self.assertEqual(entry.relative_target, "/aei")

        entry = fstab.entry("other-snap", "shared")
        self.assertEqual(entry.owner, "other-snap")
        self.assertEqual(entry.endpoint_source, "logs/shared")
        self.assertEqual(entry.target, "/snap/grafana-agent/8/shared-logs/shared-aei")
        self.assertEqual(entry.relative_target, "/shared-aei")

    def test_multiple_owners_parses_inverted_order(self):
        fstab = """
        /var/snap/charmed-kafka/common/log /snap/grafana-agent/7/shared-logs/log none bind,ro 0 0\n
        /var/snap/charmed-kafka/common/aei /snap/grafana-agent/7/shared-logs/aei none bind,ro 0 0\n
        /var/snap/other-snap/logs/shared /snap/grafana-agent/7/shared-logs/shared none bind,ro 0 0\n
        """
        fstab_file = Path(self.sandbox_root) / "single-plug-fstab"
        fstab_file.write_text(fstab)

        fstab = SnapFstab(fstab_file)
        entry = fstab.entry("charmed-kafka", "aei")
        self.assertEqual(entry.owner, "charmed-kafka")
        self.assertEqual(entry.endpoint_source, "common/aei")
        self.assertEqual(entry.target, "/snap/grafana-agent/7/shared-logs/aei")
        self.assertEqual(entry.relative_target, "/aei")

    def test_multiple_plugs_parses(self):
        fstab = """
        /var/snap/charmed-kafka/common/log /snap/grafana-agent/7/shared-logs/log none bind,ro 0 0\n
        /var/snap/other-snap/logs/shared /snap/grafana-agent/7/shared-logs/shared none bind,ro 0 0\n
        """
        fstab_file = Path(self.sandbox_root) / "single-plug-fstab"
        fstab_file.write_text(fstab)

        fstab = SnapFstab(fstab_file)
        entry = fstab.entry("charmed-kafka", "logs")
        self.assertEqual(entry.owner, "charmed-kafka")
        self.assertEqual(entry.endpoint_source, "common/log")
        self.assertEqual(entry.target, "/snap/grafana-agent/7/shared-logs/log")
        self.assertEqual(entry.relative_target, "/log")

        other_entry = fstab.entry("other-snap", "shared-logs")
        self.assertEqual(other_entry.owner, "other-snap")
        self.assertEqual(other_entry.endpoint_source, "logs/shared")
        self.assertEqual(other_entry.target, "/snap/grafana-agent/7/shared-logs/shared")
        self.assertEqual(other_entry.relative_target, "/shared")

    def test_same_slot_plugs_parses(self):
        fstab = """
        /var/snap/charmed-kafka/common/log /snap/grafana-agent/7/shared-logs/log none bind,ro 0 0\n
        /var/snap/other-snap/common/log /snap/grafana-agent/7/shared-logs/log-1 none bind,ro 0 0\n
        """
        fstab_file = Path(self.sandbox_root) / "single-plug-fstab"
        fstab_file.write_text(fstab)

        fstab = SnapFstab(fstab_file)
        entry = fstab.entry("charmed-kafka", "logs")
        self.assertEqual(entry.endpoint_source, "common/log")
        self.assertEqual(entry.target, "/snap/grafana-agent/7/shared-logs/log")
        self.assertEqual(entry.relative_target, "/log")

        other_entry = fstab.entry("other-snap", "logs")
        self.assertEqual(other_entry.owner, "other-snap")
        self.assertEqual(other_entry.endpoint_source, "common/log")
        self.assertEqual(other_entry.target, "/snap/grafana-agent/7/shared-logs/log-1")
        self.assertEqual(other_entry.relative_target, "/log-1")
