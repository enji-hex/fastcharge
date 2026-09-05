#!/bin/sh

# --- CLEANUP ---
iptables -t mangle -F XRAY_TCP 2>/dev/null
iptables -t mangle -F XRAY_UDP 2>/dev/null
iptables -t mangle -D PREROUTING -p tcp -j XRAY_TCP 2>/dev/null
iptables -t mangle -D PREROUTING -p udp -j XRAY_UDP 2>/dev/null


if [[ "$1" == "start" ]]; then
    echo "1. Route Policy (CRITICAL)"
    ip rule add fwmark 1 table 100 2>/dev/null
    ip route add local default dev lo table 100 2>/dev/null

    echo "2. Create Chains"
    iptables -t mangle -N XRAY_TCP
    iptables -t mangle -A XRAY_TCP -d 192.168.0.0/16 -j RETURN
    iptables -t mangle -A XRAY_TCP -p tcp -j TPROXY --on-port 1080 --tproxy-mark 1

    echo "3. Apply to PREROUTING (For LAN devices)"
    iptables -t mangle -A PREROUTING -j XRAY_TCP
    
    echo "4. MSS Clamping"
    iptables -t mangle -I FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
fi
