import os, sys, json
sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ['SPUG_DATA_DIR'] = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
import django
django.setup()
from apps.ops.views import FactView
from apps.ops.models import HostFact
from libs import JsonParser, Argument
from libs.utils import json_response

# 直接调用视图函数本体（绕过 auth 装饰器）
view = FactView.get.__wrapped__ if hasattr(FactView.get, '__wrapped__') else FactView.get
print('has wrapped:', hasattr(FactView.get, '__wrapped__'))
