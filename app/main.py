import os
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import date
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from dotenv import load_dotenv

from app.database import get_db, init_db, async_session, engine, DATABASE_URL
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
async def lifespan(_app: FastAPI):
    await init_db()
    # Migration: add columns introduced after initial deploy
    async with engine.begin() as conn:
        for stmt in [
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS start_date DATE",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS budget FLOAT DEFAULT 0",
        ] if not DATABASE_URL.startswith("sqlite") else [
            "ALTER TABLE tasks ADD COLUMN progress INTEGER DEFAULT 0",
            "ALTER TABLE tasks ADD COLUMN start_date DATE",
            "ALTER TABLE tasks ADD COLUMN budget FLOAT DEFAULT 0",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # column already exists
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
    task_budget_allocated = sum(t.budget for t in tasks)
    return templates.TemplateResponse(request, "project_detail.html", {
        "t": get_t(lang), "lang": lang,
        "project": project, "tasks": tasks, "kanban": kanban, "team": team,
        "now_date": date.today().strftime("%Y-%m-%d"),
        "task_budget_allocated": task_budget_allocated,
    })


# ── Projects CRUD ───────────────────────────────────────────────────────────

@app.post("/projects")
async def create_project(request: Request, db: AsyncSession = Depends(get_db),
    name: str = Form(...), client: str = Form(""), category: str = Form("tecnología"),
    status: str = Form("planning"), budget: float = Form(0), spent: float = Form(0),
    progress: int = Form(0), start_date: str = Form(...), end_date: str = Form(...),
    description: str = Form(""), owner: str = Form("Demo User")):
    if not auth_check(request):
        return RedirectResponse(url="/login", status_code=302)
    from datetime import date as dt
    p = Project(name=name, client=client, category=category, status=status,
                budget=budget, spent=spent, progress=min(100, max(0, progress)),
                start_date=dt.fromisoformat(start_date), end_date=dt.fromisoformat(end_date),
                description=description, owner=owner)
    db.add(p)
    await db.commit()
    return RedirectResponse(url="/projects", status_code=302)


@app.post("/projects/{project_id}/edit")
async def edit_project(project_id: int, request: Request, db: AsyncSession = Depends(get_db),
    name: str = Form(...), client: str = Form(""), category: str = Form("tecnología"),
    status: str = Form("active"), budget: float = Form(0), spent: float = Form(0),
    progress: int = Form(0), start_date: str = Form(...), end_date: str = Form(...),
    description: str = Form(""), owner: str = Form("Demo User")):
    if not auth_check(request):
        return RedirectResponse(url="/login", status_code=302)
    from datetime import date as dt
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404)
    p.name = name; p.client = client; p.category = category; p.status = status
    p.budget = budget; p.spent = spent; p.progress = min(100, max(0, progress))
    p.start_date = dt.fromisoformat(start_date); p.end_date = dt.fromisoformat(end_date)
    p.description = description; p.owner = owner
    await db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=302)


@app.post("/projects/{project_id}/delete")
async def delete_project(project_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        return RedirectResponse(url="/login", status_code=302)
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if p:
        await db.delete(p)
        await db.commit()
    return RedirectResponse(url="/projects", status_code=302)


# ── Team Members CRUD ────────────────────────────────────────────────────────

@app.get("/team", response_class=HTMLResponse)
async def team_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        return RedirectResponse(url="/login", status_code=302)
    lang = get_lang(request)
    members = (await db.execute(select(TeamMember).order_by(TeamMember.name))).scalars().all()
    return templates.TemplateResponse(request, "team.html", {"t": get_t(lang), "lang": lang, "members": members})


@app.post("/team")
async def create_member(request: Request, db: AsyncSession = Depends(get_db),
    name: str = Form(...), role: str = Form(""), email: str = Form(""),
    avatar_color: str = Form("#6366f1")):
    if not auth_check(request):
        return RedirectResponse(url="/login", status_code=302)
    db.add(TeamMember(name=name, role=role, email=email, avatar_color=avatar_color))
    await db.commit()
    return RedirectResponse(url="/team", status_code=302)


@app.post("/team/{member_id}/edit")
async def edit_member(member_id: int, request: Request, db: AsyncSession = Depends(get_db),
    name: str = Form(...), role: str = Form(""), email: str = Form(""),
    avatar_color: str = Form("#6366f1")):
    if not auth_check(request):
        return RedirectResponse(url="/login", status_code=302)
    m = (await db.execute(select(TeamMember).where(TeamMember.id == member_id))).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404)
    m.name = name; m.role = role; m.email = email; m.avatar_color = avatar_color
    await db.commit()
    return RedirectResponse(url="/team", status_code=302)


@app.post("/team/{member_id}/delete")
async def delete_member(member_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        return RedirectResponse(url="/login", status_code=302)
    m = (await db.execute(select(TeamMember).where(TeamMember.id == member_id))).scalar_one_or_none()
    if m:
        await db.delete(m)
        await db.commit()
    return RedirectResponse(url="/team", status_code=302)


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _recalc_project(db: AsyncSession, project_id: int):
    """Recompute project.progress (avg task progress) and project.spent (sum task budgets)."""
    tasks = (await db.execute(select(Task).where(Task.project_id == project_id))).scalars().all()
    proj = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not proj:
        return
    if tasks:
        proj.progress = round(sum(t.progress for t in tasks) / len(tasks))
        proj.spent = sum(t.budget for t in tasks)
    else:
        proj.progress = 0
        proj.spent = 0.0


# ── Tasks CRUD ──────────────────────────────────────────────────────────────

@app.post("/projects/{project_id}/tasks")
async def create_task(project_id: int, request: Request, db: AsyncSession = Depends(get_db),
    title: str = Form(...), description: str = Form(""),
    status: str = Form("todo"), priority: str = Form("medium"),
    assigned_member_id: int = Form(None), start_date: str = Form(""),
    due_date: str = Form(""), estimated_hours: float = Form(0),
    budget: float = Form(0), progress: int = Form(0), is_blocked: bool = Form(False)):
    if not auth_check(request):
        return RedirectResponse(url="/login", status_code=302)
    from datetime import date as dt
    member = None
    if assigned_member_id:
        member = (await db.execute(select(TeamMember).where(TeamMember.id == assigned_member_id))).scalar_one_or_none()
    task = Task(
        project_id=project_id, title=title, description=description,
        status=status, priority=priority,
        assigned_to=member.name if member else "",
        assigned_member_id=assigned_member_id if member else None,
        start_date=dt.fromisoformat(start_date) if start_date else None,
        due_date=dt.fromisoformat(due_date) if due_date else None,
        budget=budget, estimated_hours=estimated_hours,
        progress=min(100, max(0, progress)), is_blocked=is_blocked,
    )
    db.add(task)
    await db.flush()
    await _recalc_project(db, project_id)
    await db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=302)


@app.post("/tasks/{task_id}/edit")
async def edit_task(task_id: int, request: Request, db: AsyncSession = Depends(get_db),
    title: str = Form(...), description: str = Form(""),
    status: str = Form("todo"), priority: str = Form("medium"),
    assigned_member_id: int = Form(None), start_date: str = Form(""),
    due_date: str = Form(""), estimated_hours: float = Form(0),
    budget: float = Form(0), progress: int = Form(0), is_blocked: bool = Form(False)):
    if not auth_check(request):
        return RedirectResponse(url="/login", status_code=302)
    from datetime import date as dt
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404)
    member = None
    if assigned_member_id:
        member = (await db.execute(select(TeamMember).where(TeamMember.id == assigned_member_id))).scalar_one_or_none()
    task.title = title; task.description = description
    task.status = status; task.priority = priority
    task.assigned_to = member.name if member else task.assigned_to
    task.assigned_member_id = assigned_member_id if member else task.assigned_member_id
    task.start_date = dt.fromisoformat(start_date) if start_date else None
    task.due_date = dt.fromisoformat(due_date) if due_date else None
    task.budget = budget; task.estimated_hours = estimated_hours
    task.progress = min(100, max(0, progress)); task.is_blocked = is_blocked
    project_id = task.project_id
    await _recalc_project(db, project_id)
    await db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=302)


@app.post("/tasks/{task_id}/delete")
async def delete_task(task_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        return RedirectResponse(url="/login", status_code=302)
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task:
        project_id = task.project_id
        await db.delete(task)
        await db.flush()
        await _recalc_project(db, project_id)
        await db.commit()
        return RedirectResponse(url=f"/projects/{project_id}", status_code=302)
    raise HTTPException(status_code=404)


@app.post("/tasks/{task_id}/status")
async def update_task_status(task_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not auth_check(request):
        raise HTTPException(status_code=401)
    data = await request.json()
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404)
    task.status = data.get("status", task.status)
    await _recalc_project(db, task.project_id)
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
