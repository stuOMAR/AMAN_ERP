"""
T6.2 — Repository layer.

Usage example::

    from repositories import InvoiceRepository, ProductRepository, EmployeeRepository

    with transactional(company_id) as db:
        repo = InvoiceRepository(db)
        invoices = repo.list(invoice_type='purchase', limit=50)
"""

from repositories.invoice_repo import InvoiceRepository
from repositories.product_repo import ProductRepository
from repositories.employee_repo import EmployeeRepository

__all__ = ["InvoiceRepository", "ProductRepository", "EmployeeRepository"]
