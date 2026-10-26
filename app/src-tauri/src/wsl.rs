//! WSL 检测与命令执行封装。
//!
//! 注意：`wsl.exe --list` 系列输出是 UTF-16LE，需先解码再使用。

use std::process::Command;

fn decode_utf16(raw: Vec<u8>) -> String {
    if raw.len() >= 2 && raw[0] != 0 && raw[1] == 0 {
        let units: Vec<u16> = raw
            .chunks_exact(2)
            .map(|c| u16::from_le_bytes([c[0], c[1]]))
            .collect();
        String::from_utf16_lossy(&units)
    } else {
        String::from_utf8_lossy(&raw).into_owned()
    }
}

fn wsl_output(args: &[&str]) -> Option<String> {
    let out = Command::new("wsl.exe").args(args).output().ok()?;
    if !out.status.success() {
        return None;
    }
    Some(decode_utf16(out.stdout))
}

/// WSL 是否可用（有任意已注册发行版）。
pub fn installed() -> bool {
    wsl_output(&["--list", "--quiet"])
        .map(|s| !s.trim().is_empty())
        .unwrap_or(false)
}

/// 第一个发行版名（如 "Ubuntu"），无则 None。
pub fn distro_name() -> Option<String> {
    let list = wsl_output(&["--list", "--quiet"])?;
    list.lines()
        .map(str::trim)
        .find(|l| !l.is_empty())
        .map(String::from)
}

/// 在 WSL 内执行 bash 脚本，返回 stdout；失败返回 stderr 摘要。
pub fn run_bash(distro: &str, script: &str) -> Result<String, String> {
    let out = Command::new("wsl.exe")
        .args(["-d", distro, "-e", "bash", "-lc", script])
        .output()
        .map_err(|e| format!("无法启动 wsl.exe: {e}"))?;
    if out.status.success() {
        Ok(String::from_utf8_lossy(&out.stdout).into_owned())
    } else {
        Err(String::from_utf8_lossy(&out.stderr)
            .lines()
            .last()
            .unwrap_or("WSL 命令执行失败")
            .to_string())
    }
}

/// WSL 内 OpenFOAM 是否已安装。
pub fn openfoam_installed(distro: &str) -> bool {
    run_bash(
        distro,
        "test -f /opt/openfoam2312/etc/bashrc -o -f /usr/lib/openfoam/openfoam2312/etc/bashrc && echo yes || echo no",
    )
    .map(|s| s.trim() == "yes")
    .unwrap_or(false)
}

/// WSL 内当前用户 HOME 路径。
pub fn home_dir(distro: &str) -> Option<String> {
    run_bash(distro, "echo $HOME")
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}
