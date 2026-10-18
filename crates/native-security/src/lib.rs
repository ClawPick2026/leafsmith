//! Capability and output-path policy shared by the native host tests.
use std::path::Path;

pub fn is_supported_operation(_operation: &str) -> bool { false }
pub fn safe_relative_path(_path: &Path) -> bool { false }

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
