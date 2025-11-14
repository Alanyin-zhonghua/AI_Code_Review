#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GUI 应用启动脚本。"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 导入并运行 GUI
from agent_core.gui.test_gui import main

if __name__ == "__main__":
    main()
