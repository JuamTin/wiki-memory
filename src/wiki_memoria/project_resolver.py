from .domain import ProjectContext
from .workspace import WorkspaceResolver, bank_directory


class ProjectResolver(WorkspaceResolver):
    context_type = ProjectContext
