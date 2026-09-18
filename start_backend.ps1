# 后端启动脚本
# 使用脚本文件避免 PowerShell 终端对 --reload-exclude "*.db*" 的通配符展开问题
Set-Location $PSScriptRoot
& .\.venv\Scripts\python.exe -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload --reload-exclude "*.db*"
