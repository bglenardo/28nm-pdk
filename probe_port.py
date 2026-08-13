"""probe_port.py [PORT] -- is the SEL sketch answering on this port?

Read-only liveness check: lists all serial ports, prints any boot banner on
the chosen port, then PINGs for PONG. Does NOT select any device or touch
instruments. Q5: only one program may hold the port (close Serial Monitor).
Q6: no banner is normal; no PONG means the SEL parser isn't there.
"""
import sys
import time

import serial
import serial.tools.list_ports as lp

print("--- serial ports present ---")
ports = list(lp.comports())
if not ports:
    print("NO SERIAL PORTS FOUND")
for p in ports:
    print(f"  {p.device} | {p.description} | {p.hwid}")

port = sys.argv[1] if len(sys.argv) > 1 else "COM13"
print(f"\nopening {port} ...")
ser = serial.Serial(port=port, baudrate=115200, timeout=1)
time.sleep(2.0)  # allow reset-on-open (if it happens) to boot

print("--- lines seen after open (4 s) ---")
deadline = time.time() + 4
saw_ready = False
while time.time() < deadline:
    line = ser.readline().decode(errors="ignore").strip()
    if line:
        print("  ", repr(line))
        if line == "READY":
            saw_ready = True

ser.reset_input_buffer()
ser.write(b"PING\n")
print("--- sent PING, waiting up to 5 s for PONG ---")
deadline = time.time() + 5
saw_pong = False
while time.time() < deadline:
    line = ser.readline().decode(errors="ignore").strip()
    if line:
        print("  ", repr(line))
        if line == "PONG":
            saw_pong = True
            break

ser.close()
print(f"\nRESULT: READY banner={saw_ready}  PONG={saw_pong}")
if saw_pong:
    print("-> SEL sketch is alive on this port. Safe to run the loop.")
else:
    print("-> No PONG. Likely: wrong port, SEL sketch not flashed, "
          "or Serial Monitor/another program holds the port (Q5).")
