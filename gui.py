import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run_qt():
    try:
        from gui_qt import main
        main()
        return True
    except Exception:
        return False


def run_tk():
    from gui_tk import ModernTrackerUI
    ModernTrackerUI().run()


if __name__ == "__main__":
    if os.environ.get("CONDA_DEFAULT_ENV") == "luoke_qt":
        if not run_qt():
            run_tk()
    else:
        try:
            subprocess.Popen(["conda", "run", "-n", "luoke_qt", "python", str(ROOT / "gui_qt.py")], cwd=str(ROOT))
        except Exception:
            if not run_qt():
                run_tk()
