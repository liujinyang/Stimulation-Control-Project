# -*- coding: utf-8 -*-
"""
Created on Mon Apr 13 16:49:56 2026

@author: liujin
"""

import sys
from PySide6.QtWidgets import QApplication
from perfusion_app.controllers.app_controller import AppController

def main():
    app = QApplication(sys.argv)
    controller = AppController()
    controller.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()