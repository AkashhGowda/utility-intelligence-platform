from pathlib import Path
import runpy

# Use the current dynamic application entry instead of the legacy static backup.
runpy.run_path(
    str(Path(__file__).with_name("main_app.py")),
    run_name="__main__",
)
