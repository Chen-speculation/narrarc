#[tauri::command]
fn spawn_backend_build(talker_id: String) -> Result<(), String> {
  use std::process::{Command, Stdio};
  let cwd = get_backend_dir();
  let _child = Command::new("uv")
    .args([
      "run",
      "python",
      "-m",
      "narrative_mirror.cli_json",
      "--db",
      "data/mirror.db",
      "build",
      "--talker",
      &talker_id,
      "--config",
      "config.yml",
      "--debug",
    ])
    .env("PYTHONUNBUFFERED", "1")
    .current_dir(&cwd)
    .stdin(Stdio::null())
    .stdout(Stdio::inherit())
    .stderr(Stdio::inherit())
    .spawn()
    .map_err(|e| format!("Failed to spawn backend build: {}", e))?;
  Ok(())
}

#[tauri::command]
fn get_backend_dir() -> String {
  use std::path::Path;
  let cwd = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());
  // 用相对路径找 backend（兼容 client/ 或 client/src-tauri 启动）
  for rel in ["../backend", "../../backend"] {
    let p = cwd.join(rel);
    if p.join("pyproject.toml").exists() || p.join("src").join("narrative_mirror").exists() {
      return p
        .canonicalize()
        .unwrap_or(p)
        .to_string_lossy()
        .into_owned();
    }
  }
  // 回退：基于 CARGO_MANIFEST_DIR
  let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
  manifest
    .parent()
    .and_then(|p| p.parent())
    .map(|p| p.join("backend"))
    .unwrap_or_else(|| manifest.join("../../backend"))
    .to_string_lossy()
    .into_owned()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .invoke_handler(tauri::generate_handler![get_backend_dir, spawn_backend_build])
    .plugin(tauri_plugin_shell::init())
    .plugin(tauri_plugin_dialog::init())
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
