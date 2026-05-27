/// Constant-time comparison of two byte strings to prevent timing attacks.
pub fn verify_token(expected: &str, provided: &str) -> bool {
    if expected.len() != provided.len() {
        return false;
    }
    let mut result: u8 = 0;
    for (a, b) in expected.bytes().zip(provided.bytes()) {
        result |= a ^ b;
    }
    result == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_exact_match() {
        assert!(verify_token("my-secret-token", "my-secret-token"));
    }

    #[test]
    fn test_empty_strings() {
        assert!(verify_token("", ""));
    }

    #[test]
    fn test_length_mismatch() {
        assert!(!verify_token("abc", "abcdef"));
        assert!(!verify_token("abcdef", "abc"));
    }

    #[test]
    fn test_wrong_token() {
        assert!(!verify_token("correct-token", "wrong-token"));
    }

    #[test]
    fn test_partial_match() {
        assert!(!verify_token("abcdefgh", "abcdefxx"));
    }

    #[test]
    fn test_long_token() {
        let expected = "a".repeat(64);
        let provided = "a".repeat(64);
        assert!(verify_token(&expected, &provided));
        let mut wrong = provided.clone();
        wrong.replace_range(63..64, "b");
        assert!(!verify_token(&expected, &wrong));
    }

    #[test]
    fn test_unicode() {
        assert!(verify_token("test-123!", "test-123!"));
        assert!(!verify_token("test-123!", "test-123?"));
    }
}
