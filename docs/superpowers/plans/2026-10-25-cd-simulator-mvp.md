# cd_simulator MVP 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Windows 桌面应用：导入汽车 STL/OBJ → 设置风速 → WSL2 内 OpenFOAM 计算 → 工程可信 Cd + 三种流场可视化。

**Architecture:** Tauri (Rust) 桌面外壳 + Three.js 前端；计算管线是独立 Python 包（solver/），部署到 WSL2 内运行，通过 `wsl -e` 进程调用 + JSON 日志行通信。求解器 OpenFOAM v2312 (ESI)，steady RANS simpleFoam + kOmegaSST。

**Tech Stack:** Python 3.10+ (numpy, trimesh, pymeshfix, meshio) / OpenFOAM v2312 / Rust (Tauri v2) / TypeScript + Vite + Three.js

**关键约束（用户指定）：**
- 开发机（Linux）**不安装 OpenFOAM、不做运行时测试**。验证 = `python3 -m py_compile`（零依赖语法检查）+ 代码评审；测试代码写入但在目标环境（WSL2）首次运行。
- 所有交付物需附"未运行验证清单"。

**数据流约定（跨子系统接口，全项目一致）：**

```
Windows 端                                   WSL2 端 (solver/)
──────────                                   ─────────────────
模型文件 + RunConfig
   → 复制到 \\wsl$\Ubuntu\home\<user>\cd_simulator\runs\<run_id>\
     ├─ model.stl|obj
     └─ run_config.json  {velocity, scale}
   → wsl -d Ubuntu -e bash -lc
       "python3 ~/cd_simulator/run_pipeline.py --run-dir ~/cd_simulator/runs/<id>"
       stdout 逐行输出 JSON 事件:
         {"event":"step","name":"geometry|mesh|solve|post","status":"start|done|error","detail":...}
         {"event":"residuals","iter":N,"u":f,"p":f,"cd":f,"cl":f}
         {"event":"done","results":{...}}   /   {"event":"error","message":...}
     最终产物 runs/<id>/out/:
       results.json        {cd, cl, cd_f, cd_r, frontal_area, iterations, converged}
       viewer/surface.glb  表面 Cp 顶点色 glTF
       viewer/streamlines.json
       viewer/slice.json
```

---

### Task 0: 仓库初始化与目录骨架

**Files:** Create: `.gitignore`, 目录骨架

- [ ] `git init`，创建目录：`solver/windtunnel/`、`solver/templates/basecase/{0,constant,system}`、`solver/tests/`、`app/`、`docs/superpowers/plans/`
- [ ] `.gitignore`：`*.stl`、`*.obj`、`__pycache__/`、`app/node_modules/`、`app/src-tauri/target/`、`runs/`
- [ ] Commit: `chore: init repo structure`

### Task 1: solver/windtunnel/tiers.py — 自适应网格档位

**Files:**
- Create: `solver/windtunnel/__init__.py`、`solver/windtunnel/tiers.py`
- Test: `solver/tests/test_tiers.py`

- [ ] **Step 1: 写实现**。契约：

```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Tier:
    name: str
    base_size_per_length: float  # 背景网格尺寸 = 该系数 × 车长（经验系数，未经风洞标定）
    surface_min: int             # snappy refinementSurfaces 最小细化层级
    surface_max: int             # 最大细化层级
    nearbox_level: int           # 车周围 refinementBox 细化层级
    iterations: int              # simpleFoam 迭代步数

TIERS = (
    Tier("low",  1/28, 2, 2, 1, 1500),
    Tier("mid",  1/40, 2, 3, 2, 2500),
    Tier("high", 1/56, 3, 3, 2, 3500),
)

def select_tier(cpu_count: int, mem_gb: float) -> Tier:
    """cpu_count<8 且 mem_gb<32 → low；cpu_count<=32 且 mem_gb<=128 → mid；否则 high。
    参数非正时 raise ValueError。"""
```

- [ ] **Step 2: 写测试**（在 WSL 目标环境运行，本机不执行）：

```python
import pytest
from windtunnel.tiers import select_tier, TIERS

def test_low_tier_for_small_machine():
    assert select_tier(4, 16).name == "low"

def test_mid_tier_boundary():
    assert select_tier(8, 32).name == "mid"
    assert select_tier(32, 128).name == "mid"

def test_high_tier():
    assert select_tier(64, 256).name == "high"

def test_invalid_inputs():
    with pytest.raises(ValueError):
        select_tier(0, 16)
    with pytest.raises(ValueError):
        select_tier(4, -1)
```

- [ ] **Step 3:** `python3 -m py_compile solver/windtunnel/tiers.py` 通过 → Commit `feat(solver): adaptive mesh tier selection`

### Task 2: solver/windtunnel/geometry.py — 几何修复与正则化

**Files:**
- Create: `solver/windtunnel/geometry.py`
- Test: `solver/tests/test_geometry.py`

- [ ] **Step 1: 写实现**。契约：

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np

@dataclass
class GeometryMeta:
    length: float          # 车长 m（正则化后包围盒）
    width: float
    height: float
    frontal_area: float    # 迎风面积 m²（y-z 平面投影）
    center: tuple[float, float, float]  # 包围盒中心（x,y=0, z=height/2）
    path: Path             # cleaned.stl 输出路径

def prepare_geometry(src: Path, out_dir: Path, scale: float = 1.0,
                     voxel_divisions: int = 60) -> GeometryMeta:
    """加载 STL/OBJ → 修复水密 → 施加 scale → 平移使 min_z=0、x/y 居中 →
    体素投影估算迎风面积 → 保存 out_dir/cleaned.stl。
    src 不存在或网格为空 → raise ValueError。
    修复策略：trimesh.repair.fix_normals + fill_holes；
    若 mesh.is_watertight 仍为 False，用 pymeshfix 兜底（try/except ImportError 时
    仅警告不阻塞——非水密网格 snappyHexMesh 通常仍能处理）。"""
```

迎风面积算法（体素投影，只依赖 numpy+trimesh）：

```python
def _frontal_area(mesh, length: float, divisions: int) -> float:
    pitch = length / divisions
    grid = mesh.voxelized(pitch)
    idx = np.asarray(grid.sparse_indices)          # (N, 3) 整数格点
    yz = idx[:, [1, 2]]                            # 投影到 y-z 平面
    unique = np.unique(yz, axis=0)
    return float(unique.shape[0]) * pitch * pitch
```

- [ ] **Step 2: 写测试**（用 trimesh 内置图元构造，目标环境运行）：

```python
import numpy as np
import trimesh
from windtunnel.geometry import prepare_geometry, _frontal_area

def _box_on_ground(a=4.0, b=1.8, c=1.2):
    m = trimesh.creation.box(extents=(a, b, c))
    m.apply_translation([0, 0, c / 2 + 0.1])   # 悬空，测试会压到地面
    return m

def test_prepare_normalizes_position(tmp_path):
    src = tmp_path / "car.stl"
    _box_on_ground().export(src)
    meta = prepare_geometry(src, tmp_path / "out")
    assert meta.length == pytest.approx(4.0)
    assert meta.height == pytest.approx(1.2)
    loaded = trimesh.load(meta.path)
    assert loaded.bounds[0][2] == pytest.approx(0.0)   # 落地

def test_frontal_area_of_box():
    m = _box_on_ground()
    area = _frontal_area(m, length=4.0, divisions=100)
    assert area == pytest.approx(1.8 * 1.2, rel=0.05)  # 体素离散误差 5%

def test_missing_file(tmp_path):
    with pytest.raises(ValueError):
        prepare_geometry(tmp_path / "nope.stl", tmp_path)
```

- [ ] **Step 3:** `py_compile` 通过 → Commit `feat(solver): geometry repair & normalization`

### Task 3: solver/windtunnel/residuals.py — 日志解析与收敛/发散判定

**Files:**
- Create: `solver/windtunnel/residuals.py`
- Test: `solver/tests/test_residuals.py`

- [ ] **Step 1: 写实现**。OpenFOAM v2312 日志事实格式（正则以此为准）：

```
smoothSolver:  Solving for Ux, Initial residual = 0.01234, final residual = ..., No Iterations 3
GAMG:  Solving for p, Initial residual = 0.00456, ...
Cd : 0.312  Cl : 0.045  Cm : 0.012        （forceCoeffs 行，实际为多行格式，见下）
Cd(f) : ... Cd(r) : ...
```

```python
@dataclass
class History:
    iters: list[int]; u: list[float]; p: list[float]
    cd: list[float]; cl: list[float]

_RES_RE = re.compile(r"Solving for (U[x-z]|p), Initial residual = ([\d.eE+-]+)")
_CD_RE  = re.compile(r"^\s*Cd\s*:\s*([\d.eE+-]+)", re.MULTILINE)
_CL_RE  = re.compile(r"^\s*Cl\s*:\s*([\d.eE+-]+)", re.MULTILINE)

def parse_log(text: str) -> History: ...
def is_diverged(h: History) -> bool:
    """任一残差为 nan/inf，或最大残差 > 100 → True"""
def has_converged(h: History, window: int = 300, tol: float = 2e-3) -> bool:
    """尾部 window 个 Cd 的 (max-min)/mean < tol 且样本数 >= window → True"""
def extract_final_cd(text: str) -> tuple[float, float] | None:
    """从 forceCoeffs 末次输出提取 (Cd, Cd(f))；用于阻力分解。"""
```

- [ ] **Step 2: 写测试**：内嵌一段最小仿真日志字符串（含 3 个时间步残差 + 2 次 forceCoeffs 输出 + 一段含 nan 的变体），断言解析数量、发散判定、收敛判定（构造单调趋稳的合成 Cd 序列）。
- [ ] **Step 3:** `py_compile` 通过 → Commit `feat(solver): log parsing & convergence detection`

### Task 4: OpenFOAM case 模板（solver/templates/basecase/）

本任务是全部 CFD 领域知识所在，dict 内容必须完整写死，执行者不做临场发挥。所有数值占位符用 `string.Template` 的 `${VAR}` 语法。变量清单（casegen 传入）：

```
${U_INF} ${CELL} ${NX} ${NY} ${NZ} ${XMIN} ${YMIN} ${ZMIN} ${XMAX} ${YMAX} ${ZMAX}
${CAR_STL} ${LOC_IN_MESH} ${COFR_X} ${COFR_Z} ${AREF} ${LREF} ${NPROC} ${END_TIME}
${RELAX_P} ${RELAX_U} ${RELAX_TURB}
```

- [ ] **Step 1: `system/blockMeshDict`** — 单块六面体域，背景网格 `(${NX} ${NY} ${NZ})`，无分级（细化交给 snappy）。边界名与类型：`inlet`(patch) x=XMIN / `outlet`(patch) x=XMAX / `ground`(patch) z=ZMIN / `top`(patch) z=ZMAX / `sideL` `sideR`(patch)。
- [ ] **Step 2: `system/snappyHexMeshDict`** —

```
castellatedMesh true; snap true; addLayers true;
geometry: { "${CAR_STL}" { type triSurfaceMesh; name car; }
            nearBox { type searchableBox; min (车长×-0.75 -1.0×车宽 0.1) max (车长×1.75 1.0×车宽 车高×2.2); } }
castellatedMeshControls:
  refinementSurfaces { car { level (${SURF_MIN} ${SURF_MAX}); } }
  refinementRegions { nearBox { mode inside; level ${NEARBOX}; } }
  resolveFeatureAngle 60; nCellsBetweenLevels 3; locationInMesh ${LOC_IN_MESH};
snapControls: nSmoothPatch 3; tolerance 2.0; nSolveIter 50; nRelaxIter 5;
addLayersControls: relativeSizes true; nSurfaceLayers 3; finalLayerThickness 0.3;
  minThickness 0.05; expansionRatio 1.2;
```
- [ ] **Step 3: `system/surfaceFeaturesDict`** — `includedAngle 150`，写出 `car.eMesh`。
- [ ] **Step 4: `0/` 场文件** — `U`(inlet fixedValue (${U_INF} 0 0), car noSlip, ground/sideL/sideR/top slip, outlet inletOutlet), `p`(outlet fixedValue 0, 其余 zeroGradient), `k`(inlet: 1.5×(0.005·U)², car: kqRWallFunction, outlet inletOutlet, 滑移面 zeroGradient), `omega`(inlet: k^0.5/((0.09)^0.25·0.1L), car: omegaWallFunction, ...), `nut`(car: nutkWallFunction, 其余 calculated 0)。
- [ ] **Step 5: `constant/`** — `transportProperties`(nu 1.5e-05), `momentumTransport`? v2312 文件名为 `momentumTransport`（ESI 2312 已改名；RAS{kOmegaSST on}）。**注意执行时确认文件名**：v2312 用 `momentumTransport`。
- [ ] **Step 6: `system/fvSchemes`** — 稳健优先：`div(phi,U) bounded Gauss upwind`、`div(phi,k/omega) upwind`、`grad Gauss linear`、`laplacian Gauss linear corrected`、`snGradSchemes corrected`。
- [ ] **Step 7: `system/fvSolution`** — p: GAMG(tolerance 1e-7, relTol 0.01), U/k/omega: smoothSolver(relTol 0.1)；relaxationFactors: `fields{p ${RELAX_P}} equations{U ${RELAX_U}; k/omega ${RELAX_TURB}}`。发散重试时 casegen 以 0.4/0.4/0.4 重新渲染。
- [ ] **Step 8: `system/controlDict`** — `application simpleFoam; endTime ${END_TIME}; writeInterval ${END_TIME}; writeControl timeStep; purgeWrite 2;` + 三个 function objects：
  1. `forces_coeffs`（type forceCoeffs; libs ("libforces.so"); patches (car); rhoInf 1.2; rho rhoInf; CofR (${COFR_X} 0 ${COFR_Z}); dragDir (1 0 0); liftDir (0 0 1); pitchAxis (0 1 0); magUInf ${U_INF}; lRef ${LREF}; Aref ${AREF}; log yes; writeControl timeStep; writeInterval 10;）
  2. `surfaces`（type surfaces; libs ("libsampling.so"); surfaceFormat vtk; writeControl writeTime; fields (p U); surfaces: `car` → type sampledTriSurfaceMesh, surface "${CAR_STL}"; `slice` → type cuttingPlane, planeType pointAndNormal, planePoint (0 0 ${COFR_Z}), planeNormal (0 1 0)）
  3. `streamlines`（type streamlines; libs ("libfieldFunctionObjects.so"); writeControl writeTime; lifeTime 5; trackForward yes; cloud particleTracks; seedSamples 12; fields (U); seedPosition (车前 1.5L, 0, 0.5×车高); seedAxis (0 1 0); seedLength 0.8×车宽; interpolationScheme cellPoint;）
- [ ] **Step 9: `system/decomposeParDict`** — `method scotch; numberOfSubdomains ${NPROC};`
- [ ] **Step 10: `Allrun`**（可执行 bash）：

```bash
#!/bin/bash
set -e
source /opt/openfoam2312/etc/bashrc
cd "$(dirname "$0")"
NPROC=$1
blockMesh          > log.blockMesh 2>&1
surfaceFeatures    > log.surfaceFeatures 2>&1
snappyHexMesh -overwrite > log.snappyHexMesh 2>&1
decomposePar -force      > log.decomposePar 2>&1
mpirun --allow-run-as-root -np "$NPROC" simpleFoam -parallel > log.simpleFoam 2>&1
reconstructPar -latestTime > log.reconstructPar 2>&1
postProcess -func surfaces -latestTime > log.surfaces 2>&1
postProcess -func streamlines -latestTime > log.streamlines 2>&1
```
（WSL2 root 用户时 mpirun 需要 `--allow-run-as-root`；非 root 无副作用。）

- [ ] **Step 11:** 模板内所有 `${VAR}` 与变量清单逐一核对（`grep -o '\${[A-Z_]*}'` 交叉比对）→ Commit `feat(solver): OpenFOAM case templates`

### Task 5: solver/windtunnel/casegen.py — 模板渲染

**Files:** Create: `solver/windtunnel/casegen.py`

- [ ] **Step 1: 写实现**。契约：

```python
@dataclass
class CaseParams:
    u_inf: float; cell_size: float; n_procs: int; iterations: int
    surf_min: int; surf_max: int; nearbox_level: int
    relax: tuple[float, float, float] = (0.5, 0.55, 0.55)  # p, U, k/omega

def render_case(template_dir: Path, meta: GeometryMeta,
                case_dir: Path, p: CaseParams) -> None:
    """按上方变量清单渲染全部模板 → case_dir；
    domain: x∈[-2L, +5L], y∈[-2.5W, +2.5W], z∈[0, 4H]（margin 为行业惯例值）；
    NX/NY/NZ = ceil(各向长度/cell_size)，cell_size = tier.base_size_per_length × L；
    LOC_IN_MESH = (0, 0, 0.4H)（车体内部一点，用户可后续暴露为高级选项）；
    AREF = meta.frontal_area; LREF = meta.length; COFR_X/Z = 包围盒中心；
    复制 meta.path → case_dir/constant/triSurface/car.stl；
    Allrun 加可执行权限。"""
```

- [ ] **Step 2:** 单元测试（目标环境）：用 monkeypatch 假 meta 调 render_case 到 tmp_path，断言生成的 blockMeshDict 含正确 NX、car.stl 存在。`py_compile` 通过 → Commit `feat(solver): case rendering`

### Task 6: solver/windtunnel/postprocess.py — 结果转换

**Files:** Create: `solver/windtunnel/postprocess.py`
**依赖:** meshio（读 OpenFOAM function object 输出的 legacy VTK）+ numpy + trimesh（glTF 顶点色导出）

- [ ] **Step 1: 写实现**。契约：

```python
def diverging_colormap(v: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    """三段线性插值 RGB uint8 (N,3)：(59,76,192) → (247,247,247) → (180,4,38)，
    v 被 clip 到 [vmin, vmax]。Cp 用 vmin=-1.5, vmax=1.0。"""

def _cell_to_point(mesh: "meshio.Mesh") -> dict[str, np.ndarray]:
    """cell data → point data：np.add.at 累加到顶点再除以关联次数（所有 block 平均）。"""

def export_surface_glb(vtk_path: Path, meta: GeometryMeta, out_glb: Path) -> None:
    """读 sampledTriSurfaceMesh 的 VTK（points + triangles + p/U），
    Cp = p/(0.5·1.2·U²)，顶点色 → trimesh.Trimesh(process=False) → .glb"""

def export_streamlines_json(vtk_path: Path, out: Path) -> None:
    """meshio 读 polydata，line cells 是 (N,2) 段表 → 端点哈希链接成折线；
    输出 JSON: {"lines": [{"points": [[x,y,z]...], "speed": [f...]}...]}"""

def export_slice_json(vtk_path: Path, out: Path) -> None:
    """cuttingPlane VTK → {"points":..., "faces":..., "cp":..., "vel_mag":...}"""

def collect(case_dir: Path, meta: GeometryMeta, u_inf: float,
            out_dir: Path) -> dict:
    """定位 case/postProcessing/ 下三个 VTK 输出 → 三个 viewer 文件；
    解析 log.simpleFoam → results.json: {cd, cl, cd_f, cd_r, frontal_area,
    iterations, converged, history:{iters,u,p,cd,cl}}；返回该 dict。"""
```

- [ ] **Step 2:** 测试（目标环境）：手工构造含 point data 的小 VTK（meshio.write）→ export → 断言 JSON 结构。`py_compile` 通过 → Commit `feat(solver): postprocess exports`

### Task 7: solver/windtunnel/runner.py + run_pipeline.py — 管线编排

**Files:** Create: `solver/windtunnel/runner.py`、`solver/run_pipeline.py`

- [ ] **Step 1: runner 契约**：

```python
def emit(obj: dict) -> None:
    """print(json.dumps(obj), flush=True) —— 与 Rust 约定的 JSON 行协议"""

def run_pipeline(run_dir: Path, openfoam_bashrc: str
                 = "/opt/openfoam2312/etc/bashrc") -> dict:
    步骤（每步发 step 事件，异常发 error 事件后 raise）:
    1. 读 run_config.json {velocity, scale}
    2. prepare_geometry → meta（发 frontal_area/尺寸进 detail）
    3. select_tier(cpu, mem)（cpu/mem 从 os.cpu_count 和 /proc/meminfo 读）
       render_case(默认 relaxation) 
    4. subprocess: ["bash", "-lc", f"source {openfoam_bashrc} && ./Allrun {n_procs}"]
       cwd=case_dir；Popen 后起 tail 线程轮询 log.simpleFoam（2s 间隔），
       每有新步数就发 residuals 事件
    5. parse log → is_diverged → 若发散：render_case(relax=(0.4,0.4,0.4)) 重跑一次
       （重跑前恢复 Allrun 产物目录）；再发散 → error
    6. collect() → results.json → 发 done 事件，返回 dict
```

- [ ] **Step 2: run_pipeline.py** — argparse `--run-dir`（必填）、`--openfoam-bashrc`（默认如上），调 run_pipeline。
- [ ] **Step 3:** `py_compile` 两个文件 → Commit `feat(solver): pipeline orchestration`

### Task 8: solver/setup_wsl.sh — WSL 内环境安装脚本

- [ ] **Step 1: 写脚本**（ESI OpenFOAM 官方 Ubuntu 安装流程 + pip 依赖）：

```bash
#!/bin/bash
# 在 WSL Ubuntu 内以可 sudo 的普通用户运行
set -e
sudo sh -c 'wget -O - https://dl.openfoam.com/gpg.key > /etc/apt/trusted.gpg.d/openfoam.asc'
sudo add-apt-repository -y http://dl.openfoam.com/ubuntu/latest
sudo apt-get update
sudo apt-get install -y openfoam2312-default python3-pip
sudo apt-get install -y libopenmpi-dev openmpi-bin   # mpirun
pip3 install --user numpy trimesh meshio pymeshfix
mkdir -p ~/cd_simulator && cp -r "$(dirname "$0")/.." ~/cd_simulator/solver
```
- [ ] **Step 2:** `bash -n` 语法检查 → Commit `feat(solver): WSL setup script`

### Task 9: pytest 套件组织

- [ ] **Step 1:** `solver/tests/conftest.py`（把 solver/ 加入 sys.path）、`solver/pyproject.toml`（`[project] name="windtunnel"` + 依赖声明，dev 依赖 pytest）。
- [ ] **Step 2:** 本机不跑 pytest（依赖未装），在 README 记录目标环境运行命令 `cd ~/cd_simulator/solver && python3 -m pytest tests -v` → Commit `test(solver): unit tests`

### Task 10: Tauri 外壳（app/src-tauri/）

**Files:** Create: `app/src-tauri/Cargo.toml`、`tauri.conf.json`、`capabilities/default.json`、`src/{main.rs,lib.rs,commands.rs,wsl.rs}`、`build.rs`、`icons/`（tauri icon 默认生成）

- [ ] **Step 1: wsl.rs** — WSL 检测与执行封装：

```rust
pub fn wsl_installed() -> bool          // `wsl.exe --status` exit code 0
pub fn distro_name() -> Option<String>  // `wsl.exe --list --quiet` 首行 trim + 去除 UTF-16 null
pub fn run_in_wsl(distro: &str, script: &str) -> Result<String, String>
    // Command::new("wsl.exe").args(["-d", distro, "-e", "bash", "-lc", script])
pub fn wsl_user_home(distro: &str) -> Option<String>  // bash -c "echo $HOME"
```
（注意：`wsl --list` 输出是 UTF-16LE，需要 `String::from_utf16le_lossy` 自写转换。）

- [ ] **Step 2: commands.rs** — 四个 Tauri 命令（签名固定，前端 api.ts 按此对接）：

```rust
#[tauri::command] fn system_info() -> SystemInfo            // {cpu_count, mem_gb, tier_name}
#[tauri::command] fn detect_environment() -> EnvStatus      // {wsl, openfoam} 两个 bool
#[tauri::command] fn start_run(app: AppHandle, model_path: String,
    velocity: f64, scale: f64) -> Result<String, String>
    // run_id = 时间戳；把模型 copy 到 \\wsl$\<distro>\home\<user>\cd_simulator\runs\<id>\model.stl
    // + run_config.json；std::process::Command spawn wsl.exe -d <distro> -e bash -lc
    //   "python3 ~/cd_simulator/run_pipeline.py --run-dir ~/cd_simulator/runs/<id>"
    // stdout 按行读（BufReader + spawn 线程）→ app.emit("run-log", 行原文)；
    // run_id 存全局 Mutex<Option<Child>> 供 cancel
#[tauri::command] fn cancel_run() -> bool                   // kill 子进程树
```

- [ ] **Step 3: lib.rs** — 注册命令 + `run-log` 事件；Cargo.toml: tauri = "2", serde, serde_json。
- [ ] **Step 4:** `cargo check`（若本机无 Rust 工具链则记录跳过，目标环境验证）→ Commit `feat(app): tauri shell & wsl bridge`

### Task 11: 前端（app/src/）

**Files:** Create: `app/{package.json,vite.config.ts,index.html,tsconfig.json}`、`src/{main.ts,api.ts,viewer.ts,chart.ts,views/*.ts,styles.css}`

- [ ] **Step 1: api.ts** — 按 Task 10 命令签名写类型化封装（`invoke<SystemInfo>("system_info")` 等 + `listen<string>("run-log", ...)` + `listen<{event:string;...}>` 解析 JSON 行）。
- [ ] **Step 2: viewer.ts** — Three.js 场景管理：`createViewer(container)`；`showModel(path)`（读本地文件 → STLLoader/OBJLoader，用户经 `<input type=file>` 选文件，前端直接解析，不经 Rust）；`showResults(surfaceUrl, streamlines, slice)`（GLTFLoader 加载 surface.glb + MeshStandardMaterial vertexColors；streamlines → THREE.Line 按速度顶点色 + LineDashedMaterial 动画 dashOffset；slice → BufferGeometry 顶点色半透明面）；OrbitControls；色标 legend（纯 DOM 渐变条 + min/max 文本）。
- [ ] **Step 3: 视图流** — `views/import.ts`（拖拽/选文件 + 缩放、风速输入、档位显示来自 system_info、开始按钮）/ `views/run.ts`（残差曲线 canvas + 日志尾窗 + 取消按钮）/ `views/results.ts`（Cd 大字 + 三 tab 切换 + 精度免责声明 + 导出报告按钮）。残差 chart：简单双 y 轴 canvas 折线（对数残差 + 线性 Cd），不引第三方图表库。
- [ ] **Step 4: 首次运行向导** — `views/setup.ts`：detect_environment 失败时展示 setup_wsl.sh 内容与手动步骤说明（MVP 不做自动提权安装，给复制粘贴命令 + "重新检测"按钮——分发版本再自动化）。
- [ ] **Step 5:** `tsc --noEmit`（若本机无 Node 工具链则记录跳过）→ Commit `feat(app): frontend views & 3d viewer`

### Task 12: 文档与交付

- [ ] **Step 1: README.md** — 架构图、目标环境安装步骤（Windows + WSL2 + setup_wsl.sh）、开发说明、"未运行验证清单"（明确列出：OpenFOAM dict 语法、VTK 转换、WSL 桥、前端构建均未经运行验证；建议首次验证用 Ahmed body，25° 后倾角实验 Cd ≈ 0.30，DrivAer 有公开风洞数据）。
- [ ] **Step 2:** Commit → 汇总交付说明给用户。

---

## Self-Review 结论

- **Spec 覆盖**：导入/风速/后台计算/Cd/三可视化/自适应档位/WSL 安装向导（MVP 手动版）/错误处理（水密修复、发散重试、环境检测）均有对应 Task；spec 中"首次运行向导自动安装"在 MVP 降级为引导式手动安装（Task 11 Step 4 已注明分发版本再自动化）——已在范围内显式说明。
- **占位符扫描**：无 TBD；Task 4 模板以参数表 + dict 要点完整定义，执行时逐项写全。
- **类型一致性**：`GeometryMeta`/`Tier`/`History`/`CaseParams`/JSON 行协议字段在 Task 1–7 与 Task 10/11 间已对齐（start_run 的 run_config.json 键 `{velocity, scale}` ↔ runner 读取一致）。
