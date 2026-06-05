"""Tenant-scoped access helpers — defence in depth alongside RLS."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import ROLE_PROJECT_MANAGER, ROLE_SITE_MANAGER
from app.models.project import Project
from app.models.user import User
from app.responses import APIError


def get_company_project(db: Session, project_id: uuid.UUID, user: User) -> Project:
    """Return the project iff it belongs to the user's company, else 404.

    Cross-company access yields 404 (not 403) so existence is not leaked.
    """
    project = db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.company_id == user.company_id,
            Project.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if project is None:
        raise APIError(404, "NOT_FOUND", "Proje bulunamadı")

    # PM and Site managers may only see their own projects (Section 3.2).
    if user.role in (ROLE_PROJECT_MANAGER, ROLE_SITE_MANAGER):
        if project.project_manager_id and project.project_manager_id != user.id:
            raise APIError(403, "FORBIDDEN", "Bu projeye erişim yetkiniz yok")
    return project
