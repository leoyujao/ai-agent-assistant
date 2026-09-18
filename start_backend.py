"""
后端启动入口
用 Python 内部传参启动 uvicorn，避免 PowerShell 对 --reload-exclude "*.db*" 的通配符展开问题
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=["*.db*"],  # 排除 checkpoints.db 等数据库文件，防止写入触发无限重载
    )
