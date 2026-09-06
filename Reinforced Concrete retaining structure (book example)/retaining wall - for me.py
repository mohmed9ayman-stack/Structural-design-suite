"""
Reinforced concrete retaining wall — ULS verification
(sliding, overturning, and ground contact pressure)

Converted from the SMath worksheet "Reinforced Concrete retaining
structure.sm" (worked example following Eurocode 7, Design Approach 2 /
partial-factor Set B).

WHAT CHANGED VS. THE ORIGINAL SHEET
------------------------------------
The original worksheet typed in several numbers directly (K_a, the earth
thrust forces, the lever arms 0.6 m / 0.4 m) instead of deriving them from
the geometry. That only worked because, in that particular numeric
example, several unrelated lengths happened to equal 2.5 m by coincidence.
This script derives everything from a small set of independent inputs, so
changing one dimension updates every downstream result correctly:

  - K_a is computed from the friction angle phi (Rankine: no wall
    friction, since the sheet uses delta = 0).
  - The earth-pressure thrust (from the retained ground) and the
    surcharge thrust are computed from K_a, gamma, h_w and q_surch,
    instead of being typed in as fixed numbers.
  - The footing width B is computed as b_f2 + t_w + b_f1 (it was a
    separate, redundantly re-entered input before).
  - The stem height used for the wall/backfill self-weight is computed
    as h_stem = h_w - T_f. The original sheet reused the footing-width
    variable for this, which only gave the right answer because the two
    happened to have the same value (2.5 m) in this example.

All formulas were checked against the worksheet's own worked numbers and
against Tables 2.2 and 2.3 in the PDF (max ground pressure for the four
partial-factor combinations, for both surcharge extents) and reproduce
them exactly.

WHAT DID NOT CHANGE
--------------------
The partial (safety) factors themselves are prescribed by Eurocode 7 for
the approach/set the sheet uses; they are not free design inputs, so they
are kept as fixed constants (see PARTIAL FACTORS below) rather than
function arguments. If you work to a different design approach/set, edit
those constants.
"""

from dataclasses import dataclass
from math import radians, tan


# ---------------------------------------------------------------------------
# PARTIAL (SAFETY) FACTORS — fixed by Eurocode 7, Design Approach 2 / Set B,
# exactly as used in the source worksheet. Not meant to be changed per run;
# edit here only if you are deliberately switching design approach/set.
# ---------------------------------------------------------------------------
GAMMA_G_GROUND_SLIDE = 1.10   # unfavourable permanent (earth thrust), sliding check
GAMMA_Q_SURCH_SLIDE = 1.50    # unfavourable variable (surcharge thrust), sliding check
GAMMA_G_FAV = 0.90            # favourable permanent (self-weights resisting sliding/overturning)

GAMMA_G_GROUND_OVERTURN = 1.10
GAMMA_Q_SURCH_OVERTURN = 1.50

GAMMA_Q_GROUND_MOMENT = 1.35  # unfavourable permanent, ground-thrust moment, contact-pressure check
GAMMA_Q_SURCH_MOMENT = 1.50   # unfavourable variable, surcharge-thrust moment, contact-pressure check

# The four Set-B combinations of self-weight factors used in the sheet's
# Tables 2.2/2.3, applied to (wall+footing) and (backfill above the heel)
# self-weights respectively:
SELF_WEIGHT_COMBINATIONS = [
    ("1st", 1.00, 1.00),
    ("2nd", 1.35, 1.35),
    ("3rd", 1.00, 1.35),
    ("4th", 1.35, 1.00),
]

# ---------------------------------------------------------------------------
# SOIL-TYPE PRESETS — typical, order-of-magnitude values (gamma, phi, mu) for
# common backfill materials, just to get you a sensible starting point.
# These are NOT a substitute for site-specific geotechnical data.
#
# IMPORTANT LIMITATION: this script's earth-pressure formula (Rankine,
# Ka = tan^2(45 - phi/2)) assumes a cohesionless soil (no cohesion "c").
# That is a reasonable approximation for sands and gravels, but real clays
# derive much of their strength from cohesion, not friction angle alone,
# and are often analysed undrained (using undrained shear strength, not
# phi) for short-term stability. The "clay" presets below are only a rough
# stand-in using an equivalent effective friction angle -- treat results
# for clay backfill as illustrative, not as a real clay design, and consult
# a geotechnical engineer for actual clay-backfill retaining walls.
# ---------------------------------------------------------------------------
SOIL_PRESETS = {
    "loose sand": dict(gamma=17.0, phi=30.0, mu=0.45),
    "medium dense sand": dict(gamma=18.0, phi=32.0, mu=0.50),
    "dense sand": dict(gamma=20.0, phi=38.0, mu=0.55),
    "gravel": dict(gamma=20.0, phi=40.0, mu=0.55),
    "silty sand": dict(gamma=18.0, phi=28.0, mu=0.45),
    "stiff clay (effective-stress approx.)": dict(gamma=19.0, phi=22.0, mu=0.35),
    "soft clay (effective-stress approx.)": dict(gamma=17.0, phi=15.0, mu=0.25),
}


@dataclass
class WallInputs:
    # --- soil / material properties ---
    gamma: float      # soil unit weight [kN/m3]
    phi: float        # angle of shearing resistance [deg]
    mu: float         # base (ground-flooring) friction factor [-]
    rho: float        # reinforced-concrete unit weight [kN/m3]
    delta: float = 0  # wall-soil interface friction angle [deg] (0 -> Rankine, as in the sheet)

    # --- geometry (see the worksheet's Fig. 2.13) ---
    t_w: float = 0.3    # stem (wall) thickness [m]
    h_w: float = 3.0    # total wall height, top of stem to underside of footing [m]
    T_f: float = 0.5    # footing thickness [m]
    b_f1: float = 1.7   # heel length, backfill side, beyond the stem [m]
    b_f2: float = 0.5   # toe length, in front of the stem [m]

    # --- load ---
    q_surch: float = 10.0  # surcharge on the embankment [kN/m2]


@dataclass
class WallResults:
    B: float
    h_stem: float
    Ka: float
    P_k_wall: float
    P_k_foot: float
    G_k_ground: float
    S_k_ground: float
    s_k_surch: float
    FS_slide: float
    FS_overturn: float
    combos: list  # list of dicts, one per (self-weight combo x surcharge extent)
    governing: dict


def _validate(inp: WallInputs) -> None:
    positive = {
        "gamma": inp.gamma, "rho": inp.rho, "t_w": inp.t_w, "h_w": inp.h_w,
        "T_f": inp.T_f, "b_f1": inp.b_f1, "b_f2": inp.b_f2,
    }
    for name, value in positive.items():
        if value <= 0:
            raise ValueError(f"'{name}' must be greater than 0 (got {value}).")
    if not (0 < inp.phi < 90):
        raise ValueError(f"'phi' must be between 0 and 90 degrees (got {inp.phi}).")
    if inp.mu <= 0:
        raise ValueError(f"'mu' must be greater than 0 (got {inp.mu}).")
    if inp.q_surch < 0:
        raise ValueError(f"'q_surch' cannot be negative (got {inp.q_surch}).")
    if inp.h_w <= inp.T_f:
        raise ValueError(
            f"'h_w' ({inp.h_w}) must be greater than 'T_f' ({inp.T_f}) — "
            "the total wall height has to be taller than the footing slab itself, "
            "since h_w - T_f is the stem height."
        )


def analyze(inp: WallInputs) -> WallResults:
    _validate(inp)

    # ---- derived geometry ----
    B = inp.b_f2 + inp.t_w + inp.b_f1          # total footing width
    h_stem = inp.h_w - inp.T_f                 # stem height above the footing

    # ---- earth-pressure coefficient (Rankine, delta = 0) ----
    Ka = tan(radians(45 - inp.phi / 2)) ** 2

    # ---- characteristic self-weights (unfactored) ----
    P_k_wall = inp.t_w * h_stem * inp.rho          # stem self-weight
    P_k_foot = inp.T_f * B * inp.rho               # footing self-weight
    G_k_ground = inp.b_f1 * h_stem * inp.gamma     # backfill weight above the heel

    # ---- characteristic horizontal thrusts (over the full height h_w) ----
    S_k_ground = 0.5 * Ka * inp.gamma * inp.h_w ** 2   # triangular earth-pressure resultant
    s_k_surch = Ka * inp.q_surch * inp.h_w             # rectangular surcharge-pressure resultant

    # =========================================================
    # 1) Sliding check
    # =========================================================
    S_ground = GAMMA_G_GROUND_SLIDE * S_k_ground
    S_sur = GAMMA_Q_SURCH_SLIDE * s_k_surch
    F_slide = S_ground + S_sur

    F_stab_wall = GAMMA_G_FAV * P_k_wall * inp.mu
    F_stab_foot = GAMMA_G_FAV * P_k_foot * inp.mu
    F_stab_ground = GAMMA_G_FAV * G_k_ground * inp.mu
    F_stab = F_stab_wall + F_stab_foot + F_stab_ground

    FS_slide = F_stab / F_slide

    # =========================================================
    # 2) Overturning check
    # =========================================================
    M_s_ground = GAMMA_G_GROUND_OVERTURN * (S_k_ground * inp.h_w / 3)
    M_s_surch = GAMMA_Q_SURCH_OVERTURN * (s_k_surch * (inp.h_w / 2))
    M_rib = M_s_ground + M_s_surch  # overturning moment

    arm_wall = B / 2 - (inp.b_f2 + inp.t_w / 2)
    arm_foot = B / 2
    arm_ground = (inp.b_f2 + inp.t_w + inp.b_f1 / 2) - B / 2

    M_stab_wall = GAMMA_G_FAV * (P_k_wall * arm_wall)
    M_stab_foot = GAMMA_G_FAV * (P_k_foot * arm_foot)
    M_stab_ground = GAMMA_G_FAV * (G_k_ground * ((inp.b_f2 + inp.t_w) + inp.b_f1 / 2))
    M_stab = M_stab_wall + M_stab_foot + M_stab_ground

    FS_overturn = M_stab / M_rib

    # =========================================================
    # 3) Ground contact pressure — loop over the 4 self-weight
    #    combinations x 2 surcharge extents (beyond footing only,
    #    or over the whole embankment incl. above the heel)
    # =========================================================
    M_s_ground_c = GAMMA_Q_GROUND_MOMENT * (S_k_ground * inp.h_w / 3)
    M_s_surch_c = GAMMA_Q_SURCH_MOMENT * (s_k_surch * (inp.h_w / 2))

    # characteristic surcharge load/moment when it also covers the heel
    P_k_surch_heel = inp.q_surch * inp.b_f1
    M_k_surch_heel = P_k_surch_heel * arm_ground  # same lever arm as the backfill weight

    combos = []
    for name, gG_wall, gG_ground in SELF_WEIGHT_COMBINATIONS:
        P_wall = gG_wall * P_k_wall
        P_foot = gG_wall * P_k_foot
        P_ground = gG_ground * G_k_ground

        M_wall = gG_wall * (P_k_wall * arm_wall)
        M_foot = gG_wall * 0.0  # footing self-weight acts through the footing centroid: zero arm
        M_ground = -gG_ground * (G_k_ground * arm_ground)

        for extent, with_surch_on_heel in (("beyond footing only", False), ("whole embankment", True)):
            P_tot = P_wall + P_foot + P_ground
            M_tot = M_s_ground_c + M_s_surch_c + M_wall + M_foot + M_ground

            P_surch_heel = M_surch_heel = 0.0
            if with_surch_on_heel:
                P_surch_heel = GAMMA_Q_SURCH_MOMENT * P_k_surch_heel
                M_surch_heel = -GAMMA_Q_SURCH_MOMENT * M_k_surch_heel
                P_tot += P_surch_heel
                M_tot += M_surch_heel

            e = M_tot / P_tot
            no_tension = e <= B / 6
            if no_tension:
                sigma_max = (P_tot / B) * (1 + 6 * e / B)
            else:
                # effective-width formula when the resultant falls outside the middle third
                eff_width = 3 * (B / 2 - e)
                sigma_max = 2 * P_tot / eff_width if eff_width > 0 else float("inf")

            combos.append({
                "combination": name,
                "surcharge_extent": extent,
                "gamma_G_wall": gG_wall,
                "gamma_G_ground": gG_ground,
                "P_wall": P_wall,
                "P_foot": P_foot,
                "P_ground": P_ground,
                "P_tot": P_tot,
                "M_tot": M_tot,
                "eccentricity_e": e,
                "B_over_6": B / 6,
                "no_tension": no_tension,
                "sigma_max": sigma_max,
            })

    governing = max(combos, key=lambda c: c["sigma_max"])

    return WallResults(
        B=B, h_stem=h_stem, Ka=Ka,
        P_k_wall=P_k_wall, P_k_foot=P_k_foot, G_k_ground=G_k_ground,
        S_k_ground=S_k_ground, s_k_surch=s_k_surch,
        FS_slide=FS_slide, FS_overturn=FS_overturn,
        combos=combos, governing=governing,
    )


def print_report(inp: WallInputs, res: WallResults) -> None:
    print("=" * 72)
    print("RETAINING WALL — ULS VERIFICATION")
    print("=" * 72)
    print("\nInputs")
    print(f"  Soil unit weight        gamma   = {inp.gamma:.3f} kN/m3")
    print(f"  Friction angle          phi     = {inp.phi:.3f} deg")
    print(f"  Base friction factor    mu      = {inp.mu:.3f}")
    print(f"  Concrete unit weight    rho     = {inp.rho:.3f} kN/m3")
    print(f"  Stem thickness          t_w     = {inp.t_w:.3f} m")
    print(f"  Total wall height       h_w     = {inp.h_w:.3f} m")
    print(f"  Footing thickness       T_f     = {inp.T_f:.3f} m")
    print(f"  Heel length             b_f1    = {inp.b_f1:.3f} m")
    print(f"  Toe length              b_f2    = {inp.b_f2:.3f} m")
    print(f"  Surcharge               q_surch = {inp.q_surch:.3f} kN/m2")

    print("\nDerived geometry & earth pressure")
    print(f"  Footing width           B       = {res.B:.3f} m")
    print(f"  Stem height             h_stem  = {res.h_stem:.3f} m")
    print(f"  Active earth coeff.     Ka      = {res.Ka:.4f}")
    print(f"  Ground thrust (char.)   S_k     = {res.S_k_ground:.3f} kN/m")
    print(f"  Surcharge thrust (char.) s_k    = {res.s_k_surch:.3f} kN/m")

    print("\n1) Sliding check")
    print(f"  Factor of safety FS = {res.FS_slide:.3f}  ->  {'OK' if res.FS_slide >= 1.0 else 'NOT OK'}")

    print("\n2) Overturning check")
    print(f"  Factor of safety FS = {res.FS_overturn:.3f}  ->  {'OK' if res.FS_overturn >= 1.0 else 'NOT OK'}")

    print("\n3) Ground contact pressure (all combinations)")
    header = f"  {'combo':<5} {'surcharge extent':<20} {'P_tot [kN/m]':>13} {'e [m]':>8} {'e<=B/6':>7} {'sigma_max [kPa]':>16}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for c in res.combos:
        flag = "yes" if c["no_tension"] else "NO"
        print(f"  {c['combination']:<5} {c['surcharge_extent']:<20} {c['P_tot']:>13.2f} "
              f"{c['eccentricity_e']:>8.3f} {flag:>7} {c['sigma_max']:>16.2f}")

    g = res.governing
    print("\n  Governing case:")
    print(f"    {g['combination']} combination, surcharge {g['surcharge_extent']}")
    print(f"    Max ground pressure sigma_max = {g['sigma_max']:.2f} kPa")
    print(f"    (eccentricity e = {g['eccentricity_e']:.3f} m, B/6 = {g['B_over_6']:.3f} m, "
          f"{'no tension' if g['no_tension'] else 'TENSION -- middle-third rule violated'})")
    print("=" * 72)


def _prompt_float(label: str, default: float) -> float:
    raw = input(f"{label} [{default}]: ").strip()
    return float(raw) if raw else default


def _choose_soil_preset() -> dict:
    """Let the user pick a named soil-type preset (or none) for
    gamma/phi/mu. Returns a dict with those three keys, used only as
    *defaults* -- each value can still be overridden individually right
    after, on the gamma/phi/mu prompts."""
    names = list(SOIL_PRESETS.keys())
    print("Soil type presets (typical values -- see the caveat about clay near the")
    print("top of this file; override any individual value on the next prompts):\n")
    for i, name in enumerate(names, 1):
        v = SOIL_PRESETS[name]
        print(f"  {i}. {name:<38} gamma={v['gamma']:.1f}  phi={v['phi']:.1f}  mu={v['mu']:.2f}")
    print(f"  {len(names) + 1}. custom (type your own gamma/phi/mu)\n")

    raw = input(f"Choose a soil type [1-{len(names) + 1}], or Enter for custom: ").strip()
    if not raw:
        return {"gamma": 18.0, "phi": 30.0, "mu": 0.57}
    try:
        idx = int(raw)
    except ValueError:
        idx = len(names) + 1
    if 1 <= idx <= len(names):
        chosen = names[idx - 1]
        print(f"-> using '{chosen}' as the starting point (still editable below)\n")
        return SOIL_PRESETS[chosen]
    return {"gamma": 18.0, "phi": 30.0, "mu": 0.57}


def interactive_inputs() -> WallInputs:
    """Ask the user for each parameter, showing either the chosen soil
    preset or the worksheet's original example value as the default
    (press Enter to keep it, or type a new number to override it)."""
    print("Enter the retaining-wall parameters (press Enter to keep the default).\n")

    soil = _choose_soil_preset()

    gamma = _prompt_float("Soil unit weight gamma [kN/m3]", soil["gamma"])
    phi = _prompt_float("Friction angle phi [deg]", soil["phi"])
    mu = _prompt_float("Base friction factor mu [-]", soil["mu"])
    rho = _prompt_float("Concrete unit weight rho [kN/m3]", 25.0)
    t_w = _prompt_float("Stem thickness t_w [m]", 0.3)
    h_w = _prompt_float("Total wall height h_w [m]", 3.0)
    T_f = _prompt_float("Footing thickness T_f [m]", 0.5)
    b_f1 = _prompt_float("Heel length b_f1 [m]", 1.7)
    b_f2 = _prompt_float("Toe length b_f2 [m]", 0.5)
    q_surch = _prompt_float("Surcharge q_surch [kN/m2]", 10.0)

    return WallInputs(
        gamma=gamma, phi=phi, mu=mu, rho=rho,
        t_w=t_w, h_w=h_w, T_f=T_f, b_f1=b_f1, b_f2=b_f2,
        q_surch=q_surch,
    )


if __name__ == "__main__":
    inputs = interactive_inputs()
    try:
        results = analyze(inputs)
    except ValueError as exc:
        print(f"\nInput error: {exc}\nPlease re-run and check that value.")
    else:
        print()
        print_report(inputs, results)