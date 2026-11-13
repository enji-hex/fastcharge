#!/bin/sh

VLESS_URL="$1"
CONFIG_FILE="$2"

# 1. Extract components using sed / cut
TMP="${VLESS_URL#vless://}"
UUID="${TMP%%@*}"
HOST_PORT="${TMP#*@}"
HOST_PORT="${HOST_PORT%%\?*}"
HOST="${HOST_PORT%%:*}"
PORT="${HOST_PORT##*:}"

QUERY="${VLESS_URL#*\?}"
QUERY="${QUERY%%#*}"

# Decode URL-encoded fragment (handles emojis and spaces like %F0%9F...)
# TAG is static (proxy)
# FRAGMENT="${VLESS_URL##*#}"
# TAG=$(printf '%b' "${FRAGMENT//%/\\x}")

# Helper function to extract query parameters
get_param() {
    echo "$QUERY" | tr '&' '\n' | grep "^$1=" | cut -d= -f2
}

FLOW=$(get_param "flow")
FP=$(get_param "fp")
HEADER_TYPE=$(get_param "headerType")
PBK=$(get_param "pbk")
SECURITY=$(get_param "security")
SID=$(get_param "sid")
SNI=$(get_param "sni")
TYPE=$(get_param "type")

# Fallback defaults if missing
[ -z "$PORT" ] && PORT=443
[ -z "$TAG" ]  && TAG="vless-reality-node"

echo "Parsed Node: $TAG ($HOST:$PORT)"

# 2. Build the Xray Outbound JSON using jq
NEW_OUTBOUND=$(jq -n \
    --arg tag "proxy" \
    --arg address "$HOST" \
    --argjson port "$PORT" \
    --arg id "$UUID" \
    --arg flow "$FLOW" \
    --arg network "$TYPE" \
    --arg security "$SECURITY" \
    --arg fp "$FP" \
    --arg pbk "$PBK" \
    --arg sid "$SID" \
    --arg sni "$SNI" \
    --arg headerType "$HEADER_TYPE" \
    '{
      tag: $tag,
      protocol: "vless",
      settings: {
        vnext: [{
          address: $address,
          port: $port,
          users: [{
            id: $id,
            flow: ($flow // empty),
            encryption: "none",
            level: 0
          }]
        }]
      },
      streamSettings: {
        network: ($network // "tcp"),
        security: ($security // "none"),
        realitySettings: {
          show: false,
          fingerprint: ($fp // "chrome"),
          publicKey: $pbk,
          shortId: ($sid // ""),
          serverName: $sni,
          spx: ""
        },
        tcpSettings: {
          header: {
            type: ($headerType // "none")
          }
        }
      }
    }')

jq --argjson new_out "$NEW_OUTBOUND" \
   --arg ip "$HOST" \
   '.outbounds = [$new_out] |
    .routing.rules |= map(if .outboundTag == "direct" then .ip = [$ip] else . end)' \
   "$CONFIG_FILE" > "${CONFIG_FILE}.tmp" && mv "${CONFIG_FILE}.tmp" "$CONFIG_FILE"