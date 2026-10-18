//! Capability and output-path policy shared by the native host tests.
use std::path::Path;

pub fn is_supported_operation(operation: &str) -> bool {
    matches!(operation,
        "inspect_pdf" | "edit_pdf_text" | "annotate_pdf" | "convert_to_pdf" |
        "convert_from_pdf" | "ocr_pdf" | "ocr_image" | "form_template" |
        "protect_pdf" | "unlock_pdf" | "remove_watermark" | "compress_pdf" |
        "enhance_image" | "compress_video" | "transcribe" | "summarize" | "translate_pdf"
    )
}
pub fn safe_relative_path(path: &Path) -> bool {
    let Some(text) = path.to_str() else { return false; };
    !text.is_empty() && !text.contains(['\\', ':', '\0']) &&
        !text.chars().any(char::is_control) &&
        path.components().all(|part| matches!(part, std::path::Component::Normal(_)))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn known_operations_are_allowed_but_arbitrary_execution_is_not() {
        assert!(is_supported_operation("protect_pdf"));
        assert!(is_supported_operation("annotate_pdf"));
        assert!(!is_supported_operation("shell"));
        assert!(!is_supported_operation(""));
    }
    #[test]
    fn archive_paths_reject_traversal_absolute_and_windows_paths() {
        assert!(safe_relative_path(Path::new("bin/ffmpeg")));
        for path in ["../secret", "/etc/passwd", "C:\\Windows\\file", "a/../../b", "a\\..\\b", ""] {
            assert!(!safe_relative_path(Path::new(path)), "{path}");
        }
    }
}
