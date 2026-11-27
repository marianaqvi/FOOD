"""Minimal raw-REPL client for the Interstate 75 W (pyserial). Runs code in the board's RAM only;
it writes to the board's filesystem only when the code you send does. It never resets the board
unless asked. The board must be attached by USB with the PANEL POWER PLUGS UNPLUGGED.

    python3 scripts/boardlink.py "print(1+1)"
    python3 scripts/boardlink.py --cat /last_run.txt
"""
import glob
import sys
import time

import serial


def find_port():
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    if not ports:
        raise SystemExit("no /dev/cu.usbmodem* device: is the board attached by USB?")
    return ports[0]


class Board:
    def __init__(self, port=None):
        self.s = serial.Serial(port or find_port(), 115200, timeout=0.2)

    def read_until(self, token, timeout=10):
        buf = b""
        end = time.time() + timeout
        while time.time() < end:
            buf += self.s.read(4096)
            if token in buf:
                return buf
        raise TimeoutError("timeout waiting for %r, got %r" % (token, buf[-200:]))

    def enter_raw(self):
        self.s.write(b"\r\x03\x03")  # interrupt a running program (no reset, no file writes)
        time.sleep(0.3)
        self.s.reset_input_buffer()
        self.s.write(b"\r\x01")
        self.read_until(b"raw REPL; CTRL-B to exit\r\n>")

    def exec(self, code, timeout=60):
        data = code.encode()
        for i in range(0, len(data), 128):
            self.s.write(data[i:i + 128])
            time.sleep(0.01)
        self.s.write(b"\x04")
        buf = self.read_until(b"\x04>", timeout)
        assert buf.startswith(b"OK"), buf[:80]
        out, _, err = buf[2:-2].partition(b"\x04")
        return out.decode(errors="replace"), err.decode(errors="replace")

    def soft_reset_and_read(self, seconds=8):
        """Ctrl-D at the normal REPL: reruns main.py. Returns what it printed."""
        self.s.write(b"\r\x03\x03")
        time.sleep(0.5)
        self.s.reset_input_buffer()
        self.s.write(b"\x04")
        buf, end = b"", time.time() + seconds
        while time.time() < end:
            buf += self.s.read(4096)
        return buf.decode(errors="replace")

    def exit_raw(self):
        self.s.write(b"\x02")
        time.sleep(0.2)
        self.s.close()


if __name__ == "__main__":
    b = Board()
    b.enter_raw()
    if len(sys.argv) > 2 and sys.argv[1] == "--cat":
        code = "print(open(%r).read())" % sys.argv[2]
    else:
        code = sys.argv[1] if len(sys.argv) > 1 else "print(1)"
    out, err = b.exec(code)
    print(out, end="")
    if err:
        print("STDERR:", err, end="")
    b.exit_raw()
