use crate::protocol::{NetworkConn, ProcessInfo};
use anyhow::Result;
use std::process::Command as StdCommand;
use sysinfo::{Disks, System};

pub struct SystemSnapshot {
    pub cpu_percent: f32,
    pub ram_used_mb: u64,
    pub ram_total_mb: u64,
    pub network_connections: Vec<NetworkConn>,
    pub running_processes: Vec<ProcessInfo>,
    pub ovt_version: Option<String>,
    pub disk_free_gb: f64,
}

pub struct SystemMonitor {
    system: System,
    disks: Disks,
}

fn get_ovt_version() -> Option<String> {
    // Try to get the real version from the binary first
    if let Ok(output) = StdCommand::new("ovt").arg("--version").output() {
        if output.status.success() {
            let v = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !v.is_empty() {
                return Some(v);
            }
        }
    }
    // Fallback: check for running process
    let mut system = System::new_all();
    system.refresh_all();
    for (_, p) in system.processes() {
        let name = p.name().to_string_lossy();
        if name.contains("ovt") || name.contains("overthrone") {
            return Some("running".to_string());
        }
    }
    None
}

impl SystemMonitor {
    pub fn new() -> Self {
        let mut system = System::new_all();
        system.refresh_all();
        let disks = Disks::new_with_refreshed_list();
        Self { system, disks }
    }

    pub fn snapshot(&mut self) -> Result<SystemSnapshot> {
        self.system.refresh_all();

        let cpu_percent = self.system.global_cpu_usage();
        let ram_used_mb = self.system.used_memory() / 1024;
        let ram_total_mb = self.system.total_memory() / 1024;

        let mut processes: Vec<ProcessInfo> = self
            .system
            .processes()
            .iter()
            .map(|(_, p)| {
                let cmd: Vec<String> = p
                    .cmd()
                    .iter()
                    .map(|c| c.to_string_lossy().to_string())
                    .collect();
                ProcessInfo {
                    pid: p.pid().as_u32(),
                    name: p.name().to_string_lossy().to_string(),
                    cpu_percent: p.cpu_usage(),
                    ram_mb: p.memory() / 1024,
                    command: cmd.join(" "),
                }
            })
            .collect();

        processes.sort_by(|a, b| {
            b.cpu_percent
                .partial_cmp(&a.cpu_percent)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        processes.truncate(50);

        let disk_free_bytes: u64 = self.disks.iter().map(|d| d.available_space()).sum();
        let disk_free_gb = (disk_free_bytes as f64) / (1024.0 * 1024.0 * 1024.0);

        let connections = parse_network_connections();

        let ovt_version = get_ovt_version();

        Ok(SystemSnapshot {
            cpu_percent,
            ram_used_mb,
            ram_total_mb,
            network_connections: connections,
            running_processes: processes,
            ovt_version,
            disk_free_gb,
        })
    }
}

fn parse_network_connections() -> Vec<NetworkConn> {
    #[cfg(target_os = "linux")]
    {
        linux_network_connections()
    }
    #[cfg(not(target_os = "linux"))]
    {
        Vec::new()
    }
}

#[cfg(target_os = "linux")]
fn linux_network_connections() -> Vec<NetworkConn> {
    let mut conns = Vec::new();

    if let Ok(data) = std::fs::read_to_string("/proc/net/tcp") {
        for line in data.lines().skip(1) {
            if let Some(nc) = parse_tcp_line(line) {
                conns.push(nc);
            }
        }
    }

    if let Ok(data) = std::fs::read_to_string("/proc/net/tcp6") {
        for line in data.lines().skip(1) {
            if let Some(nc) = parse_tcp6_line(line) {
                conns.push(nc);
            }
        }
    }

    conns
}

#[cfg(target_os = "linux")]
fn parse_tcp_line(line: &str) -> Option<NetworkConn> {
    let parts: Vec<&str> = line.split_whitespace().collect();
    if parts.len() < 4 {
        return None;
    }
    let local_str = parts.get(1)?;
    let remote_str = parts.get(2)?;
    let state_hex = parts.get(3)?;

    let (local_ip, local_port) = parse_hex_sockaddr_ipv4(local_str)?;
    let (remote_ip, remote_port) = parse_hex_sockaddr_ipv4(remote_str)?;
    let state_code = u8::from_str_radix(state_hex, 16).unwrap_or(0);
    let state = tcp_state_name(state_code);

    Some(NetworkConn {
        local_addr: format!("{}:{}", local_ip, local_port),
        remote_addr: Some(format!("{}:{}", remote_ip, remote_port)),
        state,
        pid: None,
        process_name: None,
    })
}

#[cfg(target_os = "linux")]
fn parse_tcp6_line(line: &str) -> Option<NetworkConn> {
    let parts: Vec<&str> = line.split_whitespace().collect();
    if parts.len() < 4 {
        return None;
    }
    let local_str = parts.get(1)?;
    let remote_str = parts.get(2)?;
    let state_hex = parts.get(3)?;

    let (local_ip, local_port) = parse_hex_sockaddr_ipv6(local_str)?;
    let (remote_ip, remote_port) = parse_hex_sockaddr_ipv6(remote_str)?;
    let state_code = u8::from_str_radix(state_hex, 16).unwrap_or(0);
    let state = tcp_state_name(state_code);

    Some(NetworkConn {
        local_addr: format!("[{}]:{}", local_ip, local_port),
        remote_addr: Some(format!("[{}]:{}", remote_ip, remote_port)),
        state,
        pid: None,
        process_name: None,
    })
}

/// Parse hex-encoded IPv4 address:port from /proc/net/tcp (little-endian bytes)
#[cfg(target_os = "linux")]
fn parse_hex_sockaddr_ipv4(s: &str) -> Option<(String, u16)> {
    let (ip_hex, port_hex) = s.split_once(':')?;
    let ip_val = u32::from_str_radix(ip_hex, 16).ok()?;
    let port = u16::from_str_radix(port_hex, 16).ok()?;
    // /proc/net/tcp stores IPv4 in network byte order within a 32-bit field
    let ip = std::net::Ipv4Addr::new(
        ((ip_val >> 0) & 0xff) as u8,
        ((ip_val >> 8) & 0xff) as u8,
        ((ip_val >> 16) & 0xff) as u8,
        ((ip_val >> 24) & 0xff) as u8,
    );
    Some((ip.to_string(), port))
}

/// Parse hex-encoded IPv6 address:port from /proc/net/tcp6
#[cfg(target_os = "linux")]
fn parse_hex_sockaddr_ipv6(s: &str) -> Option<(String, u16)> {
    let (ip_hex, port_hex) = s.split_once(':')?;
    let port = u16::from_str_radix(port_hex, 16).ok()?;

    if ip_hex.len() != 32 {
        return None;
    }

    let mut groups: Vec<u16> = Vec::new();
    for i in 0..8 {
        let group_str = &ip_hex[i * 4..(i + 1) * 4];
        if let Ok(val) = u16::from_str_radix(group_str, 16) {
            groups.push(val.to_be());
        } else {
            return None;
        }
    }

    let ip_str = if groups[0..5].iter().all(|&g| g == 0) && groups[5] == 0xffff {
        let b = groups[6].to_be_bytes();
        let c = groups[7].to_be_bytes();
        format!("::ffff:{}.{}.{}.{}", b[0], b[1], c[0], c[1])
    } else {
        let hex: Vec<String> = groups.iter().map(|g| format!("{:x}", g)).collect();
        hex.join(":")
    };

    Some((ip_str, port))
}

#[cfg(target_os = "linux")]
fn tcp_state_name(code: u8) -> String {
    match code {
        0x01 => "ESTABLISHED".to_string(),
        0x02 => "SYN_SENT".to_string(),
        0x03 => "SYN_RECV".to_string(),
        0x04 => "FIN_WAIT1".to_string(),
        0x05 => "FIN_WAIT2".to_string(),
        0x06 => "TIME_WAIT".to_string(),
        0x07 => "CLOSE".to_string(),
        0x08 => "CLOSE_WAIT".to_string(),
        0x09 => "LAST_ACK".to_string(),
        0x0A => "LISTEN".to_string(),
        0x0B => "CLOSING".to_string(),
        _ => format!("UNKNOWN({})", code),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_network_connections() {
        let conns = parse_network_connections();
        assert!(conns.is_empty() || conns.iter().all(|c| !c.local_addr.is_empty()));
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn test_parse_tcp_line_invalid() {
        assert!(parse_tcp_line("").is_none());
        assert!(parse_tcp_line("too short").is_none());
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn test_parse_tcp6_line_invalid() {
        assert!(parse_tcp6_line("").is_none());
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn test_parse_hex_sockaddr_ipv4() {
        let (ip, port) = parse_hex_sockaddr_ipv4("0100007F:1CAB").unwrap();
        assert_eq!(ip, "127.0.0.1");
        assert_eq!(port, 7331);
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn test_parse_hex_sockaddr_ipv4_zero() {
        let (ip, port) = parse_hex_sockaddr_ipv4("00000000:0000").unwrap();
        assert_eq!(ip, "0.0.0.0");
        assert_eq!(port, 0);
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn test_tcp_state_names() {
        assert_eq!(tcp_state_name(0x01), "ESTABLISHED");
        assert_eq!(tcp_state_name(0x0A), "LISTEN");
        assert_eq!(tcp_state_name(0xFF), "UNKNOWN(255)");
    }
}
