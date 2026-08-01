"""python -m signalvault 与 Briefcase .app 的统一入口。"""

import sys
from pathlib import Path

# .app bundle 内运行时走桌面 launcher，命令行带参数时走 CLI
_IN_APP_BUNDLE = ".app/Contents/" in str(Path(__file__).resolve())

if _IN_APP_BUNDLE or len(sys.argv) <= 1:
    from signalvault.app import main

    sys.exit(main())
else:
    from signalvault.cli import app

    app()
