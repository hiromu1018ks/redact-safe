mod audit_log;
mod document_state;
mod python_worker;

use audit_log::{AuditLogger, AuditRecord};
use document_state::{MaskingDocument, Region};
use python_worker::{PingResponse, PythonWorker, WorkerStatus};
use std::sync::Mutex;
use tauri::State;

struct WorkerState(Mutex<Option<PythonWorker>>);

struct AuditState(Mutex<AuditLogger>);

struct DocumentState(Mutex<Option<MaskingDocument>>);

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

// --- Document State Commands ---

/// Create a new masking document for a source PDF.
#[tauri::command]
fn create_document(
    state: State<DocumentState>,
    source_file: String,
    source_hash: String,
) -> Result<String, String> {
    let doc = MaskingDocument::new(&source_file, &source_hash);
    let doc_id = doc.document_id.clone();
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    *guard = Some(doc);
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
fn confirm_document(state: State<DocumentState>, user: String) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_mut().ok_or("No document loaded")?;
    doc.confirm(&user)
}

/// Rollback document from confirmed to draft.
#[tauri::command]
fn rollback_document(state: State<DocumentState>, user: String) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_mut().ok_or("No document loaded")?;
    doc.rollback(&user)
}

/// Transition document to finalized status.
#[tauri::command]
fn finalize_document(state: State<DocumentState>, user: String) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_mut().ok_or("No document loaded")?;
    doc.finalize(&user)
}

/// Save document to a JSON file.
#[tauri::command]
fn save_document(state: State<DocumentState>, path: String) -> Result<(), String> {
    let guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let doc = guard.as_ref().ok_or("No document loaded")?;
    doc.save_to_file(std::path::Path::new(&path))
}

/// Load document from a JSON file.
#[tauri::command]
fn load_document(state: State<DocumentState>, path: String) -> Result<serde_json::Value, String> {
    let doc = MaskingDocument::load_from_file(std::path::Path::new(&path))?;
    let json = serde_json::to_value(&doc)
        .map_err(|e| format!("Failed to serialize document: {}", e))?;
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    *guard = Some(doc);
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
#[tauri::command]
fn analyze_pdf(
    state: State<WorkerState>,
    pdf_data_base64: String,
    password: Option<String>,
) -> Result<serde_json::Value, String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let worker = guard
        .as_mut()
        .ok_or("Python worker not initialized")?;

    let params = serde_json::json!({
        "pdf_data": pdf_data_base64,
        "password": password.unwrap_or_default(),
    });

    let result = worker.call("analyze_pdf", Some(params))?;
    Ok(result)
}

/// Attempt to decrypt a PDF with a password via Python worker.
#[tauri::command]
fn decrypt_pdf(
    state: State<WorkerState>,
    pdf_data_base64: String,
    password: String,
) -> Result<serde_json::Value, String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let worker = guard
        .as_mut()
        .ok_or("Python worker not initialized")?;

    let params = serde_json::json!({
        "pdf_data": pdf_data_base64,
        "password": password,
    });

    let result = worker.call("decrypt_pdf", Some(params))?;
    Ok(result)
}

// --- OCR Commands ---

/// Run OCR pipeline on a single page via Python worker.
#[tauri::command]
fn run_ocr(
    state: State<WorkerState>,
    pdf_data_base64: String,
    page_num: u32,
    dpi: Option<u32>,
    password: Option<String>,
) -> Result<serde_json::Value, String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let worker = guard
        .as_mut()
        .ok_or("Python worker not initialized")?;

    let params = serde_json::json!({
        "pdf_data": pdf_data_base64,
        "page_num": page_num,
        "dpi": dpi.unwrap_or(300),
        "password": password.unwrap_or_default(),
    });

    let result = worker.call("run_ocr", Some(params))?;
    Ok(result)
}

/// Run layout analysis on a single page via Python worker.
#[tauri::command]
fn run_layout_analysis(
    state: State<WorkerState>,
    pdf_data_base64: String,
    page_num: u32,
    dpi: Option<u32>,
    password: Option<String>,
) -> Result<serde_json::Value, String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let worker = guard
        .as_mut()
        .ok_or("Python worker not initialized")?;

    let params = serde_json::json!({
        "pdf_data": pdf_data_base64,
        "page_num": page_num,
        "dpi": dpi.unwrap_or(300),
        "password": password.unwrap_or_default(),
    });

    let result = worker.call("run_layout_analysis", Some(params))?;
    Ok(result)
}

/// Extract text from a digital PDF page via Python worker (PyMuPDF text layer).
#[tauri::command]
fn extract_text_digital(
    state: State<WorkerState>,
    pdf_data_base64: String,
    page_num: u32,
    password: Option<String>,
) -> Result<serde_json::Value, String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let worker = guard
        .as_mut()
        .ok_or("Python worker not initialized")?;

    let params = serde_json::json!({
        "pdf_data": pdf_data_base64,
        "page_num": page_num,
        "password": password.unwrap_or_default(),
    });

    let result = worker.call("extract_text_digital", Some(params))?;
    Ok(result)
}

/// Unified text extraction: digital path first, OCR fallback via Python worker.
#[tauri::command]
fn run_text_extraction(
    state: State<WorkerState>,
    pdf_data_base64: String,
    page_num: u32,
    dpi: Option<u32>,
    password: Option<String>,
) -> Result<serde_json::Value, String> {
    let mut guard = state.0.lock().map_err(|e| format!("Lock error: {}", e))?;
    let worker = guard
        .as_mut()
        .ok_or("Python worker not initialized")?;

    let params = serde_json::json!({
        "pdf_data": pdf_data_base64,
        "page_num": page_num,
        "dpi": dpi.unwrap_or(300),
        "password": password.unwrap_or_default(),
    });

    let result = worker.call("run_text_extraction", Some(params))?;
    Ok(result)
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
        .invoke_handler(tauri::generate_handler![
            init_worker,
            shutdown_worker,
            worker_ping,
            worker_get_status,
            log_event,
            get_log_dir,
            verify_log_chain,
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
            save_document,
            load_document,
            get_document_summary,
            analyze_pdf,
            decrypt_pdf,
            run_ocr,
            run_layout_analysis,
            extract_text_digital,
            run_text_extraction,
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
