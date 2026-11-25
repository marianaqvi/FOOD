import base64
import json
import os
import tempfile
import unittest

import _paths  # noqa: F401
import pack_assets as pa

SRC = pa.DEFAULT_SRC


class SourceInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reactions, cls.sha = pa.load_and_validate(SRC)
        cls.limits = pa.load_limits()

    def test_counts(self):
        self.assertEqual(len(self.reactions), 18)
        self.assertEqual(sum(len(r["frames"]) for r in self.reactions), 624)

    def test_ids_exact_and_ordered(self):
        self.assertEqual([r["id"] for r in self.reactions], self.limits["reaction_ids"])

    def test_every_frame_150ms_and_reaction_lengths(self):
        for r in self.reactions:
            self.assertTrue(all(f[0] == 150 for f in r["frames"]), r["id"])
            self.assertIn(sum(f[0] for f in r["frames"]), (4800, 6000), r["id"])

    def test_max_union_is_281_and_never_exceeded(self):
        counts = [pa.union_lit(*f[1:]) for r in self.reactions for f in r["frames"]]
        self.assertEqual(max(counts), 281)

    def test_masks_are_256_bytes(self):
        for r in self.reactions:
            for f in r["frames"]:
                self.assertTrue(all(len(m) == 256 for m in f[1:]))

    def test_bit_order_golden(self):
        # pixel (0,0) is the MSB of byte 0; pixel (63,31) is the LSB of byte 255
        mask = bytearray(256)
        mask[0] = 0x80
        mask[255] = 0x01
        mask[1 * 8 + 1] = 0x20  # y=1, byte 1 -> x = 8 + 2 = 10
        from reference_renderer import lit_set
        self.assertEqual(lit_set(bytes(mask)), {(0, 0), (63, 31), (10, 1)})

    def test_source_file_unchanged_by_tooling(self):
        # the source stays valid JSON with the original top-level keys
        with open(SRC, "rb") as fh:
            data = json.loads(fh.read().decode("utf-8"))
        self.assertEqual(list(data), ["width", "height", "encoding", "layers", "labels", "descriptions", "animations"])


class RejectsBadSource(unittest.TestCase):
    def _mutated(self, fn):
        with open(SRC, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        fn(data)
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(data, tmp)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        return tmp.name

    def test_bad_duration(self):
        p = self._mutated(lambda d: d["animations"]["idle"][0].__setitem__(0, 120))
        with self.assertRaises(pa.AssetError):
            pa.load_and_validate(p)

    def test_short_mask(self):
        p = self._mutated(lambda d: d["animations"]["idle"][0].__setitem__(1, base64.b64encode(b"\0" * 255).decode()))
        with self.assertRaises(pa.AssetError):
            pa.load_and_validate(p)

    def test_over_cap_coverage(self):
        full = base64.b64encode(b"\xff" * 256).decode()
        p = self._mutated(lambda d: d["animations"]["idle"][0].__setitem__(1, full))
        with self.assertRaises(pa.AssetError):
            pa.load_and_validate(p)

    def test_missing_reaction(self):
        p = self._mutated(lambda d: d["animations"].pop("morph"))
        with self.assertRaises(pa.AssetError):
            pa.load_and_validate(p)


class RoundTripParity(unittest.TestCase):
    """Every packed frame must equal the original mask bytes and timing."""

    def test_all_frames_round_trip(self):
        reactions, sha = pa.load_and_validate(SRC)
        with tempfile.TemporaryDirectory() as d:
            pa.write_all(pa.build(reactions, sha), d)
            manifest, packed = pa.read_pack(d)
            # compare against an independent decode of the raw JSON
            with open(SRC, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            checked = 0
            for rid, frames in raw["animations"].items():
                self.assertEqual(len(packed[rid]), len(frames), rid)
                for n, rec in enumerate(frames):
                    dur, a, b, fx = packed[rid][n]
                    self.assertEqual(dur, rec[0], "%s[%d] duration" % (rid, n))
                    self.assertEqual(a, base64.b64decode(rec[1]), "%s[%d] A" % (rid, n))
                    self.assertEqual(b, base64.b64decode(rec[2]), "%s[%d] B" % (rid, n))
                    self.assertEqual(fx, base64.b64decode(rec[3]), "%s[%d] FX" % (rid, n))
                    checked += 1
            self.assertEqual(checked, 624)
            self.assertEqual(manifest["total_frames"], 624)
            self.assertEqual(manifest["record_size"], 770)
            self.assertEqual(manifest["total_bytes"], 480480)
            self.assertEqual(sum(os.path.getsize(os.path.join(d, e["file"])) for e in manifest["reactions"]), 480480)

    def test_packing_is_deterministic(self):
        reactions, sha = pa.load_and_validate(SRC)
        self.assertEqual(pa.build(reactions, sha), pa.build(reactions, sha))

    def test_corruption_is_detected(self):
        reactions, sha = pa.load_and_validate(SRC)
        with tempfile.TemporaryDirectory() as d:
            pa.write_all(pa.build(reactions, sha), d)
            path = os.path.join(d, "idle.bin")
            with open(path, "rb") as fh:
                blob = bytearray(fh.read())
            blob[100] ^= 0x01
            with open(path, "wb") as fh:
                fh.write(bytes(blob))
            with self.assertRaises(pa.AssetError):
                pa.read_pack(d)
            with open(path, "wb") as fh:
                fh.write(bytes(blob[:-1]))
            with self.assertRaises(pa.AssetError):
                pa.read_pack(d)

    def test_committed_firmware_assets_are_current(self):
        if not os.path.exists(os.path.join(pa.DEFAULT_OUT, "manifest.json")):
            self.skipTest("firmware/assets not generated yet")
        self.assertEqual(pa.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
