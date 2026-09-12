"""Проекты перевода."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import ContextDep, SessionDep, StorageDep
from app.schemas.project import ProjectCreate, ProjectPublic
from app.services.projects import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectPublic, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate, context: ContextDep, session: SessionDep
) -> ProjectPublic:
    project = await ProjectService(session, context).create(
        name=payload.name,
        source_language=payload.source_language,
        target_language=payload.target_language,
        description=payload.description,
        slug=payload.slug,
    )

    return ProjectPublic.model_validate(project)


@router.get("", response_model=list[ProjectPublic])
async def list_projects(
    context: ContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ProjectPublic]:
    projects = await ProjectService(session, context).list(limit=limit, offset=offset)

    return [ProjectPublic.model_validate(project) for project in projects]


@router.get("/{project_id}", response_model=ProjectPublic)
async def get_project(
    project_id: uuid.UUID, context: ContextDep, session: SessionDep
) -> ProjectPublic:
    project = await ProjectService(session, context).get(project_id)

    return ProjectPublic.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID, context: ContextDep, session: SessionDep, storage: StorageDep
) -> Response:
    """Удалить проект со всеми книгами, сегментами, переводами и терминами.

    Необратимо: файлы книг удаляются из хранилища. Память переводов
    остаётся — она принадлежит пространству, а не проекту, и следующая
    книга той же пары возьмёт из неё готовые переводы. Проект с книгой в
    очереди на перевод не удаляется, пока задание не остановлено.
    """
    await ProjectService(session, context).delete(project_id, storage=storage)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
