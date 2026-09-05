#!/bin/sh

# XRAY-ROUTE
# Could be used anywhere Magisk/Raw Linux
SERVER_IP=127.0.0.1

LAN_IF=enp27s0
TUN_IF=xray0
XRAY_CONF=./xray.conf.json

STATE_FILE="/tmp/xray-route.state"
PID_FILE="/tmp/xray.pid"
LOG_FILE="/tmp/xray.log"

# exec all as root
[ "$(id -u)" -eq 0 ] || { echo "must run as root"; exit 1; }

vpn_on(){
    # remove stale pid
    if [ -f "$PID_FILE" ] && ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        rm -f "$PID_FILE"
    fi
    
    # prevent double start
    if [ -f "$PID_FILE" ]; then
        echo "already running"
        return 0
    fi
    
    # save default route
    ip route show default | head -n1 > "$STATE_FILE"
    LAN_GW="$(awk '/default/ {print $3}' "$STATE_FILE")" # lan gateway
    [ -n "$LAN_GW" ] || return 1

    xray run -c "$XRAY_CONF" >"$LOG_FILE" 2>&1 &
    echo "$!" > "$PID_FILE"
        
    i=0
    while [ "$i" -lt 50 ]; do
        ip link show "$TUN_IF" >/dev/null 2>&1 && break # wait for TUN UP
        sleep 1
        i=$(( i+1 ))
    done

    # cleanup if TUN still DOWN
    if ! ip link show "$TUN_IF" >/dev/null 2>&1 ; then
        kill "$(cat "$PID_FILE")" 2>/dev/null || true
        rm -f "$PID_FILE"
        return 1
    fi

    ip route del default                                        # remove previous default route
    ip route replace "$SERVER_IP" via "$LAN_GW" dev "$LAN_IF"   # route VPN traffic outside TUN
    ip route replace default dev $TUN_IF                        # route everything else via TUN

    echo "* SystemWide VPN ON"
    ip route
}

vpn_off(){
    [ -f "$STATE_FILE" ] && ip route replace $(cat "$STATE_FILE")
    ip route del "$SERVER_IP" 2>/dev/null || true

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        kill -0 "$PID" 2>/dev/null && kill "$PID" 2>/dev/null || true
        rm -f "$PID_FILE"
    fi

    rm -f "$STATE_FILE"
    
    echo "* SystemWide VPN OFF"
    ip route
}

case "$1" in
    start)      vpn_on             ;;
    stop)       vpn_off            ;;
    restart)    vpn_off; vpn_on    ;;
    *) echo "usage: $0 {start|stop|restart}"; exit 1 ;;
esac