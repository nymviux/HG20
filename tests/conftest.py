import sys

import pytest
from PySide6.QtCore import QCoreApplication

from handgame.gui.integration_controller import GUIIntegrationController


@pytest.fixture(scope="session")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv)
    yield app


@pytest.fixture
def controller(qapp):
    ctrl = GUIIntegrationController()
    yield ctrl
    ctrl.shutdown()
