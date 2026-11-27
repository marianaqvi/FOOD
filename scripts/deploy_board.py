#!/usr/bin/env python3
"""Copy the firmware to the Interstate 75 W over USB (raw REPL). Never flashes firmware, never
formats, never deletes anything except /autostart when asked.

BEFORE RUNNING: board attached to the Mac by USB, adapter NOT connected, and BOTH PANELS' POWER
PLUGS UNPLUGGED (the panels draw through the board's terminals; never Mac and panels together).

    python3 scripts/deploy_board.py --i-have-unplugged-panel-power [--secrets] [--autostart on|off]
                                    [--expect /main.py=de8d27aaf225 ...]

Safety rules it enforces:
  * a file that already exists on the board is overwritten ONLY if its SHA-256 matches either the
    new content (skipped), an entry in /deploy_manifest.json from a previous deploy, or an
    --expect path=hash-prefix you pass for a file you know you installed earlier;
  * every file is written to NAME.new, read back and SHA-256 verified, then renamed into place;
  * the manifest of what was installed is rewritten at the end; secrets are uploaded but never printed.
"""
import argparse
import binascii
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boardlink import Board  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FW = os.path.join(ROOT, "firmware")
CODE = [
    ("/power.py", "power.py"), ("/hwtest_common.py", "hwtest_common.py"), ("/renderer.py", "renderer.py"), ("/player.py", "player.py"),
    ("/fallback.py", "fallback.py"), ("/isotime.py", "isotime.py"), ("/config_store.py", "config_store.py"),
    ("/network_client.py", "network_client.py"), ("/app.py", "app.py"), ("/main.py", os.path.join("tools", "stage_runner_main.py")),
]
SHA = "import hashlib, binascii\nprint(binascii.hexlify(hashlib.sha256(open(%r,'rb').read()).digest()).decode())"
MANIFEST = "/deploy_manifest.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--i-have-unplugged-panel-power", action="store_true", required=True)
    ap.add_argument("--secrets", action="store_true", help="also upload firmware/secrets.py as /secrets.py")
    ap.add_argument("--autostart", choices=("on", "off"))
    ap.add_argument("--expect", action="append", default=[], help="/path=hash-prefix of an earlier install you vouch for")
    args = ap.parse_args()
    expect = dict(e.split("=", 1) for e in args.expect)

    jobs = [(dst, os.path.join(FW, src)) for dst, src in CODE]
    if args.secrets:
        sp = os.path.join(FW, "secrets.py")
        if not os.path.exists(sp):
            raise SystemExit("firmware/secrets.py is missing: run scripts/make_secrets.py first")
        jobs.append(("/secrets.py", sp))

    b = Board()
    b.enter_raw()

    def board_sha(p):
        out, err = b.exec(SHA % p)
        return None if err else out.strip()

    out, _ = b.exec("import os, json\ntry:\n    print(open(%r).read())\nexcept OSError:\n    print('{}')" % MANIFEST)
    manifest = json.loads(out.strip() or "{}")
    plan = []
    for dst, src in jobs:
        data = open(src, "rb").read()
        want = hashlib.sha256(data).hexdigest()
        have = board_sha(dst)
        if have is None:
            plan.append((dst, data, want, "new"))
        elif have == want:
            plan.append((dst, data, want, "same"))
        elif have == manifest.get(dst) or (dst in expect and have.startswith(expect[dst])):
            plan.append((dst, data, want, "update"))
        else:
            print("REFUSING:", dst, "exists on the board and is not something this tool installed (hash %s...)." % have[:12])
            print("         Pass --expect %s=%s if you know it is your earlier install." % (dst, have[:12]))
            b.exit_raw()
            sys.exit(1)
    for dst, data, want, kind in plan:
        print("%-8s %s" % (kind, dst if dst != "/secrets.py" else "/secrets.py (contents not shown)"))
    for dst, data, want, kind in plan:
        if kind == "same":
            continue
        b.exec("import binascii\nf = open(%r, 'wb')" % (dst + ".new"))
        for i in range(0, len(data), 384):
            _, err = b.exec("f.write(binascii.a2b_base64(%r))" % binascii.b2a_base64(data[i:i + 384], newline=False).decode())
            assert not err, err
        b.exec("f.close()")
        got = board_sha(dst + ".new")
        if got != want:
            print("READ-BACK MISMATCH for", dst, "- original left untouched")
            b.exit_raw()
            sys.exit(1)
    for dst, data, want, kind in plan:
        if kind == "same":
            continue
        b.exec("import os\nos.rename(%r, %r)" % (dst + ".new", dst))
        assert board_sha(dst) == want, dst
        print("installed", dst)
    for dst, data, want, kind in plan:
        manifest[dst] = want
    b.exec("import json\nf = open('/deploy_manifest.json.new','w')\nf.write(%r)\nf.close()\nimport os\nos.rename('/deploy_manifest.json.new','/deploy_manifest.json')" % json.dumps(manifest))
    if args.autostart == "on":
        b.exec("open('/autostart','w').close()")
        print("autostart ENABLED: the network app starts at boot (hold A+B while powering on to skip it)")
    elif args.autostart == "off":
        b.exec("import os\ntry:\n    os.remove('/autostart')\nexcept OSError:\n    pass")
        print("autostart disabled")
    out, _ = b.exec("import os\ns=os.statvfs('/')\nprint('free bytes', s[0]*s[3])")
    print(out.strip())
    b.exit_raw()


if __name__ == "__main__":
    main()
