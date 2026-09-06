# UI code map

- `MainWindow.py`: application composition, navigation callbacks, backend lifecycle, and service wiring.
- `PageRegistry.py`: page builders, category membership, and supported window resolutions. Both main and assigned windows use this registry.
- `theme/application.qss`: shared colors, spacing, and widget styles.
- `theme/__init__.py`: resource loading and one-time font registration. Apply the stylesheet at the window level so page-local styles remain intact.
- `Display/`: assigned monitor windows and screen-filling/windowed transitions.
- `widgets/ScreenSafeComboBox.py`: shared dropdown behavior; fullscreen lists are child widgets instead of native popup windows. Use this class for new dropdowns.
- `UIAnimation.py`: hover/press polish for controls.
- `PageShell.py`: shared page frames, navigation elements, and custom-painted controls.
- `Automation/`, `Configuration/`, `Controls/`, `Monitoring/`: feature pages.

Keep backend commands and trial safety decisions in the existing service/control layers. Shared visual changes belong in the theme or widget modules rather than individual pages. `MainWindow.run_app` remains the application entry point used by `main.py`.

Useful checks from the repository root: `CrockerGUI/tests/MainArgsTest.py`, `PidControlPageTest.py`, and `WindowModeTest.py` using the project Python environment. The window-mode check exercises native UI when `QT_QPA_PLATFORM=windows`; offscreen tests alone cannot verify Windows focus behavior.
