@echo off
title SynapseRAG Launcher
echo =======================================================
echo          Starting SynapseRAG Unified Stack
echo =======================================================
python run_all.py
if errorlevel 1 (
    echo Error starting SynapseRAG. Press any key to exit.
    pause
)
