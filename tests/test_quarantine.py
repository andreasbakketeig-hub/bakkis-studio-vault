"""Tests for safe quarantine and restore (Phase 2.1)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import quarantine as q
from app.core.quarantine import (
    QuarantineDestinationMismatchError,
    QuarantineError,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_QUARANTINED,
    STATUS_RESTORED,
    complete_quarantine_move,
    get_allowed_scan_paths,
    is_path_quarantined,
    load_manifest,
    move_to_quarantine,
    plan_quarantine_destination,
    register_pending_quarantine,
    restore_from_quarantine,
    safe_load_manifest,
    validate_quarantine_target,
    validate_restore_target,
)


def _fake_vst3_bundle(parent: Path, name: str = "FakePlugin.vst3") -> Path:
    bundle = parent / name
    bundle.mkdir(parents=True)
    (bundle / "Contents").mkdir()
    plist = bundle / "Contents" / "Info.plist"
    plist.write_bytes(b'<?xml version="1.0"?><plist version="1.0"><dict/></plist>')
    return bundle


class QuarantineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "quarantine"
        self.plugin_root = Path(self._tmp.name) / "plugins" / "VST3"
        self.plugin_root.mkdir(parents=True)
        self._allowed_patch = patch.object(
            q, "_allowed_roots", return_value=[self.plugin_root.resolve()]
        )
        self._allowed_patch.start()
        self.addCleanup(self._allowed_patch.stop)

    def test_move_and_restore_round_trip(self) -> None:
        bundle = _fake_vst3_bundle(self.plugin_root)
        result = move_to_quarantine(
            str(bundle),
            "Test quarantine",
            root=self.root,
            metadata={"plugin_name": "FakePlugin", "fmt": "VST3"},
        )
        self.assertFalse(bundle.exists())
        self.assertTrue(Path(result.operation.quarantine_path).exists())
        self.assertEqual(result.operation.status, STATUS_QUARANTINED)

        restore = restore_from_quarantine(result.operation.operation_id, root=self.root)
        self.assertTrue(bundle.exists())
        self.assertEqual(restore.operation.status, STATUS_RESTORED)

    def test_pending_manifest_before_move(self) -> None:
        bundle = _fake_vst3_bundle(self.plugin_root, "PendingFirst.vst3")
        op_id, dest = plan_quarantine_destination(str(bundle), root=self.root)
        register_pending_quarantine(
            str(bundle),
            "pending test",
            op_id,
            str(dest),
            root=self.root,
        )
        self.assertTrue(bundle.exists())
        data = load_manifest(self.root)
        op = data["operations"][0]
        self.assertEqual(op["status"], STATUS_PENDING)
        self.assertEqual(op["quarantine_path"], str(dest.resolve()))

    def test_failed_move_leaves_failed_row(self) -> None:
        bundle = _fake_vst3_bundle(self.plugin_root, "FailMove.vst3")
        op_id, dest = plan_quarantine_destination(str(bundle), root=self.root)
        register_pending_quarantine(
            str(bundle), "fail test", op_id, str(dest), root=self.root,
        )
        with patch("app.core.quarantine.shutil.move", side_effect=OSError("denied")):
            with self.assertRaises(QuarantineError):
                complete_quarantine_move(op_id, str(dest), root=self.root)
        data = load_manifest(self.root)
        self.assertEqual(data["operations"][0]["status"], STATUS_FAILED)
        self.assertIn("denied", data["operations"][0]["error_message"])

    def test_destination_mismatch_blocks_move(self) -> None:
        bundle = _fake_vst3_bundle(self.plugin_root, "Mismatch.vst3")
        op_id, dest = plan_quarantine_destination(str(bundle), root=self.root)
        register_pending_quarantine(
            str(bundle), "mismatch", op_id, str(dest), root=self.root,
        )
        wrong = str(dest.parent / "other_name.vst3")
        with self.assertRaises(QuarantineDestinationMismatchError):
            complete_quarantine_move(op_id, wrong, root=self.root)

    def test_collision_blocks_planning(self) -> None:
        bundle = _fake_vst3_bundle(self.plugin_root)
        dest_dir = self.root / "items" / "op_test"
        dest_dir.mkdir(parents=True)
        (dest_dir / bundle.name).mkdir()
        with self.assertRaises(QuarantineError):
            q._planned_dest_path(self.root / "items", "op_test", bundle.resolve())

    def test_corrupted_manifest_handled_safely(self) -> None:
        self.root.mkdir(parents=True)
        (self.root / "manifest.json").write_text("{not valid json", encoding="utf-8")
        data, err = safe_load_manifest(self.root)
        self.assertIsNone(data)
        self.assertIsNotNone(err)

    def test_custom_scan_path_allowlist(self) -> None:
        custom = Path(self._tmp.name) / "custom_plugins"
        custom.mkdir()
        roots = get_allowed_scan_paths([str(custom)])
        self.assertEqual(roots, [custom.resolve()])
        outside = custom.parent / "outside"
        outside.mkdir()
        bundle = _fake_vst3_bundle(outside, "Outside.vst3")
        v = validate_quarantine_target(str(bundle), scan_paths=[str(custom)])
        self.assertFalse(v.ok)

        inner = _fake_vst3_bundle(custom, "Inside.vst3")
        with patch.object(q, "_allowed_roots", return_value=[custom.resolve()]):
            v2 = validate_quarantine_target(str(inner), scan_paths=[str(custom)])
        self.assertTrue(v2.ok)

    def test_system_path_requires_extra_confirmation(self) -> None:
        bundle = _fake_vst3_bundle(self.plugin_root, "SystemPath.vst3")
        with patch.object(q, "is_system_plugin_location", return_value=True):
            v = validate_quarantine_target(str(bundle), root=self.root)
        self.assertFalse(v.ok)
        self.assertTrue(v.requires_system_ack)
        with patch.object(q, "is_system_plugin_location", return_value=True):
            v2 = validate_quarantine_target(
                str(bundle), root=self.root, system_path_acknowledged=True,
            )
        self.assertTrue(v2.ok)

    def test_symlink_matches_active_quarantine(self) -> None:
        bundle = _fake_vst3_bundle(self.plugin_root, "SymlinkTarget.vst3")
        link = self.plugin_root / "Link.vst3"
        link.symlink_to(bundle.name)
        move_to_quarantine(str(link), "symlink test", root=self.root)
        self.assertTrue(is_path_quarantined(str(link), root=self.root))
        self.assertTrue(is_path_quarantined(str(bundle.resolve()), root=self.root))

    def test_block_missing_path(self) -> None:
        missing = self.plugin_root / "Missing.vst3"
        v = validate_quarantine_target(str(missing), root=self.root)
        self.assertFalse(v.ok)

    def test_block_non_plugin_path(self) -> None:
        txt = self.plugin_root / "notes.txt"
        txt.write_text("not a plugin")
        v = validate_quarantine_target(str(txt), root=self.root)
        self.assertFalse(v.ok)

    def test_block_outside_allowed_roots(self) -> None:
        outside = Path(self._tmp.name) / "elsewhere" / "X.vst3"
        outside.parent.mkdir()
        _fake_vst3_bundle(outside.parent, "X.vst3")
        v = validate_quarantine_target(str(outside), root=self.root)
        self.assertFalse(v.ok)

    def test_manifest_write_read(self) -> None:
        bundle = _fake_vst3_bundle(self.plugin_root, "ManifestTest.vst3")
        move_to_quarantine(str(bundle), "manifest test", root=self.root)
        data = load_manifest(self.root)
        self.assertEqual(len(data["operations"]), 1)
        op = data["operations"][0]
        self.assertEqual(op["plugin_name"], "ManifestTest")
        self.assertIn("operation_id", op)

    def test_restore_blocked_when_original_exists(self) -> None:
        bundle = _fake_vst3_bundle(self.plugin_root, "BlockedRestore.vst3")
        original = str(bundle.resolve())
        result = move_to_quarantine(original, "test", root=self.root)
        _fake_vst3_bundle(self.plugin_root, "BlockedRestore.vst3")
        op = q.QuarantineOperation.from_dict(
            load_manifest(self.root)["operations"][0]
        )
        v = validate_restore_target(op, root=self.root)
        self.assertFalse(v.ok)
        with self.assertRaises(QuarantineError):
            restore_from_quarantine(result.operation.operation_id, root=self.root)

    def test_block_already_quarantined(self) -> None:
        bundle = _fake_vst3_bundle(self.plugin_root, "Twice.vst3")
        move_to_quarantine(str(bundle), "first", root=self.root)
        v = validate_quarantine_target(
            str(Path(self._tmp.name) / "plugins" / "VST3" / "Twice.vst3"),
            root=self.root,
        )
        self.assertFalse(v.ok)

    def test_pending_row_visible_via_attention_filter(self) -> None:
        bundle = _fake_vst3_bundle(self.plugin_root, "Attention.vst3")
        op_id, dest = plan_quarantine_destination(str(bundle), root=self.root)
        register_pending_quarantine(
            str(bundle), "stuck", op_id, str(dest), root=self.root,
        )
        ops = q.list_quarantine_operations(root=self.root, include_attention=True)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].status, STATUS_PENDING)


class VendorQuarantineValidationTests(unittest.TestCase):
    def test_ssl_developer_not_matched_as_vendor(self) -> None:
        from app.core.vendor_registry import match_vendor
        self.assertIsNone(match_vendor("Russell Audio Labs"))


if __name__ == "__main__":
    unittest.main()
