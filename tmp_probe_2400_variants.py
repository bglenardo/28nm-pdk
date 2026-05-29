import sys
from pathlib import Path

sys.path.insert(0, str(Path("src")))

from iv_measure.keithley2400 import Keithley2400

variants = [
    "*CLS",
    "*RST",
    "SYST:ERR?",
    "OUTP ON",
    "OUTP OFF",
    ":OUTP ON",
    "SOUR:FUNC VOLT",
    ":SOUR:FUNC VOLT",
    "SOUR:VOLT 0.1",
    ":SOUR:VOLT 0.1",
    "SENS:FUNC 'CURR'",
    "SENS:FUNC \"CURR\"",
    ":SENS:FUNC 'CURR'",
    ":SENS:FUNC \"CURR\"",
    "SENS:CURR:PROT 0.01",
    ":SENS:CURR:PROT 0.01",
    "SENS:CURR:RANG:AUTO ON",
    ":SENS:CURR:RANG:AUTO ON",
    "FORM:ELEM CURR",
    ":FORM:ELEM CURR",
    "INIT:CONT OFF",
    ":INIT:CONT OFF",
    "TRIG:COUN 1",
    ":TRIG:COUN 1",
    "ABOR",
    ":ABOR",
    "MEAS:CURR?",
    ":MEAS:CURR?",
]

k = Keithley2400(port="COM7")
k.open()
print("IDN", k.identify())
for c in variants:
    # clear queue first
    try:
        k.send_scpi("*CLS")
    except Exception:
        pass

    try:
        if c.endswith("?"):
            r = k.query_scpi(c)
            e = k.query_scpi("SYST:ERR?")
            print(f"{c:<28} => RESP {r!r} | ERR {e}")
        else:
            k.send_scpi(c)
            e = k.query_scpi("SYST:ERR?")
            print(f"{c:<28} => ERR {e}")
    except Exception as ex:
        print(f"{c:<28} => EX {ex}")

k.close()
