//! cd_simulator Tauri 库入口：注册命令与全局状态。

mod commands;
mod wsl;

use commands::RunState;
use std::sync::Mutex;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(RunState(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            commands::system_info,
            commands::detect_environment,
            commands::start_run,
            commands::cancel_run,
            commands::get_results,
            commands::get_artifact,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
