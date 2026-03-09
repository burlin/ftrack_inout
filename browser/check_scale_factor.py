"""Check DPI/scale factor in terminal. Run: python -m ftrack_inout.browser.check_scale_factor"""
from __future__ import annotations

import sys


def main() -> None:
    try:
        from PySide6 import QtWidgets, QtGui
    except Exception as e:
        print(f"PySide6 not available: {e}")
        return

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    # From primary screen (no window needed)
    screen = QtGui.QGuiApplication.primaryScreen()
    if screen:
        ratio = screen.devicePixelRatio()
        ratio_f = getattr(screen, "devicePixelRatioF", lambda: float(ratio))()
        print(f"Primary screen:")
        print(f"  devicePixelRatio()   = {ratio}")
        print(f"  devicePixelRatioF()  = {ratio_f}")
    else:
        print("No primary screen")
        ratio_f = 1.0

    # Same logic as UserTasksWidget._content_scale_factor
    scale = float(ratio_f)
    result = max(1.25, scale)
    print(f"\n_content_scale_factor() would return: {result}")

    # From a widget (after it has a window/screen)
    w = QtWidgets.QWidget()
    w.show()
    app.processEvents()
    try:
        w_ratio = w.devicePixelRatioF()
        print(f"\nFrom QWidget after show:")
        print(f"  devicePixelRatioF()  = {w_ratio}")
        print(f"  max(1.25, widget)     = {max(1.25, float(w_ratio))}")
    except Exception as e:
        print(f"\nWidget devicePixelRatioF: {e}")
    w.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
