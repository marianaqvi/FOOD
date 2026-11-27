# firmware/isotime.py
# Parse the server's UTC timestamps ("2026-11-26T20:10:00.123Z") to epoch milliseconds with
# integer maths only, so it behaves the same on MicroPython and CPython and needs no RTC.
# The device never trusts its own wall clock for expiry: it compares the command's expiry with the
# server_time that arrived in the SAME response (see app.py), so only elapsed monotonic time matters.


def _days_from_civil(y, m, d):
    if m <= 2:
        y -= 1
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    mp = m - 3 if m > 2 else m + 9
    doy = (153 * mp + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def parse_iso_ms(s):
    """'YYYY-MM-DDTHH:MM:SS[.fff]Z' -> integer epoch milliseconds. Raises ValueError on anything else."""
    if not isinstance(s, str) or len(s) < 20 or len(s) > 30 or s[-1] != "Z":
        raise ValueError("bad timestamp")
    if s[4] != "-" or s[7] != "-" or s[10] != "T" or s[13] != ":" or s[16] != ":":
        raise ValueError("bad timestamp")
    y, mo, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    hh, mi, ss = int(s[11:13]), int(s[14:16]), int(s[17:19])
    ms = 0
    rest = s[19:-1]
    if rest:
        if rest[0] != "." or not rest[1:].isdigit():
            raise ValueError("bad timestamp")
        ms = int((rest[1:] + "000")[:3])
    if not (1970 <= y <= 2200 and 1 <= mo <= 12 and 1 <= d <= 31 and hh < 24 and mi < 60 and ss < 61):
        raise ValueError("bad timestamp")
    days = _days_from_civil(y, mo, d)
    return ((days * 24 + hh) * 60 + mi) * 60000 + ss * 1000 + ms
