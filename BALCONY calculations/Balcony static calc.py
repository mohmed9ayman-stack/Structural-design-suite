"""
=======================================================================================
 CANTILEVERED BALCONY SLAB - THERMAL BREAK CONNECTOR STRUCTURAL VERIFICATION
=======================================================================================

Purpose
-------
Automates the Eurocode (EN 1990 / EN 1992-1-1) structural verification of
cantilevered balcony slabs supported on discrete thermal-break connector
modules (e.g. Peikko EBEA / Schock Isokorb-type units).

The program is fully parametric: every project-specific value is supplied
through the ProjectInput dataclasses below, so re-using it for a new balcony
only requires changing the input data - no code changes needed.

Author: Structural automation script (Python / OOP)
=======================================================================================
"""

import sys
from dataclasses import dataclass

# ---------------------------------------------------------------------------------------
# Windows console safety net.
# Some Windows terminals (PowerShell / cmd.exe) default to a legacy codepage (cp1252)
# that cannot encode certain characters. Forcing UTF-8 here prevents the script from
# crashing silently with no visible output. This report only uses plain ASCII anyway,
# but this guard is kept as cheap insurance for any future edits.
# ---------------------------------------------------------------------------------------
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass


# =======================================================================================
# I. INPUT DATA MODEL
# =======================================================================================
# Grouping the raw input variables into small, well-named dataclasses keeps the
# calculator class decoupled from "where the numbers came from" and makes the
# script trivial to reuse: just build new dataclass instances for the next project.


@dataclass
class Geometry:
    """Geometric parameters of the balcony slab."""
    l_k: float   # Cantilever projection length, wall line -> outer edge [m]
    L: float     # Total width/length of balcony slab along facade [m]
    t: float     # Concrete slab thickness [mm]
    n: int       # Number of main load-bearing thermal-break modules on this slab [pcs]

    @property
    def t_m(self) -> float:
        """Slab thickness converted to metres, for deflection (I) calculations."""
        return self.t / 1000.0


@dataclass
class Loads:
    """Characteristic (unfactored) Eurocode design loads."""
    g_self: float       # Self-weight of structural concrete slab [kN/m^2]
    g_finishes: float   # Dead load of finishes (waterproofing, screed, tiles) [kN/m^2]
    F_railing: float    # Linear edge load from handrail/balustrade [kN/m]
    q_live: float        # Imposed live load [kN/m^2]
    q_snow: float        # Characteristic snow load [kN/m^2]

    # Combination factors (EN 1990, Table A1.1 - National Annex may vary)
    psi_0_snow: float = 0.50   # Combination factor for snow, ULS
    psi_2_live: float = 0.30   # Quasi-permanent factor for live load, SLS


@dataclass
class ConnectorProperties:
    """Design resistance / stiffness of a single thermal-break element."""
    M_Rd: float    # Ultimate design bending moment resistance per element [kNm/pcs]
    V_Rd: float    # Ultimate design shear resistance per element [kN/pcs]
    k_rot: float   # Rotational spring stiffness of joint [kNm/rad per metre strip]


@dataclass
class MaterialProperties:
    """Concrete material properties."""
    E_concrete: float  # Elastic modulus [kPa == kN/m^2] (e.g. 31,000,000 kPa = 31 GPa)


@dataclass
class ProjectInput:
    """Full parametric input package for one balcony verification run."""
    label: str
    geometry: Geometry
    loads: Loads
    connector: ConnectorProperties
    material: MaterialProperties


# =======================================================================================
# II. RESULTS CONTAINER
# =======================================================================================


@dataclass
class CalculationResults:
    """Holds every intermediate and final result produced by the calculator."""
    p_ULS: float = 0.0
    F_ULS: float = 0.0

    b_trib: float = 0.0

    V_Ed_strip: float = 0.0
    M_Ed_strip: float = 0.0

    V_Ed_pcs: float = 0.0
    M_Ed_pcs: float = 0.0

    moment_utilization_pct: float = 0.0
    shear_utilization_pct: float = 0.0

    p_SLS: float = 0.0
    M_SLS_strip: float = 0.0
    M_SLS_pcs: float = 0.0
    I_section: float = 0.0
    w_ed1: float = 0.0
    w_ed2: float = 0.0
    W_Ed_total: float = 0.0


# =======================================================================================
# III. STRUCTURAL CALCULATOR
# =======================================================================================


class BalconyStructuralCalculator:
    """
    Performs the full ULS + SLS verification chain for a cantilevered balcony
    slab connected to the structure via discrete thermal-break elements.

    Usage:
        calc = BalconyStructuralCalculator(project_input)
        results = calc.run()
    """

    def __init__(self, project: ProjectInput):
        self.project = project
        self.results = CalculationResults()

    # -----------------------------------------------------------------------------
    # ULS - Load combinations
    # -----------------------------------------------------------------------------
    def _calc_uls_area_load(self) -> float:
        """p_ULS = 1.35*(g_self+g_finishes) + 1.50*q_live + 1.50*psi_0_snow*q_snow"""
        loads = self.project.loads
        p_uls = (
            1.35 * (loads.g_self + loads.g_finishes)
            + 1.50 * loads.q_live
            + 1.50 * loads.psi_0_snow * loads.q_snow
        )
        self.results.p_ULS = p_uls
        return p_uls

    def _calc_uls_edge_load(self) -> float:
        """F_ULS = 1.35 * F_railing"""
        f_uls = 1.35 * self.project.loads.F_railing
        self.results.F_ULS = f_uls
        return f_uls

    # -----------------------------------------------------------------------------
    # Tributary width
    # -----------------------------------------------------------------------------
    def _calc_tributary_width(self) -> float:
        """b_trib = L / n"""
        geo = self.project.geometry
        b_trib = geo.L / geo.n
        self.results.b_trib = b_trib
        return b_trib

    # -----------------------------------------------------------------------------
    # ULS - Forces per metre strip (1 m wide cantilever strip)
    # -----------------------------------------------------------------------------
    def _calc_forces_per_strip(self) -> None:
        geo = self.project.geometry
        r = self.results
        r.V_Ed_strip = (r.p_ULS * geo.l_k) + r.F_ULS
        r.M_Ed_strip = (r.p_ULS * geo.l_k ** 2 / 2.0) + (r.F_ULS * geo.l_k)

    # -----------------------------------------------------------------------------
    # ULS - Forces distributed onto a single element (db)
    # -----------------------------------------------------------------------------
    def _calc_forces_per_element(self) -> None:
        r = self.results
        r.V_Ed_pcs = r.V_Ed_strip * r.b_trib
        r.M_Ed_pcs = r.M_Ed_strip * r.b_trib

    # -----------------------------------------------------------------------------
    # ULS - Utilization ratios against connector resistance
    # -----------------------------------------------------------------------------
    def _calc_utilization(self) -> None:
        conn = self.project.connector
        r = self.results
        r.moment_utilization_pct = (r.M_Ed_pcs / conn.M_Rd) * 100.0
        r.shear_utilization_pct = (r.V_Ed_pcs / conn.V_Rd) * 100.0

    # -----------------------------------------------------------------------------
    # SLS - Quasi-permanent combination & tip deflection
    # -----------------------------------------------------------------------------
    def _calc_sls_deflection(self) -> None:
        geo = self.project.geometry
        loads = self.project.loads
        conn = self.project.connector
        mat = self.project.material
        r = self.results

        r.p_SLS = loads.g_self + loads.g_finishes + (loads.psi_2_live * loads.q_live)

        r.M_SLS_strip = (r.p_SLS * geo.l_k ** 2 / 2.0) + (loads.F_railing * geo.l_k)
        r.M_SLS_pcs = r.M_SLS_strip * r.b_trib

        # Component 1: deflection due to rotation of the thermal-break joint
        r.w_ed1 = (r.M_SLS_pcs * geo.l_k) / (conn.k_rot * r.b_trib) * 1000.0

        # Component 2: deflection due to bending of the concrete slab itself
        r.I_section = (r.b_trib * geo.t_m ** 3) / 12.0
        r.w_ed2 = (
            (r.p_SLS * r.b_trib * geo.l_k ** 4)
            / (8.0 * mat.E_concrete * r.I_section)
        ) * 1000.0

        r.W_Ed_total = r.w_ed1 + r.w_ed2

    # -----------------------------------------------------------------------------
    # Orchestration
    # -----------------------------------------------------------------------------
    def run(self) -> CalculationResults:
        """Executes the full calculation chain in the correct dependency order."""
        self._calc_uls_area_load()
        self._calc_uls_edge_load()
        self._calc_tributary_width()
        self._calc_forces_per_strip()
        self._calc_forces_per_element()
        self._calc_utilization()
        self._calc_sls_deflection()
        return self.results


# =======================================================================================
# IV. VERIFICATION / PASS-FAIL EVALUATION
# =======================================================================================


class VerificationEvaluator:
    """Applies pass/fail engineering judgement to the raw calculation results."""

    UTILIZATION_LIMIT_PCT = 100.0
    DEFLECTION_LIMIT_MODE = "l_k/250"  # common serviceability limit for cantilevers

    def __init__(self, project: ProjectInput, results: CalculationResults):
        self.project = project
        self.results = results

    def deflection_limit_mm(self) -> float:
        """Standard cantilever serviceability limit: l_k / 250, converted to mm."""
        return (self.project.geometry.l_k / 250.0) * 1000.0

    def moment_ok(self) -> bool:
        return self.results.moment_utilization_pct <= self.UTILIZATION_LIMIT_PCT

    def shear_ok(self) -> bool:
        return self.results.shear_utilization_pct <= self.UTILIZATION_LIMIT_PCT

    def deflection_ok(self) -> bool:
        return self.results.W_Ed_total <= self.deflection_limit_mm()

    def overall_pass(self) -> bool:
        return self.moment_ok() and self.shear_ok() and self.deflection_ok()


# =======================================================================================
# V. DIAGNOSTIC REPORT PRINTER
# =======================================================================================


class ReportPrinter:
    """Formats and prints a polished command-line diagnostic report (ASCII-only,
    safe for any Windows terminal / codepage)."""

    WIDTH = 88

    def __init__(self, project: ProjectInput, results: CalculationResults,
                 evaluator: VerificationEvaluator):
        self.project = project
        self.results = results
        self.evaluator = evaluator

    def _rule(self, char: str = "=") -> str:
        return char * self.WIDTH

    def _status(self, ok: bool) -> str:
        return "PASS" if ok else "FAIL"

    def print_report(self) -> None:
        p = self.project
        r = self.results
        geo, loads, conn, mat = p.geometry, p.loads, p.connector, p.material
        ev = self.evaluator

        print(self._rule())
        print(" STRUCTURAL VERIFICATION REPORT - CANTILEVER BALCONY / THERMAL BREAK CONNECTORS")
        print(self._rule())
        print(f" Project / Element : {p.label}")
        print(self._rule("-"))

        print(" 1. INPUT - GEOMETRY")
        print(f"    Cantilever length          l_k = {geo.l_k:>8.3f} m")
        print(f"    Slab width along facade    L   = {geo.L:>8.3f} m")
        print(f"    Slab thickness              t   = {geo.t:>8.1f} mm")
        print(f"    Number of connector modules n   = {geo.n:>8d} pcs")

        print("\n 2. INPUT - CHARACTERISTIC LOADS")
        print(f"    Self-weight                 g_self     = {loads.g_self:>8.3f} kN/m^2")
        print(f"    Finishes                    g_finishes = {loads.g_finishes:>8.3f} kN/m^2")
        print(f"    Railing edge load           F_railing  = {loads.F_railing:>8.3f} kN/m")
        print(f"    Live load                   q_live     = {loads.q_live:>8.3f} kN/m^2")
        print(f"    Snow load                   q_snow     = {loads.q_snow:>8.3f} kN/m^2")

        print("\n 3. INPUT - CONNECTOR & MATERIAL PROPERTIES")
        print(f"    Moment resistance / pcs      M_Rd   = {conn.M_Rd:>10.3f} kNm/pcs")
        print(f"    Shear resistance / pcs       V_Rd   = {conn.V_Rd:>10.3f} kN/pcs")
        print(f"    Rotational stiffness         k_rot  = {conn.k_rot:>10.1f} kNm/rad/m")
        print(f"    Concrete elastic modulus     E      = {mat.E_concrete:>10,.0f} kPa "
              f"({mat.E_concrete/1e6:.1f} GPa)")

        print(self._rule("-"))
        print(" 4. ULS LOAD COMBINATION")
        print(f"    Design area load             p_ULS = {r.p_ULS:>8.3f} kN/m^2")
        print(f"    Design edge (railing) load   F_ULS = {r.F_ULS:>8.3f} kN/m")
        print(f"    Tributary width per module   b_trib= {r.b_trib:>8.3f} m")

        print("\n 5. DESIGN FORCES - PER METRE STRIP")
        print(f"    Shear                V_Ed,strip = {r.V_Ed_strip:>8.3f} kN/m")
        print(f"    Moment                M_Ed,strip = {r.M_Ed_strip:>8.3f} kNm/m")

        print("\n 6. DESIGN FORCES - PER SINGLE CONNECTOR ELEMENT")
        print(f"    Shear                 V_Ed,pcs = {r.V_Ed_pcs:>8.3f} kN")
        print(f"    Moment                M_Ed,pcs = {r.M_Ed_pcs:>8.3f} kNm")

        print(self._rule("-"))
        print(" 7. ULTIMATE LIMIT STATE - UTILIZATION CHECK")
        print(f"    Moment:  M_Ed,pcs / M_Rd = {r.M_Ed_pcs:.3f} / {conn.M_Rd:.3f} "
              f"= {r.moment_utilization_pct:6.1f} %   [{self._status(ev.moment_ok())}]")
        print(f"    Shear :  V_Ed,pcs / V_Rd = {r.V_Ed_pcs:.3f} / {conn.V_Rd:.3f} "
              f"= {r.shear_utilization_pct:6.1f} %   [{self._status(ev.shear_ok())}]")

        print(self._rule("-"))
        print(" 8. SERVICEABILITY LIMIT STATE - TIP DEFLECTION (quasi-permanent)")
        print(f"    Quasi-permanent area load    p_SLS      = {r.p_SLS:>8.3f} kN/m^2")
        print(f"    Quasi-permanent moment/strip M_SLS,strip= {r.M_SLS_strip:>8.3f} kNm/m")
        print(f"    Quasi-permanent moment/pcs   M_SLS,pcs  = {r.M_SLS_pcs:>8.3f} kNm")
        print(f"    Section inertia (per strip)  I          = {r.I_section:>10.3e} m^4")
        print(f"    Deflection - joint rotation  w_ed1      = {r.w_ed1:>8.3f} mm")
        print(f"    Deflection - slab bending    w_ed2      = {r.w_ed2:>8.3f} mm")
        print("    ------------------------------------------------------------")
        print(f"    TOTAL TIP DEFLECTION         W_Ed       = {r.W_Ed_total:>8.3f} mm")
        limit = ev.deflection_limit_mm()
        print(f"    Serviceability limit (l_k/250)          = {limit:>8.3f} mm   "
              f"[{self._status(ev.deflection_ok())}]")

        print(self._rule("="))
        overall = "OVERALL DESIGN: PASS" if ev.overall_pass() else "OVERALL DESIGN: FAIL - REVISE"
        print(f" {overall}")
        print(self._rule("="))


# =======================================================================================
# VI. DEFAULT VALIDATION CASE (Balcony B1 Baseline)
# =======================================================================================
# Kept as a factory function so it can be reused both as a "load defaults" shortcut
# in interactive mode, and as a quick regression check if you ever refactor the maths.

def build_default_b1_project() -> ProjectInput:
    """Verified baseline project used to sanity-check the calculation engine."""
    return ProjectInput(
        label="Worker\'s Hostel Nyiregyhaza - Balcony B1",
        geometry=Geometry(l_k=1.05, L=4.5, t=150, n=3),
        loads=Loads(
            g_self=3.68,
            g_finishes=1.50,
            F_railing=1.50,
            q_live=3.00,
            q_snow=1.00,
        ),
        connector=ConnectorProperties(M_Rd=18.75, V_Rd=36.4, k_rot=2050),
        material=MaterialProperties(E_concrete=31_000_000),  # kPa == 31.0 GPa
    )


# =======================================================================================
# VII. INTERACTIVE CONSOLE INPUT COLLECTOR
# =======================================================================================


class InteractiveInputCollector:
    """
    Prompts the user in the terminal for every project input, with sensible
    defaults (from the B1 baseline) shown in brackets. Pressing ENTER on any
    prompt accepts the default shown - this lets a user quickly re-check a
    single changed dimension without retyping every value.

    Includes basic validation (numeric, positive, non-zero) so a bad entry
    re-prompts instead of crashing the whole program.
    """

    def __init__(self, defaults: ProjectInput):
        self.d = defaults

    # -----------------------------------------------------------------------------
    # Low level prompt helpers
    # -----------------------------------------------------------------------------
    @staticmethod
    def _prompt_value(prompt_text: str, default: float, min_value: float = None,
                       allow_zero: bool = False, cast=float):
        """Generic numeric prompt with default value, retry-on-bad-input."""
        while True:
            raw = input(f"    {prompt_text} [{default}]: ").strip()
            if raw == "":
                return default
            try:
                value = cast(raw)
            except ValueError:
                print("      -> Please enter a valid number.")
                continue
            if not allow_zero and value == 0:
                print("      -> Value cannot be zero.")
                continue
            if min_value is not None and value < min_value:
                print(f"      -> Value must be >= {min_value}.")
                continue
            return value

    @staticmethod
    def _prompt_text(prompt_text: str, default: str) -> str:
        raw = input(f"    {prompt_text} [{default}]: ").strip()
        return raw if raw else default

    @staticmethod
    def _prompt_yes_no(prompt_text: str, default_yes: bool = True) -> bool:
        suffix = "[Y/n]" if default_yes else "[y/N]"
        raw = input(f"{prompt_text} {suffix}: ").strip().lower()
        if raw == "":
            return default_yes
        return raw in ("y", "yes")

    # -----------------------------------------------------------------------------
    # Section-by-section collection
    # -----------------------------------------------------------------------------
    def _collect_geometry(self) -> Geometry:
        print("\n -- GEOMETRIC PARAMETERS --")
        d = self.d.geometry
        l_k = self._prompt_value("Cantilever length l_k (m)", d.l_k, min_value=0.01)
        L = self._prompt_value("Balcony width along facade L (m)", d.L, min_value=0.01)
        t = self._prompt_value("Slab thickness t (mm)", d.t, min_value=1.0)
        n = int(self._prompt_value("Number of connector modules n (pcs)", d.n,
                                    min_value=1, cast=int))
        return Geometry(l_k=l_k, L=L, t=t, n=n)

    def _collect_loads(self) -> Loads:
        print("\n -- EUROCODE DESIGN LOADS --")
        d = self.d.loads
        g_self = self._prompt_value("Self-weight g_self (kN/m^2)", d.g_self,
                                     min_value=0.0, allow_zero=True)
        g_finishes = self._prompt_value("Finishes load g_finishes (kN/m^2)",
                                         d.g_finishes, min_value=0.0, allow_zero=True)
        F_railing = self._prompt_value("Railing edge load F_railing (kN/m)",
                                        d.F_railing, min_value=0.0, allow_zero=True)
        q_live = self._prompt_value("Live load q_live (kN/m^2)", d.q_live,
                                     min_value=0.0, allow_zero=True)
        q_snow = self._prompt_value("Snow load q_snow (kN/m^2)", d.q_snow,
                                     min_value=0.0, allow_zero=True)
        return Loads(g_self=g_self, g_finishes=g_finishes, F_railing=F_railing,
                      q_live=q_live, q_snow=q_snow)

    def _collect_connector(self) -> ConnectorProperties:
        print("\n -- CONNECTOR PROPERTIES (thermal break module) --")
        d = self.d.connector
        M_Rd = self._prompt_value("Moment resistance M_Rd (kNm/pcs)", d.M_Rd,
                                   min_value=0.01)
        V_Rd = self._prompt_value("Shear resistance V_Rd (kN/pcs)", d.V_Rd,
                                   min_value=0.01)
        k_rot = self._prompt_value("Rotational stiffness k_rot (kNm/rad/m)", d.k_rot,
                                    min_value=0.01)
        return ConnectorProperties(M_Rd=M_Rd, V_Rd=V_Rd, k_rot=k_rot)

    def _collect_material(self) -> MaterialProperties:
        print("\n -- MATERIAL PROPERTIES --")
        d = self.d.material
        e_gpa_default = d.E_concrete / 1e6
        e_gpa = self._prompt_value(
            "Concrete elastic modulus E (GPa, e.g. 31 for C25/30)", e_gpa_default,
            min_value=0.01)
        return MaterialProperties(E_concrete=e_gpa * 1e6)  # convert GPa -> kPa

    # -----------------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------------
    def collect(self) -> ProjectInput:
        print("=" * 88)
        print(" INTERACTIVE INPUT - press ENTER to accept the bracketed default value")
        print("=" * 88)
        label = self._prompt_text("Project / balcony label", self.d.label)
        geometry = self._collect_geometry()
        loads = self._collect_loads()
        connector = self._collect_connector()
        material = self._collect_material()
        return ProjectInput(label=label, geometry=geometry, loads=loads,
                             connector=connector, material=material)


# =======================================================================================
# VIII. MAIN PROGRAM LOOP
# =======================================================================================


def run_single_check(project: ProjectInput) -> bool:
    """Runs the calculation + evaluation + report for one project. Returns overall pass/fail."""
    calculator = BalconyStructuralCalculator(project)
    results = calculator.run()
    evaluator = VerificationEvaluator(project, results)
    ReportPrinter(project, results, evaluator).print_report()
    return evaluator.overall_pass()


def main() -> None:
    defaults = build_default_b1_project()

    print("=" * 88)
    print(" CANTILEVER BALCONY / THERMAL BREAK CONNECTOR - STATIC VERIFICATION TOOL")
    print("=" * 88)
    print(" This tool checks ULS moment/shear utilization of the thermal-break")
    print(" connectors and the SLS tip deflection of a cantilevered balcony slab.")

    while True:
        print("\nChoose an option:")
        print("  [1] Enter custom dimensions / loads for a new check")
        print("  [2] Run the verified default baseline case (Balcony B1)")
        print("  [3] Quit")
        choice = input("Your choice [1]: ").strip() or "1"

        if choice == "1":
            collector = InteractiveInputCollector(defaults)
            project = collector.collect()
            run_single_check(project)
        elif choice == "2":
            run_single_check(defaults)
        elif choice == "3":
            print("Goodbye.")
            break
        else:
            print("Invalid choice, please enter 1, 2, or 3.")
            continue

        again = InteractiveInputCollector._prompt_yes_no(
            "\nRun another check?", default_yes=True)
        if not again:
            print("Goodbye.")
            break


if __name__ == "__main__":
    main()