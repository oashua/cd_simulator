#!/usr/bin/env python3
"""cd_simulator 求解管线 CLI（薄包装，逻辑在 windtunnel.runner）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from windtunnel.runner import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
