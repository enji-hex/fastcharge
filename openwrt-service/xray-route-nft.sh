#!/bin/sh

TABLE_NAME="xray"
MARK="1"
TABLE_NUM="100"

start(){
    # Disable Reverse Path Filtering (rp_filter)
    sysctl -w net.ipv4.conf.all.rp_filter=0 >/dev/null 2>&1
    sysctl -w net.ipv4.conf.default.rp_filter=0 >/dev/null 2>&1
    for f in /proc/sys/net/ipv4/conf/*/rp_filter; do
        echo 0 > "$f" 2>/dev/null
    done

    # Enable IP forwarding
    sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1

    uci set dhcp.@dnsmasq[0].noresolv='1' 2>/dev/null
    uci del dhcp.@dnsmasq[0].server 2>/dev/null
    uci add_list dhcp.@dnsmasq[0].server='127.0.0.1#1053' 2>/dev/null
    uci commit dhcp
    /etc/init.d/dnsmasq restart

    ip rule  add fwmark ${MARK} table ${TABLE_NUM} 2>/dev/null
    ip route add local default dev lo table ${TABLE_NUM} 2>/dev/null

    nft -f - <<EOF
table inet ${TABLE_NAME} {
    set reserved_ip {
        type ipv4_addr
        flags interval
        elements = {
            0.0.0.0/8,
            127.0.0.0/8,
            192.168.0.0/16,
            224.0.0.0/4,
            255.255.255.255/32
        }
    }

    chain prerouting {
        type filter hook prerouting priority mangle; policy accept;

        # Restrict TCP packet size 
        tcp flags syn tcp option maxseg size set 1360

        # Bypass DHCP
        udp dport { 67, 68 } return

        # Bypass LAN / Reserved IPs
        ip daddr @reserved_ip return

        # Reject QUIC (UDP 443)
        udp dport 443 reject

        # Route remaining traffic to proxy
        ip protocol { tcp, udp } tproxy ip to :1080 meta mark set ${MARK} accept
    }
}

# Block IPv6 from bypassing proxy
table ip6 ${TABLE_NAME} {
    chain prerouting {
        type filter hook prerouting priority mangle; policy accept;
        ip6 daddr != ::1 drop
    }
}
EOF
    echo "nft rules and DNS routing applied"
}

stop(){
    uci set dhcp.@dnsmasq[0].noresolv='0'
    uci del dhcp.@dnsmasq[0].server
    uci commit dhcp
    /etc/init.d/dnsmasq restart

    nft delete table inet ${TABLE_NAME} 2>/dev/null
    nft delete table ip6  ${TABLE_NAME} 2>/dev/null
    ip rule  del fwmark ${MARK} table ${TABLE_NUM} 2>/dev/null
    ip route del local default dev lo table ${TABLE_NUM} 2>/dev/null
}

stop
[ "$1" = "start" ] && start