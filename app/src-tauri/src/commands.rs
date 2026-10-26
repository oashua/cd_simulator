//! Tauri 命令：系统信息、环境检测、运行管理、结果读取。

use std::fs;
use std::io::BufRead;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};

use serde::Serialize;
use tauri::{AppHandle, Emitter, State};

use crate::wsl;

/// 与 solver/windtunnel/tiers.py 的 select_tier 保持一致（内存是硬约束）。
fn tier_name(cpu: usize, mem_gb: Option<f64>) -> &'static str {
    match mem_gb {
        Some(m) if m < 32.0 => "low",
        None => "low", // 内存未知时保守取 low
        Some(_) if cpu <= 32 => "mid",
        _ => "high",
    }
}

fn mem_gb_windows() -> Option<f64> {
    let out = Command::new("powershell")
        .args(["-NoProfile", "-Command",
            "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"])
        .output()
        .ok()?;
    let s = String::from_utf8_lossy(&out.stdout);
    s.trim().parse::<f64>().ok().map(|b| b / 1024.0 / 1024.0 / 1024.0)
}

#[derive(Serialize)]
pub struct SystemInfo {
    cpu_count: usize,
    mem_gb: Option<f64>,
    tier_name: String,
}

#[tauri::command]
pub fn system_info() -> SystemInfo {
    let cpu = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4);
    let mem = mem_gb_windows();
    SystemInfo {
        cpu_count: cpu,
        mem_gb: mem.map(|m| (m * 10.0).round() / 10.0),
        tier_name: tier_name(cpu, mem).to_string(),
    }
}

#[derive(Serialize)]
pub struct EnvStatus {
    wsl: bool,
    openfoam: bool,
    distro: Option<String>,
}

#[tauri::command]
pub fn detect_environment() -> EnvStatus {
    let distro = wsl::installed().then(wsl::distro_name).flatten();
    let openfoam = distro
        .as_deref()
        .map(wsl::openfoam_installed)
        .unwrap_or(false);
    EnvStatus {
        wsl: wsl::installed(),
        openfoam,
        distro,
    }
}

/// 全局子进程句柄，供 cancel_run 使用。
pub struct RunState(pub Arc<Mutex<Option<Child>>>);

#[derive(Serialize, Clone)]
pub struct RunConfig {
    velocity: f64,
    scale: f64,
}

#[tauri::command]
pub fn start_run(
    app: AppHandle,
    state: State<RunState>,
    model_path: String,
    velocity: f64,
    scale: f64,
) -> Result<String, String> {
    if state.0.lock().unwrap().is_some() {
        return Err("已有计算任务在运行".into());
    }
    let distro = wsl::installed()
        .then(wsl::distro_name)
        .flatten()
        .ok_or("未检测到 WSL 发行版，请先完成环境安装")?;
    let home = wsl::home_dir(&distro).ok_or("无法获取 WSL HOME 路径")?;

    // run_id：时间戳，天然不覆盖旧结果
    let run_id = format!(
        "run_{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs()
    );
    let linux_dir = format!("{home}/cd_simulator/runs/{run_id}");
    let unc_base = PathBuf::from(format!(r"\\wsl$\{distro}{}", linux_dir.replace('/', "\\")));

    fs::create_dir_all(&unc_base).map_err(|e| format!("无法在 WSL 文件系统创建运行目录: {e}"))?;
    let src = PathBuf::from(&model_path);
    let ext = src
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("stl")
        .to_lowercase();
    if !matches!(ext.as_str(), "stl" | "obj") {
        return Err("仅支持 STL/OBJ 模型文件".into());
    }
    fs::copy(&src, unc_base.join("model.stl"))
        .map_err(|e| format!("模型复制到 WSL 失败: {e}"))?;
    let config = RunConfig { velocity, scale };
    fs::write(
        unc_base.join("run_config.json"),
        serde_json::to_string(&config).unwrap(),
    )
    .map_err(|e| format!("写入 run_config.json 失败: {e}"))?;

    let mut child = Command::new("wsl.exe")
        .args([
            "-d",
            &distro,
            "-e",
            "bash",
            "-lc",
            &format!(
                "python3 {home}/cd_simulator/solver/run_pipeline.py --run-dir {linux_dir}"
            ),
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("无法启动 WSL 计算进程: {e}"))?;

    // stdout 按行转发为 run-log 事件
    let stdout = child.stdout.take().expect("stdout piped");
    let handle = app.clone();
    std::thread::spawn(move || {
        let reader = std::io::BufReader::new(stdout);
        for line in reader.lines().map_while(Result::ok) {
            let _ = handle.emit("run-log", line);
        }
    });

    let pid = child.id();
    *state.0.lock().unwrap() = Some(child);

    // 监视线程：进程退出后清空状态并发 run-exit 事件
    // （State 是借用，线程需 'static —— 持有内部 Arc 的克隆）
    let handle = app.clone();
    let shared = state.0.clone();
    std::thread::spawn(move || loop {
        {
            let guard = shared.lock().unwrap();
            match guard.as_ref() {
                Some(c) if c.id() == pid => {}
                _ => return, // 已被 cancel 或替换
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(500));
        let mut guard = shared.lock().unwrap();
        if let Some(c) = guard.as_mut() {
            if c.id() == pid {
                match c.try_wait() {
                    Ok(Some(status)) => {
                        *guard = None;
                        let _ = handle.emit("run-exit", status.code());
                        return;
                    }
                    Ok(None) => {}
                    Err(_) => {
                        *guard = None;
                        return;
                    }
                }
            }
        }
    });

    Ok(run_id)
}

#[tauri::command]
pub fn cancel_run(state: State<RunState>) -> bool {
    let mut guard = state.0.lock().unwrap();
    if let Some(child) = guard.as_mut() {
        let ok = child.kill().is_ok();
        *guard = None;
        ok
    } else {
        false
    }
}

fn run_out_dir(run_id: &str) -> Result<PathBuf, String> {
    let distro = wsl::distro_name().ok_or("未检测到 WSL 发行版")?;
    let home = wsl::home_dir(&distro).ok_or("无法获取 WSL HOME")?;
    Ok(PathBuf::from(format!(
        r"\\wsl$\{distro}{}\cd_simulator\runs\{}\out",
        home.replace('/', "\\"),
        run_id
    )))
}

#[tauri::command]
pub fn get_results(run_id: String) -> Result<serde_json::Value, String> {
    let path = run_out_dir(&run_id)?.join("results.json");
    let text = fs::read_to_string(path).map_err(|e| format!("读取 results.json 失败: {e}"))?;
    serde_json::from_str(&text).map_err(|e| format!("解析 results.json 失败: {e}"))
}

/// 读取 viewer 产物（surface.glb / streamlines.json / slice.json），base64 返回。
#[tauri::command]
pub fn get_artifact(run_id: String, name: String) -> Result<String, String> {
    let allowed = ["surface.glb", "streamlines.json", "slice.json"];
    if !allowed.contains(&name.as_str()) {
        return Err(format!("非法产物名: {name}"));
    }
    let path = run_out_dir(&run_id)?.join("viewer").join(&name);
    let bytes = fs::read(path).map_err(|e| format!("读取 {name} 失败: {e}"))?;
    let mut b64 = String::with_capacity((bytes.len() + 2) / 3 * 4);
    // 无第三方依赖的 base64：借用标准库编码（6bit 手写实现，体积小风险低）
    const TABLE: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    for chunk in bytes.chunks(3) {
        let b = [chunk[0], *chunk.get(1).unwrap_or(&0), *chunk.get(2).unwrap_or(&0)];
        let n = ((b[0] as u32) << 16) | ((b[1] as u32) << 8) | b[2] as u32;
        b64.push(TABLE[(n >> 18) as usize & 63] as char);
        b64.push(TABLE[(n >> 12) as usize & 63] as char);
        b64.push(if chunk.len() > 1 { TABLE[(n >> 6) as usize & 63] as char } else { '=' });
        b64.push(if chunk.len() > 2 { TABLE[n as usize & 63] as char } else { '=' });
    }
    Ok(b64)
}
