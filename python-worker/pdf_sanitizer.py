"""
PDF Sanitizer Module for RedactSafe

Handles hidden data removal and post-finalization verification for safe PDF output.
This module ensures that finalized PDFs contain no recoverable sensitive data.
"""

import fitz


def sanitize_metadata(doc: fitz.Document) -> list:
    """Remove all metadata from the PDF document.

    Clears XMP metadata, DocInfo dictionary fields, and any embedded metadata streams.

    Args:
        doc: PyMuPDF document object (will be modified in place)

    Returns:
        List of strings describing what was removed
    """
    removed = []

    # Step 1: Clear DocInfo metadata (title, author, subject, keywords, creator, producer)
    old_metadata = doc.metadata
    metadata_fields = ["title", "author", "subject", "keywords", "creator", "producer"]
    for field in metadata_fields:
        value = old_metadata.get(field, "")
        if value:
            removed.append(f"metadata.{field}: '{value}'")

    doc.set_metadata({
        "title": "",
        "author": "",
        "subject": "",
        "keywords": "",
        "creator": "",
        "producer": "",
        "creationDate": "",
        "modDate": "",
        "trapped": "",
        "encryption": "",
    })

    # Step 2: Remove XMP metadata stream
    # XMP metadata is stored as a stream in the document catalog
    try:
        catalog = doc.pdf_catalog()
        if catalog is not None:
            xref = catalog.xref
            # Remove Metadata entry from catalog if present
            cat_obj = doc.xref_object(xref)
            if "Metadata" in cat_obj:
                doc.xref_set_key(xref, "Metadata", "null")
                removed.append("xmp_metadata_stream")
    except Exception:
        pass

    return removed


def sanitize_annotations(doc: fitz.Document) -> list:
    """Remove all annotations from every page.

    Removes text annotations, link annotations, widget annotations,
    markup annotations, and any other annotation types.

    Args:
        doc: PyMuPDF document object (will be modified in place)

    Returns:
        List of strings describing what was removed
    """
    removed = []
    total_annotations = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        annots = list(page.annots() or [])
        for annot in annots:
            annot_type = annot.type
            info = annot.info
            annot_type_name = annot.type[1] if isinstance(annot_type, tuple) and len(annot_type) > 1 else str(annot_type)
            content = info.get("content", "")
            title = info.get("title", "")
            removed.append(f"page{page_num + 1}_annot_{annot_type_name}: title='{title}', content='{content[:50]}'")
            page.delete_annot(annot)
            total_annotations += 1

    if total_annotations > 0:
        removed.insert(0, f"total_annotations_removed: {total_annotations}")

    return removed


def sanitize_embedded_files(doc: fitz.Document) -> list:
    """Remove all embedded files from the PDF.

    Removes file attachments embedded in the PDF document catalog.

    Args:
        doc: PyMuPDF document object (will be modified in place)

    Returns:
        List of strings describing what was removed
    """
    removed = []

    try:
        # Remove EmbeddedFiles from catalog
        catalog = doc.pdf_catalog()
        if catalog is not None:
            xref = catalog.xref
            cat_obj = doc.xref_object(xref)
            if "Names" in cat_obj:
                # Check if there's an EmbeddedFiles tree
                names_obj_str = doc.xref_object(xref)
                if "EmbeddedFiles" in names_obj_str:
                    doc.xref_set_key(xref, "Names", "null")
                    removed.append("embedded_files_tree")

        # Also check the document's embedded file count
        embfile_count = doc.embfile_count()
        if embfile_count > 0:
            for i in range(embfile_count):
                info = doc.embfile_info(i)
                filename = info.get("filename", f"embedded_{i}")
                removed.append(f"embedded_file: '{filename}'")

            # Delete all embedded files
            for i in range(embfile_count):
                doc.embfile_del(i)

    except Exception as e:
        removed.append(f"embedded_files_error: {str(e)}")

    return removed


def sanitize_form_fields(doc: fitz.Document) -> list:
    """Remove all form fields (AcroForm/XFA) from the PDF.

    Removes interactive form widgets and the AcroForm dictionary.

    Args:
        doc: PyMuPDF document object (will be modified in place)

    Returns:
        List of strings describing what was removed
    """
    removed = []

    # Remove widgets from all pages
    total_widgets = 0
    for page_num in range(len(doc)):
        page = doc[page_num]
        widgets = list(page.widgets() or [])
        for widget in widgets:
            field_name = widget.field_name or f"unnamed_{total_widgets}"
            field_type = widget.field_type_string
            removed.append(f"page{page_num + 1}_widget_{field_type}: '{field_name}'")
            # Remove the widget annotation
            widget_rect = widget.rect
            # Widgets are annotations - find and delete
            for annot in page.annots() or []:
                if abs(annot.rect.x0 - widget_rect.x0) < 1 and abs(annot.rect.y0 - widget_rect.y0) < 1:
                    page.delete_annot(annot)
                    break
            total_widgets += 1

    if total_widgets > 0:
        removed.insert(0, f"total_widgets_removed: {total_widgets}")

    # Remove AcroForm from catalog
    try:
        catalog = doc.pdf_catalog()
        if catalog is not None:
            xref = catalog.xref
            cat_obj = doc.xref_object(xref)
            if "AcroForm" in cat_obj:
                doc.xref_set_key(xref, "AcroForm", "null")
                removed.append("acroform_dictionary")
    except Exception:
        pass

    # Remove XFA content (XML form data)
    try:
        catalog = doc.pdf_catalog()
        if catalog is not None:
            xref = catalog.xref
            cat_obj = doc.xref_object(xref)
            if "XFA" in cat_obj:
                doc.xref_set_key(xref, "XFA", "null")
                removed.append("xfa_content")
    except Exception:
        pass

    return removed


def sanitize_javascript(doc: fitz.Document) -> list:
    """Remove all JavaScript actions from the PDF.

    Removes OpenAction, additional actions (AA), and any JavaScript name trees.

    Args:
        doc: PyMuPDF document object (will be modified in place)

    Returns:
        List of strings describing what was removed
    """
    removed = []

    try:
        catalog = doc.pdf_catalog()
        if catalog is None:
            return removed
        xref = catalog.xref

        # Remove OpenAction (auto-execute on open)
        cat_obj = doc.xref_object(xref)
        if "OpenAction" in cat_obj:
            doc.xref_set_key(xref, "OpenAction", "null")
            removed.append("open_action")

        # Remove Additional Actions (AA) dictionary
        cat_obj = doc.xref_object(xref)
        if "AA" in cat_obj:
            doc.xref_set_key(xref, "AA", "null")
            removed.append("additional_actions")

        # Remove JavaScript name tree
        cat_obj = doc.xref_object(xref)
        if "Names" in cat_obj:
            names_str = cat_obj
            if "JavaScript" in names_str:
                # Remove the Names dictionary entirely (contains JS references)
                doc.xref_set_key(xref, "Names", "null")
                removed.append("javascript_names_tree")

    except Exception as e:
        removed.append(f"javascript_error: {str(e)}")

    return removed


def sanitize_bookmarks(doc: fitz.Document) -> list:
    """Remove all bookmarks (Outlines) from the PDF.

    Args:
        doc: PyMuPDF document object (will be modified in place)

    Returns:
        List of strings describing what was removed
    """
    removed = []

    toc = doc.get_toc()
    if toc:
        count = len(toc)
        doc.set_toc([])
        removed.append(f"bookmarks_removed: {count}")

    # Also remove Outlines from catalog
    try:
        catalog = doc.pdf_catalog()
        if catalog is not None:
            xref = catalog.xref
            cat_obj = doc.xref_object(xref)
            if "Outlines" in cat_obj:
                doc.xref_set_key(xref, "Outlines", "null")
                removed.append("outlines_catalog_entry")
    except Exception:
        pass

    return removed


def sanitize_hidden_layers(doc: fitz.Document) -> list:
    """Remove optional content (OC) properties / hidden layers.

    Args:
        doc: PyMuPDF document object (will be modified in place)

    Returns:
        List of strings describing what was removed
    """
    removed = []

    try:
        catalog = doc.pdf_catalog()
        if catalog is None:
            return removed
        xref = catalog.xref

        # Remove OCProperties (Optional Content Properties)
        cat_obj = doc.xref_object(xref)
        if "OCProperties" in cat_obj:
            doc.xref_set_key(xref, "OCProperties", "null")
            removed.append("ocproperties")

        # Remove Properties dictionary (may contain OCG/OCMD refs)
        cat_obj = doc.xref_object(xref)
        if "Properties" in cat_obj:
            # Check if it contains OC-related entries
            prop_str = cat_obj
            if "OCG" in prop_str or "OCMD" in prop_str:
                doc.xref_set_key(xref, "Properties", "null")
                removed.append("properties_oc_refs")

    except Exception as e:
        removed.append(f"hidden_layers_error: {str(e)}")

    return removed


def set_permissions(doc: fitz.Document) -> list:
    """Set copy-prevention permissions on the PDF.

    Configures the PDF to prevent:
    - Copying text/images
    - Printing (except as image)
    - Editing
    - Adding annotations

    Args:
        doc: PyMuPDF document object (will be modified in place via save)

    Returns:
        List of strings describing what was configured
    """
    applied = []

    # PyMuPDF permission flags:
    # PERM_PRINT = 4 (low-res print)
    # PERM_MODIFY = 8 (modify)
    # PERM_COPY = 16 (copy)
    # PERM_ANNOTATE = 32 (annotate)
    # We set NO copy, NO modify, NO annotate
    # Allow printing (as image only)
    perm_flags = (
        fitz.PDF_PERM_PRINT      # Allow printing (image-based)
        | fitz.PDF_PERM_ACCESSIBILITY  # Allow accessibility
    )

    # Encrypt with empty password but restrictions
    doc.save(
        doc.name if doc.name else "temp.pdf",
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="RedactSafe_Owner_2024!",
        user_pw="",
        permissions=perm_flags,
        garbage=4,
        deflate=True,
    )

    applied.append("encryption: AES-256")
    applied.append("permissions: print_only, no_copy, no_modify, no_annotate")

    return applied


def sanitize_pdf(doc: fitz.Document, set_perms: bool = True) -> dict:
    """Apply all sanitization steps to a PDF document.

    Performs complete hidden data removal:
    1. Metadata removal (XMP, DocInfo)
    2. Annotation removal
    3. Embedded file removal
    4. Form field removal (AcroForm/XFA)
    5. JavaScript action removal
    6. Bookmark removal
    7. Hidden layer removal
    8. Copy-prevention permissions

    Args:
        doc: PyMuPDF document object (will be modified in place)
        set_perms: Whether to set copy-prevention permissions

    Returns:
        Dictionary with sanitization results:
            {removed_items: [...], applied_settings: [...]}
    """
    all_removed = []
    all_applied = []

    # Step 1: Remove metadata
    items = sanitize_metadata(doc)
    all_removed.extend(items)

    # Step 2: Remove annotations
    items = sanitize_annotations(doc)
    all_removed.extend(items)

    # Step 3: Remove embedded files
    items = sanitize_embedded_files(doc)
    all_removed.extend(items)

    # Step 4: Remove form fields
    items = sanitize_form_fields(doc)
    all_removed.extend(items)

    # Step 5: Remove JavaScript actions
    items = sanitize_javascript(doc)
    all_removed.extend(items)

    # Step 6: Remove bookmarks
    items = sanitize_bookmarks(doc)
    all_removed.extend(items)

    # Step 7: Remove hidden layers
    items = sanitize_hidden_layers(doc)
    all_removed.extend(items)

    # Step 8: Set permissions
    if set_perms:
        items = set_permissions(doc)
        all_applied.extend(items)

    return {
        "removed_items": all_removed,
        "applied_settings": all_applied,
    }


def verify_safe_pdf(doc: fitz.Document) -> dict:
    """Verify that a finalized PDF is safe.

    Checks for:
    1. Zero extractable text across all pages
    2. No hidden data (annotations, embedded files, form fields, JavaScript, etc.)
    3. No metadata containing sensitive information

    Args:
        doc: PyMuPDF document object to verify

    Returns:
        Dictionary with verification results:
            {
                valid: bool,
                text_check: {passed: bool, total_text_length: int},
                hidden_data_check: {
                    passed: bool,
                    issues: [{type: str, detail: str}, ...]
                },
                metadata_check: {passed: bool, issues: [...]},
                object_scan: {passed: bool, issues: [...]}
            }
    """
    issues = []
    all_checks_passed = True

    # --- Check 1: No extractable text ---
    total_text_length = 0
    pages_with_text = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text").strip()
        if text:
            total_text_length += len(text)
            pages_with_text.append(page_num + 1)

    text_check = {
        "passed": total_text_length == 0,
        "total_text_length": total_text_length,
    }
    if not text_check["passed"]:
        text_check["pages_with_text"] = pages_with_text
        text_check["sample_text"] = doc[pages_with_text[0] - 1].get_text("text")[:200]
        issues.append({
            "type": "text_found",
            "detail": f"Extractable text found on pages {pages_with_text} (total {total_text_length} chars)",
        })
        all_checks_passed = False

    # --- Check 2: No hidden data ---
    hidden_issues = []

    # Check annotations
    total_annotations = 0
    for page_num in range(len(doc)):
        page = doc[page_num]
        annots = list(page.annots() or [])
        for annot in annots:
            annot_type = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else str(annot.type)
            hidden_issues.append({
                "type": "annotation",
                "detail": f"Page {page_num + 1}: annotation type '{annot_type}' found",
            })
            total_annotations += 1

    # Check embedded files
    embfile_count = doc.embfile_count()
    if embfile_count > 0:
        for i in range(embfile_count):
            info = doc.embfile_info(i)
            filename = info.get("filename", f"embedded_{i}")
            hidden_issues.append({
                "type": "embedded_file",
                "detail": f"Embedded file '{filename}' found",
            })

    # Check form widgets
    total_widgets = 0
    for page_num in range(len(doc)):
        page = doc[page_num]
        widgets = list(page.widgets() or [])
        for widget in widgets:
            field_name = widget.field_name or f"unnamed"
            hidden_issues.append({
                "type": "form_widget",
                "detail": f"Page {page_num + 1}: form widget '{field_name}' found",
            })
            total_widgets += 1

    # Check AcroForm
    try:
        catalog = doc.pdf_catalog()
        if catalog is not None:
            xref = catalog.xref
            cat_obj = doc.xref_object(xref)
            if "AcroForm" in cat_obj:
                hidden_issues.append({
                    "type": "acroform",
                    "detail": "AcroForm dictionary found in catalog",
                })
            if "XFA" in cat_obj:
                hidden_issues.append({
                    "type": "xfa",
                    "detail": "XFA content found in catalog",
                })
    except Exception:
        pass

    # Check JavaScript
    try:
        catalog = doc.pdf_catalog()
        if catalog is not None:
            xref = catalog.xref
            cat_obj = doc.xref_object(xref)
            if "OpenAction" in cat_obj:
                hidden_issues.append({
                    "type": "javascript",
                    "detail": "OpenAction found in catalog",
                })
            if "AA" in cat_obj:
                hidden_issues.append({
                    "type": "javascript",
                    "detail": "Additional Actions (AA) found in catalog",
                })
            if "JavaScript" in cat_obj:
                hidden_issues.append({
                    "type": "javascript",
                    "detail": "JavaScript name tree found in catalog",
                })
    except Exception:
        pass

    # Check Outlines (bookmarks)
    toc = doc.get_toc()
    if toc:
        hidden_issues.append({
            "type": "bookmarks",
            "detail": f"{len(toc)} bookmarks found",
        })

    # Check hidden layers (OCProperties)
    try:
        catalog = doc.pdf_catalog()
        if catalog is not None:
            xref = catalog.xref
            cat_obj = doc.xref_object(xref)
            if "OCProperties" in cat_obj:
                hidden_issues.append({
                    "type": "hidden_layers",
                    "detail": "OCProperties (hidden layers) found in catalog",
                })
    except Exception:
        pass

    hidden_data_check = {
        "passed": len(hidden_issues) == 0,
        "issues": hidden_issues,
    }
    if not hidden_data_check["passed"]:
        issues.extend(hidden_issues)
        all_checks_passed = False

    # --- Check 3: No sensitive metadata ---
    metadata_issues = []
    metadata = doc.metadata
    sensitive_fields = ["title", "author", "subject", "keywords", "creator", "producer"]
    for field in sensitive_fields:
        value = metadata.get(field, "")
        if value and value.strip():
            metadata_issues.append({
                "type": "metadata",
                "detail": f"Metadata field '{field}' contains: '{value}'",
            })

    # Check XMP metadata
    try:
        catalog = doc.pdf_catalog()
        if catalog is not None:
            xref = catalog.xref
            cat_obj = doc.xref_object(xref)
            if "Metadata" in cat_obj:
                metadata_issues.append({
                    "type": "xmp_metadata",
                    "detail": "XMP metadata stream found in catalog",
                })
    except Exception:
        pass

    metadata_check = {
        "passed": len(metadata_issues) == 0,
        "issues": metadata_issues,
    }
    if not metadata_check["passed"]:
        issues.extend(metadata_issues)
        all_checks_passed = False

    # --- Check 4: Full PDF object scan ---
    object_issues = []
    try:
        xref_len = doc.xref_length()
        for xref in range(1, xref_len):
            try:
                obj_str = doc.xref_object(xref)
                # Check for JavaScript actions in any object
                if "/JS" in obj_str or "/JavaScript" in obj_str:
                    obj_type = doc.xref_object(xref, compressed=True)[:100]
                    object_issues.append({
                        "type": "javascript_object",
                        "detail": f"Object {xref} contains JavaScript reference: {obj_type}...",
                    })
                # Check for embedded file streams
                if "/EmbeddedFile" in obj_str:
                    object_issues.append({
                        "type": "embedded_stream",
                        "detail": f"Object {xref} contains embedded file stream",
                    })
                # Check for launch actions
                if "/Launch" in obj_str or "/SubmitForm" in obj_str:
                    object_issues.append({
                        "type": "action",
                        "detail": f"Object {xref} contains Launch or SubmitForm action",
                    })
                # Check for GoTo actions that could leak structure
                if "/GoTo" in obj_str or "/GoToR" in obj_str:
                    object_issues.append({
                        "type": "navigation",
                        "detail": f"Object {xref} contains GoTo navigation action",
                    })
            except Exception:
                pass
    except Exception as e:
        object_issues.append({
            "type": "scan_error",
            "detail": f"Error during object scan: {str(e)}",
        })

    object_scan = {
        "passed": len(object_issues) == 0,
        "issues": object_issues,
    }
    if not object_scan["passed"]:
        issues.extend(object_issues)
        all_checks_passed = False

    return {
        "valid": all_checks_passed,
        "text_check": text_check,
        "hidden_data_check": hidden_data_check,
        "metadata_check": metadata_check,
        "object_scan": object_scan,
    }


def verify_safe_pdf_base64(pdf_data_b64: str) -> dict:
    """Verify a safe PDF from base64-encoded data.

    Convenience function for JSON-RPC calls.

    Args:
        pdf_data_b64: Base64-encoded PDF data

    Returns:
        Verification results dictionary
    """
    import base64

    pdf_bytes = base64.b64decode(pdf_data_b64)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    try:
        return verify_safe_pdf(doc)
    finally:
        doc.close()
