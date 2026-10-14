# UI code map

- `MainWindow.py`: application composition, navigation callbacks, backend lifecycle, and service wiring.
- `WorkspaceShell.py`: persistent collapsible page directory, current-page selection, and separate navigation/window actions.
- `PageRegistry.py`: page builders, category membership, and supported window resolutions. Both main and assigned windows use this registry.
- `theme/application.qss`: shared colors, spacing, and widget styles.
- `theme/workspace.qss`: graphite surfaces, readable typography, red action accents, and workspace navigation styling.
- `theme/palette.py`: shared palette and resolution of higher-specificity legacy styles, including translucent colors.
- `theme/__init__.py`: resource loading and one-time font registration. Apply the stylesheet at the window level so page-local styles remain intact.
- `Display/`: assigned monitor windows and screen-filling/windowed transitions.
- `widgets/AppDialogs.py`: shared in-window dialogs, confirmations, and file pickers. Use `AppDialog`, `AppMessageBox`, and `AppFileDialog` for all new popups; keep their owning page/window as the parent. `show()` / `open()` are asynchronous and `exec()` preserves a modal result without a native popup window.
- `widgets/DialogOverlay.py`: nested modality, window-bound sizing, keyboard focus, and reusable dialog cleanup.
- `widgets/InlinePopups.py`: calendars, tooltips, and text editing menus. The popup service is installed once in `run_app`; use `ScreenSafeDateEdit` for date inputs and `InlineToolTip` for explicit chart hover text.
- `widgets/ScreenSafeComboBox.py`: child-widget dropdowns in every display mode. Use this class for all new dropdowns.
- `theme/dialogs.qss` and `widgets/PidDialog.py`: shared popup appearance and layout.
- `UIAnimation.py`: hover/press polish for controls.
- `PageShell.py`: shared page frames, navigation elements, and custom-painted controls.
- `Automation/`, `Configuration/`, `Controls/`, `Monitoring/`: feature pages.

Keep backend commands and trial safety decisions in the existing service/control layers. Shared visual changes belong in the theme or widget modules rather than individual pages. `MainWindow.run_app` remains the application entry point used by `main.py`.

Expand a category in the left directory to see its pages. The page name and arrow navigate within the main workspace; the adjacent `+` opens or raises a separate native window. Each page has one persistent instance: returning it with **Go to main workspace** in its Workspace menu preserves its inputs and running operation. Use the directory's edge arrow (left to collapse, right to reopen) or **Pages** to hide/reopen it. Links and Back buttons inside a detached page navigate that window; the main workspace stays on its current page. The Workspace menu can bring detached windows forward or tile them.

Useful checks from the repository root: `CrockerGUI/tests/MainArgsTest.py`, `PidControlPageTest.py`, and `WindowModeTest.py` using the project Python environment. The window-mode check exercises native UI when `QT_QPA_PLATFORM=windows`; offscreen tests alone cannot verify Windows focus behavior.

Popup checks: `tests/AppPopupsTest.py`, `tests/PopupPagesTest.py`, and `tests/HardwareProfileOverlayTest.py`. Run with `QT_QPA_PLATFORM=windows` to check the native Windows focus path. The page check uses simulation and issues no hardware commands.
