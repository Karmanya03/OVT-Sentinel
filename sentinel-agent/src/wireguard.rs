use anyhow::{Context, Result};
use std::net::IpAddr;
use std::process::Stdio;
use tokio::process::Command;

pub struct WireGuard {
    config: String,
}

impl WireGuard {
    pub fn new(config_path: &str) -> Self {
        Self {
            config: config_path.to_string(),
        }
    }

    pub async fn up(&self) -> Result<IpAddr> {
        let output = Command::new("wg-quick")
            .args(["up", &self.config])
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .output()
            .await
            .context(
                "Failed to spawn 'wg-quick'. Install wireguard-tools first: \
                 apt install wireguard-tools",
            )?;

        if !output.status.success() {
            anyhow::bail!("wg-quick up failed with exit code: {}", output.status);
        }

        let iface = self
            .extract_interface_name()
            .await
            .context("failed to determine WireGuard interface name")?;

        let ip = self
            .extract_interface_ip(&iface)
            .await
            .context("failed to get WireGuard interface IP")?;

        tracing::info!("WireGuard interface '{}' up with IP {}", iface, ip);
        Ok(ip)
    }

    pub async fn down(&self) -> Result<()> {
        let output = Command::new("wg-quick")
            .args(["down", &self.config])
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .output()
            .await
            .context("failed to run wg-quick down")?;

        if !output.status.success() {
            tracing::warn!("wg-quick down exited with code: {}", output.status);
        }
        Ok(())
    }

    async fn extract_interface_name(&self) -> Result<String> {
        let path = std::path::Path::new(&self.config);
        let stem = path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("wg0");
        Ok(stem.to_string())
    }

    async fn extract_interface_ip(&self, iface: &str) -> Result<IpAddr> {
        let output = Command::new("ip")
            .args(["-4", "addr", "show", iface])
            .output()
            .await
            .context("failed to run ip addr show")?;

        let stdout = String::from_utf8_lossy(&output.stdout);
        for line in stdout.lines() {
            let trimmed = line.trim();
            if let Some(rest) = trimmed.strip_prefix("inet ") {
                if let Some(ip_str) = rest.split('/').next() {
                    if let Ok(ip) = ip_str.parse::<IpAddr>() {
                        return Ok(ip);
                    }
                }
            }
        }

        anyhow::bail!(
            "could not find IPv4 address on interface '{}'. \
             Ensure 'wireguard-tools' and 'iproute2' are installed.",
            iface
        )
    }
}
