#!/bin/sh

ROUTER="root@192.168.1.1"
MNT="/mnt/usb"

echo "Copying files to router..."
scp ./XRAY_CONN/openwrt/config.json         "$ROUTER:$MNT/"
scp ./XRAY_CONN/openwrt/xray-route-nft.sh   "$ROUTER:$MNT/"
scp ./XRAY_CONN/openwrt/xray-ow             "$ROUTER:/etc/init.d/"

scp -r ./XRAY_CONN/openwrt/www/.            "$ROUTER:/www/"

echo "Setting permissions..."

# exit 0

ssh "$ROUTER" <<EOF
chmod +x $MNT/xray-route-nft.sh /etc/init.d/xray-ow

uci set uhttpd.main.home='/www'
uci set uhttpd.main.index_page='index.html'

uci delete uhttpd.main.cgi_prefix 2>/dev/null
uci add_list uhttpd.main.cgi_prefix='/cgi-bin'

uci delete uhttpd.main.error_page 2>/dev/null
uci commit uhttpd
/etc/init.d/uhttpd restart # start web server

EOF
