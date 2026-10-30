import pyvisa
import time


class DC215:
    """
    Wraps an SRS DC215 voltage/current source reached over Ethernet
    (bare socket, port 5025 per manual Table 18), exposing simple
    set_voltage()/read_voltage()/read_current() methods.

    NOTE: MONO? index -> quantity mapping (0=voltage, 1=current) is
    inferred from typical SRS conventions and the abridged command
    index, not confirmed against the full command description on page
    139 of the manual. Verify empirically (set a known voltage via
    set_voltage(), confirm read_voltage() tracks it) before trusting
    this on real hardware.
    """

    OVERLOAD_SENTINEL = 9.999e3 * 0.999  # per manual: error reading = 9.999999E3

    def __init__(self, ip: str, port: int = 5025, timeout_ms: int = 5000,
                 i_compliance_a: float = 0.1):
        self.rm = pyvisa.ResourceManager()
        self.inst = self.rm.open_resource(f"TCPIP0::{ip}::{port}::SOCKET")
        self.inst.read_termination = '\r\n'
        self.inst.write_termination = '\r\n'
        self.inst.timeout = timeout_ms

        idn = self.inst.query("*IDN?").strip()
        print(f"Connected to: {idn}")

        self._configure(i_compliance_a)

    def _configure(self, i_compliance_a: float) -> None:
        self.inst.write("*RST")
        time.sleep(0.2)
        self.inst.write("VORI 0")                        # 0 = voltage output mode (per abridged index / inferred)
        self.inst.write(f"LIMI 1,{i_compliance_a:.6g}")   # current compliance limit (parameter order inferred)
        self.inst.write("SENS 0")                         # 0 = 2-wire sense
        self.inst.write("MEAS 1")                         # enable measurement engine
        self.inst.write("OUTP 1")  
        self.inst.write("INTG 0")                         # output ON
        time.sleep(0.3)

    def set_voltage(self, volts: float) -> None:
        """Source a voltage on the output (SORC 0,<value> per abridged index)."""
        self.inst.write(f"SORC 0,{volts:.6f}")

    def _read_monitor(self, monitor_index: int) -> float:
        resp = self.inst.query(f"MONO? {monitor_index}").strip()
        try:
            val = float(resp.split(",")[0])
        except (ValueError, IndexError):
            print(f"WARNING: could not parse MONO? {monitor_index} response: {resp!r}")
            return float("nan")
        if abs(val) >= self.OVERLOAD_SENTINEL:
            print(f"WARNING: overload/error reading on MONO? {monitor_index}")
            return float("nan")
        return val

    def read_voltage(self) -> float:
        return self._read_monitor(0)

    def read_current(self) -> float:
        return self._read_monitor(1)

    def read_both(self) -> tuple[float, float]:
        """Convenience method returning (voltage, current) together."""
        return self.read_voltage(), self.read_current()

    def output_off(self) -> None:
        self.inst.write("OUTP 0")
        try:
            self.inst.write("OUTP 0")
        except Exception:
            pass

    def close(self) -> None:
        self.output_off()
        try:
            self.inst.close()
        except Exception:
            pass
        try:
            self.rm.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


if __name__ == "__main__":
    dc215 = DC215(ip="192.168.1.50", i_compliance_a=0.02)
    dc215.set_voltage(1)
    time.sleep(1)
    v, i = dc215.read_both()
    print(f"V={v}, I={i}")