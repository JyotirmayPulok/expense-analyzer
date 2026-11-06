"""Entry point for Streamlit Community Cloud (it looks for streamlit_app.py by default).

Runs app.py, so `streamlit run app.py` and `streamlit run streamlit_app.py` behave the same.
"""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
