use serde::{Deserialize, Serialize};
use std::io::{BufRead, Write};
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use tauri::{AppHandle, Manager};

/// JSON-RPC request sent to Python worker
#[derive(Serialize, Deserialize, Debug)]
struct JsonRpcRequest {
    jsonrpc: String,
    id: u64,
    method: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    params: Option<serde_json::Value>,
}

/// JSON-RPC response from Python worker
#[derive(Serialize, Deserialize, Debug)]
struct JsonRpcResponse {
    jsonrpc: String,
    id: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<JsonRpcError>,
}

#[derive(Serialize, Deserialize, Debug)]
struct JsonRpcError {
    code: i64,
    message: String,
}

/// Manages the Python worker subprocess
pub struct PythonWorker {
    child: Child,
    next_id: u64,
}

impl PythonWorker {
    /// Spawn a new Python worker process
    pub fn spawn(app_handle: &AppHandle) -> Result<Self, String> {
        let python_path = Self::find_python().ok_or("Python not found")?;
        let worker_path = Self::worker_script_path(app_handle)?;

        log::info!("Starting Python worker: {} {}", python_path.display(), worker_path.display());

        let child = Command::new(&python_path)
            .arg(&worker_path)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .creation_flags(0x08000000) // CREATE_NO_WINDOW on Windows
            .spawn()
            .map_err(|e| format!("Failed to spawn Python worker: {}", e))?;

        Ok(Self {
            child,
            next_id: 1,
        })
    }

    /// Find Python executable
    fn find_python() -> Option<PathBuf> {
        // Try common Python commands
        let candidates = ["python3", "python", "py"];
        for cmd in candidates {
            if let Ok(output) = Command::new(cmd).arg("--version").output() {
                if output.status.success() {
                    return Some(PathBuf::from(cmd));
                }
            }
        }
        None
    }

    /// Get the path to the worker.py script
    fn worker_script_path(app_handle: &AppHandle) -> Result<PathBuf, String> {
        let resource_path = app_handle
            .path()
            .resource_dir()
            .map_err(|e| format!("Failed to get resource dir: {}", e))?;

        // In dev mode, worker.py is at <project_root>/python-worker/worker.py
        // In production, it will be bundled with the app
        let dev_path = resource_path
            .parent()
            .and_then(|p| p.parent())
            .map(|p| p.join("python-worker").join("worker.py"));

        if let Some(ref path) = dev_path {
            if path.exists() {
                return Ok(path.to_path_buf());
            }
        }

        // Production path: resource_dir/python-worker/worker.py
        let prod_path = resource_path.join("python-worker").join("worker.py");
        if prod_path.exists() {
            return Ok(prod_path);
        }

        Err(format!(
            "worker.py not found. Searched: {:?}",
            dev_path
        ))
    }

    /// Send a JSON-RPC request and wait for the response
    pub fn call(
        &mut self,
        method: &str,
        params: Option<serde_json::Value>,
    ) -> Result<serde_json::Value, String> {
        let id = self.next_id;
        self.next_id += 1;

        let request = JsonRpcRequest {
            jsonrpc: "2.0".to_string(),
            id,
            method: method.to_string(),
            params,
        };

        let request_json = serde_json::to_string(&request)
            .map_err(|e| format!("Failed to serialize request: {}", e))?;

        // Write request to stdin
        let stdin = self
            .child
            .stdin
            .as_mut()
            .ok_or("Worker stdin not available")?;
        writeln!(stdin, "{}", request_json).map_err(|e| format!("Failed to write to stdin: {}", e))?;
        stdin
            .flush()
            .map_err(|e| format!("Failed to flush stdin: {}", e))?;

        // Read response from stdout
        let stdout = self.child.stdout.as_mut().ok_or("Worker stdout not available")?;
        let mut reader = std::io::BufReader::new(stdout);
        let mut response_line = String::new();
        reader
            .read_line(&mut response_line)
            .map_err(|e| format!("Failed to read from stdout: {}", e))?;

        let response: JsonRpcResponse = serde_json::from_str(response_line.trim())
            .map_err(|e| format!("Failed to parse response: {} (raw: {})", e, response_line))?;

        if let Some(error) = response.error {
            return Err(format!("Worker error [{}]: {}", error.code, error.message));
        }

        response.result.ok_or("No result in response".to_string())
    }

    /// Check if the worker process is still running
    pub fn is_alive(&mut self) -> bool {
        match self.child.try_wait() {
            Ok(Some(_)) => false,
            Ok(None) => true,
            Err(_) => false,
        }
    }

    /// Kill the worker process
    pub fn kill(&mut self) -> Result<(), String> {
        self.child
            .kill()
            .map_err(|e| format!("Failed to kill worker: {}", e))
    }
}

// Response types for Tauri commands
#[derive(Serialize, Deserialize)]
pub struct PingResponse {
    pub pong: bool,
    pub message: String,
}

#[derive(Serialize, Deserialize)]
pub struct WorkerStatus {
    pub connected: bool,
    pub version: Option<String>,
    pub error: Option<String>,
}
