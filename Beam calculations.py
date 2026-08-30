"""
EUROCODE 2 (EN 1992-1-1) SIMPLY-SUPPORTED RC BEAM DESIGN — INTERACTIVE, TEXT ONLY
====================================================================================
Asks for span, section size, concrete class and loading, then designs
flexural steel, shear links, checks deflection and anchorage, and prints
a clear final summary of the dimensions and reinforcement to use.

No external libraries required — only the Python standard library.

Run with:  python "ec2_beam_design_textonly.py"
Press Enter on any prompt to accept the default shown in [brackets].
"""

import math

# ==========================================================
# CONCRETE CLASS TABLE (EN 1992-1-1 Table 3.1)
# class name -> (f_ck [MPa], f_ctm [MPa])
# ==========================================================
CONCRETE_CLASSES = {
    "C12/15": (12.0, 1.6),
    "C16/20": (16.0, 1.9),
    "C20/25": (20.0, 2.2),
    "C25/30": (25.0, 2.6),
    "C28/35": (28.0, 2.8),
    "C30/37": (30.0, 2.9),
    "C32/40": (32.0, 3.0),
    "C35/45": (35.0, 3.2),
    "C40/50": (40.0, 3.5),
    "C45/55": (45.0, 3.8),
    "C50/60": (50.0, 4.1),
}

BAR_SIZES_MM = [8, 10, 12, 16, 20, 25, 32]
SPACING_ROUND_MM = 25.0
MIN_PRACTICAL_SPACING_MM = 75.0


def ask_float(prompt, default):
    raw = input(f"{prompt} [{default}]: ").strip()
    if raw == "":
        return float(default)
    try:
        return float(raw)
    except ValueError:
        print(f"  -> Could not read that as a number, using default {default}.")
        return float(default)


def ask_int(prompt, default):
    raw = input(f"{prompt} [{default}]: ").strip()
    if raw == "":
        return int(default)
    try:
        return int(raw)
    except ValueError:
        print(f"  -> Could not read that as a whole number, using default {default}.")
        return int(default)


def ask_concrete_class(default="C30/37"):
    print("\nAvailable concrete classes (EN 1992-1-1 Table 3.1):")
    names = list(CONCRETE_CLASSES.keys())
    for i, name in enumerate(names, start=1):
        fck, fctm = CONCRETE_CLASSES[name]
        print(f"  {i:2d}) {name:8s}  (f_ck={fck:.0f} MPa, f_ctm={fctm:.1f} MPa)")
    raw = input(f"Choose a number or type the class name [{default}]: ").strip()
    if raw == "":
        return default
    if raw in CONCRETE_CLASSES:
        return raw
    try:
        idx = int(raw)
        if 1 <= idx <= len(names):
            return names[idx - 1]
    except ValueError:
        pass
    print(f"  -> Not recognised, using default {default}.")
    return default


def round_down_to_step(value, step, minimum):
    stepped = math.floor(value / step) * step
    return max(stepped, minimum)


def deflection_limit_span_to_depth(K, f_ck, rho, rho_0, rho_prime):
    """EN 1992-1-1 Cl. 7.4.2, Expressions 7.16a / 7.16b, correct branch selection."""
    if rho <= rho_0:
        ratio = rho_0 / rho
        L_d = K * (11.0 + 1.5 * math.sqrt(f_ck) * ratio
                    + 3.2 * math.sqrt(f_ck) * (ratio - 1.0) ** 1.5)
        branch = "7.16a (rho <= rho_0)"
    else:
        denom = max(rho - rho_prime, 1e-6)
        L_d = K * (11.0 + 1.5 * math.sqrt(f_ck) * rho_0 / denom
                    + (1.0 / 12.0) * math.sqrt(f_ck) * math.sqrt(max(rho_prime / rho_0, 0.0)))
        branch = "7.16b (rho > rho_0)"
    return L_d, branch


def main():
    print("=" * 70)
    print(" EUROCODE 2 (EN 1992-1-1) — INTERACTIVE RC BEAM DESIGN")
    print(" Simply supported beam, uniformly distributed load")
    print("=" * 70)

    print("\n--- Geometry ---")
    L = ask_float("Effective span L (m)", 6.0)
    b = ask_float("Beam width b (mm)", 250.0)
    h = ask_float("Beam depth h (mm)", 450.0)
    c_nom = ask_float("Nominal cover c_nom (mm)", 35.0)

    print("\n--- Materials ---")
    concrete_class = ask_concrete_class("C30/37")
    f_ck, f_ctm = CONCRETE_CLASSES[concrete_class]
    f_yk = ask_float("Steel characteristic yield strength f_yk (MPa)", 500.0)

    print("\n--- Loading (characteristic, unfactored) ---")
    g_k_sdl = ask_float("Superimposed dead load g_k (kN/m, excludes self-weight)", 12.0)
    q_k = ask_float("Variable (live) load q_k (kN/m)", 10.0)

    print("\n--- Reinforcement choices ---")
    print(f"Common bar sizes (mm): {BAR_SIZES_MM}")
    dia_bar = ask_float("Tension (bottom) bar diameter (mm)", 20.0)
    dia_top = ask_float("Compression / top (hanger) bar diameter (mm)", 12.0)
    n_top = ask_int("Number of top bars", 2)
    dia_link = ask_float("Link (stirrup) diameter (mm)", 8.0)
    n_legs = ask_int("Number of link legs", 2)

    # ------------------------------------------------------
    gamma_c = 1.5
    gamma_s = 1.15
    alpha_cc = 1.0

    f_cd = (alpha_cc * f_ck) / gamma_c
    f_yd = f_yk / gamma_s

    # Self-weight as a distributed load: width(m) x depth(m) x unit weight(kN/m3) = kN/m
    # (unit weight of reinforced concrete taken as 25 kN/m3)
    g_k_sw = (b / 1000.0) * (h / 1000.0) * 25.0          # kN/m, used in the design equations
    W_sw_total = g_k_sw * L                               # kN, total self-weight force over the span
    g_k = g_k_sw + g_k_sdl

    q_Ed = 1.35 * g_k + 1.50 * q_k
    M_Ed = (q_Ed * (L ** 2)) / 8.0
    V_Ed = (q_Ed * L) / 2.0

    # ------------------------------------------------------
    # FLEXURAL DESIGN
    # ------------------------------------------------------
    d = h - c_nom - dia_link - (dia_bar / 2.0)

    mu = (M_Ed * 1e6) / (b * (d ** 2) * f_cd)
    mu_lim = 0.296

    doubly_reinforced_needed = mu > mu_lim
    mu_calc = mu_lim if doubly_reinforced_needed else mu

    z = (d / 2.0) * (1.0 + math.sqrt(1.0 - 2.0 * mu_calc))
    z = min(z, 0.95 * d)
    x = (d - z) / 0.4

    A_s_req = (M_Ed * 1e6) / (f_yd * z)
    A_s_min = max(0.26 * (f_ctm / f_yk) * b * d, 0.0013 * b * d)
    A_s_max = 0.04 * b * h
    A_s_needed = max(A_s_req, A_s_min)

    A_bar = math.pi * (dia_bar ** 2) / 4.0
    n_bars = max(2, math.ceil(A_s_needed / A_bar))
    A_s_prov = n_bars * A_bar
    steel_ok = A_s_prov <= A_s_max

    clear_gap_req = max(dia_bar, 20.0)
    width_avail = b - 2.0 * (c_nom + dia_link)
    width_needed = n_bars * dia_bar + (n_bars - 1) * clear_gap_req
    bars_fit_single_layer = width_needed <= width_avail

    A_top = n_top * (math.pi * (dia_top ** 2) / 4.0)

    # ------------------------------------------------------
    # SHEAR DESIGN
    # ------------------------------------------------------
    cot_theta = 2.5
    tan_theta = 1.0 / cot_theta
    nu_1 = 0.6 * (1.0 - f_ck / 250.0)

    V_Rd_max = (1.0 * b * z * nu_1 * f_cd) / (cot_theta + tan_theta) * 1e-3
    shear_crushing_ok = V_Ed <= V_Rd_max

    A_sw = n_legs * (math.pi * (dia_link ** 2) / 4.0)
    rho_w_min = 0.08 * math.sqrt(f_ck) / f_yk
    s_max_from_rho_min = A_sw / (rho_w_min * b)
    s_max_geom = 0.75 * d

    def required_spacing(V_zone_kN):
        Asw_s_req = (V_zone_kN * 1e3) / (z * f_yd * cot_theta)
        s_strength = s_max_geom if Asw_s_req <= 0 else A_sw / Asw_s_req
        s_allow = min(s_strength, s_max_from_rho_min, s_max_geom)
        return round_down_to_step(s_allow, SPACING_ROUND_MM, MIN_PRACTICAL_SPACING_MM)

    s_support = required_spacing(V_Ed)
    V_quarter = q_Ed * (L / 4.0)
    s_midspan = required_spacing(V_quarter)

    # ------------------------------------------------------
    # DEFLECTION
    # ------------------------------------------------------
    rho = A_s_prov / (b * d)
    rho_prime = A_top / (b * d)
    rho_0 = 1e-3 * math.sqrt(f_ck)
    K = 1.0

    L_d_basic, branch_used = deflection_limit_span_to_depth(K, f_ck, rho, rho_0, rho_prime)
    F_s = min(A_s_prov / A_s_req, 1.5)
    L_d_limit = L_d_basic * F_s
    L_d_actual = (L * 1000.0) / d
    deflection_ok = L_d_actual <= L_d_limit

    # ------------------------------------------------------
    # ANCHORAGE
    # ------------------------------------------------------
    f_ctd = (0.7 * f_ctm) / gamma_c
    f_bd = 2.25 * 1.0 * 1.0 * f_ctd
    l_bd = (dia_bar / 4.0) * (f_yd / f_bd)
    a_1 = 0.5 * z * cot_theta
    curtailment_dist = max(800.0, a_1 + l_bd / 2.0)

    overall_ok = (not doubly_reinforced_needed) and steel_ok and bars_fit_single_layer \
        and shear_crushing_ok and deflection_ok

    # ==========================================================
    # FINAL SUMMARY — the part you actually build from
    # ==========================================================
    print("\n" + "=" * 70)
    print("FINAL DESIGN — USE THESE DIMENSIONS AND REINFORCEMENT")
    print("=" * 70)
    print(f"Inputs: span = {L:.2f} m | concrete = {concrete_class} | "
          f"g_k = {g_k_sdl:.1f} kN/m (SDL) | q_k = {q_k:.1f} kN/m (live)")
    print(f"Self-weight              : {g_k_sw:.2f} kN/m ({b:.0f}mm x {h:.0f}mm x 25 kN/m3), "
          f"= {W_sw_total:.2f} kN total over the {L:.2f} m span")
    print("-" * 70)
    print(f"Section size            : {b:.0f} mm wide x {h:.0f} mm deep")
    print(f"Nominal cover           : {c_nom:.0f} mm")
    print(f"Bottom (tension) steel  : {n_bars} x Ø{dia_bar:.0f} mm bars "
          f"(A_s,prov = {A_s_prov:.0f} mm^2, need >= {A_s_needed:.0f} mm^2)")
    print(f"Top (hanger) steel      : {n_top} x Ø{dia_top:.0f} mm bars")
    print(f"Shear links             : {n_legs}-leg Ø{dia_link:.0f} mm")
    print(f"  - near supports       : @ {s_support:.0f} mm centres (for ~1.5 m from each end, or to {curtailment_dist/1000:.2f} m)")
    print(f"  - mid-span region     : @ {s_midspan:.0f} mm centres")
    print(f"Bottom bar curtailment  : 2 bars continuous full length, "
          f"2 bars may be curtailed at {curtailment_dist/1000:.2f} m from each support")
    print(f"Anchorage length (l_bd) : {l_bd:.0f} mm past the point where bars are no longer needed")
    print("-" * 70)
    print(f"Overall status: {'ALL CHECKS PASS - this design is adequate' if overall_ok else 'ONE OR MORE CHECKS FAILED - see warnings below'}")
    print("=" * 70)

    if not overall_ok:
        print("\nWarnings / things to fix:")
        if doubly_reinforced_needed:
            print(f" - mu = {mu:.4f} exceeds the singly-reinforced limit (0.296). "
                   f"Increase the section depth, use a higher concrete class, or add compression steel.")
        if not steel_ok:
            print(f" - Provided tension steel ({A_s_prov:.0f} mm^2) exceeds A_s,max ({A_s_max:.0f} mm^2). "
                   f"Use a bigger section.")
        if not bars_fit_single_layer:
            print(f" - {n_bars} bars of Ø{dia_bar:.0f} mm do not fit in one layer within the width "
                   f"(need ~{width_needed:.0f} mm, have {width_avail:.0f} mm). Use a wider beam, "
                   f"a smaller/fewer bar diameter, or a second layer.")
        if not shear_crushing_ok:
            print(f" - V_Ed ({V_Ed:.1f} kN) exceeds the strut crushing capacity V_Rd,max ({V_Rd_max:.1f} kN). "
                   f"Increase the section size or concrete class.")
        if not deflection_ok:
            print(f" - Span/depth ratio ({L_d_actual:.2f}) exceeds the allowable limit ({L_d_limit:.2f}). "
                   f"Increase the beam depth or the tension steel area.")

    # ==========================================================
    # FULL CALCULATION DETAIL (for your records / checking)
    # ==========================================================
    print("\n" + "=" * 70)
    print("FULL CALCULATION DETAIL")
    print("=" * 70)
    print(f"Concrete {concrete_class}: f_ck={f_ck:.0f} MPa, f_cd={f_cd:.2f} MPa, f_ctm={f_ctm:.2f} MPa")
    print(f"Steel: f_yk={f_yk:.0f} MPa, f_yd={f_yd:.1f} MPa")
    print(f"Self-weight (UDL)             : {b:.0f}mm x {h:.0f}mm x 25 kN/m3 = {g_k_sw:.2f} kN/m")
    print(f"Self-weight (total over span) : {g_k_sw:.2f} kN/m x {L:.2f} m = {W_sw_total:.2f} kN")
    print(f"g_k(total, self-weight+SDL)   : {g_k:.2f} kN/m | q_k = {q_k:.2f} kN/m")
    print(f"Factored design load q_Ed     : {q_Ed:.2f} kN/m")
    print(f"Design moment M_Ed            : {M_Ed:.2f} kNm")
    print(f"Design shear V_Ed             : {V_Ed:.2f} kN")
    print(f"Effective depth d             : {d:.1f} mm")
    print(f"Moment factor mu (limit 0.296): {mu:.4f}")
    print(f"Lever arm z / N.A. depth x    : {z:.1f} mm / {x:.1f} mm")
    print(f"A_s required / min / max      : {A_s_req:.1f} / {A_s_min:.1f} / {A_s_max:.1f} mm^2")
    print(f"Strut capacity V_Rd,max       : {V_Rd_max:.1f} kN")
    print(f"Min shear-reo max spacing     : {s_max_from_rho_min:.0f} mm | Geometric max (0.75d): {s_max_geom:.0f} mm")
    print(f"Deflection formula used       : Expression {branch_used}")
    print(f"rho / rho_0 / rho'            : {rho:.5f} / {rho_0:.5f} / {rho_prime:.5f}")
    print(f"L/d actual vs limit           : {L_d_actual:.2f} <= {L_d_limit:.2f} (F_s={F_s:.3f})")
    print("=" * 70)


if __name__ == "__main__":
    main()