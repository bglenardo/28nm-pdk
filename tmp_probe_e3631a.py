import sys
from pathlib import Path

sys.path.insert(0, str(Path("src")))

from iv_measure.e3631a import E3631A

cmds = [
    "*CLS",
    "*RST",
    "SYST:ERR?",
    "OUTP ON",
    "OUTP OFF",
    "OUTP 1",
    "OUTP 0",
    "APPL P6V, 0.000000, 0.100000",
    "APPL P25V, 0.000000, 0.100000",
]

s = E3631A(port="COM5")
s.open()
print("IDN", s.identify())
for c in cmds:
    try:
        if c.endswith("?"):
            r = s.query_scpi(c)
            print(f"{c:<30} => RESP {r!r}")
        else:
            s.send_scpi(c)
            e = s.query_scpi("SYST:ERR?")
            print(f"{c:<30} => ERR {e}")
    except Exception as ex:
        print(f"{c:<30} => EX {ex}")
s.close()
