@echo off
cd /d "C:\Users\mariu\Downloads\mm_engine\analysis"
echo ===== %date% %time% ===== >> "C:\Users\mariu\Downloads\hedging_strategy\analysis_data\mm_babysit.log"
python mm_babysit.py --brief >> "C:\Users\mariu\Downloads\hedging_strategy\analysis_data\mm_babysit.log" 2>&1
