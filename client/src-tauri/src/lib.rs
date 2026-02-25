use std::io::{BufRead, BufReader, Write};
use std::ops::DerefMut;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use tauri::{Emitter, Manager};

/// Long-lived backend process: stdin/stdout for JSON lines; child kept for kill on exit.
struct BackendProcess {
  child: Child,
  stdin: Option<std::process::ChildStdin>,
  stdout: Option<BufReader<std::process::ChildStdout>>,
}

/// Spawn backend: dev uses uv run python, release uses bundled sidecar via std::process::Command.
fn spawn_backend_process(app: Option<&tauri::AppHandle>) -> Result<BackendProcess, String> {
  let (cwd, db_arg) = get_backend_cwd_and_db(app);

  #[cfg(debug_assertions)]
  {
    let mut child = Command::new("uv")
      .args([
        "run",
        "python",
        "-m",
        "narrative_mirror.cli_json",
        "--db",
        &db_arg,
        "stdio",
      ])
      .env("PYTHONUNBUFFERED", "1")
      .env("PYTHONIOENCODING", "utf-8")
      .current_dir(&cwd)
      .stdin(Stdio::piped())
      .stdout(Stdio::piped())
      .stderr(Stdio::inherit())
      .spawn()
      .map_err(|e| format!("Failed to spawn backend: {}", e))?;
    let stdin = child.stdin.take();
    let stdout = child.stdout.take().map(BufReader::new);
    Ok(BackendProcess {
      child,
      stdin,
      stdout,
    })
  }

  #[cfg(not(debug_assertions))]
  {
    let app = app.ok_or("AppHandle required for sidecar")?;
    let resource_dir = app
      .path()
      .resource_dir()
      .map_err(|e| format!("resource_dir: {}", e))?;
    let target = env!("TARGET");
    let sidecar_name = format!(
      "backend-{}{}",
      target,
      if cfg!(windows) { ".exe" } else { "" }
    );
    let sidecar_path = resource_dir
      .join("bin")
      .join("backend")
      .join(&sidecar_name);
    if !sidecar_path.exists() {
      return Err(format!(
        "Sidecar not found: {}",
        sidecar_path.display()
      ));
    }
    let mut child = Command::new(&sidecar_path)
      .args(["--db", &db_arg, "stdio"])
      .current_dir(&cwd)
      .stdin(Stdio::piped())
      .stdout(Stdio::piped())
      .stderr(Stdio::inherit())
      .spawn()
      .map_err(|e| format!("Failed to spawn sidecar: {}", e))?;
    let stdin = child.stdin.take();
    let stdout = child.stdout.take().map(BufReader::new);
    Ok(BackendProcess {
      child,
      stdin,
      stdout,
    })
  }
}

#[tauri::command]
fn spawn_backend_build(
  app: tauri::AppHandle,
  talker_id: String,
  config_overrides: Option<String>,
) -> Result<(), String> {
  use std::process::{Command, Stdio};
  let (cwd, _) = get_backend_cwd_and_db(Some(&app));
  #[cfg(debug_assertions)]
  {
    let mut args = vec![
      "run".to_string(),
      "python".to_string(),
      "-m".to_string(),
      "narrative_mirror.cli_json".to_string(),
      "--db".to_string(),
      "data/mirror.db".to_string(),
      "build".to_string(),
      "--talker".to_string(),
      talker_id.clone(),
      "--config".to_string(),
      "config.yml".to_string(),
    ];
    if let Some(ref overrides) = config_overrides {
      if !overrides.is_empty() {
        args.push("--config-overrides".to_string());
        args.push(overrides.clone());
      }
    }
    args.push("--debug".to_string());
    let _child = Command::new("uv")
      .args(&args)
      .env("PYTHONUNBUFFERED", "1")
      .env("PYTHONIOENCODING", "utf-8")
      .current_dir(&cwd)
      .stdin(Stdio::null())
      .stdout(Stdio::inherit())
      .stderr(Stdio::inherit())
      .spawn()
      .map_err(|e| format!("Failed to spawn backend build: {}", e))?;
  }

  #[cfg(not(debug_assertions))]
  {
    let resource_dir = app
      .path()
      .resource_dir()
      .map_err(|e| format!("resource_dir: {}", e))?;
    let target = env!("TARGET");
    let sidecar_name = format!(
      "backend-{}{}",
      target,
      if cfg!(windows) { ".exe" } else { "" }
    );
    let sidecar_path = resource_dir
      .join("bin")
      .join("backend")
      .join(&sidecar_name);
    let mut args: Vec<&str> = vec![
      "--db",
      "data/mirror.db",
      "build",
      "--talker",
      &talker_id,
      "--config",
      "config.yml",
      "--debug",
    ];
    if let Some(ref overrides) = config_overrides {
      if !overrides.is_empty() {
        args = vec![
          "--db",
          "data/mirror.db",
          "build",
          "--talker",
          &talker_id,
          "--config",
          "config.yml",
          "--config-overrides",
          overrides,
          "--debug",
        ];
      }
    }
    let _child = Command::new(&sidecar_path)
      .args(args)
      .current_dir(&cwd)
      .stdin(Stdio::null())
      .stdout(Stdio::inherit())
      .stderr(Stdio::inherit())
      .spawn()
      .map_err(|e| format!("Failed to spawn sidecar build: {}", e))?;
  }
  Ok(())
}

#[tauri::command]
fn log_frontend_error(message: String) {
  eprintln!("[Frontend Error] {}", message);
}

#[tauri::command]
fn get_backend_dir(app: tauri::AppHandle) -> String {
  let (cwd, _) = get_backend_cwd_and_db(Some(&app));
  cwd.to_string_lossy().into_owned()
}

/// Returns (backend_cwd, db_path_for_args). In release, ensures app_data dir exists with config.
fn get_backend_cwd_and_db(app: Option<&tauri::AppHandle>) -> (PathBuf, String) {
  #[cfg(debug_assertions)]
  {
    use std::path::Path;
    let cwd = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());
    for rel in ["../backend", "../../backend"] {
      let p = cwd.join(rel);
      if p.join("pyproject.toml").exists() || p.join("src").join("narrative_mirror").exists() {
        let path = p.canonicalize().unwrap_or(p);
        let db = path.join("data").join("mirror.db");
        return (
          path,
          db.to_str().unwrap_or("data/mirror.db").to_string(),
        );
      }
    }
    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
    let path = manifest
      .parent()
      .and_then(|p| p.parent())
      .map(|p| p.join("backend"))
      .unwrap_or_else(|| manifest.join("../../backend"));
    let db = path.join("data").join("mirror.db");
    (
      path,
      db.to_str().unwrap_or("data/mirror.db").to_string(),
    )
  }

  #[cfg(not(debug_assertions))]
  {
    let app = app.expect("AppHandle required in release");
    let app_data = app
      .path()
      .app_data_dir()
      .expect("app_data_dir");
    let backend_dir = app_data.join("narrarc").join("backend");
    let data_dir = backend_dir.join("data");
    let config_path = backend_dir.join("config.yml");
    let res_dir = app.path().resource_dir().ok();
    let config_example = res_dir.as_ref().and_then(|r| {
      let p = r.join("config.yml.example");
      if p.exists() {
        Some(p)
      } else {
        let p2 = r.join("backend").join("config.yml.example");
        p2.exists().then_some(p2)
      }
    });
    if let Some(ref ex) = config_example {
      if ex.exists() && !config_path.exists() {
        let _ = std::fs::create_dir_all(&backend_dir);
        let _ = std::fs::copy(ex, &config_path);
      }
    }
    let _ = std::fs::create_dir_all(&data_dir);
    let db_path = data_dir.join("mirror.db");
    (
      backend_dir,
      db_path.to_str().unwrap_or("data/mirror.db").to_string(),
    )
  }
}

/// Single request/response: write one JSON line, read one line, return parsed value or error from {"type":"error","message":"..."}.
#[tauri::command]
async fn backend_request(
  state: tauri::State<'_, Arc<Mutex<BackendProcess>>>,
  payload: serde_json::Value,
) -> Result<serde_json::Value, String> {
  let request = serde_json::to_string(&payload).map_err(|e| e.to_string())?;
  let state = state.inner().clone();
  let line = tauri::async_runtime::spawn_blocking(move || {
    let mut guard = state.lock().map_err(|e| e.to_string())?;
    let process = guard.deref_mut();
    let stdin = process
      .stdin
      .as_mut()
      .ok_or("backend process stdin gone")?;
    writeln!(stdin, "{}", request).map_err(|e| e.to_string())?;
    stdin.flush().map_err(|e| e.to_string())?;
    let stdout = process
      .stdout
      .as_mut()
      .ok_or("backend process stdout gone")?;
    let mut line = String::new();
    stdout.read_line(&mut line).map_err(|e| e.to_string())?;
    Ok::<_, String>(line)
  })
  .await
  .map_err(|e| e.to_string())??;
  let value: serde_json::Value =
    serde_json::from_str(line.trim()).map_err(|e| format!("backend invalid JSON: {}", e))?;
  if let Some(msg) = value.get("type").and_then(|t| t.as_str()) {
    if msg == "error" {
      let message = value
        .get("message")
        .and_then(|m| m.as_str())
        .unwrap_or("unknown error");
      return Err(message.to_string());
    }
  }
  Ok(value)
}

/// Stream query: write request then read stdout line-by-line; emit each progress line to frontend
/// in real time (so agent steps appear incrementally), then return the result line.
#[tauri::command]
async fn backend_query_stream(
  app: tauri::AppHandle,
  state: tauri::State<'_, Arc<Mutex<BackendProcess>>>,
  talker: String,
  question: String,
  config_overrides: Option<serde_json::Value>,
) -> Result<serde_json::Value, String> {
  let mut payload = serde_json::json!({
    "cmd": "query",
    "talker": talker,
    "question": question,
    "stream": true,
    "config": "config.yml",
  });
  if let Some(ref overrides) = config_overrides {
    payload["config_overrides"] = overrides.clone();
  }
  let request = serde_json::to_string(&payload).map_err(|e| e.to_string())?;
  let (tx, mut rx) = tokio::sync::mpsc::channel::<String>(64);
  let result_cell = Arc::new(Mutex::new(None::<serde_json::Value>));
  let error_cell = Arc::new(Mutex::new(None::<String>));
  let result_cell_r = result_cell.clone();
  let error_cell_r = error_cell.clone();
  let app_handle = app.clone();

  let recv_handle = tauri::async_runtime::spawn(async move {
    while let Some(line) = rx.recv().await {
      let trimmed = line.trim();
      if trimmed.is_empty() {
        continue;
      }
      if let Ok(v) = serde_json::from_str::<serde_json::Value>(trimmed) {
        match v.get("type").and_then(|t| t.as_str()) {
          Some("progress") => {
            let _ = app_handle.emit("backend://progress", &v);
          }
          Some("result") => {
            if let Ok(mut g) = result_cell_r.lock() {
              *g = Some(v);
            }
            break;
          }
          Some("error") => {
            if let Ok(mut g) = error_cell_r.lock() {
              *g = v
                .get("message")
                .and_then(|m| m.as_str())
                .map(|s| s.to_string());
            }
            break;
          }
          _ => {}
        }
      }
    }
  });

  let tx_block = tx.clone();
  let state = state.inner().clone();
  tauri::async_runtime::spawn_blocking(move || {
    let mut guard = state.lock().map_err(|e| e.to_string())?;
    let process = guard.deref_mut();
    let stdin = process
      .stdin
      .as_mut()
      .ok_or("backend process stdin gone")?;
    writeln!(stdin, "{}", request).map_err(|e| e.to_string())?;
    stdin.flush().map_err(|e| e.to_string())?;
    let stdout = process
      .stdout
      .as_mut()
      .ok_or("backend process stdout gone")?;
    loop {
      let mut line = String::new();
      if stdout.read_line(&mut line).map_err(|e| e.to_string())? == 0 {
        break;
      }
      let trimmed = line.trim();
      let stop = !trimmed.is_empty()
        && serde_json::from_str::<serde_json::Value>(trimmed)
          .map(|v| {
            let t = v.get("type").and_then(|t| t.as_str());
            t == Some("result") || t == Some("error")
          })
          .unwrap_or(false);
      tx_block.blocking_send(line).map_err(|e| e.to_string())?;
      if stop {
        break;
      }
    }
    Ok::<_, String>(())
  })
  .await
  .map_err(|e| e.to_string())??;

  drop(tx);
  let _ = recv_handle.await;
  if let Ok(mut g) = error_cell.lock() {
    if let Some(msg) = g.take() {
      return Err(msg);
    }
  }
  let out = result_cell
    .lock()
    .map_err(|e| e.to_string())?
    .take()
    .ok_or_else(|| "backend stream did not return result".to_string());
  out
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .invoke_handler(tauri::generate_handler![
      get_backend_dir,
      spawn_backend_build,
      log_frontend_error,
      backend_request,
      backend_query_stream,
    ])
    .plugin(tauri_plugin_shell::init())
    .plugin(tauri_plugin_dialog::init())
    .on_window_event(|window, event| {
      if let tauri::WindowEvent::CloseRequested { .. } = event {
        if let Some(state) = window.try_state::<Arc<Mutex<BackendProcess>>>() {
          if let Ok(mut guard) = state.inner().lock() {
            let _ = guard.child.kill();
          }
        }
      }
    })
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      let backend = match spawn_backend_process(Some(app.handle())) {
        Ok(p) => Arc::new(Mutex::new(p)),
        Err(e) => {
          log::error!("Backend spawn failed: {}", e);
          return Err(e.into());
        }
      };
      app.manage(backend);
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
