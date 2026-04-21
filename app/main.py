import os
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import date
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from dotenv import load_dotenv

from app.database import get_db, init_db, async_session
from app.models import Project, Task, TeamMember, User
from app.auth import verify_password, create_token, decode_token, hash_password, auth_check
from app.seed import seed_database
from app.agent import assign_task, detect_risks, generate_report, analyze_budget
from app.i18n import get_t

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def get_lang(request: Request) -> str:
    return request.cookies.get("pf_lang", "en")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with async_session() as db:
        await seed_database(db)
    yield


app = FastAPI(title="Projects Factory PM", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(url="/dashboard" if auth_check(request) else "/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if auth_check(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    lang = get_lang(request)
    return templates.TemplateResponse(request, "login.html", {"t": get_t(lang), "lang": lang})


@app.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    lang = get_lang(request)
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request, "login.html", {
            "t": get_t(lang), "lang": lang,
            "error": "Invalid credentials" if lang == "en" else "Credenciales incorrectas"
        })
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie("access_token", create_token(email), httponly=True, max_age=3600 * 8)
    return response


@app.get("/logout")
async def logout():
    r = RedirectResponse(url="/login", status_code=302)
    r.delete_cookie("access_token")
    return r


@app.get("/lang/{lang}")
async def set_lang(lang: str, request: Request):
    r = RedirectResponse(url=request.headers.get("referer", "/dashboard"), status_code=302)
    r.set_cookie("pf_lang", lang if lang in ("en", "es") else "en")
    return r


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        return RedirectResponse(url="/login", status_code=302)
    lang = get_lang(request)
    projects = (await db.execute(select(Project).order_by(Project.created_at.desc()))).scalars().all()
    total_budget = sum(p.budget for p in projects)
    total_spent = sum(p.spent for p in projects)
    active = [p for p in projects if p.status == "active"]
    avg_progress = round(sum(p.progress for p in projects) / len(projects), 1) if projects else 0
    return templates.TemplateResponse(request, "dashboard.html", {
        "t": get_t(lang), "lang": lang,
        "projects": projects, "total_budget": total_budget, "total_spent": total_spent,
        "active_count": len(active), "avg_progress": avg_progress,
    })


@app.get("/projects", response_class=HTMLResponse)
async def projects_page(request: Request, status: str = None, search: str = None, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        return RedirectResponse(url="/login", status_code=302)
    lang = get_lang(request)
    q = select(Project).order_by(Project.created_at.desc())
    if status:
        q = q.where(Project.status == status)
    if search:
        q = q.where(Project.name.ilike(f"%{search}%") | Project.client.ilike(f"%{search}%"))
    projects = (await db.execute(q)).scalars().all()
    return templates.TemplateResponse(request, "projects.html", {
        "t": get_t(lang), "lang": lang,
        "projects": projects, "filter_status": status or "", "search": search or "",
    })


@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: int, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        return RedirectResponse(url="/login", status_code=302)
    lang = get_lang(request)
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404)
    tasks = (await db.execute(select(Task).where(Task.project_id == project_id).order_by(Task.priority.desc()))).scalars().all()
    team = (await db.execute(select(TeamMember))).scalars().all()
    statuses = ["backlog", "todo", "in_progress", "review", "done"]
    kanban = {s: [t for t in tasks if t.status == s] for s in statuses}
    return templates.TemplateResponse(request, "project_detail.html", {
        "t": get_t(lang), "lang": lang,
        "project": project, "tasks": tasks, "kanban": kanban, "team": team,
        "now_date": date.today().strftime("%Y-%m-%d"),
    })


@app.post("/tasks/{task_id}/status")
async def update_task_status(task_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        raise HTTPException(status_code=401)
    data = await request.json()
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404)
    task.status = data.get("status", task.status)
    await db.commit()
    return JSONResponse({"ok": True})


@app.post("/api/agent/assign/{task_id}")
async def api_assign(task_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        raise HTTPException(status_code=401)
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404)
    team = (await db.execute(select(TeamMember))).scalars().all()
    result = await assign_task(task, team, get_lang(request))
    return JSONResponse({"result": result})


@app.post("/api/agent/risks/{project_id}")
async def api_risks(project_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        raise HTTPException(status_code=401)
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404)
    tasks = (await db.execute(select(Task).where(Task.project_id == project_id))).scalars().all()
    result = await detect_risks(project, list(tasks), get_lang(request))
    return JSONResponse({"result": result})


@app.post("/api/agent/report/{project_id}")
async def api_report(project_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        raise HTTPException(status_code=401)
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404)
    tasks = (await db.execute(select(Task).where(Task.project_id == project_id))).scalars().all()
    result = await generate_report(project, list(tasks), get_lang(request))
    return JSONResponse({"result": result})


@app.post("/api/agent/budget/{project_id}")
async def api_budget(project_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        raise HTTPException(status_code=401)
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404)
    tasks = (await db.execute(select(Task).where(Task.project_id == project_id))).scalars().all()
    result = await analyze_budget(project, list(tasks), get_lang(request))
    return JSONResponse({"result": result})
