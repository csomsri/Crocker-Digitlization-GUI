"""Exercise page resizing with the real theme, without controlling hardware."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QPushButton, QWidget, QBoxLayout
from python.app.ResponsiveLayout import ResponsiveRow
from python.app.PageRegistry import PAGE_BUILDERS, DETAIL_BUILDERS
from python.app.HomePage import HomePage
from python.app.theme import load_stylesheet, load_app_font


def main():
    app = QApplication.instance() or QApplication([])
    font = load_app_font()
    app.setProperty("appFontFamily", font)
    app.setStyleSheet(load_stylesheet(font))
    noop = lambda *args: None
    host = QWidget()
    row = ResponsiveRow(host)
    for _ in range(3):
        button = QPushButton("Resize test")
        button.setMinimumWidth(180)
        row.addWidget(button)
    host.show()
    for width, direction in ((900, QBoxLayout.LeftToRight),
                             (300, QBoxLayout.TopToBottom),
                             (900, QBoxLayout.LeftToRight)):
        host.resize(width, 400)
        for _ in range(12):
            app.processEvents()
        assert row.direction() == direction
        rectangles = [row.itemAt(i).geometry() for i in range(3)]
        for i, rect in enumerate(rectangles):
            assert host.rect().contains(rect)
            assert all(not rect.intersects(other) for other in rectangles[i + 1:])
    host.close()

    builders = {"Home": lambda: HomePage(list(PAGE_BUILDERS), noop, noop)}
    builders.update({name: lambda b=b: b(noop, noop) for name, b in PAGE_BUILDERS.items()})
    for name, (_, builder) in DETAIL_BUILDERS.items():
        kwargs = {}
        if name in {"Field Ctrl", "PID Control", "PythonPID"}:
            kwargs = {"backend_mode": "simulation"}
        elif name == "Settings":
            kwargs = {"set_display_mode": noop, "set_window_resolution": noop}
        elif name == "Display Controller":
            kwargs = dict(monitoring_pages=["RF Power Monitoring"],
                          monitor_entries=lambda: [], show_on_monitor=noop,
                          controller_layout=lambda: "Auto")
        builders[name] = lambda b=builder, kw=kwargs: b(noop, **kw)
    for name, builder in builders.items():
        page = builder()
        try:
            page.show()
            for width, height in ((1920, 1080), (1366, 768), (1280, 820),
                                  (800, 600), (480, 800), (1920, 1080)):
                page.resize(width, height)
                for _ in range(12):
                    app.processEvents()
                assert (page.width(), page.height()) == (width, height), name
                assert page.scroll_area.geometry().size() == page.size(), name
                if name == "Field Ctrl" and width >= 1280:
                    tabs = page.control_tab_buttons
                    assert len({button.y() for button in tabs}) == 1, "Tabs stacked on desktop"
                    assert tabs[0].parentWidget().height() < 80, "Oversized tab header"
                    for index, button in enumerate(tabs):
                        button.click()
                        assert page.control_stack.currentIndex() == index
                    tabs[0].click()
                    arrows = [button for button in page.findChildren(QPushButton)
                              if button.accessibleName() in {"Increase digit", "Decrease digit"}]
                    assert len(arrows) == 12
                    assert all(not button.icon().isNull() for button in arrows)
                if width >= 1280:
                    assert page.scroll_area.horizontalScrollBar().maximum() == 0, name
            print(f"Resize passed: {name}")
        finally:
            page.close()
            page.deleteLater()
            app.processEvents()
    print("Responsive layout checks passed")


if __name__ == "__main__":
    main()
