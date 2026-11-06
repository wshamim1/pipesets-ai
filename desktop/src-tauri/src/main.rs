// Pipesets desktop (v0): a native window around the existing React UI, with the FastAPI
// backend started as a child process (from backend/.venv, or its PyInstaller build).
//
// Flow: pick a free localhost port → start uvicorn on it → open the window on
// loading.html, which polls /health and then loads the app. The port reaches the UI as
// window.__PIPESETS_API_BASE__ (read by frontend/src/types.ts). Quitting stops the backend.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, File};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

struct Backend(Mutex<Option<Child>>);

/// The repo's backend/ folder. v0 runs from a checkout; PIPESETS_BACKEND_DIR overrides it.
fn backend_dir() -> PathBuf {
    match std::env::var("PIPESETS_BACKEND_DIR") {
        Ok(dir) => PathBuf::from(dir),
        Err(_) => PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../backend"),
    }
}

fn free_port() -> std::io::Result<u16> {
    Ok(TcpListener::bind("127.0.0.1:0")?.local_addr()?.port())
}

// backend/desktop_main.py serves on 127.0.0.1, keeps its data in PIPESETS_DATA_DIR,
// copies the repo's dev data on first launch, and exits if this app's process goes away
// (a crash or force-quit skips RunEvent::Exit). It runs from backend/.venv, or — when
// PIPESETS_BACKEND_BIN is set (`npm run dev:packaged`) — as the PyInstaller build.
fn start_backend(port: u16, data_dir: &PathBuf, log_path: &PathBuf) -> std::io::Result<Child> {
    let dir = backend_dir();
    let log = File::create(log_path)?;
    let mut cmd = match std::env::var("PIPESETS_BACKEND_BIN") {
        Ok(bin) => Command::new(bin),
        Err(_) => {
            let mut c = Command::new(dir.join(".venv/bin/python"));
            c.arg("desktop_main.py");
            c
        }
    };
    cmd.args(["--port", &port.to_string()])
        .arg("--import-from")
        .arg(&dir)
        .env("PIPESETS_DATA_DIR", data_dir)
        .current_dir(&dir)
        .stdout(Stdio::from(log.try_clone()?))
        .stderr(Stdio::from(log))
        .spawn()
}

fn stop_backend(app: &tauri::AppHandle) {
    if let Some(mut child) = app.state::<Backend>().0.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn main() {
    let app = tauri::Builder::default()
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let port = free_port()?;
            let log_dir = app.path().app_log_dir()?;
            fs::create_dir_all(&log_dir)?;
            let log_path = log_dir.join("backend.log");
            let data_dir = app.path().app_data_dir()?;
            fs::create_dir_all(&data_dir)?;

            let api_base = match start_backend(port, &data_dir, &log_path) {
                Ok(child) => {
                    *app.state::<Backend>().0.lock().unwrap() = Some(child);
                    format!("http://127.0.0.1:{port}")
                }
                Err(e) => {
                    eprintln!("Could not start the backend from {:?}: {e}", backend_dir());
                    String::new() // loading.html shows the error
                }
            };

            let init = format!(
                "window.__PIPESETS_API_BASE__ = {:?}; window.__PIPESETS_BACKEND_LOG__ = {:?};",
                api_base,
                log_path.display().to_string()
            );
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("loading.html".into()))
                .title("Pipesets")
                .inner_size(1440.0, 900.0)
                .min_inner_size(1024.0, 680.0)
                .initialization_script(&init)
                // Tauri's native drop handler swallows HTML5 drag-and-drop, which the
                // sidebar → canvas node drag relies on; we don't use Tauri's file-drop events
                .disable_drag_drop_handler()
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the Pipesets app");

    app.run(|app, event| {
        if let RunEvent::Exit = event {
            stop_backend(app);
        }
    });
}
