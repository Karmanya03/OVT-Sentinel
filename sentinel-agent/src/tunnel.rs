use anyhow::{Context, Result};
use std::process::Stdio;
use tokio::process::Command;
use tokio::sync::watch;

const TUNNEL_TIMEOUT_SECS: u64 = 45;

#[allow(dead_code)]
pub struct Tunnel {
    public_url: String,
    shutdown_tx: watch::Sender<bool>,
}

impl Tunnel {
    pub fn public_url(&self) -> &str {
        &self.public_url
    }
}

pub async fn start_cloudflared_tunnel(local_port: u16) -> Result<Tunnel> {
    let mut child = Command::new("cloudflared")
        .args([
            "tunnel",
            "--url",
            &format!("http://localhost:{}", local_port),
            "--no-autoupdate",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .context(
            "Failed to spawn 'cloudflared'. Install from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/",
        )?;

    // cloudflared writes structured JSON logs to stderr
    let stderr = child
        .stderr
        .take()
        .context("failed to capture cloudflared stderr")?;

    let mut reader = tokio::io::BufReader::new(stderr);
    use tokio::io::AsyncBufReadExt;

    let mut line_buf = String::new();
    let public_url;

    loop {
        line_buf.clear();
        let n: usize = tokio::time::timeout(
            std::time::Duration::from_secs(TUNNEL_TIMEOUT_SECS),
            reader.read_line(&mut line_buf),
        )
        .await
        .context("cloudflared did not establish a tunnel within 45s — check your internet connection")?
        .context("failed to read cloudflared output")?;

        if n == 0 {
            child.wait().await?;
            anyhow::bail!("cloudflared exited without establishing a tunnel");
        }

        if let Some(url) = extract_cloudflared_url(&line_buf) {
            public_url = url;
            tracing::info!("Tunnel established: {}", public_url);
            break;
        }
    }

    let (shutdown_tx, mut shutdown_rx) = watch::channel(false);
    let mut child = child;

    tokio::spawn(async move {
        loop {
            tokio::select! {
                _ = shutdown_rx.changed() => {
                    let _ = child.kill().await;
                    let _ = child.wait().await;
                    break;
                }
                status = child.wait() => {
                    match status {
                        Ok(s) => tracing::warn!("cloudflared process exited unexpectedly: {}", s),
                        Err(e) => tracing::error!("cloudflared process error: {}", e),
                    }
                    break;
                }
            }
        }
    });

    Ok(Tunnel {
        public_url,
        shutdown_tx,
    })
}

fn extract_cloudflared_url(line: &str) -> Option<String> {
    // cloudflared outputs structured JSON logs like:
    // {"level":"info","msg":"+-- https://xyz.trycloudflare.com --+","time":"..."}
    // or {"level":"info","msg":"started tunnel","url":"https://xyz.trycloudflare.com","time":"..."}
    //
    // Try JSON parsing first
    if let Some(url) = extract_from_json(line) {
        return Some(url);
    }

    // Fallback: look for https://<anything>.trycloudflare.com in plain text
    extract_from_text(line)
}

fn extract_from_json(line: &str) -> Option<String> {
    let parsed: serde_json::Value = serde_json::from_str(line.trim()).ok()?;

    // Check for top-level "url" field
    let raw_url = parsed
        .get("url")
        .or_else(|| parsed.get("obj")?.get("url"))?
        .as_str()?;

    let raw_url = raw_url.trim().trim_matches('"');

    // Must be a valid tunnel URL (random subdomain, not api.trycloudflare.com)
    if !raw_url.starts_with("https://") || !raw_url.contains("trycloudflare.com") {
        return None;
    }
    // Reject the api endpoint itself
    if raw_url.contains("api.trycloudflare.com") {
        return None;
    }

    Some(raw_url.replacen("https://", "wss://", 1))
}

fn extract_from_text(line: &str) -> Option<String> {
    // Fallback for plain-text output (ascii box)
    let trimmed = line.trim();
    let start = trimmed.find("https://")?;
    let rest = &trimmed[start..];
    let end = rest.find(|c: char| c.is_whitespace() || c == '|' || c == '+' || c == '"').unwrap_or(rest.len());
    let url = rest[..end].trim().trim_matches('"');

    if !url.contains("trycloudflare.com") || url.contains("api.trycloudflare.com") {
        return None;
    }

    Some(url.replacen("https://", "wss://", 1))
}

pub async fn register_tunnel(register_url: &str, tunnel_ws_url: &str, token: &str) -> Result<()> {
    let payload = serde_json::json!({
        "token": token,
        "url": tunnel_ws_url,
    });

    let client = reqwest::Client::new();
    let resp = client
        .post(register_url)
        .json(&payload)
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await
        .context("failed to send registration request")?;

    if resp.status().is_success() {
        tracing::info!("Bot registration successful: {}", tunnel_ws_url);
        Ok(())
    } else {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        anyhow::bail!("bot registration failed ({}): {}", status, body)
    }
}
