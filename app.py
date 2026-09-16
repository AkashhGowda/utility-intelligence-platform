from pathlib import Path
import runpy

from services.admin_ui import render_admin_control_center


# Keep the established operational application as the single source of page logic.
runpy.run_path(
    str(Path(__file__).with_name("app_backup_before_admin_ui.py")),
    run_name="__main__",
)
