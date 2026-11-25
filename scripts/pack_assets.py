#!/usr/bin/env python3
"""Pack the canonical sheep animation JSON into compact per-reaction binaries.

Usage (from the repo root, standard CPython 3.8+, no third-party packages):

    python3 scripts/pack_assets.py                # validate + write firmware/assets/
    python3 scripts/pack_assets.py --check        # validate + confirm firmware/assets/ is up to date
    python3 scripts/pack_assets.py --out some/dir # write somewhere else

The source JSON is never modified. Masks are copied byte for byte.

Binary format (version 1)
-------------------------
One file per reaction: ``<reaction_id>.bin``.  The file is a plain concatenation
of fixed-size records, one per frame, in playback order.  No header, so a frame
can be read with a single seek + readinto():

    offset  size  field
    0       2     duration_ms    uint16, little-endian
    2       256   sheep_a mask   32 rows x 8 bytes, row-major, MSB-first
    258     256   sheep_b mask
    514     256   effects mask
    total   770 bytes per frame

Pixel (x, y) in a mask is lit when ``mask[y*8 + (x >> 3)] & (0x80 >> (x & 7))``.
Layers are drawn in the order A, B, effects; later layers overwrite earlier
layers at shared pixels.

``manifest.json`` lists every reaction with frame count, duration, byte size,
CRC32 and SHA-256, plus the source hash used as ``asset_version``.
"""
import argparse
import base64
import binascii
import hashlib
import json
import os
import struct
import sys
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = os.path.join(REPO, "assets", "food_sheep_animation_assets.json")
DEFAULT_OUT = os.path.join(REPO, "firmware", "assets")
LIMITS_PATH = os.path.join(REPO, "shared", "limits.json")

FORMAT_VERSION = 1
WIDTH, HEIGHT = 64, 32
ROW_BYTES = WIDTH // 8
MASK_BYTES = ROW_BYTES * HEIGHT  # 256
LAYERS = ("sheep_a", "sheep_b", "effects")
RECORD_SIZE = 2 + MASK_BYTES * len(LAYERS)  # 770
ENCODING = "base64 row-major MSB-first 1-bit, 8 bytes per row"
RECORD_LAYOUT = (
    "u16le duration_ms + sheep_a[256] + sheep_b[256] + effects[256]; "
    "mask = 32 rows x 8 bytes, row-major, MSB-first"
)

_POPCOUNT = [bin(i).count("1") for i in range(256)]


class AssetError(Exception):
    """Raised when the source JSON violates an invariant."""


def load_limits():
    with open(LIMITS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def union_lit(a, b, c):
    """Number of distinct lit pixels across three masks (overlaps counted once)."""
    return sum(_POPCOUNT[x | y | z] for x, y, z in zip(a, b, c))


def _decode_mask(text, where):
    if not isinstance(text, str):
        raise AssetError("%s: mask is not a string" % where)
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AssetError("%s: invalid base64 (%s)" % (where, exc))
    if len(raw) != MASK_BYTES:
        raise AssetError("%s: mask is %d bytes, expected %d" % (where, len(raw), MASK_BYTES))
    if base64.b64encode(raw).decode("ascii") != text:
        raise AssetError("%s: base64 is not canonical" % where)
    return raw


def load_and_validate(src_path=DEFAULT_SRC):
    """Decode and validate the whole source.

    Returns (reactions, source_sha256) where reactions is an ordered list of
    dicts: {"id", "label", "description", "frames": [(duration_ms, a, b, fx), ...]}.
    """
    limits = load_limits()
    with open(src_path, "rb") as fh:
        blob = fh.read()
    source_sha256 = hashlib.sha256(blob).hexdigest()
    data = json.loads(blob.decode("utf-8"))

    if data.get("width") != WIDTH or data.get("height") != HEIGHT:
        raise AssetError("source is %sx%s, expected %dx%d" % (data.get("width"), data.get("height"), WIDTH, HEIGHT))
    if data.get("encoding") != ENCODING:
        raise AssetError("unexpected encoding string: %r" % data.get("encoding"))
    if tuple(data.get("layers", ())) != LAYERS:
        raise AssetError("unexpected layers: %r" % (data.get("layers"),))

    expected_ids = limits["reaction_ids"]
    anims = data["animations"]
    if list(anims.keys()) != expected_ids:
        raise AssetError("reaction IDs/order differ from shared/limits.json: %r" % list(anims.keys()))
    if set(data["labels"]) != set(expected_ids) or set(data["descriptions"]) != set(expected_ids):
        raise AssetError("labels/descriptions do not cover exactly the reaction IDs")

    exp = limits["expected_source"]
    max_lit = limits["max_lit_habitat_pixels"]
    reactions = []
    total_frames = 0
    global_max = 0
    for rid in expected_ids:
        frames = []
        for n, rec in enumerate(anims[rid]):
            where = "%s[%d]" % (rid, n)
            if not isinstance(rec, list) or len(rec) != 1 + len(LAYERS):
                raise AssetError("%s: frame must be [duration, a, b, effects]" % where)
            dur = rec[0]
            if not isinstance(dur, int) or isinstance(dur, bool) or not (1 <= dur <= 0xFFFF):
                raise AssetError("%s: bad duration %r" % (where, dur))
            if dur != limits["frame_ms"]:
                raise AssetError("%s: duration %d != %d ms" % (where, dur, limits["frame_ms"]))
            masks = tuple(_decode_mask(rec[1 + i], "%s.%s" % (where, LAYERS[i])) for i in range(3))
            lit = union_lit(*masks)
            if lit > max_lit:
                raise AssetError("%s: %d lit pixels exceeds the fixed maximum %d" % (where, lit, max_lit))
            global_max = max(global_max, lit)
            frames.append((dur,) + masks)
        total_ms = sum(f[0] for f in frames)
        if total_ms not in exp["reaction_duration_ms"]:
            raise AssetError("%s: total %d ms not in %r" % (rid, total_ms, exp["reaction_duration_ms"]))
        total_frames += len(frames)
        reactions.append({
            "id": rid,
            "label": data["labels"][rid],
            "description": data["descriptions"][rid],
            "frames": frames,
        })

    if len(reactions) != exp["reactions"]:
        raise AssetError("expected %d reactions, found %d" % (exp["reactions"], len(reactions)))
    if total_frames != exp["frames"]:
        raise AssetError("expected %d frames, found %d" % (exp["frames"], total_frames))
    if global_max != exp["max_union_lit_pixels"]:
        raise AssetError("max union coverage is %d, expected %d" % (global_max, exp["max_union_lit_pixels"]))
    return reactions, source_sha256


def encode_reaction(frames):
    out = bytearray()
    for dur, a, b, fx in frames:
        out += struct.pack("<H", dur) + a + b + fx
    assert len(out) == RECORD_SIZE * len(frames)
    return bytes(out)


def build(reactions, source_sha256):
    """Return {filename: bytes} including manifest.json (deterministic)."""
    files = {}
    entries = []
    for r in reactions:
        blob = encode_reaction(r["frames"])
        name = r["id"] + ".bin"
        files[name] = blob
        entries.append({
            "id": r["id"],
            "label": r["label"],
            "file": name,
            "frames": len(r["frames"]),
            "duration_ms": sum(f[0] for f in r["frames"]),
            "bytes": len(blob),
            "crc32": zlib.crc32(blob) & 0xFFFFFFFF,
            "sha256": hashlib.sha256(blob).hexdigest(),
        })
    manifest = {
        "format_version": FORMAT_VERSION,
        "asset_version": source_sha256[:12],
        "source_sha256": source_sha256,
        "width": WIDTH,
        "height": HEIGHT,
        "layers": list(LAYERS),
        "record_size": RECORD_SIZE,
        "record_layout": RECORD_LAYOUT,
        "total_frames": sum(e["frames"] for e in entries),
        "total_bytes": sum(e["bytes"] for e in entries),
        "max_lit_pixels": max(union_lit(*f[1:]) for r in reactions for f in r["frames"]),
        "reactions": entries,
    }
    files["manifest.json"] = (json.dumps(manifest, indent=1) + "\n").encode("utf-8")
    return files


def write_all(files, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for name, blob in files.items():
        path = os.path.join(out_dir, name)
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(blob)
        os.replace(tmp, path)


def read_pack(pack_dir):
    """Read a pack back: returns (manifest, {id: [(duration, a, b, fx), ...]}).

    Verifies file sizes and checksums against the manifest.
    """
    with open(os.path.join(pack_dir, "manifest.json"), "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    if manifest["format_version"] != FORMAT_VERSION or manifest["record_size"] != RECORD_SIZE:
        raise AssetError("unsupported pack format")
    result = {}
    for ent in manifest["reactions"]:
        with open(os.path.join(pack_dir, ent["file"]), "rb") as fh:
            blob = fh.read()
        if len(blob) != ent["bytes"] or len(blob) != RECORD_SIZE * ent["frames"]:
            raise AssetError("%s: wrong size %d" % (ent["file"], len(blob)))
        if (zlib.crc32(blob) & 0xFFFFFFFF) != ent["crc32"]:
            raise AssetError("%s: CRC32 mismatch" % ent["file"])
        if hashlib.sha256(blob).hexdigest() != ent["sha256"]:
            raise AssetError("%s: SHA-256 mismatch" % ent["file"])
        frames = []
        for off in range(0, len(blob), RECORD_SIZE):
            rec = blob[off:off + RECORD_SIZE]
            dur = struct.unpack_from("<H", rec, 0)[0]
            frames.append((dur, rec[2:258], rec[258:514], rec[514:770]))
        result[ent["id"]] = frames
    return manifest, result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true", help="do not write; fail if --out is missing or stale")
    args = ap.parse_args(argv)

    try:
        reactions, sha = load_and_validate(args.src)
    except (AssetError, OSError, ValueError, KeyError) as exc:
        print("VALIDATION FAILED: %s" % exc, file=sys.stderr)
        return 2
    files = build(reactions, sha)
    nframes = sum(len(r["frames"]) for r in reactions)
    total = sum(len(b) for n, b in files.items() if n.endswith(".bin"))
    print("source ok: %d reactions, %d frames, asset_version=%s" % (len(reactions), nframes, sha[:12]))
    print("packed size: %d bytes in %d files (+ manifest)" % (total, len(reactions)))

    if args.check:
        stale = []
        for name, blob in files.items():
            path = os.path.join(args.out, name)
            if not os.path.exists(path):
                stale.append(name)
                continue
            with open(path, "rb") as fh:
                if fh.read() != blob:
                    stale.append(name)
        if stale:
            print("STALE or missing in %s: %s" % (args.out, ", ".join(stale)), file=sys.stderr)
            return 1
        print("up to date: %s" % args.out)
        return 0

    write_all(files, args.out)
    print("wrote %d files to %s" % (len(files), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
