"""解析 simpleFoam / forceCoeffs 日志，判定收敛与发散。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# ESI v2312: "smoothSolver:  Solving for Ux, Initial residual = 0.012, final residual = ..., No Iterations 3"
_RES_RE = re.compile(r"Solving for (U[x-z]|p), Initial residual = ([\d.eE+-]+)")
# forceCoeffs 每次输出形如：
#   Cm    : 0.012
#   Cd    : 0.312
#   Cl    : 0.045
_CD_RE = re.compile(r"^\s*Cd\s*:\s*([\d.eE+-]+)", re.MULTILINE)
_CL_RE = re.compile(r"^\s*Cl\s*:\s*([\d.eE+-]+)", re.MULTILINE)
_CD_FR_RE = re.compile(r"Cd\(f\)\s*:\s*([\d.eE+-]+)")
_CD_RR_RE = re.compile(r"Cd\(r\)\s*:\s*([\d.eE+-]+)")
_TIME_RE = re.compile(r"^Time = (\d+)\s*$", re.MULTILINE)


@dataclass
class History:
    iters: list[int] = field(default_factory=list)
    u: list[float] = field(default_factory=list)
    p: list[float] = field(default_factory=list)
    cd: list[float] = field(default_factory=list)
    cl: list[float] = field(default_factory=list)


def _f(s: str) -> float:
    return float(s)


def parse_log(text: str) -> History:
    """按时间步分段聚合：U 取三方向最大残差，p 取本段残差；Cd/Cl 全文收集。"""
    h = History()
    parts = _TIME_RE.split(text)  # [头部, t1, 段1, t2, 段2, ...]
    for i in range(1, len(parts) - 1, 2):
        t = int(parts[i])
        chunk = parts[i + 1]
        uv = [(_f(v), n) for n, v in _RES_RE.findall(chunk)]
        p_vals = [_f(v) for n, v in uv if n == "p"]
        u_vals = [_f(v) for n, v in uv if n.startswith("U")]
        if not u_vals and not p_vals:
            continue
        h.iters.append(t)
        h.u.append(max(u_vals) if u_vals else math.nan)
        h.p.append(p_vals[0] if p_vals else math.nan)
    h.cd = [_f(x) for x in _CD_RE.findall(text)]
    h.cl = [_f(x) for x in _CL_RE.findall(text)]
    n = min(len(h.cd), len(h.cl))
    h.cd, h.cl = h.cd[:n], h.cl[:n]
    return h


def _bad(v: float) -> bool:
    return math.isnan(v) or math.isinf(v)


def is_diverged(h: History) -> bool:
    """任一残差 nan/inf，或最大残差 > 100 判为发散。"""
    for series in (h.u, h.p):
        for v in series:
            if _bad(v) or v > 100.0:
                return True
    for v in h.cd:
        if _bad(v) or abs(v) > 100.0:
            return True
    return False


def has_converged(h: History, window: int = 300, tol: float = 2e-3) -> bool:
    """尾部 window 个 Cd 的极差/均值 < tol 判为收敛（均值接近 0 时用绝对极差）。"""
    if len(h.cd) < window:
        return False
    tail = h.cd[-window:]
    lo, hi = min(tail), max(tail)
    mean = sum(tail) / len(tail)
    spread = (hi - lo) / abs(mean) if abs(mean) > 1e-6 else hi - lo
    return spread < tol


def extract_final_cd(text: str) -> tuple[float, float, float] | None:
    """提取最后一次 forceCoeffs 输出的 (Cd, Cd(f), Cd(r))，无输出时返回 None。"""
    cds = _CD_RE.findall(text)
    if not cds:
        return None
    cd = _f(cds[-1])
    fr = _CD_FR_RE.findall(text)
    rr = _CD_RR_RE.findall(text)
    cd_f = _f(fr[-1]) if fr else math.nan
    cd_r = _f(rr[-1]) if rr else math.nan
    return cd, cd_f, cd_r
