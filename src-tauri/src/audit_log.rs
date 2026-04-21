use chrono::{Local, NaiveDate};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

const APP_DATA_SUBDIR: &str = "RedactSafe";
const LOGS_DIR: &str = "logs";
const LOG_FILE_PREFIX: &str = "audit";
const LOG_FILE_EXT: &str = ".jsonl";
const ROOT_HASH_FILE: &str = "root_hashes.jsonl";
const GENESIS_HASH: &str = "sha256:0000000000000000000000000000000000000000000000000000000000000000";

/// A single audit log record.
#[derive(Debug, Clone, serde::Serialize, Deserialize)]
pub struct AuditRecord {
    pub timestamp: String,
    pub event: String,
    pub user: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub document_id: Option<String>,
    pub prev_hash: String,
    pub hash: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<serde_json::Value>,
}

/// Manages audit log files with hash chain integrity.
pub struct AuditLogger {
    logs_dir: PathBuf,
    last_hash: Mutex<String>,
    daily_record_count: Mutex<u64>,
    current_date: Mutex<NaiveDate>,
}

impl AuditLogger {
    /// Create a new AuditLogger, initializing the log directory and loading the last hash.
    pub fn new() -> Result<Self, String> {
        let logs_dir = get_logs_dir()?;

        // Create logs directory if it doesn't exist
        fs::create_dir_all(&logs_dir)
            .map_err(|e| format!("Failed to create logs directory: {}", e))?;

        // Load last hash from the most recent log file
        let (last_hash, record_count, current_date) = Self::load_last_state(&logs_dir)?;

        Ok(AuditLogger {
            logs_dir,
            last_hash: Mutex::new(last_hash),
            daily_record_count: Mutex::new(record_count),
            current_date: Mutex::new(current_date),
        })
    }

    /// Load the last hash, record count, and date from existing log files.
    fn load_last_state(
        logs_dir: &Path,
    ) -> Result<(String, u64, NaiveDate), String> {
        let today = Local::now().date_naive();
        let today_log_path = get_log_file_path(logs_dir, &today);

        if today_log_path.exists() {
            // Read the last line of today's log file
            let content = fs::read_to_string(&today_log_path)
                .map_err(|e| format!("Failed to read log file: {}", e))?;
            let last_line = content.lines().last().unwrap_or("");

            if !last_line.is_empty() {
                if let Ok(record) = serde_json::from_str::<AuditRecord>(last_line) {
                    let count = content.lines().count() as u64;
                    return Ok((record.hash, count, today));
                }
            }
            return Ok((GENESIS_HASH.to_string(), 0, today));
        }

        // Check if yesterday's log exists - save root hash for yesterday if needed
        let yesterday = today.pred_opt().unwrap_or(today);
        let yesterday_log_path = get_log_file_path(logs_dir, &yesterday);
        if yesterday_log_path.exists() {
            let content = fs::read_to_string(&yesterday_log_path)
                .map_err(|e| format!("Failed to read yesterday's log file: {}", e))?;
            let last_line = content.lines().last().unwrap_or("");

            if !last_line.is_empty() {
                if let Ok(record) = serde_json::from_str::<AuditRecord>(last_line) {
                    // Save yesterday's root hash
                    Self::save_root_hash(logs_dir, &yesterday, &record.hash, content.lines().count() as u64)?;
                    return Ok((record.hash, 0, today));
                }
            }
        }

        // No existing logs - start fresh
        Ok((GENESIS_HASH.to_string(), 0, today))
    }

    /// Log an audit event.
    /// Filters PII text from the data field to prevent personal information
    /// from being stored in audit logs. Only structural metadata (region_id, bbox, type, etc.) is retained.
    pub fn log_event(
        &self,
        event: &str,
        user: &str,
        document_id: Option<&str>,
        data: Option<serde_json::Value>,
    ) -> Result<AuditRecord, String> {
        let now = Local::now();

        // Filter PII text from data field
        let data = data.map(|d| filter_pii_from_data(&d));
        let today = now.date_naive();

        // Check if we need to rotate (new day)
        {
            let mut current_date = self.current_date.lock().map_err(|e| e.to_string())?;
            let mut count = self.daily_record_count.lock().map_err(|e| e.to_string())?;

            if today != *current_date {
                // Day changed - save root hash for previous day
                if *count > 0 {
                    let prev_hash = self.last_hash.lock().map_err(|e| e.to_string())?;
                    Self::save_root_hash(&self.logs_dir, &current_date, &prev_hash, *count)?;
                }
                *current_date = today;
                *count = 0;
            }
        }

        let timestamp = now.to_rfc3339();

        // Get previous hash
        let prev_hash = {
            let h = self.last_hash.lock().map_err(|e| e.to_string())?;
            h.clone()
        };

        // Build record content for hashing (without the hash field)
        let record_content = serde_json::json!({
            "timestamp": timestamp,
            "event": event,
            "user": user,
            "document_id": document_id,
            "prev_hash": prev_hash,
            "data": data,
        });

        // Compute hash: SHA-256(prev_hash + record_content)
        let hash_input = format!("{}{}", prev_hash, record_content);
        let hash = compute_sha256(&hash_input);

        // Build final record
        let mut record_map = serde_json::Map::new();
        if let serde_json::Value::Object(map) = record_content {
            record_map = map;
        }
        record_map.insert("hash".to_string(), serde_json::Value::String(hash.clone()));

        let record = AuditRecord {
            timestamp: record_map["timestamp"].as_str().unwrap_or("").to_string(),
            event: record_map["event"].as_str().unwrap_or("").to_string(),
            user: record_map["user"].as_str().unwrap_or("").to_string(),
            document_id: document_id.map(|s| s.to_string()),
            prev_hash,
            hash,
            data: data.clone(),
        };

        // Write to log file
        let log_path = get_log_file_path(&self.logs_dir, &today);
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(|e| format!("Failed to open log file: {}", e))?;

        let line = serde_json::to_string(&record)
            .map_err(|e| format!("Failed to serialize log record: {}", e))?;
        writeln!(file, "{}", line)
            .map_err(|e| format!("Failed to write log record: {}", e))?;

        // Update state
        {
            let mut h = self.last_hash.lock().map_err(|e| e.to_string())?;
            *h = record.hash.clone();
        }
        {
            let mut count = self.daily_record_count.lock().map_err(|e| e.to_string())?;
            *count += 1;
        }

        Ok(record)
    }

    /// Save the daily root hash to a separate file.
    fn save_root_hash(
        logs_dir: &Path,
        date: &NaiveDate,
        root_hash: &str,
        record_count: u64,
    ) -> Result<(), String> {
        let root_hash_path = logs_dir.join(ROOT_HASH_FILE);

        let entry = serde_json::json!({
            "date": date.to_string(),
            "root_hash": root_hash,
            "record_count": record_count,
        });

        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&root_hash_path)
            .map_err(|e| format!("Failed to open root hash file: {}", e))?;

        let line = serde_json::to_string(&entry)
            .map_err(|e| format!("Failed to serialize root hash entry: {}", e))?;
        writeln!(file, "{}", line)
            .map_err(|e| format!("Failed to write root hash entry: {}", e))?;

        Ok(())
    }

    /// Save root hash for the current day (call on shutdown).
    #[allow(dead_code)]
    pub fn save_current_day_root_hash(&self) -> Result<(), String> {
        let current_date = self.current_date.lock().map_err(|e| e.to_string())?;
        let count = self.daily_record_count.lock().map_err(|e| e.to_string())?;
        let last_hash = self.last_hash.lock().map_err(|e| e.to_string())?;

        if *count > 0 && *last_hash != GENESIS_HASH {
            Self::save_root_hash(&self.logs_dir, &current_date, &last_hash, *count)?;
        }

        Ok(())
    }

    /// Get the logs directory path.
    pub fn logs_dir(&self) -> &Path {
        &self.logs_dir
    }

    /// Verify the integrity of a log file's hash chain.
    pub fn verify_chain(log_path: &Path) -> Result<ChainVerificationResult, String> {
        let content = fs::read_to_string(log_path)
            .map_err(|e| format!("Failed to read log file: {}", e))?;

        let mut prev_hash = GENESIS_HASH.to_string();
        let mut record_count = 0;
        let mut first_invalid_index: Option<usize> = None;

        for (i, line) in content.lines().enumerate() {
            if line.trim().is_empty() {
                continue;
            }

            let record: AuditRecord = serde_json::from_str(line)
                .map_err(|e| format!("Failed to parse record at line {}: {}", i + 1, e))?;

            // Verify prev_hash chain
            if record.prev_hash != prev_hash && first_invalid_index.is_none() {
                first_invalid_index = Some(i);
            }

            // Recompute hash to verify
            let record_content = serde_json::json!({
                "timestamp": record.timestamp,
                "event": record.event,
                "user": record.user,
                "document_id": record.document_id,
                "prev_hash": record.prev_hash,
                "data": record.data,
            });
            let hash_input = format!("{}{}", record.prev_hash, record_content);
            let expected_hash = compute_sha256(&hash_input);

            if record.hash != expected_hash && first_invalid_index.is_none() {
                first_invalid_index = Some(i);
            }

            prev_hash = record.hash;
            record_count += 1;
        }

        Ok(ChainVerificationResult {
            total_records: record_count,
            valid: first_invalid_index.is_none(),
            first_invalid_index,
        })
    }
}

/// Result of chain verification.
#[derive(Debug, serde::Serialize)]
pub struct ChainVerificationResult {
    pub total_records: u64,
    pub valid: bool,
    pub first_invalid_index: Option<usize>,
}

/// Compute SHA-256 hash of a string, prefixed with "sha256:".
fn compute_sha256(input: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(input.as_bytes());
    let result = hasher.finalize();
    format!("sha256:{}", hex::encode(result))
}

/// Get the logs directory path (%APPDATA%/RedactSafe/logs/).
fn get_logs_dir() -> Result<PathBuf, String> {
    let app_data = dirs::data_dir().ok_or("Failed to determine APPDATA directory")?;
    Ok(app_data.join(APP_DATA_SUBDIR).join(LOGS_DIR))
}

/// Get the log file path for a given date.
fn get_log_file_path(logs_dir: &Path, date: &NaiveDate) -> PathBuf {
    logs_dir.join(format!(
        "{}_{}{}",
        LOG_FILE_PREFIX,
        date.format("%Y-%m-%d"),
        LOG_FILE_EXT
    ))
}

/// Parse a date string (YYYY-MM-DD) into a NaiveDate.
pub fn parse_date(date_str: &str) -> Result<NaiveDate, String> {
    NaiveDate::parse_from_str(date_str, "%Y-%m-%d")
        .map_err(|e| format!("Failed to parse date '{}': {}", date_str, e))
}

/// Get the current OS username.
pub fn get_current_user() -> String {
    std::env::var("USERNAME").unwrap_or_else(|_| "unknown".to_string())
}

/// Fields that may contain PII text and should be stripped from audit log data.
const PII_TEXT_FIELDS: &[&str] = &[
    "text",
    "original_text",
    "matched_text",
    "content",
    "value",
    "excerpt",
    "preview",
    "description",
    "detail_text",
    "name_text",
];

/// Filter potential PII text fields from audit log data.
/// Retains structural metadata (region_id, bbox, type, page, etc.) but removes
/// fields that could contain actual personal information text.
fn filter_pii_from_data(data: &serde_json::Value) -> serde_json::Value {
    match data {
        serde_json::Value::Object(map) => {
            let filtered: serde_json::Map<String, serde_json::Value> = map
                .iter()
                .filter(|(key, _)| {
                    let key_lower = key.to_lowercase();
                    !PII_TEXT_FIELDS.iter().any(|f| key_lower == *f)
                })
                .map(|(k, v)| (k.clone(), filter_pii_from_data(v)))
                .collect();
            serde_json::Value::Object(filtered)
        }
        serde_json::Value::Array(arr) => {
            serde_json::Value::Array(arr.iter().map(filter_pii_from_data).collect())
        }
        other => other.clone(),
    }
}
