from datetime import datetime, date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import User, Project, Task, TeamMember
from app.auth import hash_password

TEAM = [
    ("Andrés Gómez",    "Tech Lead",           "agomez@pf.io",    "#6366f1"),
    ("Camila Herrera",  "Frontend Dev",        "cherrera@pf.io",  "#8b5cf6"),
    ("Luis Ramírez",    "Backend Dev",         "lramirez@pf.io",  "#22d3ee"),
    ("Natalia Flores",  "UX Designer",         "nflores@pf.io",   "#4ade80"),
    ("Santiago Díaz",   "Data Engineer",       "sdiaz@pf.io",     "#fb923c"),
    ("Isabella Martínez","Project Manager",    "imartinez@pf.io", "#f472b6"),
    ("Rodrigo Campos",  "DevOps",              "rcampos@pf.io",   "#facc15"),
    ("Elena Vega",      "QA Engineer",         "evega@pf.io",     "#2dd4bf"),
]

PROJECTS = [
    {
        "name": "AI Platform Migration",
        "description": "Migración de la plataforma legacy a arquitectura de microservicios con AI Agents integrados.",
        "client": "TechStart Lima",
        "category": "tecnología",
        "status": "active",
        "budget": 120000,
        "spent": 72000,
        "start_date": date.today() - timedelta(days=45),
        "end_date": date.today() + timedelta(days=30),
        "progress": 60,
        "tasks": [
            ("Auditoría arquitectura legacy",         "Mapear todos los módulos del sistema actual",                  "done",        "high",     0, 16, 18),
            ("Diseño microservicios",                  "Definir boundaries y contratos de cada servicio",              "done",        "high",     1, 24, 22),
            ("Setup infraestructura cloud",            "Configurar Kubernetes, CI/CD, monitoring",                    "done",        "critical", 6, 32, 35),
            ("Migración módulo autenticación",         "Extraer auth service con JWT y OAuth2",                       "done",        "high",     2, 20, 19),
            ("Migración módulo pagos",                 "Integrar Stripe + fallback local",                            "in_progress", "critical", 2, 40, 15),
            ("AI Agent integración — soporte",         "Implementar agente AaaS para soporte técnico",                "in_progress", "high",     0, 30, 12),
            ("Migración módulo reportes",              "Migrar generación de reportes a servicio async",              "in_progress", "medium",   4, 20, 8),
            ("Testing de integración",                 "Suite completa de tests end-to-end",                          "todo",        "high",     7, 28, 0),
            ("Documentación API",                     "OpenAPI specs para todos los microservicios",                  "todo",        "medium",   1, 16, 0),
            ("Performance tuning",                    "Optimizar queries y caching Redis",                            "todo",        "medium",   2, 20, 0),
            ("Security audit",                        "Penetration testing y hardening",                              "review",      "critical", 0, 24, 20),
            ("Training equipo cliente",               "Capacitar al equipo de TechStart en la nueva plataforma",     "todo",        "low",      5, 8,  0),
        ]
    },
    {
        "name": "Expansión Colombia — E-commerce",
        "description": "Implementación de plataforma e-commerce con agente de ventas IA para mercado colombiano.",
        "client": "Retail360",
        "category": "retail",
        "status": "active",
        "budget": 85000,
        "spent": 34000,
        "start_date": date.today() - timedelta(days=20),
        "end_date": date.today() + timedelta(days=60),
        "progress": 40,
        "tasks": [
            ("Research mercado CO",                   "Análisis competencia y regulaciones locales",                  "done",        "high",     5, 12, 14),
            ("Setup Shopify + integraciones",         "Configurar tienda y medios de pago locales (PSE, Nequi)",     "done",        "high",     2, 16, 18),
            ("Agente IA ventas — Zara",               "Configurar y entrenar agente Zara para ventas",               "in_progress", "critical", 0, 20, 10),
            ("Catálogo 500 productos",                "Carga y optimización SEO del catálogo inicial",               "in_progress", "high",     1, 40, 20),
            ("Integración logística — Servientrega",  "API de tracking y generación de guías",                       "todo",        "high",     2, 16, 0),
            ("Campaña lanzamiento digital",           "Google Ads + Meta Ads para lanzamiento",                      "todo",        "medium",   5, 12, 0),
            ("Setup analytics y dashboards",          "GA4, hotjar y reportes automáticos",                          "todo",        "medium",   4, 8,  0),
            ("QA plataforma completa",                "Testing en dispositivos móviles y browsers",                  "todo",        "high",     7, 20, 0),
            ("Soft launch — 50 usuarios beta",        "Prueba controlada con clientes seleccionados",                "backlog",     "medium",   5, 8,  0),
            ("Go-live público",                       "Lanzamiento oficial con campaña",                             "backlog",     "high",     5, 4,  0),
        ]
    },
    {
        "name": "AI-Finance — Fintech Kapital",
        "description": "Implementación módulo AI-Finance para automatización de cierre contable y detección de fraude.",
        "client": "Fintech Kapital",
        "category": "fintech",
        "status": "on_hold",
        "budget": 200000,
        "spent": 50000,
        "start_date": date.today() - timedelta(days=60),
        "end_date": date.today() + timedelta(days=90),
        "progress": 25,
        "tasks": [
            ("Auditoría procesos financieros",        "Mapear flujos de cierre mensual y puntos de dolor",           "done",        "high",     3, 20, 22),
            ("Diseño modelo detección anomalías",     "Arquitectura ML para fraud detection",                        "done",        "critical", 4, 40, 38),
            ("Integración ERP SAP",                   "Conectar AI-Finance con SAP via API",                         "in_progress", "critical", 2, 60, 25),
            ("Modelo cierre automatizado",            "Pipeline de cierre en 4 horas vs 3 días actuales",            "in_progress", "high",     4, 48, 15),
            ("Dashboard CFO en tiempo real",          "Panel ejecutivo con KPIs financieros live",                   "review",      "high",     1, 24, 22),
            ("Training modelo con datos históricos",  "Entrenamiento con 3 años de transacciones",                   "todo",        "critical", 4, 80, 0),
            ("Validación regulatoria",                "Revisión cumplimiento SFC Colombia",                          "todo",        "high",     5, 16, 0),
            ("Testing paralelo 30 días",              "Correr AI-Finance en paralelo con proceso manual",            "backlog",     "high",     3, 40, 0),
            ("Capacitación equipo finanzas",          "Training CFO y equipo contable",                              "backlog",     "medium",   5, 16, 0),
        ]
    },
    {
        "name": "Marketing Automation Platform",
        "description": "Plataforma de automatización de marketing con agente IA para gestión de campañas multicanal.",
        "client": "Projects Factory (interno)",
        "category": "marketing",
        "status": "planning",
        "budget": 45000,
        "spent": 2250,
        "start_date": date.today() + timedelta(days=5),
        "end_date": date.today() + timedelta(days=90),
        "progress": 5,
        "tasks": [
            ("Definición de requerimientos",          "Workshop con stakeholders para definir alcance",              "done",        "high",     5, 8, 9),
            ("Selección stack tecnológico",           "Evaluar n8n vs custom vs Make.com",                          "in_progress", "medium",   0, 6, 4),
            ("Diseño arquitectura",                   "Diagrama de flujos y integraciones necesarias",               "todo",        "high",     0, 12, 0),
            ("Integración WhatsApp + Email",          "Conectar Whapi y SendGrid al motor de automatización",       "todo",        "high",     2, 20, 0),
            ("Agente IA — gestión campañas",          "AI Agent que optimiza envíos según engagement",              "backlog",     "high",     0, 30, 0),
            ("Dashboard métricas campañas",           "Visualización en tiempo real de opens, clicks, conversiones","backlog",     "medium",   1, 16, 0),
            ("A/B testing engine",                    "Framework para testing automático de mensajes",               "backlog",     "medium",   2, 24, 0),
        ]
    },
]


async def seed_database(db: AsyncSession):
    existing = await db.execute(select(User))
    if existing.scalar_one_or_none():
        return

    db.add(User(email="demo@projectsfactory.io", name="Demo User", password_hash=hash_password("demo123")))

    members = []
    for (name, role, email, color) in TEAM:
        m = TeamMember(name=name, role=role, email=email, avatar_color=color)
        db.add(m)
        members.append(m)
    await db.flush()

    for proj_data in PROJECTS:
        tasks_raw = proj_data.pop("tasks")
        proj = Project(**proj_data, owner="Demo User")
        db.add(proj)
        await db.flush()

        for (title, desc, status, priority, member_idx, est_h, act_h) in tasks_raw:
            member = members[member_idx]
            due = date.today() + timedelta(days=14) if status not in ("done", "backlog") else None
            task = Task(
                project_id=proj.id, title=title, description=desc,
                status=status, priority=priority,
                assigned_to=member.name, assigned_member_id=member.id,
                due_date=due, estimated_hours=est_h, actual_hours=act_h,
                is_blocked=(status == "in_progress" and priority == "critical" and act_h < 10),
            )
            db.add(task)

    await db.commit()
