from PySide6.QtWidgets import QApplication
from perfusion_app.controllers.app_controller import AppController


def main() -> int:
    app = QApplication([])
    controller = AppController()
    controller.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
