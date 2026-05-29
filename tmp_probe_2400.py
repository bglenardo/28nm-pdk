import sys
from pathlib import Path

sys.path.insert(0, str(Path("src")))

from iv_measure.keithley2400 import Keithley2400

cmds = [
    "*RST",
    ":SOUR:FUNC VOLT",
    ":SENS:FUNC \"CURR\"",
    ":SENS:CURR:PROT 0.01",
    ":SENS:CURR:RANG:AUTO ON",
    ":SYST:RSEN ON",
    ":INIT:CONT OFF",
    ":TRIG:COUN 1",
    ":FORM:ELEM CURR",
    ":ABOR",
    ":OUTP ON",
    ":OUTP OFF",
]

k = Keithley2400(port="COM7")
k.open()
print("IDN", k.identify())
for c in cmds:
    try:
        k.send_scpi(c)
        e = k.query_scpi("SYST:ERR?")
        print(f"{c} => {e}")
    except Exception as ex:
        print(f"{c} => EX {ex}")
k.close()
