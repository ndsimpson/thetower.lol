import os

import streamlit as st
from streamlit import source_util
from streamlit.runtime.scriptrunner import get_script_run_ctx

page = "live/live_progress.py"  # MODIFY TO YOUR PAGE

ctx = get_script_run_ctx()
ctx_main_script = ""
if ctx:
    ctx_main_script = ctx.main_script_path

st.write("**Main Script File**")
st.text(f"\"{ctx_main_script}\"")

st.write("**Current Working Directory**")
st.text(f"\"{os.getcwd()}\"")

st.write("**Normalized Current Working Directory**")
st.text(f"\"{os.path.normpath(os.getcwd())}\"")

st.write("**Main Script Path**")
main_script_path = os.path.join(os.getcwd(), ctx_main_script)
st.text(f"\"{main_script_path}\"")

st.write("**Main Script Directory**")
main_script_directory = os.path.dirname(main_script_path)
st.text(f"\"{main_script_directory}\"")

st.write("**Normalized Path**")
page = os.path.normpath(page)
st.text(f"\"{page}\"")

st.write("**Requested Page**")
requested_page = os.path.join(main_script_directory, page)
st.text(f"\"{requested_page}\"")

st.write("**All Pages Page**")
all_app_pages = list(source_util.get_pages(ctx_main_script).values())
st.json(all_app_pages, expanded=True)

st.page_link(page, label="Go to page")