from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from GetMail.mail_service import health_snapshot, lookup_mailbox

STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="GetMail",
    description="使用 mail_token 查询 Resend 收件箱中的最新验证码和邮件摘要。",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class MailboxLookupRequest(BaseModel):
    mail_token: str = Field(..., min_length=8, description="注册项目生成的邮箱查询 token")
    timeout: int = Field(default=15, ge=0, le=120, description="查询等待秒数")
    limit: int = Field(default=10, ge=1, le=20, description="返回的最新邮件条数")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return health_snapshot()


@app.post("/api/mailbox/lookup")
def mailbox_lookup(req: MailboxLookupRequest) -> dict:
    try:
        return lookup_mailbox(req.mail_token, timeout=req.timeout, limit=req.limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"mail_token 无效: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"邮件查询失败: {e}") from e


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("GETMAIL_HOST", "0.0.0.0")
    port = int(os.environ.get("GETMAIL_PORT", "8021"))
    uvicorn.run("GetMail.app:app", host=host, port=port, reload=False)
