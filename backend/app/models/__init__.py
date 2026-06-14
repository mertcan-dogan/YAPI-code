"""Model registry — importing this package registers all tables on Base.metadata."""
from app.models.base import Base
from app.models.company import Company
from app.models.user import User
from app.models.project import Project
from app.models.cost_entry import CostEntry
from app.models.client_invoice import ClientInvoice
from app.models.subcontractor import Subcontractor
from app.models.equipment_log import EquipmentLog
from app.models.budget_line_item import BudgetLineItem
from app.models.audit_log import AuditLog
from app.models.ai_alert import AIAlert
from app.models.custom_category import CustomCostCategory
from app.models.variation import Variation
from app.models.budget_template import CustomBudgetTemplate
from app.models.approval_request import ApprovalRequest
from app.models.notification import Notification
from app.models.kpi_snapshot import KPISnapshot
from app.models.ai_conversation import AIConversation

__all__ = [
    "Base",
    "Company",
    "User",
    "Project",
    "CostEntry",
    "ClientInvoice",
    "Subcontractor",
    "EquipmentLog",
    "BudgetLineItem",
    "AuditLog",
    "AIAlert",
    "CustomCostCategory",
    "Variation",
    "CustomBudgetTemplate",
    "ApprovalRequest",
    "Notification",
    "KPISnapshot",
    "AIConversation",
]
