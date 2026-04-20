import os
from anthropic import AsyncAnthropic
from app.models import Project, Task

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


async def assign_task(task: Task, team_members: list, lang: str = "es") -> str:
    lang_instr = "Respond in Spanish." if lang == "es" else "Respond in English."
    team_str = "\n".join([f"- {m.name} ({m.role})" for m in team_members])
    prompt = f"""{lang_instr}
You are an AI project management assistant.

Recommend the best team member to assign this task, and explain why:

**Task:** {task.title}
**Description:** {task.description}
**Priority:** {task.priority}
**Estimated hours:** {task.estimated_hours}h

**Available team members:**
{team_str}

Provide:
1. **Recommended assignee** — name and role
2. **Reason** — why this person is the best fit (skills, availability signal, task type)
3. **Tips** — 2 specific suggestions to complete this task successfully

Be concise. Max 150 words."""

    r = await client.messages.create(model="claude-sonnet-4-6", max_tokens=400,
                                     messages=[{"role": "user", "content": prompt}])
    return r.content[0].text


async def detect_risks(project: Project, tasks: list[Task], lang: str = "es") -> str:
    lang_instr = "Respond in Spanish." if lang == "es" else "Respond in English."
    budget_pct = round((project.spent / project.budget * 100), 1) if project.budget else 0
    progress = project.progress
    blocked = [t for t in tasks if t.is_blocked]
    in_progress = [t for t in tasks if t.status == "in_progress"]
    overdue = [t for t in tasks if t.due_date and t.status not in ("done",) and str(t.due_date) < str(__import__("datetime").date.today())]

    prompt = f"""{lang_instr}
You are an AI project risk analyst.

Analyze this project and identify risks:

**Project:** {project.name}
**Status:** {project.status}
**Progress:** {progress}%
**Budget used:** {budget_pct}% (${project.spent:,.0f} of ${project.budget:,.0f})
**Blocked tasks:** {len(blocked)} — {', '.join([t.title for t in blocked[:3]])}
**Overdue tasks:** {len(overdue)} — {', '.join([t.title for t in overdue[:3]])}
**In progress:** {len(in_progress)} tasks simultaneously

Provide:
1. **Overall risk level:** 🔴 High / 🟡 Medium / 🟢 Low
2. **Top 3 risks** — each with impact and likelihood
3. **Immediate actions** — 3 specific steps to mitigate risks

Be direct and actionable. Max 200 words."""

    r = await client.messages.create(model="claude-sonnet-4-6", max_tokens=500,
                                     messages=[{"role": "user", "content": prompt}])
    return r.content[0].text


async def generate_report(project: Project, tasks: list[Task], lang: str = "es") -> str:
    lang_instr = "Write the report in Spanish." if lang == "es" else "Write the report in English."
    by_status = {}
    for t in tasks:
        by_status.setdefault(t.status, []).append(t.title)
    total_est = sum(t.estimated_hours for t in tasks)
    total_act = sum(t.actual_hours for t in tasks)
    budget_pct = round((project.spent / project.budget * 100), 1) if project.budget else 0

    prompt = f"""{lang_instr}
Generate a concise executive status report for this project:

**{project.name}** | Client: {project.client}
**Period:** Weekly update
**Overall progress:** {project.progress}%
**Budget:** ${project.spent:,.0f} spent / ${project.budget:,.0f} total ({budget_pct}%)
**Hours:** {total_act:.0f}h actual / {total_est:.0f}h estimated

**Tasks by status:**
- Done: {len(by_status.get('done', []))}
- In progress: {len(by_status.get('in_progress', []))} — {', '.join(by_status.get('in_progress', [])[:3])}
- Blocked: {len([t for t in tasks if t.is_blocked])}
- Remaining: {len(by_status.get('todo', [])) + len(by_status.get('backlog', []))}

Format as a professional report with: Executive Summary, Accomplishments This Week, In Progress, Risks & Blockers, Next Steps. Max 250 words."""

    r = await client.messages.create(model="claude-sonnet-4-6", max_tokens=600,
                                     messages=[{"role": "user", "content": prompt}])
    return r.content[0].text


async def analyze_budget(project: Project, tasks: list[Task], lang: str = "es") -> str:
    lang_instr = "Respond in Spanish." if lang == "es" else "Respond in English."
    budget_pct = round((project.spent / project.budget * 100), 1) if project.budget else 0
    remaining = project.budget - project.spent
    progress = project.progress
    projected_final = (project.spent / progress * 100) if progress > 0 else project.budget
    overrun = projected_final - project.budget

    prompt = f"""{lang_instr}
You are an AI financial analyst for projects.

Analyze the budget health of this project:

**Project:** {project.name}
**Budget:** ${project.budget:,.0f}
**Spent:** ${project.spent:,.0f} ({budget_pct}%)
**Remaining:** ${remaining:,.0f}
**Progress:** {progress}%
**Projected final cost:** ${projected_final:,.0f}
**Projected overrun/savings:** ${abs(overrun):,.0f} {'OVERRUN' if overrun > 0 else 'SAVINGS'}

Provide:
1. **Budget health:** 🔴 At risk / 🟡 Watch closely / 🟢 On track
2. **Burn rate analysis** — is spend proportional to progress?
3. **Forecast** — expected final cost and confidence
4. **3 recommendations** — specific actions to optimize budget

Max 180 words. Be specific with numbers."""

    r = await client.messages.create(model="claude-sonnet-4-6", max_tokens=450,
                                     messages=[{"role": "user", "content": prompt}])
    return r.content[0].text
