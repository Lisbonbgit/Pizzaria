@echo off
REM Compila PrintBridge.exe usando o compilador C# que ja vem no Windows.
set CSC=C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
  echo Nao encontrei o csc.exe do .NET Framework. Este PC precisa do .NET Framework 4.x.
  pause & exit /b 1
)
"%CSC%" /nologo /platform:x86 /reference:System.Web.Extensions.dll /reference:System.Drawing.dll /out:PrintBridge.exe PrintBridge.cs
if errorlevel 1 ( echo FALHOU a compilacao. & pause & exit /b 1 )
echo OK: PrintBridge.exe criado.
PrintBridge.exe --selftest
pause
