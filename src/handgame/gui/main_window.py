import logging
from enum import Enum, auto

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QStackedWidget, 
    QMessageBox, QLabel, QPushButton, QHBoxLayout
)
from PySide6.QtCore import Qt, Slot

logger = logging.getLogger("HandGame2")

# =====================================================================
# 1. ENUM DEFINING AVAILABLE SCREENS (GUI-CORE-4)
# =====================================================================
class Screen(Enum):
    MAIN_MENU = 0
    GAME_SELECT = 1
    SETTINGS = 2
    CAMERA_CALIBRATION = 3
    DEMO_MODE = 4
    DEV_MODE = 5
    RESULTS = 6
    GAME_VIEW = 7


# =====================================================================
# 2. VIEW PLACEHOLDERS (to be replaced by Kamil's and Oskar's final classes)
# =====================================================================
# Note: once real screens exist, import them here
# (e.g. from gui.views.main_menu import MainMenu) and swap in.
class DummyScreen(QWidget):
    """Placeholder view for testing the router before real screens exist."""
    def __init__(self, name: str, router_callback):
        super().__init__()
        layout = QVBoxLayout(self)
        
        label = QLabel(f"To jest ekran: {name}")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("font-size: 24px; font-weight: bold;")
        
        btn_back = QPushButton("Wróć do Menu Głównego")
        btn_back.setFixedSize(250, 50)
        btn_back.clicked.connect(lambda: router_callback(Screen.MAIN_MENU))
        
        layout.addWidget(label)
        layout.addWidget(btn_back, alignment=Qt.AlignmentFlag.AlignCenter)


# =====================================================================
# 3. MAIN APPLICATION WINDOW CLASS (GUI-CORE-3)
# =====================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HandGame 2.0")
        
        # Target RPi resolution / optimization
        self.resize(1024, 768)
        self.setMinimumSize(800, 600)

        # 1. Init core modules (GUI-CORE-8)
        self._init_core_modules()

        # 2. Init UI (layouts and router)
        self._init_ui()
        
        logger.info("MainWindow zostało pomyślnie zainicjalizowane.")

    def _init_core_modules(self):
        """Init hook for external modules (camera, AI, session); creates manager instances."""
        logger.debug("Inicjalizacja modułów sprzętowych i logiki...")
        # TODO: self.camera_manager = CameraManager()
        # TODO: self.inference_worker = InferenceWorker()
        # TODO: self.session_manager = SessionManager()
        
        # Placeholders for safe_teardown
        self.camera_manager = None
        self.inference_worker = None

    def _init_ui(self):
        """Builds the main app shell (QStackedWidget)."""
        # Central widget (base for everything)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Main app layout
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0) # No margins around app

        # Screen router
        self.router = QStackedWidget()
        self.main_layout.addWidget(self.router)

        # Add screens to router
        self._register_screens()

        # Set start screen
        self.change_screen(Screen.MAIN_MENU)

    def _register_screens(self):
        """Registers all views in the QStackedWidget (GUI-CORE-4). Order must match the Screen enum values."""
        logger.debug("Rejestracja ekranów w routerze...")
        
        # Kamil will wire in his real classes here:
        # e.g. self.main_menu = MainMenu(router_callback=self.change_screen)
        
        self.screens = {
            Screen.MAIN_MENU: DummyScreen("Menu Główne", self.change_screen),
            Screen.GAME_SELECT: DummyScreen("Wybór Gry", self.change_screen),
            Screen.SETTINGS: DummyScreen("Ustawienia", self.change_screen),
            Screen.CAMERA_CALIBRATION: DummyScreen("Kalibracja Kamery", self.change_screen),
            Screen.DEMO_MODE: DummyScreen("Tryb Demonstracyjny", self.change_screen),
            Screen.DEV_MODE: DummyScreen("Tryb Developerski", self.change_screen),
            Screen.RESULTS: DummyScreen("Wyniki Ostatniej Gry", self.change_screen),
            Screen.GAME_VIEW: DummyScreen("Widok Minigry", self.change_screen),
        }
        
        # Add widgets to router in correct order
        for screen_enum in Screen:
            if screen_enum in self.screens:
                self.router.addWidget(self.screens[screen_enum])

    # =====================================================================
    # CONTROL METHODS (ROUTER AND STATE)
    # =====================================================================
    @Slot(Screen)
    def change_screen(self, screen: Screen):
        """Switches the currently displayed screen."""
        logger.info(f"Przełączanie ekranu na: {screen.name}")
        self.router.setCurrentIndex(screen.value)

    @Slot()
    def emergency_reset(self):
        """Emergency return handler (GUI-CORE-9 / DEMO-4); stops current game/camera and returns to menu."""
        logger.warning("Wymuszono awaryjny reset sesji! Powrót do menu...")
        
        # TODO: self.session_manager.reset()
        # TODO: if self.inference_worker.isRunning(): self.inference_worker.stop()
        
        self.change_screen(Screen.MAIN_MENU)
        QMessageBox.warning(
            self, 
            "Awaryjny Reset", 
            "Sesja została awaryjnie zresetowana.\nPowrót do Menu Głównego."
        )

    # =====================================================================
    # CLEANUP AND SHUTDOWN (GRACEFUL SHUTDOWN)
    # =====================================================================
    @Slot()
    def safe_teardown(self):
        """Stops all workers and releases camera USB ports. Called by app.aboutToQuit from main.py."""
        logger.info("Inicjowanie procedury bezpiecznego zamykania z MainWindow (Teardown)...")
        
        if self.inference_worker:
            logger.info("Zatrzymywanie workera AI...")
            # self.inference_worker.stop()
            # self.inference_worker.wait(2000)
            
        if self.camera_manager:
            logger.info("Zwalnianie dostępu do kamer USB...")
            # self.camera_manager.release_all()
            
        logger.info("Wszystkie zasoby zostały prawidłowo zwolnione.")