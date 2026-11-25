#!/usr/bin/env python3
"""Export per-frame render hashes from the Python reference renderer.

The browser test (web/tests/parity.test.ts) recomputes the same hashes with the
TypeScript compositor. Any difference in pixel, layer order, origin or colour
maths fails that test.

    python3 scripts/export_golden.py          # write tests/golden/render_hashes.json
    python3 scripts/export_golden.py --check  # fail if the committed file is stale

Hash = first 16 hex chars of SHA-256 over the hardware buffer as RGB bytes,
row-major. Keys: "<reaction>:<frame>" -> [origin0_chained, origin64_chained, single].
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pack_assets as pa  # noqa: E402
import reference_renderer as rr  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "tests", "golden", "render_hashes.json")
COLOURS = ["#F0F5F1", "#FFB34F", "#75CAFF"]  # three distinct colours so layer order matters
SCALE = 100


def digest(buf):
    flat = bytes(c for row in buf for px in row for c in px)
    return hashlib.sha256(flat).hexdigest()[:16]


def build():
    reactions, sha = pa.load_and_validate()
    hashes = {}
    for r in reactions:
        for n, (_dur, a, b, fx) in enumerate(r["frames"]):
            masks = (a, b, fx)
            hashes["%s:%d" % (r["id"], n)] = [
                digest(rr.compose(masks, COLOURS, SCALE, origin=0)),
                digest(rr.compose(masks, COLOURS, SCALE, origin=64)),
                digest(rr.compose(masks, COLOURS, SCALE, origin=0, mode=rr.SINGLE)),
            ]
    return {
        "asset_version": sha[:12],
        "colours": COLOURS,
        "scale_permille": SCALE,
        "columns": ["chained_origin_0", "chained_origin_64", "single_origin_0"],
        "hashes": hashes,
    }


def main():
    text = json.dumps(build(), indent=0, sort_keys=False) + "\n"
    if "--check" in sys.argv:
        ok = os.path.exists(OUT) and open(OUT, encoding="utf-8").read() == text
        print("golden up to date" if ok else "golden STALE or missing: run scripts/export_golden.py")
        return 0 if ok else 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("wrote %s (%d frames)" % (OUT, len(json.loads(text)["hashes"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
