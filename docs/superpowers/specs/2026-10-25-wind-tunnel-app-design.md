# 汽车风洞仿真应用（cd_simulator）设计文档

日期：2026-10-25
状态：已获用户批准

## 目标

Windows 桌面应用：导入汽车 3D 模型（STL/OBJ）→ 设置风速 → 后台计算（OpenFOAM）→ 查看工程可信的风阻系数 Cd 与流场可视化（表面压力云图 / 流线 / 切片）。分发给别人使用，目标机器规格各异，网格规模自适应。

## 用户确认的关键决策

1. **精度路线**：工程可信 Cd（±0.01–0.03），核心求解器 OpenFOAM（steady RANS, simpleFoam + kOmegaSST），应用内嵌 WSL2 运行环境，接受安装复杂。
2. **模型输入**：STL / OBJ 三角网格。
3. **UI 技术栈**：Tauri + Three.js。
4. **MVP 范围**：基础流程（导入 → 设风速 → 后台计算 → Cd + 三种可视化）。不含：计算过程残差实时监控面板的高级功能、几何预处理交互工具、参数扫描。
5. **分发对象**：第三方用户，机器规格各异 → 网格预算按 CPU 核数/内存自适应分档。
6. **开发约束（用户明确指示）**：开发机（Linux, 64核/1TB/2×RTX 6000 Ada）**不安装 OpenFOAM、不做本机运行测试**。所有 solver 管线代码直接面向 Windows/WSL2 目标编写，交付时标注"未运行验证"。

## 架构

```
┌─ Windows 桌面应用 (Tauri + Three.js) ────────────────┐
│  前端 UI：模型导入/查看 · 参数设置 · 残差监控 · 结果渲染  │
│  Rust 层：任务调度 · 进程管理 · 环境检测                │
└──────────────┬───────────────────────────────────────┘
               │ wsl -e 命令执行 + \\wsl$ 文件交换 + 日志流
┌──────────────▼───────────────────────────────────────┐
│  WSL2 (Ubuntu) + OpenFOAM                             │
│  预处理(trimesh水密修复) → snappyHexMesh → simpleFoam  │
│  → forceCoeffs(Cd) → 后处理导出(流线/云图/切片数据)      │
└───────────────────────────────────────────────────────┘
```

- WSL2 原生安装 OpenFOAM（apt），不用 Docker Desktop（避免许可与体积）。
- 首次运行向导：检测 WSL2 → `wsl --install`（需管理员权限 + 重启）→ 安装 OpenFOAM。
- Rust 通过 `wsl -e bash -c` 执行管线脚本；case 文件经 `\\wsl$\Ubuntu\...` 路径交换；stdout/stderr 流式回传前端。

## 计算管线

1. **导入**：STL/OBJ 解析（前端 three.js STLLoader/OBJLoader），单位假设米，界面可调缩放。
2. **几何预处理**（WSL 内 Python：trimesh + pymeshfix）：水密修复、法向一致、按包围盒自动定位到风洞域标准位置（离地间隙、迎角 MVP 固定为默认值）。
3. **自适应网格档位**（按目标机核数/内存）：
   - `<8 核` → ~8M cells，预计 ~20 分钟
   - `8–32 核` → ~20M cells，预计 1–2 小时
   - `>32 核 或 内存>64GB` → ~50M cells，预计 3–6 小时
   映射到背景网格尺寸 + snappyHexMesh 细化层级。
4. **求解**：simpleFoam steady RANS，kOmegaSST，边界条件：速度入口 / 压力出口 / 滑移地面 / 车身 no-slip 壁面。MVP 简化：车轮不转、地面静止（界面注明）。
5. **Cd 提取**：forceCoeffs function object，输出 Cd、Cl 及压差/粘性阻力分解；收敛判据 + NaN 发散检测（自动降松弛重试一次）。
6. **后处理**（WSL 内 Python + PyVista）：
   - 表面压力 → 顶点色 glTF
   - 流线 → seed 面采样 + streamline 积分 → 折线 JSON
   - 切片（x/z 平面速度/压力）→ structured grid JSON

## 前端

- 主界面：左侧参数面板（风速、网格档位、开始/停止）+ 中央 Three.js 3D 视图 + 底部残差曲线（日志流实时刷新）。
- 结果页：Cd 数值 + 三个 tab（压力云图 / 流线动画 / 切片），3D 可交互（旋转/缩放）。
- 结果导出 JSON 报告（完整配置 + Cd + 时间戳），供复现。

## 错误处理

- 水密修复失败：报错并指出问题（非流形边数量等）。
- 求解发散：自动降松弛重试一次，仍失败则报错。
- WSL2/OpenFOAM 未安装：引导向导。
- 应用内精度声明：自适应网格 + 车轮不转 + 静止地面下，Cd 绝对值偏差 ±0.01–0.03，趋势对比可信。

## 测试策略（受用户约束调整）

- **不做本机运行测试**（用户明确指示，开发机不装 OpenFOAM）。
- 代码层面验证：Python 脚本语法/单元测试（mock OpenFOAM 调用）、Rust `cargo check`、前端 `tsc`/构建通过。
- 管线正确性留待用户在 Windows/WSL2 环境首次运行时验证；推荐基准：Ahmed body（Cd≈0.30 @25° 后倾角，有实验值）、DrivAer（有风洞数据）。
- 交付物中明确列出"未运行验证清单"。

## 项目结构

```
cd_simulator/
├── app/                    # Tauri 应用
│   ├── src-tauri/          # Rust：命令、WSL 进程管理、环境检测
│   └── src/                # Three.js + TypeScript 前端
├── solver/                 # 与 UI 解耦的计算管线（部署到 WSL 内）
│   ├── templates/          # OpenFOAM case 模板（0/ system/ constant/）
│   ├── preprocess.py       # 水密修复 + 定位
│   ├── run_case.py         # 档位决策 + mesh + solve 编排
│   └── postprocess.py      # Cd 提取 + 三种可视化数据导出
├── docs/superpowers/specs/
└── tests/                  # Python 单元测试（mock OpenFOAM）
```
