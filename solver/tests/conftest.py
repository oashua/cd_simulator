import sys
from pathlib import Path

# 让 pytest 无需安装即可 import windtunnel
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
