#!/bin/sh

# Navigate to your project directory
cd /home/[path/to/project/]Furnace-Controller/streamlit || exit

# Run streamlit using the specific conda environment's python
/home/[USERNAME]/miniconda3/envs/furnace/bin/streamlit run main.py
