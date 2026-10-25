import tempfile
import unittest
from pathlib import Path

import yaml

from iv_measure.config import load_project_config


class TestHP34401AConfig(unittest.TestCase):
    def test_load_project_config_reads_current_meter(self):
        payload = {
            "instruments": {
                "keithley_2400": {
                    "type": "Keithley2400",
                    "port": "COM7",
                    "quantity": "Vd",
                    "baudrate": 9600,
                },
                "keithley_e3631a_a": {
                    "type": "E3631A",
                    "port": "COM5",
                    "baudrate": 9600,
                    "channel_map": {"P25V": "Vg"},
                },
                "hp34401a_1v8": {
                    "type": "HP34401A",
                    "port": "COM8",
                    "baudrate": 9600,
                    "measure_current_cmd": "MEAS:CURR:DC?",
                    "current_meter": True,
                    "sample_every_n_points": 10,
                },
            },
            "assignments": {"gate_source": "keithley_e3631a_a", "drain_source": "keithley_2400"},
            "sweep": {"gate_voltages_v": [0.0], "drain_start_v": 0.0, "drain_stop_v": 1.0, "drain_step_v": 0.1},
        }

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "instrument_list.yaml"
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            cfg = load_project_config(path)

        self.assertIsNotNone(cfg.current_meter)
        self.assertEqual(cfg.current_meter.port, "COM8")
        self.assertEqual(cfg.current_meter.measure_current_cmd, "MEAS:CURR:DC?")
        self.assertEqual(cfg.sample_every_n_points, 10)


if __name__ == "__main__":
    unittest.main()
