"""
后端启动入口
用 Python 内部传参启动 uvicorn，避免 PowerShell 对 --reload-exclude "*.db*" 的通配符展开问题
"""
import os

import uvicorn

if __name__ == "__main__":
    # 默认只监听本机。这个后端没有鉴权，绑 0.0.0.0 等于让同网段的任何人都能
    # 调用它、消耗你的 API Key。需要局域网或容器访问时再显式设 HOST=0.0.0.0。
    host = os.getenv("HOST", "127.0.0.1")

    uvicorn.run(
        "api:app",
        host=host,
        port=int(os.getenv("PORT", "8000")),
        reload=True,
        reload_excludes=["*.db*"],  # 排除 checkpoints.db 等数据库文件，防止写入触发无限重载
    )
