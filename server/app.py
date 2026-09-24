#业务逻辑都在 agent_runner.py 和 agent/ 里，这里只做“接口”
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
#直接返回一个文件（比如 index.html）。
from fastapi.staticfiles import StaticFiles
#挂载静态目录（CSS、JS）。
from pydantic import BaseModel
#BaseModel自动校验检查，输出不符合规范直接输出422错误

from server.agent_runner import chat, reset_history
from agent.calendar_store import add_event, list_events, update_event, delete_event
from agent.ics_exporter import build_ics, send_ics_email
from fastapi.responses import Response

from agent.pending_store import (
    load_pending,
    add_pending,
    delete_pending,
    update_pending,
    pop_pending,
)

BASE_DIR = Path(__file__).parent.parent  #这里的 __file__ 是 server/app.py，找的是当前.py文件
#.parent返回上一级目录，BASE_DIR = ...\the_kings_hand
STATIC_DIR = BASE_DIR / "static"
#F:\Project_2_langchain\the_kings_hand / "static"= F:\Project_2_langchain\the_kings_hand\static

app = FastAPI() #将FastAPI应用于app

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
#任何 /static/xxx 的请求，都去 STATIC_DIR 里找文件。

class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    output: str
    steps: list
    tasks: list = []  #指默认返回空表格


class AddPendingRequest(BaseModel):
    id: str
    title: str
    start: str | None = None
    end: str | None = None
    location: str = ""
    note: str = ""


class IdRequest(BaseModel):
    id: str


class UpdatePendingRequest(BaseModel):
    id: str
    title: str
    start: str | None = None
    end: str | None = None
    location: str = ""
    note: str = ""

class ExportEmailRequest(BaseModel):
    to_email: str

class EventUpdateRequest(BaseModel):
    id: str
    title: str
    start: str
    end: str
    location: str = ""
    note: str = ""


class EventDeleteRequest(BaseModel):
    id: str


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
#浏览器访问 http://127.0.0.1:8000 时，直接把 static/index.html 返回去。


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest):
    result = chat(req.message)
    return result


@app.post("/reset")
def reset_endpoint():
    reset_history()
    return {"status": "ok"}


@app.get("/events")
def list_events_endpoint():
    return {"events": list_events()}


@app.get("/pending")
def pending_endpoint():
    return load_pending()


@app.post("/pending/add")
def add_pending_endpoint(req: AddPendingRequest):
    add_pending(req.model_dump())
    return {"status": "ok"}


@app.post("/pending/delete")
def delete_pending_endpoint(req: IdRequest):
    ok = delete_pending(req.id)
    return {"status": "ok" if ok else "not_found"}


@app.post("/pending/update")
def update_pending_endpoint(req: UpdatePendingRequest):
    fields = {
        "title": req.title,
        "start": req.start,
        "end": req.end,
        "location": req.location,
        "note": req.note,
    }
    result = update_pending(req.id, fields)
    if result is None:
        return {"status": "not_found"}
    return {"status": "ok", "task": result}


@app.post("/pending/confirm")
def confirm_pending_endpoint(req: IdRequest):
    task = pop_pending(req.id)
    if task is None:
        return {"status": "not_found"}
    event = add_event(
        task["title"],
        task["start"],
        task["end"],
        task.get("location", ""),
        task.get("note", ""),
    )
    return {"status": "ok", "event": event}

@app.get("/export_ics")
def export_ics_endpoint():
    events = list_events()
    ics_text = build_ics(events)
    return Response(
        content=ics_text,
        media_type="text/calendar",
        headers={
            "Content-Disposition": 'attachment; filename="the_kings_hand.ics"'
        },
    )

@app.post("/export_email")
def export_email_endpoint(req: ExportEmailRequest):
    events = list_events()
    ok, msg = send_ics_email(events, req.to_email)
    return {"status": "ok" if ok else "error", "message": msg}

@app.post("/event/update")
def event_update_endpoint(req: EventUpdateRequest):
    fields = {
        "title": req.title,
        "start": req.start,
        "end": req.end,
        "location": req.location,
        "note": req.note,
    }
    result = update_event(req.id, fields)
    if result is None:
        return {"status": "not_found"}
    return {"status": "ok", "event": result}


@app.post("/event/delete")
def event_delete_endpoint(req: EventDeleteRequest):
    ok = delete_event(req.id)
    return {"status": "ok" if ok else "not_found"}