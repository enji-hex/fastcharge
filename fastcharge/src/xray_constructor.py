
from pathlib import Path
from urllib.parse import urlsplit,unquote
import json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLIENT_SRC_CONFIG_PATH  = PROJECT_ROOT / "local" / "config.client.json"
ROUTING_SRC_CONFIG_PATH = PROJECT_ROOT / "local" / "routing" 

# generate XRAY client config from vless link
def export_xray_config(vless_link:str, routing_name:str):
    data = urlsplit(vless_link)
    id = data.username
    ip = data.hostname
    port = data.port
    
    query = dict(map(
        lambda part: part.split('='),
        data.query.split('&')) # apply lambda for EACH url KV part
        )
    tag = unquote(data.fragment)

    routing_path = (ROUTING_SRC_CONFIG_PATH / routing_name)
    if not routing_path.exists(): raise Exception("Invalid routing")
    
    client_conf = json.loads(Path.read_text(CLIENT_SRC_CONFIG_PATH))
    routing_conf = json.loads(routing_path.read_text())
    
    
    routing_conf['routing'].get('rules',[]).insert(0,{
        "type":"field",
        "ip":[ip],
        "outboundTag":"direct"
    })
    routing_conf['routing']['rules'].append(
        {
            "type": "field",
            "network": "udp,tcp",
            "outboundTag": tag
    })
        

    client_conf['routing']  = routing_conf['routing']
    client_conf['inbounds'] = routing_conf['inbounds']

    # set custom dns if exists
    if routing_conf.get('dns'):
        client_conf['dns'] = routing_conf['dns']

    for o in client_conf['outbounds']:
        if routing_name == "tproxy.json" and o['tag']=="direct":
            o['streamSettings'] = {
                "sockopt": {
                    "mark": 255
                }
            }
        if o['tag'] == 'vless':
            o['tag'] = tag
            vnext = o['settings']['vnext'][0]
            vnext['address'] = ip
            vnext['port']    = port
            vnext['users']  = [
                {
                   "id":id,
                   "encryption":query.get('encryption','none')
                }]
            if query.get('flow'):
                vnext['users'][0]['flow'] = query['flow']

            o['streamSettings']['network'] = query['type']
            o['streamSettings']['security'] = query['security']
            o['streamSettings']['realitySettings']['serverName'] = query['sni']
            o['streamSettings']['realitySettings']['fingerprint'] = query['fp']
            o['streamSettings']['realitySettings']['publicKey'] = query['pbk']
            o['streamSettings']['realitySettings']['shortId'] = query['sid']
            if routing_name == "tproxy.json":
                o['streamSettings']['sockopt'] = {
                    "mark": 255
                }

    return client_conf
