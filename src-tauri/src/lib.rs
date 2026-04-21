mod audit_log;
mod python_worker;

use audit_log::{AuditLogger, AuditRecord};
use python_worker::{PingResponse, PythonWorker, WorkerStatus};
use std::sync::Mutex;
use tauri::State;

struct WorkerState(Mutex<Option<PythonWorker>>);

struct AuditState(Mutex<AuditLogger>);

#[tauri::command]
fn worker_ping(
    state: State<WorkerState>,
    message: Option<String>,
) -> Result<PingResponse, String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;

    let worker = guard
        .as_mut()
        .ok_or("Python worker not initialized")?;

    let params = serde_json::json!({
        "message": message.unwrap_or_default()
    });

    let result = worker.call("ping", Some(params))?;

    Ok(PingResponse {
        pong: result["pong"].as_bool().unwrap_or(false),
        message: result["message"]
            .as_str()
            .unwrap_or("")
            .to_string(),
    })
}

#[tauri::command]
fn worker_get_status(state: State<WorkerState>) -> WorkerStatus {
    let mut guard = match state.0.lock() {
        Ok(g) => g,
        Err(_) => {
            return WorkerStatus {
                connected: false,
                version: None,
                error: Some("Lock error".to_string()),
            }
        }
    };

    match guard.as_mut() {
        Some(worker) => {
            if !worker.is_alive() {
                WorkerStatus {
                    connected: false,
                    version: None,
                    error: Some("Worker process died".to_string()),
                }
            } else {
                match worker.call("get_version", None) {
                    Ok(result) => WorkerStatus {
                        connected: true,
                        version: result["version"]
                            .as_str()
                            .map(|s| s.to_string()),
                        error: None,
                    },
                    Err(e) => WorkerStatus {
                        connected: false,
                        version: None,
                        error: Some(e),
                    },
                }
            }
        }
        None => WorkerStatus {
            connected: false,
            version: None,
            error: Some("Worker not initialized".to_string()),
        },
    }
}

#[tauri::command]
fn init_worker(app_handle: tauri::AppHandle, state: State<WorkerState>) -> Result<WorkerStatus, String> {
    let worker = PythonWorker::spawn(&app_handle)?;

    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    *guard = Some(worker);

    // Drop the lock before calling get_status
    drop(guard);

    let status = worker_get_status(state);
    Ok(status)
}

#[tauri::command]
fn shutdown_worker(state: State<WorkerState>) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;

    if let Some(worker) = guard.as_mut() {
        worker.kill()?;
    }
    *guard = None;

    Ok(())
}

/// Log an audit event via Tauri command.
#[tauri::command]
fn log_event(
    state: State<AuditState>,
    event: String,
    user: Option<String>,
    document_id: Option<String>,
    data: Option<serde_json::Value>,
) -> Result<AuditRecord, String> {
    let logger = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let user = user.unwrap_or_else(audit_log::get_current_user);
    logger.log_event(&event, &user, document_id.as_deref(), data)
}

/// Get the current audit log directory path.
#[tauri::command]
fn get_log_dir(state: State<AuditState>) -> Result<String, String> {
    let logger = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    Ok(logger.logs_dir().to_string_lossy().to_string())
}

/// Verify the integrity of a specific day's log file.
#[tauri::command]
fn verify_log_chain(
    state: State<AuditState>,
    date: String,
) -> Result<audit_log::ChainVerificationResult, String> {
    let logger = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let parsed_date = audit_log::parse_date(&date)?;
    let log_path = logger.logs_dir().join(format!(
        "audit_{}.jsonl",
        parsed_date.format("%Y-%m-%d"),
    ));
    AuditLogger::verify_chain(&log_path)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(WorkerState(Mutex::new(None)))
        .manage(AuditState(Mutex::new(
            AuditLogger::new().expect("Failed to initialize audit logger"),
        )))
        .invoke_handler(tauri::generate_handler![
            init_worker,
            shutdown_worker,
            worker_ping,
            worker_get_status,
            log_event,
            get_log_dir,
            verify_log_chain,
        ])
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
        .on_window_event(|_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Save root hash on window close (graceful shutdown)
                // Access the audit state from the app handle
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
