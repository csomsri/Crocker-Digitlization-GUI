"""Ownership checks shared by manual, PID, BO and GA workspaces."""
from PySide6.QtWidgets import QApplication


def active_controller(backend, requester=None):
    if backend is None:
        return None
    for page in QApplication.allWidgets():
        if page is requester or getattr(page,'backend',None) is not backend:
            continue
        if getattr(page,'pid_enabled',False) or getattr(page,'tuning_session_active',False):
            return page
    return None
