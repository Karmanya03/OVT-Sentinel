use crate::protocol::AgentMessage;
use anyhow::{Context, Result};
use base64::Engine;
use base64::engine::general_purpose::STANDARD as BASE64;
use std::process::Command as StdCommand;

const BROWSERS: &[&str] = &[
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "chrome",
];

fn find_browser() -> Option<&'static str> {
    BROWSERS
        .iter()
        .find(|b| {
            StdCommand::new("which")
                .arg(b)
                .output()
                .map(|o| o.status.success())
                .unwrap_or(false)
        })
        .copied()
}

fn capture_screenshot(url: &str) -> Result<Vec<u8>> {
    let browser_path =
        find_browser().ok_or_else(|| anyhow::anyhow!("no chromium/chrome binary found on VM"))?;

    let tmp_dir = std::env::temp_dir();
    let screenshot_path = tmp_dir.join(format!("sentinel_screenshot_{}.png", uuid::Uuid::new_v4()));
    let path_str = screenshot_path.to_string_lossy().to_string();

    let output = StdCommand::new(browser_path)
        .args([
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            &format!("--screenshot={}", path_str),
            "--window-size=1280,720",
            "--hide-scrollbars",
            url,
        ])
        .output()
        .context("failed to execute chromium screenshot")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let _ = std::fs::remove_file(&screenshot_path);
        anyhow::bail!(
            "chromium exited with code {:?}: {}",
            output.status.code().unwrap_or(-1),
            stderr
        );
    }

    if !screenshot_path.exists() {
        anyhow::bail!("chromium did not produce a screenshot file");
    }

    let data = std::fs::read(&screenshot_path).context("failed to read screenshot file")?;
    let _ = std::fs::remove_file(&screenshot_path);
    Ok(data)
}

pub fn take_screenshot() -> Result<AgentMessage> {
    match capture_screenshot("about:blank") {
        Ok(data) => Ok(AgentMessage::Screenshot {
            data_base64: BASE64.encode(&data),
        }),
        Err(e) => Ok(AgentMessage::Error {
            message: format!("screenshot error: {}", e),
            request_id: None,
        }),
    }
}

pub fn browse_url(url: &str) -> Result<AgentMessage> {
    match capture_screenshot(url) {
        Ok(data) => Ok(AgentMessage::Screenshot {
            data_base64: BASE64.encode(&data),
        }),
        Err(e) => Ok(AgentMessage::Error {
            message: format!("browse screenshot error: {}", e),
            request_id: None,
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_find_browser_returns_some_or_none() {
        let result = find_browser();
        if let Some(b) = result {
            assert!(BROWSERS.contains(&b), "unknown browser: {b}");
        }
    }

    #[test]
    fn test_browser_list() {
        assert!(BROWSERS.contains(&"chromium"));
        assert!(BROWSERS.contains(&"chrome"));
    }

    #[test]
    fn test_take_screenshot_graceful_on_ci() {
        let result = take_screenshot().unwrap();
        match result {
            AgentMessage::Error { .. } => {}      // expected when no browser
            AgentMessage::Screenshot { .. } => {} // ok if browser exists
            _ => panic!("unexpected variant"),
        }
    }

    #[test]
    fn test_browse_url_graceful_on_ci() {
        let result = browse_url("https://example.com").unwrap();
        match result {
            AgentMessage::Error { .. } | AgentMessage::Screenshot { .. } => {}
            _ => panic!("unexpected variant"),
        }
    }
}
