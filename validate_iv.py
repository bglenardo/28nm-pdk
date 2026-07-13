"""validate_iv.py -- automated shape grader for output-family IV sweeps.

Turns the human eyeball-the-PNG step (CLAUDE.md Q8) into a check that runs
after every measurement, so a physically-meaningless run gets FLAGGED instead
of silently counting as done. This is the safeguard that would have caught the
2026-07-13 bench failure: an nMOS routine on a pMOS device produced six Vg
curves lying exactly on top of each other, pinned at the Keithley's -10 mA
compliance rail.

Grades an "output family" = Id vs sweep param (Vd), one curve per step value
(Vg). Pure function over the RoutineMeasurement list the runner already
returns -- no hardware, no I/O.

The three failure modes, each straight from Q8:
  1. LEAKAGE FLOOR   -- "All-flat-at-nA = nothing selected." |Id| never rises
                        above the nA-scale leakage floor.
  2. COMPLIANCE PIN  -- "Pinned at one value = compliance limit, not physics."
                        A large fraction of points sit at |I_compliance|.
  3. NO MODULATION   -- a working family FANS with Vg; if the step curves lie
                        on top of each other, the gate isn't controlling the
                        channel (the other half of the 2026-07-13 signature).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

# --- Thresholds (each cited). Tuned to PASS a healthy fanned family and FAIL
# --- the 2026-07-13 pMOS-on-nMOS-routine capture used as the negative fixture.

# Q8: room-temp mid-geometry NMOS reads uA-to-tens-of-uA; the leakage floor is
# nA-scale. 1 uA sits comfortably between them.
LEAKAGE_FLOOR_A = 1e-6

# A point within this fraction of |I_compliance| is treated as rail-pinned.
COMPLIANCE_TOL_FRAC = 0.02
# Fail if more than this fraction of all points are pinned at compliance.
COMPLIANCE_MAX_PINNED_FRAC = 0.25

# Fail if the spread across step (Vg) curves -- measured at the sweep endpoint
# where a real family fans the most -- is below this fraction of peak |Id|.
# A healthy family spreads by more than this; overlapping curves fall short.
MIN_MODULATION_FRAC = 0.05


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reasons: list[str]  # empty when ok; one human-readable line per failure

    def __str__(self) -> str:
        if self.ok:
            return "PASS"
        return "SUSPECT: " + "; ".join(self.reasons)


def grade_output_family(points, compliance_a: float = 0.01) -> Verdict:
    """Grade an output-family sweep. `points` = list[RoutineMeasurement].

    compliance_a: the drain-source current compliance magnitude (default 0.01 A
    = instrument_list.yaml keithley_2400 current_compliance_a). Points at this
    magnitude are the rail, not physics.
    """
    reasons: list[str] = []

    currents = [p.drain_i_a for p in points]
    if not currents:
        return Verdict(False, ["no measurement points"])

    abs_currents = [abs(i) for i in currents]
    peak = max(abs_currents)

    # 1. Leakage floor: nothing ever conducts above the nA-scale floor.
    if peak < LEAKAGE_FLOOR_A:
        reasons.append(
            f"peak |Id| {peak:.2e} A below {LEAKAGE_FLOOR_A:.0e} A leakage "
            "floor (Q8: all-flat-at-nA = nothing selected)"
        )

    # 2. Compliance-pinned: too many points sitting on the rail.
    comp = abs(compliance_a)
    pinned = sum(1 for a in abs_currents if a >= comp * (1.0 - COMPLIANCE_TOL_FRAC))
    pinned_frac = pinned / len(abs_currents)
    if pinned_frac > COMPLIANCE_MAX_PINNED_FRAC:
        reasons.append(
            f"{pinned_frac:.0%} of points pinned at |compliance| "
            f"({comp:.3g} A) (Q8: pinned = compliance limit, not physics)"
        )

    # 3. Gate modulation: measure the spread of Id across step (Vg) curves at
    # the common sweep endpoint (largest |sweep value|), where a real output
    # family fans out the most.
    by_step: dict[float, dict[float, float]] = defaultdict(dict)
    for p in points:
        by_step[p.step_value_v][p.sweep_value_v] = p.drain_i_a
    if len(by_step) >= 2:
        # Pick the sweep value furthest from zero that every step curve reached.
        common_sweeps = set.intersection(*(set(d) for d in by_step.values()))
        if common_sweeps:
            endpoint = max(common_sweeps, key=abs)
            id_at_endpoint = [by_step[s][endpoint] for s in by_step]
            spread = max(id_at_endpoint) - min(id_at_endpoint)
            if peak > 0 and (spread / peak) < MIN_MODULATION_FRAC:
                reasons.append(
                    f"Vg curves overlap: spread {spread:.2e} A across step "
                    f"values at sweep={endpoint:.3g} V is < "
                    f"{MIN_MODULATION_FRAC:.0%} of peak |Id| (Q8: no gate "
                    "modulation = gate not controlling the channel)"
                )

    return Verdict(not reasons, reasons)
