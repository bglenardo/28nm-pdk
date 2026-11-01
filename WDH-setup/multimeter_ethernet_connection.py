import pyvisa
import re

def parse_current(raw_reading: str) -> float:
    """
    Parses a Keithley 2701 :READ? response like:
      '+2.63107650E-05ADC,+81720.815841SECS,+833425RDNG#'
    and returns just the current value in Amps as a float.
    """
    first_field = raw_reading.strip().split(",")[0]
    match = re.match(r"[+-]?\d+\.?\d*[Ee]?[+-]?\d*", first_field)
    if not match:
        raise ValueError(f"Could not parse current from: {raw_reading!r}")
    return float(match.group())

class CurrentReader:
    """
    Wraps a Keithley 2701 (no plug-in card installed -- measures DC current
    directly through the front-panel INPUT terminals) reached over Ethernet
    via a raw SCPI socket connection.
    """

    def __init__(self, ip_address: str = "192.168.1.47", port: int = 1394,
                 timeout_ms: int = 5000):
        self.rm = pyvisa.ResourceManager()
        self.inst = self.rm.open_resource(f"TCPIP0::{ip_address}::{port}::SOCKET")
        self.inst.read_termination = '\n'
        self.inst.write_termination = '\n'
        self.inst.timeout = timeout_ms

        idn = self.inst.query("*IDN?").strip()
        print(f"Connected to: {idn}")

        self.inst.write("*RST")

        # No plug-in card installed, so no channel addressing (@101) is
        # needed -- measure directly through the front-panel INPUT terminals.
        self.inst.write(':SENS:FUNC "CURR:DC"')
        self.inst.write(":SENS:CURR:DC:RANG:AUTO ON")

    def read_current(self) -> float:
        """Take one DC current reading and return it as a float (Amps)."""
        reading = self.inst.query(":READ?").strip()
        try:
            return float(parse_current(reading.split(",")[0]))
        except (ValueError, IndexError):
            print(f"WARNING: could not parse reading '{reading}'")
            return float("nan")

    

    def close(self) -> None:
        try:
            self.inst.close()
        except Exception:
            pass
        try:
            self.rm.close()
        except Exception:
            pass

    # --- context manager support: lets you do `with CurrentReader() as cr:` ---
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


if __name__ == "__main__":
    with CurrentReader() as cr:
        i = cr.read_current()
        print(f"Current: {i} A")