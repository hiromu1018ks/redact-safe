mod audit_log;
mod document_state;
mod python_worker;

use audit_log::{AuditLogger, AuditRecord};
use document_state::{DocumentStatus, MaskingDocument, OperatorInfo, Region};
use python_worker::{PingResponse, PythonWorker, WorkerStatus};
use std::sync::Mutex;
use tauri::{Emitter, Manager, State};

struct WorkerState(Mutex<Option<PythonWorker>>);

/// Ensure the worker process is alive, restarting it if necessary.
/// Returns a locked MutexGuard holding the mutable PythonWorker.
fn ensure_worker_alive<'a>(
    state: &'a State<'a, WorkerState>,
    app_handle: &'a tauri::AppHandle,
) -> Result<std::sync::MutexGuard<'a, Option<PythonWorker>>, String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;

    if let Some(ref mut worker) = *guard {
        if !worker.is_alive() {
            log::info!("Python worker process died, auto-restarting...");
            // Drop the old worker (its Drop impl will clean up)
            *guard = None;
        }
    }

    if guard.is_none() {
        log::info!("Spawning new Python worker (auto-restart)");
        let new_worker = PythonWorker::spawn(app_handle)?;
        *guard = Some(new_worker);
    }

    Ok(guard)
}

/// Call a Python worker method with auto-restart on dead process.
fn worker_call(
    state: &State<WorkerState>,
    app_handle: &tauri::AppHandle,
    method: &str,
    params: Option<serde_json::Value>,
) -> Result<serde_json::Value, String> {
    worker_call_with_timeout(state, app_handle, method, params, std::time::Duration::from_secs(300))
}

/// Call a Python worker method with auto-restart and custom timeout.
fn worker_call_with_timeout(
    state: &State<WorkerState>,
    app_handle: &tauri::AppHandle,
    method: &str,
    params: Option<serde_json::Value>,
    timeout: std::time::Duration,
) -> Result<serde_json::Value, String> {
    let mut guard = ensure_worker_alive(state, app_handle)?;
    let worker = guard
        .as_mut()
        .ok_or("Python worker not initialized")?;
    worker.call_with_timeout(method, params, timeout)
}

struct AuditState(Mutex<AuditLogger>);

struct DocumentState(Mutex<Option<MaskingDocument>>);

/// Tracks the auto-save file path for the current document.
struct AutoSavePathState(Mutex<Option<String>>);

#[tauri::command]
fn worker_ping(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    message: Option<String>,
) -> Result<PingResponse, String> {
    let params = serde_json::json!({
        "message": message.unwrap_or_default()
    });

    let result = worker_call(&state, &app_handle, "ping", Some(params))?;

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

/// Cancel the current worker operation by killing the process.
/// The pending invoke on the frontend will receive an error.
#[tauri::command]
fn cancel_worker(app_handle: tauri::AppHandle, state: State<WorkerState>) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;

    if let Some(worker) = guard.as_mut() {
        worker.kill()?;
    }
    *guard = None;

    // Notify frontend that the operation was cancelled
    let _ = app_handle.emit("worker-cancelled", ());

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

// --- Document State Commands ---

/// Get the current OS username.
#[tauri::command]
fn get_os_username() -> String {
    audit_log::get_current_user()
}

/// Create a new masking document for a source PDF.
#[tauri::command]
fn create_document(
    state: State<DocumentState>,
    auto_save_state: State<AutoSavePathState>,
    source_file: String,
    source_hash: String,
    os_username: Option<String>,
    display_name: Option<String>,
) -> Result<String, String> {
    let operator = os_username.map(|os_uname| {
        OperatorInfo::new(&os_uname, display_name.as_deref().unwrap_or(&os_uname))
    });
    let doc = MaskingDocument::new(&source_file, &source_hash, operator);
    let doc_id = doc.document_id.clone();

    // Set auto-save path based on document ID
    let auto_save_path = document_state::get_auto_save_path(&doc_id)?;

    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    *guard = Some(doc);

    // Set the auto-save path
    let mut path_guard = auto_save_state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    *path_guard = Some(auto_save_path.to_string_lossy().to_string());

    Ok(doc_id)
}

/// Get the current document as JSON.
#[tauri::command]
fn get_document(state: State<DocumentState>) -> Result<Option<serde_json::Value>, String> {
    let guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    match guard.as_ref() {
        Some(doc) => {
            let json = serde_json::to_value(doc)
                .map_err(|e| format!("Failed to serialize document: {}", e))?;
            Ok(Some(json))
        }
        None => Ok(None),
    }
}

/// Get the status of the current document.
#[tauri::command]
fn get_document_status(state: State<DocumentState>) -> Result<Option<String>, String> {
    let guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    Ok(guard.as_ref().map(|doc| doc.status.as_str().to_string()))
}

/// Add a page to the current document.
#[tauri::command]
fn add_page(
    state: State<DocumentState>,
    page: u32,
    width_pt: f64,
    height_pt: f64,
    rotation_deg: u16,
    extraction_path: String,
) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_mut().ok_or("No document loaded")?;
    if !doc.status.is_editable() {
        return Err(format!("Cannot modify document in '{}' status", doc.status.as_str()));
    }
    doc.add_page(page, width_pt, height_pt, rotation_deg, &extraction_path);
    Ok(())
}

/// Add a masking region to a page.
#[tauri::command]
fn add_region(
    state: State<DocumentState>,
    page_num: u32,
    region: Region,
) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_mut().ok_or("No document loaded")?;
    if !doc.status.is_editable() {
        return Err(format!("Cannot modify document in '{}' status", doc.status.as_str()));
    }
    doc.add_region(page_num, region)
}

/// Toggle a region's enabled state.
#[tauri::command]
fn toggle_region(
    state: State<DocumentState>,
    page_num: u32,
    region_id: String,
) -> Result<bool, String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_mut().ok_or("No document loaded")?;
    if !doc.status.is_editable() {
        return Err(format!("Cannot modify document in '{}' status", doc.status.as_str()));
    }
    doc.toggle_region(page_num, &region_id)
}

/// Remove a masking region.
#[tauri::command]
fn remove_region(
    state: State<DocumentState>,
    page_num: u32,
    region_id: String,
) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_mut().ok_or("No document loaded")?;
    if !doc.status.is_editable() {
        return Err(format!("Cannot modify document in '{}' status", doc.status.as_str()));
    }
    doc.remove_region(page_num, &region_id)
}

/// Update a region's bounding box.
#[tauri::command]
fn update_region_bbox(
    state: State<DocumentState>,
    page_num: u32,
    region_id: String,
    bbox: [f64; 4],
) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_mut().ok_or("No document loaded")?;
    if !doc.status.is_editable() {
        return Err(format!("Cannot modify document in '{}' status", doc.status.as_str()));
    }
    doc.update_region_bbox(page_num, &region_id, bbox)
}

/// Set all regions on a page (or all pages) to enabled/disabled.
#[tauri::command]
fn set_all_regions_enabled(
    state: State<DocumentState>,
    page_num: Option<u32>,
    enabled: bool,
) -> Result<u32, String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_mut().ok_or("No document loaded")?;
    if !doc.status.is_editable() {
        return Err(format!("Cannot modify document in '{}' status", doc.status.as_str()));
    }
    doc.set_all_regions_enabled(page_num, enabled)
}

/// Transition document to confirmed status.
#[tauri::command]
fn confirm_document(
    _app_handle: tauri::AppHandle,
    state: State<DocumentState>,
    audit: State<AuditState>,
    os_username: String,
    display_name: String,
) -> Result<(), String> {
    let operator = OperatorInfo::new(&os_username, &display_name);
    let doc_id;
    {
        let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
        let doc = guard.as_mut().ok_or("No document loaded")?;
        doc_id = doc.document_id.clone();
        doc.confirm(operator.clone())?;
    }
    // Log audit event outside the lock
    let logger = audit.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    logger.log_event(
        "document_confirmed",
        &os_username,
        Some(&doc_id),
        Some(serde_json::json!({
            "action": "confirmed",
            "os_username": os_username,
            "display_name": display_name,
        })),
    )?;
    Ok(())
}

/// Rollback document from confirmed to draft.
#[tauri::command]
fn rollback_document(
    _app_handle: tauri::AppHandle,
    state: State<DocumentState>,
    audit: State<AuditState>,
    os_username: String,
    display_name: String,
) -> Result<(), String> {
    let operator = OperatorInfo::new(&os_username, &display_name);
    let doc_id;
    {
        let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
        let doc = guard.as_mut().ok_or("No document loaded")?;
        doc_id = doc.document_id.clone();
        doc.rollback(operator.clone())?;
    }
    let logger = audit.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    logger.log_event(
        "document_rolled_back",
        &os_username,
        Some(&doc_id),
        Some(serde_json::json!({
            "action": "rolled_back",
            "os_username": os_username,
            "display_name": display_name,
        })),
    )?;
    Ok(())
}

/// Check if the finalizer's OS username matches the document creator or confirmer.
/// Returns true if a warning should be shown (match detected).
#[tauri::command]
fn check_finalizer_creator_match(
    state: State<DocumentState>,
    os_username: String,
) -> Result<bool, String> {
    let guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_ref().ok_or("No document loaded")?;

    // Warn if finalizer matches the creator (editor)
    if doc.is_same_creator(&os_username) {
        return Ok(true);
    }

    // Also warn if finalizer matches the confirmer (should be different person)
    if let Some(ref confirmer) = doc.confirmed_by {
        if confirmer.os_username == os_username {
            return Ok(true);
        }
    }

    Ok(false)
}

/// Transition document to finalized status.
#[tauri::command]
fn finalize_document(
    _app_handle: tauri::AppHandle,
    state: State<DocumentState>,
    audit: State<AuditState>,
    os_username: String,
    display_name: String,
) -> Result<(), String> {
    let operator = OperatorInfo::new(&os_username, &display_name);
    let doc_id;
    {
        let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
        let doc = guard.as_mut().ok_or("No document loaded")?;
        doc_id = doc.document_id.clone();
        doc.finalize(operator.clone())?;
    }
    let logger = audit.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    logger.log_event(
        "document_finalized",
        &os_username,
        Some(&doc_id),
        Some(serde_json::json!({
            "action": "finalized",
            "os_username": os_username,
            "display_name": display_name,
        })),
    )?;
    Ok(())
}

/// Set the output file path for the finalized safe PDF.
#[tauri::command]
fn set_output_file(state: State<DocumentState>, path: String) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_mut().ok_or("No document loaded")?;
    doc.set_output_file(&path);
    Ok(())
}

/// Get document info with source_file hidden in finalized state.
#[tauri::command]
fn get_document_safe(state: State<DocumentState>) -> Result<Option<serde_json::Value>, String> {
    let guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    match guard.as_ref() {
        Some(doc) => {
            let mut json = serde_json::to_value(doc)
                .map_err(|e| format!("Failed to serialize document: {}", e))?;
            // In finalized state, hide source_file
            if doc.status == DocumentStatus::Finalized {
                if let Some(obj) = json.as_object_mut() {
                    obj.remove("source_file");
                }
            }
            Ok(Some(json))
        }
        None => Ok(None),
    }
}

/// Get document summary. In finalized state, hides source_file and shows output_file.
#[tauri::command]
fn get_document_summary_safe(state: State<DocumentState>) -> Result<Option<serde_json::Value>, String> {
    let guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    match guard.as_ref() {
        Some(doc) => {
            let mut summary = serde_json::json!({
                "document_id": doc.document_id,
                "status": doc.status.as_str(),
                "revision": doc.revision,
                "confirmed_by": doc.confirmed_by,
                "finalized_by": doc.finalized_by,
                "created_by": doc.created_by,
                "page_count": doc.pages.len(),
                "total_regions": doc.total_regions_count(),
                "enabled_regions": doc.enabled_regions_count(),
            });
            if doc.status == DocumentStatus::Draft || doc.status == DocumentStatus::Confirmed {
                summary["source_file"] = serde_json::json!(doc.source_file);
            }
            if doc.status == DocumentStatus::Finalized {
                summary["output_file"] = serde_json::json!(doc.output_file);
            }
            Ok(Some(summary))
        }
        None => Ok(None),
    }
}

/// Save document to a JSON file.
#[tauri::command]
fn save_document(state: State<DocumentState>, path: String) -> Result<(), String> {
    let guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_ref().ok_or("No document loaded")?;
    doc.save_to_file(std::path::Path::new(&path))
}

/// Auto-save the current document to its tracked auto-save path.
/// Creates a backup before saving, uses atomic write for crash safety.
#[tauri::command]
fn auto_save_document(
    state: State<DocumentState>,
    auto_save_state: State<AutoSavePathState>,
) -> Result<bool, String> {
    let save_path = {
        let path_guard = auto_save_state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
        path_guard.clone()
    };

    let save_path = match save_path {
        Some(p) if !p.is_empty() => p,
        _ => return Ok(false), // No auto-save path set yet
    };

    let path = std::path::Path::new(&save_path);

    // Create backup before saving (maintains 3 generations)
    if path.exists() {
        let guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
        if let Some(doc) = guard.as_ref() {
            MaskingDocument::create_backup(path)?;
            doc.save_to_file(path)?;
            return Ok(true);
        }
    }

    // First auto-save: just write the file (no backup needed yet)
    let guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    if let Some(doc) = guard.as_ref() {
        doc.save_to_file(path)?;
        return Ok(true);
    }

    Ok(false)
}

/// Set the auto-save file path for the current document.
#[tauri::command]
fn set_auto_save_path(
    auto_save_state: State<AutoSavePathState>,
    path: String,
) -> Result<(), String> {
    let mut guard = auto_save_state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    *guard = if path.is_empty() { None } else { Some(path) };
    Ok(())
}

/// Get the current auto-save file path.
#[tauri::command]
fn get_auto_save_path(auto_save_state: State<AutoSavePathState>) -> Result<Option<String>, String> {
    let guard = auto_save_state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    Ok(guard.clone())
}

/// Generate an auto-save file path based on the document ID.
#[tauri::command]
fn generate_auto_save_path(state: State<DocumentState>) -> Result<String, String> {
    let guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_ref().ok_or("No document loaded")?;
    let path = document_state::get_auto_save_path(&doc.document_id)?;
    Ok(path.to_string_lossy().to_string())
}

/// Check if a document file can be recovered (is corrupt but has backup).
#[tauri::command]
fn can_recover_document(path: String) -> Result<bool, String> {
    Ok(MaskingDocument::can_recover(std::path::Path::new(&path)))
}

/// List available backups for a document file.
#[tauri::command]
fn list_backups(path: String) -> Result<Vec<document_state::BackupInfo>, String> {
    Ok(MaskingDocument::list_backups(std::path::Path::new(&path)))
}

/// Load document from a JSON file with crash recovery support.
/// If the file is corrupt, attempts to recover from the latest backup.
#[tauri::command]
fn load_document(state: State<DocumentState>, auto_save_state: State<AutoSavePathState>, path: String) -> Result<serde_json::Value, String> {
    let doc = MaskingDocument::load_from_file(std::path::Path::new(&path))?;
    let json = serde_json::to_value(&doc)
        .map_err(|e| format!("Failed to serialize document: {}", e))?;
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    *guard = Some(doc);
    // Set auto-save path to the loaded file's location
    let mut path_guard = auto_save_state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    *path_guard = Some(path);
    Ok(json)
}

/// Get summary info about the current document.
#[tauri::command]
fn get_document_summary(state: State<DocumentState>) -> Result<Option<serde_json::Value>, String> {
    let guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    match guard.as_ref() {
        Some(doc) => {
            let summary = serde_json::json!({
                "document_id": doc.document_id,
                "source_file": doc.source_file,
                "status": doc.status.as_str(),
                "revision": doc.revision,
                "confirmed_by": doc.confirmed_by,
                "finalized_by": doc.finalized_by,
                "created_by": doc.created_by,
                "page_count": doc.pages.len(),
                "total_regions": doc.total_regions_count(),
                "enabled_regions": doc.enabled_regions_count(),
            });
            Ok(Some(summary))
        }
        None => Ok(None),
    }
}

// --- PDF Analysis Commands ---

/// Analyze a PDF file via Python worker: detect encryption, signatures, page info.
/// Accepts either a file path (preferred) or base64-encoded data.
#[tauri::command]
fn analyze_pdf(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    file_path: Option<String>,
    pdf_data_base64: Option<String>,
    password: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = if let Some(path) = file_path {
        serde_json::json!({
            "pdf_path": path,
            "password": password.unwrap_or_default(),
        })
    } else {
        serde_json::json!({
            "pdf_data": pdf_data_base64.unwrap_or_default(),
            "password": password.unwrap_or_default(),
        })
    };

    worker_call(&state, &app_handle, "analyze_pdf", Some(params))
}

/// Attempt to decrypt a PDF with a password via Python worker.
#[tauri::command]
fn decrypt_pdf(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    file_path: Option<String>,
    pdf_data_base64: Option<String>,
    password: String,
) -> Result<serde_json::Value, String> {
    let mut params = serde_json::json!({
        "password": password,
    });
    if let Some(path) = file_path {
        params["pdf_path"] = serde_json::json!(path);
    } else {
        params["pdf_data"] = serde_json::json!(pdf_data_base64.unwrap_or_default());
    }

    worker_call(&state, &app_handle, "decrypt_pdf", Some(params))
}

// --- OCR Commands ---

/// Run OCR pipeline on a single page via Python worker.
#[tauri::command]
fn run_ocr(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    file_path: Option<String>,
    pdf_data_base64: Option<String>,
    page_num: u32,
    dpi: Option<u32>,
    password: Option<String>,
) -> Result<serde_json::Value, String> {
    let mut params = serde_json::json!({
        "page_num": page_num,
        "dpi": dpi.unwrap_or(300),
        "password": password.unwrap_or_default(),
    });
    if let Some(path) = file_path {
        params["pdf_path"] = serde_json::json!(path);
    } else {
        params["pdf_data"] = serde_json::json!(pdf_data_base64.unwrap_or_default());
    }

    worker_call(&state, &app_handle, "run_ocr", Some(params))
}

/// Run layout analysis on a single page via Python worker.
#[tauri::command]
fn run_layout_analysis(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    pdf_data_base64: String,
    page_num: u32,
    dpi: Option<u32>,
    password: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({
        "pdf_data": pdf_data_base64,
        "page_num": page_num,
        "dpi": dpi.unwrap_or(300),
        "password": password.unwrap_or_default(),
    });

    worker_call(&state, &app_handle, "run_layout_analysis", Some(params))
}

/// Extract text from a digital PDF page via Python worker (PyMuPDF text layer).
#[tauri::command]
fn extract_text_digital(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    pdf_data_base64: String,
    page_num: u32,
    password: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({
        "pdf_data": pdf_data_base64,
        "page_num": page_num,
        "password": password.unwrap_or_default(),
    });

    worker_call(&state, &app_handle, "extract_text_digital", Some(params))
}

/// Unified text extraction: digital path first, OCR fallback via Python worker.
#[tauri::command]
fn run_text_extraction(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    file_path: Option<String>,
    pdf_data_base64: Option<String>,
    page_num: u32,
    dpi: Option<u32>,
    password: Option<String>,
) -> Result<serde_json::Value, String> {
    let mut params = serde_json::json!({
        "page_num": page_num,
        "dpi": dpi.unwrap_or(300),
        "password": password.unwrap_or_default(),
    });
    if let Some(path) = file_path {
        params["pdf_path"] = serde_json::json!(path);
    } else {
        params["pdf_data"] = serde_json::json!(pdf_data_base64.unwrap_or_default());
    }

    worker_call(&state, &app_handle, "run_text_extraction", Some(params))
}

// --- BBox Normalization Commands ---

/// Normalize OCR bounding boxes: convert to PDF points, merge lines, correct rotation.
#[allow(clippy::too_many_arguments)]
#[tauri::command]
fn normalize_bboxes(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    pdf_data_base64: String,
    page_num: u32,
    regions: serde_json::Value,
    dpi: Option<f64>,
    rotation_deg: Option<u16>,
    password: Option<String>,
    merge_lines: Option<bool>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({
        "pdf_data": pdf_data_base64,
        "page_num": page_num,
        "regions": regions,
        "dpi": dpi.unwrap_or(300.0),
        "rotation_deg": rotation_deg.unwrap_or(0),
        "password": password.unwrap_or_default(),
        "merge_lines": merge_lines.unwrap_or(true),
    });

    worker_call(&state, &app_handle, "normalize_bboxes", Some(params))
}

// --- PII Detection Commands ---

/// Detect PII in text regions using regex-based rules + MeCab name detection via Python worker.
#[tauri::command]
fn detect_pii(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    text_regions: serde_json::Value,
    enabled_types: Option<Vec<String>>,
    rules_path: Option<String>,
    enable_name_detection: Option<bool>,
    custom_rules_dir: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({
        "text_regions": text_regions,
        "enabled_types": enabled_types,
        "rules_path": rules_path,
        "enable_name_detection": enable_name_detection.unwrap_or(true),
        "custom_rules_dir": custom_rules_dir,
    });

    worker_call(&state, &app_handle, "detect_pii", Some(params))
}

/// Detect PII from a PDF page (combines text extraction + detection) via Python worker.
#[allow(clippy::too_many_arguments)]
#[tauri::command]
fn detect_pii_pdf(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    file_path: Option<String>,
    pdf_data_base64: Option<String>,
    page_num: u32,
    enabled_types: Option<Vec<String>>,
    rules_path: Option<String>,
    password: Option<String>,
    enable_name_detection: Option<bool>,
    custom_rules_dir: Option<String>,
) -> Result<serde_json::Value, String> {
    let mut params = serde_json::json!({
        "page_num": page_num,
        "enabled_types": enabled_types,
        "rules_path": rules_path,
        "password": password.unwrap_or_default(),
        "enable_name_detection": enable_name_detection.unwrap_or(true),
        "custom_rules_dir": custom_rules_dir,
    });
    if let Some(path) = file_path {
        params["pdf_path"] = serde_json::json!(path);
    } else {
        params["pdf_data"] = serde_json::json!(pdf_data_base64.unwrap_or_default());
    }

    worker_call(&state, &app_handle, "detect_pii_pdf", Some(params))
}

/// Load detection rules from YAML file via Python worker.
#[tauri::command]
fn load_detection_rules(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    rules_path: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({
        "rules_path": rules_path,
    });

    worker_call(&state, &app_handle, "load_detection_rules", Some(params))
}

/// Load custom rules from the custom rules directory via Python worker.
#[tauri::command]
fn load_custom_rules(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    rules_dir: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({
        "rules_dir": rules_dir,
    });

    worker_call(&state, &app_handle, "load_custom_rules", Some(params))
}

/// Load and merge bundled + custom rules via Python worker.
#[tauri::command]
fn load_all_rules(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    rules_path: Option<String>,
    custom_rules_dir: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({
        "rules_path": rules_path,
        "custom_rules_dir": custom_rules_dir,
    });

    worker_call(&state, &app_handle, "load_all_rules", Some(params))
}

/// Validate detection rules against the schema via Python worker.
#[tauri::command]
fn validate_rules(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    rules_content: String,
    format: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({
        "rules_content": rules_content,
        "format": format,
    });

    worker_call(&state, &app_handle, "validate_rules", Some(params))
}

/// Check a regex pattern for catastrophic backtracking risks via Python worker.
#[tauri::command]
fn check_regex_safety(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    pattern: String,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({
        "pattern": pattern,
    });

    worker_call(&state, &app_handle, "check_regex_safety", Some(params))
}

/// Detect person names in text regions using MeCab morphological analysis via Python worker.
#[tauri::command]
fn detect_names(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    text_regions: serde_json::Value,
    enabled_types: Option<Vec<String>>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({
        "text_regions": text_regions,
        "enabled_types": enabled_types,
    });

    worker_call(&state, &app_handle, "detect_names", Some(params))
}

/// Finalize masking: rasterize PDF pages, burn black rectangles, regenerate PDF via Python worker.
/// Returns the finalized PDF as base64-encoded data.
/// The Python worker now also sanitizes hidden data and verifies the output.
#[tauri::command]
fn finalize_masking_pdf(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    doc_state: State<DocumentState>,
    pdf_path: String,
    dpi: Option<u32>,
    margin_pt: Option<f64>,
    password: Option<String>,
) -> Result<serde_json::Value, String> {
    // Collect pages and their enabled regions from document state
    let pages_info;
    {
        let guard = doc_state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
        let doc = guard.as_ref().ok_or("No document loaded")?;

        pages_info = doc.pages.iter().map(|page| {
            let regions: Vec<serde_json::Value> = page.regions.iter().map(|r| {
                serde_json::json!({
                    "id": r.id,
                    "bbox": r.bbox,
                    "region_type": r.region_type.as_str(),
                    "confidence": r.confidence,
                    "enabled": r.enabled,
                    "source": r.source.as_str(),
                })
            }).collect();

            serde_json::json!({
                "page_num": page.page - 1,  // Convert to 0-indexed
                "width_pt": page.width_pt,
                "height_pt": page.height_pt,
                "rotation_deg": page.rotation_deg,
                "regions": regions,
            })
        }).collect::<Vec<_>>();
    }

    // Call Python worker to perform the finalization (includes sanitization + verification)
    let params = serde_json::json!({
        "pdf_path": pdf_path,
        "pages": pages_info,
        "dpi": dpi.unwrap_or(300),
        "margin_pt": margin_pt.unwrap_or(3.0),
        "password": password.unwrap_or_default(),
    });

    worker_call_with_timeout(&state, &app_handle, "finalize_masking", Some(params), std::time::Duration::from_secs(600))
}

/// Verify that a finalized PDF is safe (no text, no hidden data) via Python worker.
#[tauri::command]
fn verify_safe_pdf(
    app_handle: tauri::AppHandle,
    state: State<WorkerState>,
    pdf_data_base64: String,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({
        "pdf_data": pdf_data_base64,
    });

    worker_call(&state, &app_handle, "verify_safe_pdf", Some(params))
}

/// Generate the output filename for a finalized safe PDF.
/// Format: <original_filename>_redacted_<YYYYMMDD_HHMMSS>_r<revision>.pdf
#[tauri::command]
fn generate_output_filename(
    state: State<DocumentState>,
    output_dir: String,
) -> Result<String, String> {
    let guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_ref().ok_or("No document loaded")?;

    // Extract base filename without extension
    let source = &doc.source_file;
    let base_name = std::path::Path::new(source)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("document");

    // Generate timestamp
    let now = chrono::Local::now();
    let timestamp = now.format("%Y%m%d_%H%M%S");

    // Build output filename with revision
    let filename = format!("{}_redacted_{}_r{}.pdf", base_name, timestamp, doc.revision);
    let output_path = std::path::Path::new(&output_dir).join(&filename);

    // If file already exists, auto-increment
    if output_path.exists() {
        for i in 2..=100 {
            let alt_filename = format!("{}_redacted_{}_r{}.pdf", base_name, timestamp, i);
            let alt_path = std::path::Path::new(&output_dir).join(&alt_filename);
            if !alt_path.exists() {
                return Ok(alt_path.to_string_lossy().to_string());
            }
        }
    }

    Ok(output_path.to_string_lossy().to_string())
}

/// Read a file and return its contents as a base64-encoded string.
/// Limited to 100MB to prevent excessive memory usage.
#[tauri::command]
fn read_file_as_base64(path: String) -> Result<String, String> {
    use std::fs;
    use base64::{Engine as _, engine::general_purpose::STANDARD as BASE64_STANDARD};

    const MAX_SIZE: u64 = 100 * 1024 * 1024; // 100MB
    let metadata = fs::metadata(&path).map_err(|e| format!("Failed to read metadata '{}': {}", path, e))?;
    if metadata.len() > MAX_SIZE {
        return Err(format!("File too large ({} bytes, max {} bytes)", metadata.len(), MAX_SIZE));
    }

    let bytes = fs::read(&path).map_err(|e| format!("Failed to read file '{}': {}", path, e))?;
    Ok(BASE64_STANDARD.encode(&bytes))
}

/// Save base64-encoded data to a file.
/// Limited to 100MB of decoded data.
#[tauri::command]
fn save_base64_to_file(path: String, data: String) -> Result<(), String> {
    use std::fs;
    use base64::{Engine as _, engine::general_purpose::STANDARD as BASE64_STANDARD};

    const MAX_SIZE: usize = 100 * 1024 * 1024; // 100MB
    let bytes = BASE64_STANDARD
        .decode(&data)
        .map_err(|e| format!("Failed to decode base64 data: {}", e))?;
    if bytes.len() > MAX_SIZE {
        return Err(format!("Data too large ({} bytes, max {} bytes)", bytes.len(), MAX_SIZE));
    }
    fs::write(&path, &bytes)
        .map_err(|e| format!("Failed to write file '{}': {}", path, e))?;
    Ok(())
}

/// Copy a file from one path to another.
#[tauri::command]
fn copy_file(from: String, to: String) -> Result<(), String> {
    std::fs::copy(&from, &to)
        .map_err(|e| format!("Failed to copy '{}': {}", from, e))?;
    Ok(())
}

/// Remove a file (used for temp file cleanup).
#[tauri::command]
fn remove_file(path: String) -> Result<(), String> {
    std::fs::remove_file(&path)
        .map_err(|e| format!("Failed to remove '{}': {}", path, e))?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(WorkerState(Mutex::new(None)))
        .manage(AuditState(Mutex::new(
            AuditLogger::new().expect("Failed to initialize audit logger"),
        )))
        .manage(DocumentState(Mutex::new(None)))
        .manage(AutoSavePathState(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            init_worker,
            shutdown_worker,
            cancel_worker,
            worker_ping,
            worker_get_status,
            log_event,
            get_log_dir,
            verify_log_chain,
            get_os_username,
            check_finalizer_creator_match,
            create_document,
            get_document,
            get_document_status,
            add_page,
            add_region,
            toggle_region,
            remove_region,
            update_region_bbox,
            set_all_regions_enabled,
            confirm_document,
            rollback_document,
            finalize_document,
            set_output_file,
            get_document_safe,
            get_document_summary_safe,
            save_document,
            load_document,
            auto_save_document,
            set_auto_save_path,
            get_auto_save_path,
            generate_auto_save_path,
            can_recover_document,
            list_backups,
            get_document_summary,
            analyze_pdf,
            decrypt_pdf,
            run_ocr,
            run_layout_analysis,
            extract_text_digital,
            run_text_extraction,
            normalize_bboxes,
            detect_pii,
            detect_pii_pdf,
            load_detection_rules,
            load_custom_rules,
            load_all_rules,
            validate_rules,
            check_regex_safety,
            detect_names,
            finalize_masking_pdf,
            verify_safe_pdf,
            generate_output_filename,
            read_file_as_base64,
            save_base64_to_file,
            copy_file,
            remove_file,
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Debug)
                        .build(),
                )?;
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Save root hash on window close (graceful shutdown)
                let app_handle = window.app_handle();
                if let Some(audit_state) = app_handle.try_state::<AuditState>() {
                    if let Ok(logger) = audit_state.0.lock() {
                        if let Err(e) = logger.save_current_day_root_hash() {
                            eprintln!("Failed to save root hash on shutdown: {}", e);
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
