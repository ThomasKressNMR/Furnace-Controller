@echo off
REM Initialize and activate the conda environment, then change directory and run Streamlit
call C:\ProgramData\miniconda3\Scripts\activate.bat furnace
cd /d C:\Users\Forse\Documents\Temperature_logging\streamlit
streamlit run streamlit_app.py
pause