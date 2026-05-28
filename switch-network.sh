#!/bin/bash

# ── Connection profiles (adjust names to match your system) ──
ETH0_CONN="Wired connection 1"   # eth0: NAT / internet (192.168.5.x)
ETH2_CONN="cs-lab"               # eth2: AD lab       (192.168.6.20)

# ── Static IP for AD lab ──
AD_LAB_IP="192.168.6.20/24"      # AD DC is at 192.168.6.10


# ── Help ──
if [ "$1" == "help" ] || [ -z "$1" ]; then
    echo "Usage: $0 [nat|lab|both|status]"
    echo ""
    echo "  nat    — Internet only          (eth0 up, eth2/eth1 down)"
    echo "  lab    — AD lab only (isolated) (eth2 up, eth0 down)"
    echo "  both   — Internet + AD lab      (eth0 + eth2 together)"
    echo "  status — Show current IPs and routes"
    exit 1
fi


# ── ORIGINAL: nat mode (unchanged from your backup) ──
if [ "$1" == "nat" ]; then
    echo "Switching to NAT (eth0)..."
    nmcli connection modify "$ETH2_CONN" ipv4.never-default yes
    nmcli connection modify "$ETH0_CONN" ipv4.never-default no
    nmcli connection down "$ETH2_CONN" && nmcli connection up "$ETH2_CONN"
    nmcli connection down "$ETH0_CONN" && nmcli connection up "$ETH0_CONN"
    echo "Default route now via eth0."


# ── ORIGINAL: lab mode (unchanged from your backup) ──
elif [ "$1" == "lab" ]; then
    echo "Switching to homelab (eth2)..."
    nmcli connection modify "$ETH0_CONN" ipv4.never-default yes
    nmcli connection modify "$ETH2_CONN" ipv4.never-default no
    nmcli connection down "$ETH0_CONN" && nmcli connection up "$ETH0_CONN"
    nmcli connection down "$ETH2_CONN" && nmcli connection up "$ETH2_CONN"
    echo "Default route now via eth2."


# ── NEW: both mode — NAT (eth0) + AD lab (eth2) together ──
elif [ "$1" == "both" ]; then
    echo "Switching to NAT + AD lab..."
    echo ""

    # eth0 — default route for internet
    echo "  -> Bringing up eth0 (NAT) for internet..."
    nmcli connection modify "$ETH0_CONN" ipv4.never-default no
    nmcli connection down "$ETH0_CONN" 2>/dev/null
    nmcli connection up "$ETH0_CONN"

    # eth2 — AD lab static IP, no default route
    echo "  -> Bringing up eth2 (AD lab) as ${AD_LAB_IP} ..."
    nmcli connection modify "$ETH2_CONN" \
        ipv4.method manual \
        ipv4.addresses "$AD_LAB_IP" \
        ipv4.gateway "" \
        ipv4.dns "" \
        ipv4.ignore-auto-dns yes \
        ipv4.never-default yes
    nmcli connection down "$ETH2_CONN" 2>/dev/null
    nmcli connection up "$ETH2_CONN"

    echo ""
    echo "[✓] Internet + AD lab active"
    echo ""
    echo "  Interface        IP                      Role"
    echo "  ─────────────────────────────────────────────────"
    dev0=$(nmcli -t -f GENERAL.DEVICES connection show "$ETH0_CONN" 2>/dev/null | head -1 | cut -d: -f2)
    ip0=$(ip -4 -o addr show "$dev0" 2>/dev/null | awk '{print $4}' | head -1)
    printf "  %-16s %-23s %s\n" "$dev0" "${ip0:-?}" "NAT / internet (default route)"

    dev2=$(nmcli -t -f GENERAL.DEVICES connection show "$ETH2_CONN" 2>/dev/null | head -1 | cut -d: -f2)
    ip2=$(ip -4 -o addr show "$dev2" 2>/dev/null | awk '{print $4}' | head -1)
    printf "  %-16s %-23s %s\n" "$dev2" "${ip2:-?}" "AD lab (isolated, no default)"

    echo ""
    echo "  Default route:"
    ip route show default | sed 's/^/    /'
    echo ""
    echo "  Test AD DC:  ping -c 1 192.168.6.10"
    echo "  Test internet: ping -c 1 8.8.8.8"


# ── Status ──
elif [ "$1" == "status" ]; then
    echo "Current network state:"
    echo ""
    for conn in "$ETH0_CONN" "$ETH2_CONN"; do
        dev=$(nmcli -t -f GENERAL.DEVICES connection show "$conn" 2>/dev/null | head -1 | cut -d: -f2)
        if [ -n "$dev" ]; then
            ip=$(ip -4 -o addr show "$dev" 2>/dev/null | awk '{print $4}' | head -1)
            echo "  ${conn}:  ${dev}  ${ip:-UP (no IPv4)}"
        else
            echo "  ${conn}:  (inactive)"
        fi
    done
    echo ""
    echo "  Default route(s):"
    ip route show default | sed 's/^/    /'


else
    echo "Unknown mode: $1"
    echo "Usage: $0 [nat|lab|both|status]"
    exit 1
fi
