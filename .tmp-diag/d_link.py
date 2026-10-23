import os, sys
sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ['SPUG_DATA_DIR'] = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
import django; django.setup()
from apps.host.models import Host
from apps.ops.kernel.inventory import build_inventory, inject_private_keys
from pyinfra.api import Config, State
from pyinfra.api.connect import connect_all, disconnect_all
from pyinfra.api.state import StateStage
from pyinfra.facts.files import Link, File, Directory

ip, pwd, usr = sys.argv[1], sys.argv[2], sys.argv[3]
h = Host(id=999, name='l', hostname=ip, port=22, username=usr)
h.password = pwd
inv, _ = build_inventory([h])
st = State(inv, Config(PARALLEL=1, CONNECT_TIMEOUT=10))
inject_private_keys(st, [h])
ph = list(inv)[0]
try:
    st.set_stage(StateStage.Connect); connect_all(st)
    for p in ('/tmp/spug-idem/link', '/tmp/spug-idem/file.txt'):
        print(p, 'Link=', ph.get_fact(Link, path=p), 'File=', ph.get_fact(File, path=p))
finally:
    st.set_stage(StateStage.Disconnect); disconnect_all(st)
