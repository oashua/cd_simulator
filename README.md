# cd_simulator — 汽车风洞仿真桌面应用

导入汽车 3D 模型（STL/OBJ）→ 设置来流风速 → WSL2 内 OpenFOAM 计算 → 输出工程可信的风阻系数 Cd 与流场可视化（表面压力云图 / 流线 / 切片）。

## 架构

```
Windows 桌面应用 (Tauri + Three.js)
  │ wsl -e bash + JSON 行协议 + \\wsl$ 文件交换
  ▼
WSL2 (Ubuntu) + OpenFOAM v2312 (ESI)
  几何预处理(trimesh) → snappyHexMesh → simpleFoam(kOmegaSST)
  → forceCoeffs(Cd) → 后处理(meshio → glTF/JSON)
```

- **solver/**：计算管线，Python 包 `windtunnel` + OpenFOAM case 模板，与 UI 完全解耦，部署到 WSL 内运行。
- **app/**：Tauri v2 桌面外壳（Rust）+ Three.js 前端。

## 目标环境安装（Windows 用户）

1. 管理员 PowerShell：`wsl --install -d Ubuntu --no-launch`，重启，完成 Ubuntu 初始配置。
2. 在 WSL Ubuntu 内执行 `solver/setup_wsl.sh`（安装 OpenFOAM v2312、MPI、Python 依赖，并部署管线到 `~/cd_simulator/solver`）。
3. 安装应用（NSIS 安装包，由 `app/` 构建产出）。

## 开发

```bash
# solver 测试（在装好依赖的环境）
cd solver && pip3 install -e ".[dev]" && python3 -m pytest tests -v

# 应用构建（Windows，需 Rust + Node）
cd app && npm install && npm run tauri build   # 或 cargo tauri dev
```

## 物理与数值假设（诚实声明）

- steady RANS（simpleFoam + kOmegaSST），入口湍流强度 0.5%、长度尺度 0.1L。
- **车轮不转、地面静止（slip）**，无移动地面模拟。
- 网格规模按机器规格自适应三档（low/mid/high，见 `solver/windtunnel/tiers.py`），无人工调优。
- 在此条件下 Cd 绝对值预期偏差 **±0.01–0.03**；不同配置间的趋势对比更可信。
- 迎风面积由体素投影自动估算（离散误差 ~2%）。

## 未运行验证清单（首次实机运行前必读）

本项目按用户要求在开发机上**未安装 OpenFOAM、未做任何运行测试**，以下内容均为"代码写好但从未运行"状态：

| 项目 | 状态 | 首次验证方法 |
|---|---|---|
| OpenFOAM dict 语法（v2312） | ⚠️ 未验证 | 小 case 手动跑 `blockMesh`/`surfaceFeatures`/`snappyHexMesh`；注意 v2312 的 `physicalProperties`（旧版叫 `transportProperties`） |
| `system/streamlines` function object 参数 | ⚠️ seed 语法可能需对照 v2312 文档微调 | `postProcess -func streamlines -latestTime` |
| meshio 读 OpenFOAM VTK 输出（点/单元数据的归属） | ⚠️ 未验证 | 检查 surface/slice VTK 里 p、U 在 point_data 还是 cell_data |
| Rust 侧 WSL 桥（UTF-16 解码、`\\wsl$` 复制、进程流） | ⚠️ 未验证（`cargo check` 也未跑，本机无工具链） | Windows 实机构建 + 冒烟测试 |
| 前端 TS 编译与 Three.js 渲染 | ⚠️ 未验证（`tsc` 未跑） | `npm install && npm run build` |
| solver Python 单元测试 | ⚠️ 未运行（依赖未装） | `python3 -m pytest tests -v` |

**建议的首次端到端验证基准**：Ahmed body（25° 后倾角，实验 Cd ≈ 0.30）；第二步用 DrivAer（有公开风洞数据）。若 Cd 偏差过大，优先检查：迎风面积估算、`Aref` 渲染值、网格档位是否足够、边界层层数。

## 目录

```
solver/
├── windtunnel/        # tiers/geometry/residuals/casegen/postprocess/runner
├── templates/basecase # OpenFOAM case 模板（string.Template 渲染）
├── run_pipeline.py    # CLI 入口
├── setup_wsl.sh       # WSL 环境安装脚本
└── tests/
app/
├── src-tauri/         # Rust：system_info/detect_environment/start_run/cancel_run/get_results/get_artifact
└── src/               # TS：api/viewer/chart + views(setup/import/run/results)
docs/superpowers/      # 设计文档与实施计划
```
