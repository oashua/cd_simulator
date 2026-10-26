"""管线编排：几何 -> 网格 -> 求解 -> 后处理，输出 JSON 行事件供 Rust 端消费。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .casegen import CaseParams, render_case
from .geometry import prepare_geometry
from .postprocess import collect
from .residuals import is_diverged, parse_log
from .tiers import select_tier

def _detect_bashrc() -> str:
    """探测 OpenFOAM bashrc：apt 包装在 /usr/lib/openfoam，官方脚本装在 /opt。"""
    for p in (
        "/opt/openfoam2312/etc/bashrc",
        "/usr/lib/openfoam/openfoam2312/etc/bashrc",
    ):
        if Path(p).is_file():
            return p
    return "/opt/openfoam2312/etc/bashrc"  # 兜底：未安装时保留可读的报错路径


DEFAULT_OPENFOAM_BASHRC = _detect_bashrc()


def emit(obj: dict) -> None:
    """与 Rust 端约定的 JSON 行协议。"""
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def _step(name: str, status: str, **detail) -> None:
    emit({"event": "step", "name": name, "status": status, **detail})


def _system_specs() -> tuple[int, float]:
    cpu = os.cpu_count() or 4
    mem_gb = 16.0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mem_gb = int(line.split()[1]) / (1024 * 1024)
                break
    except OSError:
        pass
    return cpu, mem_gb


def _template_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / "basecase"


def _run_openfoam(case_dir: Path, n_procs: int, bashrc: str) -> Path:
    """后台跑 Allrun，tail 求解日志发 residuals 事件；返回 log.simpleFoam 路径。"""
    log_path = case_dir / "log.simpleFoam"
    cmd = ["bash", "-lc", f"source {bashrc} && ./Allrun {n_procs}"]
    proc = subprocess.Popen(
        cmd, cwd=case_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    stop = threading.Event()

    def tail() -> None:
        last_iter = -1
        while not stop.is_set() and proc.poll() is None:
            if log_path.exists():
                h = parse_log(log_path.read_text(errors="replace"))
                if h.iters and h.iters[-1] > last_iter:
                    last_iter = h.iters[-1]
                    emit(
                        {
                            "event": "residuals",
                            "iter": last_iter,
                            "u": h.u[-1],
                            "p": h.p[-1],
                            "cd": h.cd[-1] if h.cd else None,
                            "cl": h.cl[-1] if h.cl else None,
                        }
                    )
            time.sleep(2.0)

    t = threading.Thread(target=tail, daemon=True)
    t.start()
    try:
        stdout, _ = proc.communicate()
    finally:
        stop.set()
        t.join(timeout=3)
    if proc.returncode != 0:
        detail = stdout.decode(errors="replace")[-2000:] if stdout else ""
        raise RuntimeError(f"Allrun 失败 (exit {proc.returncode}): {detail}")
    if not log_path.exists():
        raise RuntimeError("Allrun 完成但缺少 log.simpleFoam")
    return log_path


def run_pipeline(
    run_dir: Path, openfoam_bashrc: str = DEFAULT_OPENFOAM_BASHRC
) -> dict:
    """执行完整管线。run_dir 内应有 model.stl|obj 与 run_config.json。

    不覆盖已有结果：run_dir 由 Rust 端按时间戳新建，天然隔离。
    """
    run_dir = Path(run_dir).resolve()
    out_dir = run_dir / "out"
    case_dir = run_dir / "case"

    config = json.loads((run_dir / "run_config.json").read_text())
    velocity = float(config["velocity"])
    scale = float(config.get("scale", 1.0))

    model = next(
        (p for p in sorted(run_dir.glob("model.*")) if p.suffix in (".stl", ".obj")),
        None,
    )
    if model is None:
        raise FileNotFoundError(f"run_dir 中没有 model.stl/model.obj: {run_dir}")

    # 1. 几何
    _step("geometry", "start")
    meta = prepare_geometry(model, run_dir / "geometry", scale=scale)
    _step(
        "geometry",
        "done",
        length=round(meta.length, 3),
        frontal_area=round(meta.frontal_area, 4),
    )

    # 2. 档位 + case 渲染
    cpu, mem_gb = _system_specs()
    tier = select_tier(cpu, mem_gb)
    n_procs = max(1, min(cpu, 64))
    params = CaseParams(
        u_inf=velocity,
        cell_size=tier.base_size_per_length * meta.length,
        n_procs=n_procs,
        iterations=tier.iterations,
        surf_min=tier.surface_min,
        surf_max=tier.surface_max,
        nearbox_level=tier.nearbox_level,
    )
    _step("mesh", "start", tier=tier.name, n_procs=n_procs)
    render_case(_template_dir(), meta, case_dir, params)

    # 3. 求解（含发散自动降松弛重试一次）
    _step("solve", "start")
    log_path = _run_openfoam(case_dir, n_procs, openfoam_bashrc)
    _step("mesh", "done")
    _step("solve", "done")

    if is_diverged(parse_log(log_path.read_text(errors="replace"))):
        _step("solve", "retry", detail="检测到发散，降松弛因子重跑")
        shutil.rmtree(case_dir)
        params.relax = (0.4, 0.4, 0.4)
        render_case(_template_dir(), meta, case_dir, params)
        _step("solve", "start")
        log_path = _run_openfoam(case_dir, n_procs, openfoam_bashrc)
        _step("solve", "done")
        if is_diverged(parse_log(log_path.read_text(errors="replace"))):
            raise RuntimeError("降松弛重跑后仍发散，请检查模型几何或降低风速")

    # 4. 后处理
    _step("post", "start")
    results = collect(case_dir, velocity, out_dir)
    results["frontal_area"] = meta.frontal_area
    results["tier"] = tier.name
    (out_dir / "results.json").write_text(json.dumps(results, indent=2))
    _step("post", "done")

    emit(
        {
            "event": "done",
            "results": {
                k: v for k, v in results.items() if k != "history"
            },
        }
    )
    return results


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="cd_simulator 求解管线")
    parser.add_argument(
        "--run-dir", required=True, help="包含 model 与 run_config.json 的目录"
    )
    parser.add_argument("--openfoam-bashrc", default=DEFAULT_OPENFOAM_BASHRC)
    args = parser.parse_args(argv)

    try:
        run_pipeline(Path(args.run_dir), args.openfoam_bashrc)
        return 0
    except Exception as exc:  # noqa: BLE001 - 顶层边界：错误以 JSON 事件上报
        emit({"event": "error", "message": str(exc)})
        return 1
