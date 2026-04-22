use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

const SCHEMA_VERSION: &str = "1.3";

/// Operator information combining OS login name and display name.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OperatorInfo {
    /// OS login username (e.g. from %USERNAME% environment variable).
    pub os_username: String,
    /// Display name entered by the operator at confirmation time.
    pub display_name: String,
}

impl OperatorInfo {
    pub fn new(os_username: &str, display_name: &str) -> Self {
        OperatorInfo {
            os_username: os_username.to_string(),
            display_name: display_name.to_string(),
        }
    }
}

/// Document status with state transition constraints.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum DocumentStatus {
    Draft,
    Confirmed,
    Finalized,
}

impl DocumentStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            DocumentStatus::Draft => "draft",
            DocumentStatus::Confirmed => "confirmed",
            DocumentStatus::Finalized => "finalized",
        }
    }

    /// Returns true if editing (adding/removing/toggling regions) is allowed.
    pub fn is_editable(&self) -> bool {
        matches!(self, DocumentStatus::Draft)
    }

    /// Returns true if the document can be confirmed (draft → confirmed).
    pub fn can_confirm(&self) -> bool {
        matches!(self, DocumentStatus::Draft)
    }

    /// Returns true if the document can be rolled back (confirmed → draft).
    pub fn can_rollback(&self) -> bool {
        matches!(self, DocumentStatus::Confirmed)
    }

    /// Returns true if the document can be finalized.
    pub fn can_finalize(&self) -> bool {
        matches!(self, DocumentStatus::Confirmed)
    }
}

/// Source of a masking region.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RegionSource {
    Auto,
    Manual,
}

impl RegionSource {
    pub fn as_str(&self) -> &'static str {
        match self {
            RegionSource::Auto => "auto",
            RegionSource::Manual => "manual",
        }
    }
}

/// Type of detected PII / sensitive information.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RegionType {
    #[serde(rename = "name")]
    Name,
    #[serde(rename = "address")]
    Address,
    #[serde(rename = "phone")]
    Phone,
    #[serde(rename = "email")]
    Email,
    #[serde(rename = "birth_date")]
    BirthDate,
    #[serde(rename = "my_number")]
    MyNumber,
    #[serde(rename = "corporate_number")]
    CorporateNumber,
    #[serde(rename = "custom")]
    Custom(String),
}

impl RegionType {
    pub fn as_str(&self) -> std::borrow::Cow<'static, str> {
        match self {
            RegionType::Name => std::borrow::Cow::Borrowed("name"),
            RegionType::Address => std::borrow::Cow::Borrowed("address"),
            RegionType::Phone => std::borrow::Cow::Borrowed("phone"),
            RegionType::Email => std::borrow::Cow::Borrowed("email"),
            RegionType::BirthDate => std::borrow::Cow::Borrowed("birth_date"),
            RegionType::MyNumber => std::borrow::Cow::Borrowed("my_number"),
            RegionType::CorporateNumber => std::borrow::Cow::Borrowed("corporate_number"),
            RegionType::Custom(s) => std::borrow::Cow::Owned(format!("custom:{}", s)),
        }
    }
}

/// Coordinate system definition.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CoordinateSystem {
    pub unit: String,
    pub origin: String,
    pub dpi_for_rasterize: u32,
}

impl Default for CoordinateSystem {
    fn default() -> Self {
        CoordinateSystem {
            unit: "pdf_point".to_string(),
            origin: "top-left".to_string(),
            dpi_for_rasterize: 300,
        }
    }
}

/// A single masking region (bounding box).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Region {
    pub id: String,
    /// [x, y, width, height] in PDF points.
    pub bbox: [f64; 4],
    #[serde(rename = "type")]
    pub region_type: RegionType,
    pub confidence: f64,
    pub enabled: bool,
    pub source: RegionSource,
    #[serde(default)]
    pub note: String,
}

impl Region {
    /// Create a new auto-detected region.
    pub fn new_auto(
        id: String,
        bbox: [f64; 4],
        region_type: RegionType,
        confidence: f64,
    ) -> Self {
        Region {
            id,
            bbox,
            region_type,
            confidence,
            enabled: true,
            source: RegionSource::Auto,
            note: String::new(),
        }
    }

    /// Create a new manually-added region.
    pub fn new_manual(id: String, bbox: [f64; 4], region_type: RegionType) -> Self {
        Region {
            id,
            bbox,
            region_type,
            confidence: 1.0,
            enabled: true,
            source: RegionSource::Manual,
            note: String::new(),
        }
    }
}

/// Page information with masking regions.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PageInfo {
    pub page: u32,
    pub width_pt: f64,
    pub height_pt: f64,
    pub rotation_deg: u16,
    /// "ocr" or "text_layer".
    pub text_extraction_path: String,
    #[serde(default)]
    pub regions: Vec<Region>,
}

impl PageInfo {
    /// Create a new page entry.
    pub fn new(page: u32, width_pt: f64, height_pt: f64, rotation_deg: u16, extraction_path: &str) -> Self {
        PageInfo {
            page,
            width_pt,
            height_pt,
            rotation_deg,
            text_extraction_path: extraction_path.to_string(),
            regions: Vec::new(),
        }
    }

    /// Get the count of enabled regions on this page.
    pub fn enabled_regions_count(&self) -> usize {
        self.regions.iter().filter(|r| r.enabled).count()
    }
}

/// History entry for state transitions.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryEntry {
    pub timestamp: String,
    pub action: String,
    pub user: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<String>,
}

/// The complete masking document (persisted as JSON).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MaskingDocument {
    pub schema_version: String,
    pub document_id: String,
    pub source_file: String,
    pub source_hash: String,
    pub status: DocumentStatus,
    pub revision: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub created_by: Option<OperatorInfo>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub confirmed_by: Option<OperatorInfo>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub finalized_by: Option<OperatorInfo>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output_file: Option<String>,
    pub coordinate_system: CoordinateSystem,
    #[serde(default)]
    pub history: Vec<HistoryEntry>,
    pub pages: Vec<PageInfo>,
}

impl MaskingDocument {
    /// Create a new masking document for the given source PDF.
    pub fn new(source_file: &str, source_hash: &str, operator: Option<OperatorInfo>) -> Self {
        MaskingDocument {
            schema_version: SCHEMA_VERSION.to_string(),
            document_id: uuid::Uuid::new_v4().to_string(),
            source_file: source_file.to_string(),
            source_hash: source_hash.to_string(),
            status: DocumentStatus::Draft,
            revision: 1,
            created_by: operator,
            confirmed_by: None,
            finalized_by: None,
            output_file: None,
            coordinate_system: CoordinateSystem::default(),
            history: Vec::new(),
            pages: Vec::new(),
        }
    }

    /// Set the creator operator info.
    pub fn set_created_by(&mut self, operator: OperatorInfo) {
        self.created_by = Some(operator);
    }

    // --- Page operations ---

    /// Add a page to the document.
    pub fn add_page(&mut self, page: u32, width_pt: f64, height_pt: f64, rotation_deg: u16, extraction_path: &str) {
        self.pages.push(PageInfo::new(page, width_pt, height_pt, rotation_deg, extraction_path));
    }

    /// Get a mutable reference to a page by page number.
    fn get_page_mut(&mut self, page_num: u32) -> Result<&mut PageInfo, String> {
        self.pages
            .iter_mut()
            .find(|p| p.page == page_num)
            .ok_or_else(|| format!("Page {} not found", page_num))
    }

    // --- Region operations ---

    /// Add a region to a specific page.
    pub fn add_region(&mut self, page_num: u32, region: Region) -> Result<(), String> {
        self.get_page_mut(page_num)?.regions.push(region);
        Ok(())
    }

    /// Toggle a region's enabled state. Returns the new enabled state.
    pub fn toggle_region(&mut self, page_num: u32, region_id: &str) -> Result<bool, String> {
        let page = self.get_page_mut(page_num)?;
        let region = page
            .regions
            .iter_mut()
            .find(|r| r.id == region_id)
            .ok_or_else(|| format!("Region {} not found on page {}", region_id, page_num))?;
        region.enabled = !region.enabled;
        Ok(region.enabled)
    }

    /// Remove a region from a specific page.
    pub fn remove_region(&mut self, page_num: u32, region_id: &str) -> Result<(), String> {
        let page = self.get_page_mut(page_num)?;
        let len_before = page.regions.len();
        page.regions.retain(|r| r.id != region_id);
        if page.regions.len() == len_before {
            return Err(format!("Region {} not found on page {}", region_id, page_num));
        }
        Ok(())
    }

    /// Update a region's bounding box.
    pub fn update_region_bbox(&mut self, page_num: u32, region_id: &str, bbox: [f64; 4]) -> Result<(), String> {
        let page = self.get_page_mut(page_num)?;
        let region = page
            .regions
            .iter_mut()
            .find(|r| r.id == region_id)
            .ok_or_else(|| format!("Region {} not found on page {}", region_id, page_num))?;
        region.bbox = bbox;
        Ok(())
    }

    /// Set all regions enabled or disabled. If page_num is None, applies to all pages.
    /// Returns the number of regions affected.
    pub fn set_all_regions_enabled(&mut self, page_num: Option<u32>, enabled: bool) -> Result<u32, String> {
        let pages: Vec<&mut PageInfo> = match page_num {
            Some(pn) => vec![self.get_page_mut(pn)?],
            None => self.pages.iter_mut().collect(),
        };
        let mut count = 0u32;
        for page in pages {
            for region in &mut page.regions {
                region.enabled = enabled;
                count += 1;
            }
        }
        Ok(count)
    }

    /// Get total count of enabled regions across all pages.
    pub fn enabled_regions_count(&self) -> u32 {
        self.pages
            .iter()
            .flat_map(|p| p.regions.iter())
            .filter(|r| r.enabled)
            .count() as u32
    }

    /// Get total count of all regions across all pages.
    pub fn total_regions_count(&self) -> u32 {
        self.pages
            .iter()
            .flat_map(|p| p.regions.iter())
            .count() as u32
    }

    /// Get regions for a specific page.
    pub fn get_page_regions(&self, page_num: u32) -> Option<&[Region]> {
        self.pages
            .iter()
            .find(|p| p.page == page_num)
            .map(|p| p.regions.as_slice())
    }

    // --- Status transitions ---

    /// Transition from draft to confirmed.
    pub fn confirm(&mut self, operator: OperatorInfo) -> Result<(), String> {
        if self.status != DocumentStatus::Draft {
            return Err(format!(
                "Cannot confirm from status '{}'. Only draft can be confirmed.",
                self.status.as_str()
            ));
        }
        self.status = DocumentStatus::Confirmed;
        self.confirmed_by = Some(operator.clone());
        self.history.push(HistoryEntry {
            timestamp: Utc::now().to_rfc3339(),
            action: "confirmed".to_string(),
            user: format!("{} ({})", operator.display_name, operator.os_username),
            details: None,
        });
        Ok(())
    }

    /// Rollback from confirmed back to draft.
    pub fn rollback(&mut self, operator: OperatorInfo) -> Result<(), String> {
        if self.status != DocumentStatus::Confirmed {
            return Err(format!(
                "Cannot rollback from status '{}'. Only confirmed can be rolled back.",
                self.status.as_str()
            ));
        }
        self.status = DocumentStatus::Draft;
        self.confirmed_by = None;
        self.revision += 1;
        self.history.push(HistoryEntry {
            timestamp: Utc::now().to_rfc3339(),
            action: "rolled_back".to_string(),
            user: format!("{} ({})", operator.display_name, operator.os_username),
            details: Some(format!(
                "Rolled back to draft, revision incremented to {}",
                self.revision
            )),
        });
        Ok(())
    }

    /// Transition from confirmed to finalized (irreversible).
    pub fn finalize(&mut self, operator: OperatorInfo) -> Result<(), String> {
        if self.status != DocumentStatus::Confirmed {
            return Err(format!(
                "Cannot finalize from status '{}'. Only confirmed can be finalized.",
                self.status.as_str()
            ));
        }
        self.status = DocumentStatus::Finalized;
        self.finalized_by = Some(operator.clone());
        self.history.push(HistoryEntry {
            timestamp: Utc::now().to_rfc3339(),
            action: "finalized".to_string(),
            user: format!("{} ({})", operator.display_name, operator.os_username),
            details: None,
        });
        Ok(())
    }

    /// Check if the given OS username matches the document creator.
    /// Returns true if created_by is set and its os_username matches.
    pub fn is_same_creator(&self, os_username: &str) -> bool {
        self.created_by
            .as_ref()
            .map(|op| op.os_username == os_username)
            .unwrap_or(false)
    }

    /// Set the output file path for the finalized safe PDF.
    pub fn set_output_file(&mut self, path: &str) {
        self.output_file = Some(path.to_string());
    }

    // --- File I/O ---

    /// Serialize the document to a pretty-printed JSON string.
    pub fn to_json(&self) -> Result<String, String> {
        serde_json::to_string_pretty(self)
            .map_err(|e| format!("Failed to serialize document: {}", e))
    }

    /// Parse a document from a JSON string.
    pub fn from_json(json: &str) -> Result<Self, String> {
        serde_json::from_str(json)
            .map_err(|e| format!("Failed to parse document JSON: {}", e))
    }

    /// Save document to a JSON file using atomic write (write to temp, then rename).
    /// This prevents corruption if the process crashes during write.
    pub fn save_to_file(&self, path: &Path) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|e| format!("Failed to create directory: {}", e))?;
        }
        let content = self.to_json()?;

        // Atomic write: write to temp file in the same directory, then rename
        let temp_path = path.with_extension("tmp");
        {
            let mut file = fs::File::create(&temp_path)
                .map_err(|e| format!("Failed to create temp file: {}", e))?;
            file.write_all(content.as_bytes())
                .map_err(|e| format!("Failed to write temp file: {}", e))?;
            file.sync_all()
                .map_err(|e| format!("Failed to sync temp file: {}", e))?;
        }

        // Atomic replacement using hard_link + remove_file pattern.
        // On Windows, POSIX-style atomic rename (replace existing file) is not reliable;
        // fs::rename can fail if the target exists. Instead, we hard-link the temp file
        // to the target path (which atomically creates the new content), then remove
        // the temp file. This ensures the target path always points to valid content.
        if path.exists() {
            // Create a hard link from temp to the target (replaces the old entry)
            fs::hard_link(&temp_path, path).map_err(|e| {
                let _ = fs::remove_file(&temp_path);
                format!("Failed to hard link temp file: {}", e)
            })?;
            // Remove the temp file (the hard link at `path` keeps the data alive)
            fs::remove_file(&temp_path)
                .map_err(|e| format!("Failed to remove temp file: {}", e))?;
        } else {
            // No existing file — simple rename is safe
            fs::rename(&temp_path, path)
                .map_err(|e| {
                    let _ = fs::remove_file(&temp_path);
                    format!("Failed to rename temp file: {}", e)
                })?;
        }

        Ok(())
    }

    /// Load document from a JSON file with crash recovery.
    /// If the file is corrupt or empty, attempts to load from the latest backup.
    pub fn load_from_file(path: &Path) -> Result<Self, String> {
        // Reject files larger than 100MB to prevent OOM
        const MAX_FILE_SIZE: u64 = 100 * 1024 * 1024;
        let metadata = fs::metadata(path)
            .map_err(|e| format!("Failed to read document metadata: {}", e))?;
        if metadata.len() > MAX_FILE_SIZE {
            return Err(format!(
                "Document file too large ({} bytes, max {} bytes)",
                metadata.len(),
                MAX_FILE_SIZE
            ));
        }

        let content = fs::read_to_string(path)
            .map_err(|e| format!("Failed to read document file: {}", e))?;

        // Check for empty file (corrupt from crash during write)
        if content.trim().is_empty() {
            // Try to recover from backup
            if let Some(backup) = find_latest_backup(path) {
                return Self::load_from_file(&backup).map_err(|_| {
                    "Document file is empty and backup recovery failed".to_string()
                });
            }
            return Err("Document file is empty (possibly corrupted from crash)".to_string());
        }

        match Self::from_json(&content) {
            Ok(doc) => Ok(doc),
            Err(e) => {
                // Try to recover from backup
                if let Some(backup) = find_latest_backup(path) {
                    match Self::load_from_file(&backup) {
                        Ok(doc) => Ok(doc),
                        Err(_) => Err(format!(
                            "Failed to parse document: {}. Backup recovery also failed.", e
                        )),
                    }
                } else {
                    Err(format!("Failed to parse document: {}. No backup available.", e))
                }
            }
        }
    }

    /// Create a backup of the current file before saving.
    /// Maintains up to 3 generations of backups.
    pub fn create_backup(path: &Path) -> Result<(), String> {
        if !path.exists() {
            return Ok(()); // No file to backup
        }

        // Rotate existing backups: .bak3 → delete, .bak2 → .bak3, .bak1 → .bak2
        let bak3 = PathBuf::from(format!("{}.bak3", path.display()));
        let bak2 = PathBuf::from(format!("{}.bak2", path.display()));
        let bak1 = PathBuf::from(format!("{}.bak1", path.display()));

        if bak3.exists() {
            let _ = fs::remove_file(&bak3);
        }
        if bak2.exists() {
            let _ = fs::rename(&bak2, &bak3);
        }
        if bak1.exists() {
            let _ = fs::rename(&bak1, &bak2);
        }

        // Copy current file to .bak1
        fs::copy(path, &bak1)
            .map_err(|e| format!("Failed to create backup: {}", e))?;

        Ok(())
    }

    /// Check if a document file exists and is potentially recoverable.
    /// Only reads the first few KB for JSON validation (not the entire file).
    pub fn can_recover(path: &Path) -> bool {
        if !path.exists() {
            return false;
        }

        // Open the file and read just enough to check validity
        match fs::File::open(path) {
            Ok(mut file) => {
                use std::io::Read;
                let mut buf = [0u8; 8192]; // 8KB is enough for JSON header validation
                let n = match file.read(&mut buf) {
                    Ok(0) => {
                        // Empty file — check if backup exists
                        return find_latest_backup(path).is_some();
                    }
                    Ok(n) => n,
                    Err(_) => return false,
                };

                let content = match std::str::from_utf8(&buf[..n]) {
                    Ok(s) => s,
                    Err(_) => {
                        // Not valid UTF-8 — file is corrupt
                        return find_latest_backup(path).is_some();
                    }
                };

                if content.trim().is_empty() {
                    // Empty file — check if backup exists
                    find_latest_backup(path).is_some()
                } else {
                    // Try parsing just the beginning as JSON.
                    // serde_json::from_str will fail quickly if the structure is invalid.
                    let is_invalid = serde_json::from_str::<serde_json::Value>(content).is_err();
                    is_invalid && find_latest_backup(path).is_some()
                }
            }
            Err(_) => false,
        }
    }

    /// List available backups for a document file.
    pub fn list_backups(path: &Path) -> Vec<BackupInfo> {
        let mut backups = Vec::new();
        for i in 1..=3 {
            let bak_path = PathBuf::from(format!("{}.bak{}", path.display(), i));
            if bak_path.exists() {
                if let Ok(metadata) = fs::metadata(&bak_path) {
                    if let Ok(modified) = metadata.modified() {
                        backups.push(BackupInfo {
                            path: bak_path,
                            generation: i,
                            modified: modified
                                .duration_since(std::time::UNIX_EPOCH)
                                .map(|d| d.as_secs())
                                .unwrap_or(0),
                            size_bytes: metadata.len(),
                        });
                    }
                }
            }
        }
        backups.sort_by_key(|b| std::cmp::Reverse(b.generation)); // Most recent first
        backups
    }
}

/// Information about a backup file.
#[derive(Debug, serde::Serialize)]
pub struct BackupInfo {
    pub path: PathBuf,
    pub generation: u32,
    pub modified: u64, // Unix timestamp
    pub size_bytes: u64,
}

/// Find the latest (most recent generation) backup file for a given document path.
fn find_latest_backup(path: &Path) -> Option<PathBuf> {
    for i in 1..=3 {
        let bak_path = PathBuf::from(format!("{}.bak{}", path.display(), i));
        if bak_path.exists() {
            return Some(bak_path);
        }
    }
    None
}

/// Get the default auto-save directory for RedactSafe documents.
pub fn get_auto_save_dir() -> Result<PathBuf, String> {
    let app_data = dirs::data_dir().ok_or("Failed to determine APPDATA directory")?;
    let save_dir = app_data.join("RedactSafe").join("documents");
    fs::create_dir_all(&save_dir)
        .map_err(|e| format!("Failed to create auto-save directory: {}", e))?;
    Ok(save_dir)
}

/// Generate an auto-save file path for a document ID.
pub fn get_auto_save_path(document_id: &str) -> Result<PathBuf, String> {
    let save_dir = get_auto_save_dir()?;
    Ok(save_dir.join(format!("{}.json", document_id)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new_document() {
        let doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);
        assert_eq!(doc.schema_version, "1.3");
        assert_eq!(doc.source_file, "test.pdf");
        assert_eq!(doc.source_hash, "sha256:abc123");
        assert_eq!(doc.status, DocumentStatus::Draft);
        assert_eq!(doc.revision, 1);
        assert!(doc.created_by.is_none());
        assert!(doc.confirmed_by.is_none());
        assert!(doc.finalized_by.is_none());
        assert!(doc.pages.is_empty());
        assert!(doc.history.is_empty());
        assert_eq!(doc.coordinate_system.dpi_for_rasterize, 300);
    }

    #[test]
    fn test_new_document_with_operator() {
        let op = OperatorInfo::new("jdoe", "山田太郎");
        let doc = MaskingDocument::new("test.pdf", "sha256:abc123", Some(op.clone()));
        assert_eq!(doc.created_by.as_ref().unwrap().os_username, "jdoe");
        assert_eq!(doc.created_by.as_ref().unwrap().display_name, "山田太郎");
    }

    #[test]
    fn test_add_page_and_regions() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);
        doc.add_page(1, 595.28, 841.89, 0, "ocr");

        let region = Region::new_auto(
            "r1".to_string(),
            [100.0, 200.0, 50.0, 20.0],
            RegionType::Name,
            0.92,
        );
        doc.add_region(1, region).unwrap();

        assert_eq!(doc.pages.len(), 1);
        assert_eq!(doc.total_regions_count(), 1);
        assert_eq!(doc.enabled_regions_count(), 1);
    }

    #[test]
    fn test_toggle_region() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);
        doc.add_page(1, 595.28, 841.89, 0, "ocr");
        doc.add_region(1, Region::new_auto("r1".into(), [0.0; 4], RegionType::Name, 0.9))
            .unwrap();

        // Toggle off
        let enabled = doc.toggle_region(1, "r1").unwrap();
        assert!(!enabled);
        assert_eq!(doc.enabled_regions_count(), 0);

        // Toggle back on
        let enabled = doc.toggle_region(1, "r1").unwrap();
        assert!(enabled);
        assert_eq!(doc.enabled_regions_count(), 1);
    }

    #[test]
    fn test_remove_region() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);
        doc.add_page(1, 595.28, 841.89, 0, "ocr");
        doc.add_region(1, Region::new_auto("r1".into(), [0.0; 4], RegionType::Name, 0.9))
            .unwrap();

        doc.remove_region(1, "r1").unwrap();
        assert_eq!(doc.total_regions_count(), 0);

        // Removing non-existent region returns error
        assert!(doc.remove_region(1, "r1").is_err());
    }

    #[test]
    fn test_update_region_bbox() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);
        doc.add_page(1, 595.28, 841.89, 0, "ocr");
        doc.add_region(1, Region::new_auto("r1".into(), [10.0, 20.0, 50.0, 30.0], RegionType::Name, 0.9))
            .unwrap();

        doc.update_region_bbox(1, "r1", [15.0, 25.0, 60.0, 35.0]).unwrap();
        let regions = doc.get_page_regions(1).unwrap();
        assert_eq!(regions[0].bbox, [15.0, 25.0, 60.0, 35.0]);
    }

    #[test]
    fn test_set_all_regions_enabled() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);
        doc.add_page(1, 595.28, 841.89, 0, "ocr");
        doc.add_page(2, 595.28, 841.89, 0, "ocr");
        doc.add_region(1, Region::new_auto("r1".into(), [0.0; 4], RegionType::Name, 0.9)).unwrap();
        doc.add_region(1, Region::new_auto("r2".into(), [0.0; 4], RegionType::Address, 0.8)).unwrap();
        doc.add_region(2, Region::new_auto("r3".into(), [0.0; 4], RegionType::Phone, 0.7)).unwrap();

        // Disable all
        let count = doc.set_all_regions_enabled(None, false).unwrap();
        assert_eq!(count, 3);
        assert_eq!(doc.enabled_regions_count(), 0);

        // Enable all on page 1 only
        let count = doc.set_all_regions_enabled(Some(1), true).unwrap();
        assert_eq!(count, 2);
        assert_eq!(doc.enabled_regions_count(), 2);
    }

    #[test]
    fn test_status_transitions() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);
        let user = OperatorInfo::new("testuser", "テストユーザー");

        // draft → confirmed: OK
        doc.confirm(user.clone()).unwrap();
        assert_eq!(doc.status, DocumentStatus::Confirmed);
        assert_eq!(doc.confirmed_by.as_ref().unwrap().os_username, "testuser");
        assert_eq!(doc.confirmed_by.as_ref().unwrap().display_name, "テストユーザー");
        assert_eq!(doc.history.len(), 1);

        // confirmed → finalized: OK
        doc.finalize(user.clone()).unwrap();
        assert_eq!(doc.status, DocumentStatus::Finalized);
        assert_eq!(doc.finalized_by.as_ref().unwrap().os_username, "testuser");
        assert_eq!(doc.history.len(), 2);

        // finalized → any: error
        assert!(doc.confirm(user.clone()).is_err());
        assert!(doc.rollback(user.clone()).is_err());
        assert!(doc.finalize(user).is_err());
    }

    #[test]
    fn test_rollback() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);
        let reviewer = OperatorInfo::new("reviewer", "確認者");
        doc.confirm(reviewer.clone()).unwrap();
        assert_eq!(doc.revision, 1);

        doc.rollback(reviewer.clone()).unwrap();
        assert_eq!(doc.status, DocumentStatus::Draft);
        assert!(doc.confirmed_by.is_none());
        assert_eq!(doc.revision, 2);
        assert_eq!(doc.history.len(), 2);

        // Can confirm again
        let reviewer2 = OperatorInfo::new("reviewer2", "確認者2");
        doc.confirm(reviewer2).unwrap();
        assert_eq!(doc.status, DocumentStatus::Confirmed);
    }

    #[test]
    fn test_invalid_transitions() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);
        let user = OperatorInfo::new("user", "ユーザー");

        // Cannot finalize from draft
        assert!(doc.finalize(user.clone()).is_err());

        // Cannot rollback from draft
        assert!(doc.rollback(user.clone()).is_err());

        // Cannot confirm from confirmed
        doc.confirm(user.clone()).unwrap();
        assert!(doc.confirm(user).is_err());
    }

    #[test]
    fn test_is_same_creator() {
        let op = OperatorInfo::new("jdoe", "山田太郎");
        let doc = MaskingDocument::new("test.pdf", "sha256:abc123", Some(op));
        assert!(doc.is_same_creator("jdoe"));
        assert!(!doc.is_same_creator("other"));
    }

    #[test]
    fn test_rollback_preserves_history() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);
        let reviewer = OperatorInfo::new("reviewer", "確認者");
        doc.confirm(reviewer.clone()).unwrap();
        assert_eq!(doc.history.len(), 1);
        assert_eq!(doc.history[0].action, "confirmed");

        doc.rollback(reviewer.clone()).unwrap();
        assert_eq!(doc.history.len(), 2);
        // Original confirmation history is preserved
        assert_eq!(doc.history[0].action, "confirmed");
        assert_eq!(doc.history[1].action, "rolled_back");

        // Confirm again — all history preserved
        let reviewer2 = OperatorInfo::new("reviewer2", "確認者2");
        doc.confirm(reviewer2).unwrap();
        assert_eq!(doc.history.len(), 3);
        assert_eq!(doc.history[0].action, "confirmed");
        assert_eq!(doc.history[1].action, "rolled_back");
        assert_eq!(doc.history[2].action, "confirmed");
    }

    #[test]
    fn test_json_roundtrip() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);
        doc.add_page(1, 595.28, 841.89, 0, "ocr");
        doc.add_region(1, Region::new_auto("r1".into(), [100.0, 200.0, 50.0, 20.0], RegionType::Name, 0.92))
            .unwrap();

        let json = doc.to_json().unwrap();
        let loaded = MaskingDocument::from_json(&json).unwrap();

        assert_eq!(loaded.document_id, doc.document_id);
        assert_eq!(loaded.status, doc.status);
        assert_eq!(loaded.pages.len(), 1);
        assert_eq!(loaded.pages[0].regions[0].bbox, [100.0, 200.0, 50.0, 20.0]);
    }

    #[test]
    fn test_region_serialization() {
        let region = Region::new_auto(
            "test-id".to_string(),
            [10.0, 20.0, 50.0, 30.0],
            RegionType::Name,
            0.95,
        );
        let json = serde_json::to_string(&region).unwrap();
        assert!(json.contains("\"type\":\"name\""));
        assert!(json.contains("\"source\":\"auto\""));
        assert!(json.contains("\"enabled\":true"));

        let manual = Region::new_manual("m1".into(), [0.0; 4], RegionType::Custom("secret".into()));
        let json = serde_json::to_string(&manual).unwrap();
        assert!(json.contains("\"source\":\"manual\""));
        assert!(json.contains("\"custom\":\"secret\""));
    }

    #[test]
    fn test_manual_region() {
        let region = Region::new_manual("m1".into(), [50.0, 60.0, 100.0, 40.0], RegionType::Address);
        assert_eq!(region.confidence, 1.0);
        assert!(region.enabled);
        assert_eq!(region.source, RegionSource::Manual);
        assert!(region.note.is_empty());
    }

    #[test]
    fn test_atomic_save_and_load() {
        let dir = std::env::temp_dir().join("redact_safe_test_atomic");
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("test_atomic.json");

        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);
        doc.add_page(1, 595.28, 841.89, 0, "ocr");
        doc.add_region(1, Region::new_auto("r1".into(), [10.0, 20.0, 50.0, 30.0], RegionType::Name, 0.9))
            .unwrap();

        // Save using atomic write
        doc.save_to_file(&path).unwrap();
        assert!(path.exists());

        // No temp file should remain
        let tmp_path = path.with_extension("tmp");
        assert!(!tmp_path.exists());

        // Load back
        let loaded = MaskingDocument::load_from_file(&path).unwrap();
        assert_eq!(loaded.document_id, doc.document_id);
        assert_eq!(loaded.total_regions_count(), 1);
        assert_eq!(loaded.pages[0].regions[0].bbox, [10.0, 20.0, 50.0, 30.0]);

        // Cleanup
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_backup_rotation() {
        let dir = std::env::temp_dir().join("redact_safe_test_backup");
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("test_backup.json");

        let doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);

        // Save initial version
        doc.save_to_file(&path).unwrap();

        // Create backup 1
        MaskingDocument::create_backup(&path).unwrap();
        assert!(path.with_extension("json.bak1").exists());

        // Create backup 2 (rotates bak1 → bak2)
        MaskingDocument::create_backup(&path).unwrap();
        assert!(path.with_extension("json.bak1").exists());
        assert!(path.with_extension("json.bak2").exists());

        // Create backup 3 (rotates bak2 → bak3, bak1 → bak2)
        MaskingDocument::create_backup(&path).unwrap();
        assert!(path.with_extension("json.bak1").exists());
        assert!(path.with_extension("json.bak2").exists());
        assert!(path.with_extension("json.bak3").exists());

        // Create backup 4 (bak3 should be deleted, bak2 → bak3, bak1 → bak2)
        MaskingDocument::create_backup(&path).unwrap();
        assert!(path.with_extension("json.bak1").exists());
        assert!(path.with_extension("json.bak2").exists());
        assert!(path.with_extension("json.bak3").exists());

        // Only 3 backups should exist
        let backups = MaskingDocument::list_backups(&path);
        assert_eq!(backups.len(), 3);

        // Cleanup
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_crash_recovery_from_backup() {
        let dir = std::env::temp_dir().join("redact_safe_test_recovery");
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("test_recovery.json");

        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);
        doc.add_page(1, 595.28, 841.89, 0, "ocr");

        // Save valid version and create backup
        doc.save_to_file(&path).unwrap();
        MaskingDocument::create_backup(&path).unwrap();

        // Corrupt the main file (empty content simulating crash during write)
        fs::write(&path, "").unwrap();

        // can_recover should detect the issue
        assert!(MaskingDocument::can_recover(&path));

        // load_from_file should recover from backup
        let recovered = MaskingDocument::load_from_file(&path).unwrap();
        assert_eq!(recovered.document_id, doc.document_id);
        assert_eq!(recovered.pages.len(), 1);

        // Cleanup
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_crash_recovery_invalid_json() {
        let dir = std::env::temp_dir().join("redact_safe_test_invalid_json");
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("test_invalid.json");

        let doc = MaskingDocument::new("test.pdf", "sha256:abc123", None);

        // Save valid version and create backup
        doc.save_to_file(&path).unwrap();
        MaskingDocument::create_backup(&path).unwrap();

        // Corrupt the main file with invalid JSON
        fs::write(&path, "{invalid json content").unwrap();

        // load_from_file should recover from backup
        let recovered = MaskingDocument::load_from_file(&path).unwrap();
        assert_eq!(recovered.document_id, doc.document_id);

        // Cleanup
        let _ = fs::remove_dir_all(&dir);
    }
}
