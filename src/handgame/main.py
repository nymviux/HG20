import sys
import logging
from logging.handlers import RotatingFileHandler
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox, QMainWindow
from PySide6.QtCore import Qt

# Docelowe importy (odkomentuj, gdy pliki będą gotowe):
# from handgame.gui.widgets.main_window import MainWindow
from handgame.gui.integration_controller import GUIIntegrationController

def setup_logging() -> logging.Logger:
    """
    Konfiguruje globalny system logowania z rotacją plików,
    aby nie zapchać pamięci (np. karty SD na Raspberry Pi).
    """
    logger = logging.getLogger("HandGame2")
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(module)s:%(lineno)d | %(message)s"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        "handgame_runtime.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def global_exception_hook(exc_type, exc_value, exc_traceback):
    """Globalny przechwytywacz błędów."""
    logger = logging.getLogger("HandGame2")
    
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.critical("Nieobsłużony wyjątek krytyczny!", exc_info=(exc_type, exc_value, exc_traceback))

    if QApplication.instance():
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle("Krytyczny Błąd")
        msg_box.setText("Aplikacja musi zostać zamknięta.")
        msg_box.setDetailedText(f"Szczegóły:\n{exc_value}")
        msg_box.exec()
        QApplication.instance().quit()


def main():
    # 1. Inicjalizacja logowania i hooków
    logger = setup_logging()
    logger.info("Uruchamianie aplikacji HandGame 2.0...")
    sys.excepthook = global_exception_hook

    # 2. Inicjalizacja frameworku PySide6
    app = QApplication(sys.argv)
    app.setApplicationName("HandGame 2.0")
    app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)

    try:
        # 3. Inicjalizacja "Mózgu" aplikacji (Backend/Kontrakt)
        controller = GUIIntegrationController()

        # 4. Inicjalizacja głównego okna aplikacji (Frontend)
        class DummyMainWindow(QMainWindow):
            def __init__(self, ctrl):
                super().__init__()
                self.controller = ctrl
                self.setWindowTitle("HandGame 2.0 - Shell")
                self.resize(1024, 768)
                
            def safe_teardown(self):
                logger = logging.getLogger("HandGame2")
                logger.info("Zamykanie okna GUI...")

        window = DummyMainWindow(controller)
        window.show()

        # 5. Podpięcie KONTRAKTU BEZPIECZNEGO ZAMYKANIA
        # Sygnał aboutToQuit najpierw powiadomi okno, a potem wywoła shutdown() w kontrolerze, 
        # co bezpiecznie zatrzyma workery kamer i AI bez wywoływania crasha[cite: 2].
        app.aboutToQuit.connect(window.safe_teardown)
        app.aboutToQuit.connect(controller.shutdown)

        # Opcjonalnie: Symulacja rozpoczęcia testowej gry na starcie
        # controller.select_camera("CAMERA_1", "PLAYER_1")
        # controller.prepare_game("PUZZLE", 1)

        logger.info("Aplikacja gotowa, wchodzenie w główną pętlę zdarzeń (Event Loop).")
        
        # 6. BLOKUJĄCA PĘTLA APLIKACJI
        exit_code = app.exec()
        logger.info(f"Aplikacja zakończyła działanie z kodem wyjścia: {exit_code}")
        sys.exit(exit_code)

    except Exception as e:
        logger.critical(f"Błąd inicjalizacji aplikacji: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()