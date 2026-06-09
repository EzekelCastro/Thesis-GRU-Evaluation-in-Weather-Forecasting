"""
app.py
Navigation entry point — routes between Variable Importance and Model Evaluation pages.

Run with:
    streamlit run app.py
"""

import streamlit as st

st.set_page_config(
    page_title="Weather Prediction Comparison",
    page_icon="🌤",
    layout="wide",
    initial_sidebar_state="expanded",
)

pg = st.navigation([
    st.Page("pages/2_Variable_Importance.py", title="Variable Importance", icon="📊"),
    st.Page("pages/model_evaluation.py",      title="Model Evaluation",    icon="🌤"),
])
pg.run()
