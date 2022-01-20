@echo off

set dirname=%~dp0
set PYTHONPATH=%dirname%
for /f "delims=" %%i in ('python -m blogger.appvars') do set RESULT=%%i
SET venv=%RESULT%\app\.venv

if not exist %venv% (
	echo Creating python virtual env at %venv%
	python -m venv %venv%
)

REM on non-windows platforms the python and pip binaries will be under .venv/bin rather than .venv\Scripts
SET python=%venv%\Scripts\python.exe
SET pip=%venv%\Scripts\pip.exe

"%pip%" install -r "%dirname%/requirements.txt" --quiet --disable-pip-version-check
IF %ERRORLEVEL% NEQ 0 (
	EXIT /B %ERRORLEVEL%
)


"%python%" -m blogger.blogger %*
