
@echo off
setlocal enabledelayedexpansion

REM One-shot environment setup for the EMG bracelet app (Windows).
REM Creates a virtual environment, installs Python dependencies, and (if
REM arduino-cli is present) installs the ESP32 core and required libraries.

cd /d "%~dp0"

REM 1. Find Python 3.10-3.12. TensorFlow has no Windows wheel for 3.13.
set "PYCMD="
for %%V in (3.12 3.11 3.10) do (
    if not defined PYCMD (
        py -%%V -c "import sys" >nul 2>&1 && set "PYCMD=py -%%V"
    )
)
if not defined PYCMD (
    echo ERROR: need Python 3.10-3.12 ^(3.12 recommended^), 64-bit.
    echo Install it from https://www.python.org/downloads/windows/ , tick
    echo "Add python.exe to PATH" during install, then re-run this script.
    exit /b 1
)
echo Using %PYCMD%
%PYCMD% --version

REM 2. Create the venv.
if not exist ".venv\" (
    %PYCMD% -m venv .venv
    if errorlevel 1 exit /b 1
) else (
    echo Virtual environment already exists. Skipping creation.
)
call .venv\Scripts\activate.bat

REM 3. Install dependencies.
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo pip install failed. Most common cause: wrong Python version.
    echo TensorFlow has no Windows wheel for Python 3.13 - use 3.12.
    exit /b 1
)

REM 4. ESP32 core and Arduino libraries.
where arduino-cli >nul 2>&1
if errorlevel 1 (
    echo NOTE: arduino-cli not found on PATH. To flash the bracelet, install it
    echo       from https://arduino.github.io/arduino-cli/latest/installation/
) else (
    REM Pin arduino-cli's data dir to an ASCII path (C:\Arduino15).
    set "ARDUINO_CFG=C:\Arduino15\arduino-cli.yaml"
    if not exist "C:\Arduino15" mkdir "C:\Arduino15"

    if not exist "!ARDUINO_CFG!" (
        (
            echo board_manager:
            echo     additional_urls: []
            echo directories:
            echo     data: C:\Arduino15
            echo     downloads: C:\Arduino15\staging
            echo     user: %USERPROFILE%\Documents\Arduino
        ) > "!ARDUINO_CFG!"
        echo Created !ARDUINO_CFG! ^(arduino-cli data dir pinned to C:\Arduino15^)
    )

    REM 4-1. Check and install ESP32 core.
    echo.
    echo Checking ESP32 core...

    arduino-cli --config-file "!ARDUINO_CFG!" core list | findstr /B /C:"esp32:esp32 " >nul

    if errorlevel 1 (
        echo Installing ESP32 core...
        arduino-cli --config-file "!ARDUINO_CFG!" core update-index
        if errorlevel 1 (
            echo ERROR: Failed to update ESP32 index.
            exit /b 1
        )

        arduino-cli --config-file "!ARDUINO_CFG!" core install esp32:esp32
        if errorlevel 1 (
            echo ERROR: Failed to install ESP32 core.
            exit /b 1
        )
    ) else (
        echo ESP32 core already installed. Skipping.
    )

    REM 4-2. Check and install required Arduino libraries.
    echo.
    echo Checking Arduino libraries...

    for %%L in ("Adafruit NeoPixel" "Adafruit Unified Sensor" "Adafruit BNO055") do (
        arduino-cli --config-file "!ARDUINO_CFG!" lib list | findstr /I /C:"%%~L" >nul

        if errorlevel 1 (
            echo Installing %%~L...
            arduino-cli --config-file "!ARDUINO_CFG!" lib install "%%~L"

            if errorlevel 1 (
                echo ERROR: Failed to install %%~L.
                exit /b 1
            )
        ) else (
            echo %%~L already installed. Skipping.
        )
    )
)

echo.
echo Done. Run the app with:
echo     .venv\Scripts\activate.bat
echo     python client_app\main.py
endlocal
