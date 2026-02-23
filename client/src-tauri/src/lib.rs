use std::io::{BufRead, BufReader, Write};
use std::ops::DerefMut;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use tauri::{Emitter, Manager};

/// Long-lived backend process: stdin/stdout for JSON lines; child kept for kill on exit.
struct BackendProcess {
  child: Child,
  stdin: Option<std::process::ChildStdin>,
  stdout: Option<BufReader<std::process::ChildStdout>>,
}

fn spawn_backend_process() -> Result<BackendProcess, String> {
  let cwd = get_backend_dir_impl();
  let mut child = Command::new("uv")
    .args([
      "run",
      "python",
      "-m",
      "narrative_mirror.cli_json",
      "--db",
      "data/mirror.db",
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

#[tauri::command]
fn spawn_backend_build(talker_id: String) -> Result<(), String> {
  use std::process::{Command, Stdio};
  let cwd = get_backend_dir_impl();
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
    .env("PYTHONIOENCODING", "utf-8")
    .current_dir(&cwd)
    .stdin(Stdio::null())
    .stdout(Stdio::inherit())
    .stderr(Stdio::inherit())
    .spawn()
    .map_err(|e| format!("Failed to spawn backend build: {}", e))?;
  Ok(())
}

#[tauri::command]
fn log_frontend_error(message: String) {
  eprintln!("[Frontend Error] {}", message);
}

#[tauri::command]
fn get_backend_dir() -> String {
  get_backend_dir_impl()
}

fn get_backend_dir_impl() -> String {
  use std::path::Path;
  let cwd = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());
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
  let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
  manifest
    .parent()
    .and_then(|p| p.parent())
    .map(|p| p.join("backend"))
    .unwrap_or_else(|| manifest.join("../../backend"))
    .to_string_lossy()
    .into_owned()
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
) -> Result<serde_json::Value, String> {
  let payload = serde_json::json!({
    "cmd": "query",
    "talker": talker,
    "question": question,
    "stream": true,
    "config": "config.yml",
  });
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
  let backend = match spawn_backend_process() {
    Ok(p) => Arc::new(Mutex::new(p)),
    Err(e) => {
      log::error!("Backend spawn failed: {}", e);
      panic!("Backend spawn failed: {}", e);
    }
  };
  tauri::Builder::default()
    .manage(backend)
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
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
