@echo off
echo ====================================================
echo Starting Git Push to github.com/diptesh224/doctask-diptesh-narendra
echo ====================================================
echo.

:: Ensure origin is set correctly
git remote remove origin >nul 2>&1
git remote add origin https://diptesh224@github.com/diptesh224/doctask-diptesh-narendra.git

:: Push to remote main branch
echo Triggering Git push...
echo (A browser window or popup will appear shortly asking you to authenticate with GitHub. Please approve it.)
echo.
git push -u origin main

echo.
echo ====================================================
echo Git Push completed.
echo ====================================================
pause
