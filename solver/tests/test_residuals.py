import math

from windtunnel.residuals import (
    History,
    extract_final_cd,
    has_converged,
    is_diverged,
    parse_log,
)

SAMPLE_LOG = """
Time = 1
smoothSolver:  Solving for Ux, Initial residual = 0.5, final residual = 0.04, No Iterations 3
smoothSolver:  Solving for Uy, Initial residual = 0.4, final residual = 0.03, No Iterations 3
smoothSolver:  Solving for Uz, Initial residual = 0.3, final residual = 0.02, No Iterations 3
GAMG:  Solving for p, Initial residual = 0.2, final residual = 0.01, No Iterations 10
Time = 2
smoothSolver:  Solving for Ux, Initial residual = 0.1, final residual = 0.01, No Iterations 3
GAMG:  Solving for p, Initial residual = 0.05, final residual = 0.005, No Iterations 10
Time = 3
smoothSolver:  Solving for Ux, Initial residual = 0.05, final residual = 0.005, No Iterations 3
GAMG:  Solving for p, Initial residual = 0.02, final residual = 0.002, No Iterations 10
 forces forceCoeffs write:
    Cm    : 0.012
    Cd    : 0.312
    Cl    : 0.045
    Cd(f) : 0.15
    Cd(r) : 0.162
Time = 4
smoothSolver:  Solving for Ux, Initial residual = 0.02, final residual = 0.002, No Iterations 3
GAMG:  Solving for p, Initial residual = 0.01, final residual = 0.001, No Iterations 10
 forces forceCoeffs write:
    Cm    : 0.011
    Cd    : 0.301
    Cl    : 0.044
    Cd(f) : 0.145
    Cd(r) : 0.156
"""

NAN_LOG = """
Time = 5
GAMG:  Solving for p, Initial residual = nan, final residual = nan, No Iterations 10
"""


def test_parse_log_history():
    h = parse_log(SAMPLE_LOG)
    # Time=1..4 共 4 个时间步有 Ux/p
    assert len(h.iters) == 4
    assert h.iters == [1, 2, 3, 4]
    # U 取三方向最大值
    assert h.u[0] == 0.5
    assert h.p[0] == 0.2
    assert len(h.cd) == 2 and h.cd == [0.312, 0.301]
    assert h.cl == [0.045, 0.044]


def test_extract_final_cd():
    assert extract_final_cd(SAMPLE_LOG) == (0.301, 0.145, 0.156)
    assert extract_final_cd("nothing here") is None


def test_divergence_nan():
    assert is_diverged(parse_log(NAN_LOG))
    assert not is_diverged(parse_log(SAMPLE_LOG))


def test_divergence_explosion():
    h = History()
    h.u = [1e6]
    h.p = [0.1]
    assert is_diverged(h)


def test_convergence():
    h = History()
    h.cd = [0.3] * 500
    assert has_converged(h)
    h2 = History()
    h2.cd = [0.3 + 0.1 * (i % 2) for i in range(500)]  # 大幅振荡
    assert not has_converged(h2)
    h3 = History()
    h3.cd = [0.3] * 299
    assert not has_converged(h3)  # 样本不足


def test_convergence_near_zero_cd():
    h = History()
    h.cd = [1e-9 + 1e-9 * (i % 2) for i in range(400)]
    # 均值接近 0 时退化为绝对极差：1e-9 < tol，判收敛
    assert has_converged(h)
