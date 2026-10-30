import pyvisa
import time

rm = pyvisa.ResourceManager()
srs = rm.open_resource("TCPIP0::192.168.1.50::5025::SOCKET")
srs.read_termination = '\r\n'
srs.write_termination = '\r\n'
srs.timeout = 5000

print(srs.query("*IDN?"))

srs.write("*RST")
time.sleep(0.2)

# Send each config command individually and check for errors after EACH one
commands = [
    "VORI 0",
    "LIMI 1,0.02",
    "SENS 0",
    "MEAS 1",
    "OUTP 1",
]

for cmd in commands:
    srs.write(cmd)
    time.sleep(0.1)
    err = srs.query("LERR?").strip()
    print(f"Sent: {cmd!r} -> LERR? = {err!r}")

# Check whether output actually reports itself as ON
print("OUTP? ->", srs.query("OUTP?").strip())
print("MEAS? ->", srs.query("MEAS?").strip())
print("VORI? ->", srs.query("VORI?").strip())