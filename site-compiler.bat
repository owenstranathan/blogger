@echo off

set dirname=%~dp0
call py %dirname%/site-compiler.py %*
