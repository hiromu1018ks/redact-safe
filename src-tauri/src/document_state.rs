use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

const SCHEMA_VERSION: &str = "1.2";

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

/// Type of detected PII / sensitive information.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RegionType {
    Name,
    Address,
    Phone,
    Email,
    BirthDate,
    MyNumber,
    CorporateNumber,
    Custom(String),
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
    pub confirmed_by: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub finalized_by: Option<String>,
    pub coordinate_system: CoordinateSystem,
    #[serde(default)]
    pub history: Vec<HistoryEntry>,
    pub pages: Vec<PageInfo>,
}

impl MaskingDocument {
    /// Create a new masking document for the given source PDF.
    pub fn new(source_file: &str, source_hash: &str) -> Self {
        MaskingDocument {
            schema_version: SCHEMA_VERSION.to_string(),
            document_id: uuid::Uuid::new_v4().to_string(),
            source_file: source_file.to_string(),
            source_hash: source_hash.to_string(),
            status: DocumentStatus::Draft,
            revision: 1,
            confirmed_by: None,
            finalized_by: None,
            coordinate_system: CoordinateSystem::default(),
            history: Vec::new(),
            pages: Vec::new(),
        }
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
    pub fn confirm(&mut self, user: &str) -> Result<(), String> {
        if self.status != DocumentStatus::Draft {
            return Err(format!(
                "Cannot confirm from status '{}'. Only draft can be confirmed.",
                self.status.as_str()
            ));
        }
        self.status = DocumentStatus::Confirmed;
        self.confirmed_by = Some(user.to_string());
        self.history.push(HistoryEntry {
            timestamp: Utc::now().to_rfc3339(),
            action: "confirmed".to_string(),
            user: user.to_string(),
            details: None,
        });
        Ok(())
    }

    /// Rollback from confirmed back to draft.
    pub fn rollback(&mut self, user: &str) -> Result<(), String> {
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
            user: user.to_string(),
            details: Some(format!(
                "Rolled back to draft, revision incremented to {}",
                self.revision
            )),
        });
        Ok(())
    }

    /// Transition from confirmed to finalized (irreversible).
    pub fn finalize(&mut self, user: &str) -> Result<(), String> {
        if self.status != DocumentStatus::Confirmed {
            return Err(format!(
                "Cannot finalize from status '{}'. Only confirmed can be finalized.",
                self.status.as_str()
            ));
        }
        self.status = DocumentStatus::Finalized;
        self.finalized_by = Some(user.to_string());
        self.history.push(HistoryEntry {
            timestamp: Utc::now().to_rfc3339(),
            action: "finalized".to_string(),
            user: user.to_string(),
            details: None,
        });
        Ok(())
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

    /// Save document to a JSON file.
    pub fn save_to_file(&self, path: &Path) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|e| format!("Failed to create directory: {}", e))?;
        }
        let content = self.to_json()?;
        fs::write(path, content)
            .map_err(|e| format!("Failed to write document file: {}", e))?;
        Ok(())
    }

    /// Load document from a JSON file.
    pub fn load_from_file(path: &Path) -> Result<Self, String> {
        let content = fs::read_to_string(path)
            .map_err(|e| format!("Failed to read document file: {}", e))?;
        Self::from_json(&content)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new_document() {
        let doc = MaskingDocument::new("test.pdf", "sha256:abc123");
        assert_eq!(doc.schema_version, "1.2");
        assert_eq!(doc.source_file, "test.pdf");
        assert_eq!(doc.source_hash, "sha256:abc123");
        assert_eq!(doc.status, DocumentStatus::Draft);
        assert_eq!(doc.revision, 1);
        assert!(doc.confirmed_by.is_none());
        assert!(doc.finalized_by.is_none());
        assert!(doc.pages.is_empty());
        assert!(doc.history.is_empty());
        assert_eq!(doc.coordinate_system.dpi_for_rasterize, 300);
    }

    #[test]
    fn test_add_page_and_regions() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123");
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
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123");
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
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123");
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
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123");
        doc.add_page(1, 595.28, 841.89, 0, "ocr");
        doc.add_region(1, Region::new_auto("r1".into(), [10.0, 20.0, 50.0, 30.0], RegionType::Name, 0.9))
            .unwrap();

        doc.update_region_bbox(1, "r1", [15.0, 25.0, 60.0, 35.0]).unwrap();
        let regions = doc.get_page_regions(1).unwrap();
        assert_eq!(regions[0].bbox, [15.0, 25.0, 60.0, 35.0]);
    }

    #[test]
    fn test_set_all_regions_enabled() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123");
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
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123");
        let user = "testuser";

        // draft → confirmed: OK
        doc.confirm(user).unwrap();
        assert_eq!(doc.status, DocumentStatus::Confirmed);
        assert_eq!(doc.confirmed_by.as_deref(), Some(user));
        assert_eq!(doc.history.len(), 1);

        // confirmed → finalized: OK
        doc.finalize(user).unwrap();
        assert_eq!(doc.status, DocumentStatus::Finalized);
        assert_eq!(doc.finalized_by.as_deref(), Some(user));
        assert_eq!(doc.history.len(), 2);

        // finalized → any: error
        assert!(doc.confirm(user).is_err());
        assert!(doc.rollback(user).is_err());
        assert!(doc.finalize(user).is_err());
    }

    #[test]
    fn test_rollback() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123");
        doc.confirm("reviewer").unwrap();
        assert_eq!(doc.revision, 1);

        doc.rollback("reviewer").unwrap();
        assert_eq!(doc.status, DocumentStatus::Draft);
        assert!(doc.confirmed_by.is_none());
        assert_eq!(doc.revision, 2);
        assert_eq!(doc.history.len(), 2);

        // Can confirm again
        doc.confirm("reviewer2").unwrap();
        assert_eq!(doc.status, DocumentStatus::Confirmed);
    }

    #[test]
    fn test_invalid_transitions() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123");

        // Cannot finalize from draft
        assert!(doc.finalize("user").is_err());

        // Cannot rollback from draft
        assert!(doc.rollback("user").is_err());

        // Cannot confirm from confirmed
        doc.confirm("user").unwrap();
        assert!(doc.confirm("user").is_err());
    }

    #[test]
    fn test_json_roundtrip() {
        let mut doc = MaskingDocument::new("test.pdf", "sha256:abc123");
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
}
