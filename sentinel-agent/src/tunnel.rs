use anyhow::{Context, Result};
use std::process::Stdio;
use tokio::process::Command;
use tokio::sync::watch;

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

pub async fn start_bore_tunnel(local_port: u16) -> Result<Tunnel> {
    let mut child = Command::new("bore")
        .args([
            "local",
            &local_port.to_string(),
            "--to",
            "bore.pub",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .kill_on_drop(true)
        .spawn()
        .context(
            "Failed to spawn 'bore'. Install it first: cargo install bore-cli",
        )?;

    let stdout = child
        .stdout
        .take()
        .context("failed to capture bore stdout")?;

    let mut reader = tokio::io::BufReader::new(stdout);
    use tokio::io::AsyncBufReadExt;

    let mut line_buf = String::new();
    let public_url;

    loop {
        line_buf.clear();
        let n = reader
            .read_line(&mut line_buf)
            .await
            .context("failed to read bore output")?;
        if n == 0 {
            child.wait().await?;
            anyhow::bail!("bore exited without establishing a tunnel");
        }
        let trimmed = line_buf.trim();
        if let Some(url) = extract_bore_url(trimmed) {
            public_url = format!("ws://{}", url);
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
                        Ok(s) => tracing::warn!("bore process exited unexpectedly: {}", s),
                        Err(e) => tracing::error!("bore process error: {}", e),
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

fn extract_bore_url(line: &str) -> Option<String> {
    let start = line.find("bore.pub:")?;
    let rest = &line[start..];
    let end = rest.find(|c: char| !c.is_ascii_digit()).unwrap_or(rest.len());
    Some(rest[..end.min(start + 50)].to_string())
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
