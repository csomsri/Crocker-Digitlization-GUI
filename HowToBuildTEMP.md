# Temporary Complete Build Guide

This guide builds the Crocker Digitalization GUI, its C++ engine, the
`CycloViz` Python extension, ZeroMQ support, the control simulator, and the
cyclotron plant model.

The project requires:

- Git with submodule support
- CMake 3.22 or newer
- A C++20 compiler
- Python 3.11 or 3.12, including development headers
- OpenGL development libraries and a working graphics driver

An NVIDIA GPU and CUDA are **not currently required** by the active CMake
build. The project contains a CUDA source file, but it is not compiled by the
current `CMakeLists.txt`.

## Windows 10/11 - PowerShell

### 1. Install system tools

Install the following applications:

1. **Git for Windows**: <https://git-scm.com/download/win>
2. **CMake**: <https://cmake.org/download/>
3. **Python 3.12, 64-bit**: <https://www.python.org/downloads/windows/>
4. **Visual Studio 2022 or Build Tools 2022**:
   <https://visualstudio.microsoft.com/downloads/>

In the Visual Studio installer, select **Desktop development with C++** and
ensure these components are installed:

- MSVC C++ x64/x86 build tools
- Windows 10 or Windows 11 SDK
- C++ CMake tools for Windows

During the Python installation, select **Add python.exe to PATH**. Open a new
PowerShell window afterward.

Verify the tools:

```powershell
git --version
cmake --version
python --version
where.exe python
```

`python --version` must report the interpreter you intend to use. Python 3.11
and 3.12 extensions are not interchangeable: a `cp311` `CycloViz` module only
loads in Python 3.11, and a `cp312` module only loads in Python 3.12.

If Windows keeps selecting the Microsoft Store Python 3.11 alias, open
**Settings > Apps > Advanced app settings > App execution aliases** and disable
the unwanted `python.exe` and `python3.exe` aliases. Then reopen PowerShell and
run `where.exe python` again.

### 2. Clone the repository and submodules

```powershell
git clone --recurse-submodules https://github.com/csomsri/Crocker-Digitlization-GUI.git
Set-Location Crocker-Digitlization-GUI
git submodule update --init --recursive
```

If the repository was already cloned:

```powershell
git pull
git submodule sync --recursive
git submodule update --init --recursive
```

### 3. Create the Python environment

Run these commands from the repository root:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r .\CrockerGUI\requirements.txt
```

Using the virtual environment's full Python path avoids accidentally building
with a different Python installation.

### 4. Configure and build everything

```powershell
Set-Location .\CrockerGUI

cmake -S . -B build `
  -DCROCKER_BUILD_PYTHON=ON `
  -DCROCKER_BUILD_OPENGL_TEST=OFF `
  -DBUILD_TESTING=ON `
  -DPython_EXECUTABLE="$((Resolve-Path ..\.venv\Scripts\python.exe).Path)"

cmake --build build --config Release --parallel
```

The build should create a file similar to this directly inside `CrockerGUI`:

```text
CycloViz.cp312-win_amd64.pyd
```

The number in the filename will match the selected Python version.

### 5. Run the tests

```powershell
ctest --test-dir build -C Release --output-on-failure
& ..\.venv\Scripts\python.exe .\tests\MainArgsTest.py
```

### 6. Run the GUI

Run these commands from the `CrockerGUI` directory:

```powershell
# Original in-process channel smoke simulator
& ..\.venv\Scripts\python.exe .\main.py -simulation -smoke

# Regular GUI with the cyclotron model acting as the ZMQ plant
& ..\.venv\Scripts\python.exe .\main.py -simulation -cyclotron

# Connect the GUI to external LabVIEW/ZMQ hardware
& ..\.venv\Scripts\python.exe .\main.py -ZMQ
```

To use a different ZMQ bind endpoint:

```powershell
& ..\.venv\Scripts\python.exe .\main.py -ZMQ --zmq-endpoint tcp://0.0.0.0:5556
```

### 7. Optional OpenGL diagnostic

To build the standalone OpenGL test, reconfigure with the option enabled:

```powershell
cmake -S . -B build `
  -DCROCKER_BUILD_PYTHON=ON `
  -DCROCKER_BUILD_OPENGL_TEST=ON `
  -DBUILD_TESTING=ON `
  -DPython_EXECUTABLE="$((Resolve-Path ..\.venv\Scripts\python.exe).Path)"

cmake --build build --config Release --parallel
& .\build\Release\CrockerOpenGLTest.exe
```

## Ubuntu - Bash

These instructions target a currently supported Ubuntu desktop release.

### 1. Install system packages

```bash
sudo apt update
sudo apt install -y \
  build-essential \
  cmake \
  git \
  python3 \
  python3-dev \
  python3-pip \
  python3-venv \
  libgl1-mesa-dev \
  libegl1 \
  libxkbcommon-x11-0 \
  libxcb-cursor0 \
  libxcb-xinerama0 \
  xorg-dev
```

Verify the tools:

```bash
git --version
cmake --version
python3 --version
c++ --version
```

If Ubuntu's CMake is older than 3.22, install a newer CMake release before
continuing.

### 2. Clone the repository and submodules

```bash
git clone --recurse-submodules https://github.com/csomsri/Crocker-Digitlization-GUI.git
cd Crocker-Digitlization-GUI
git submodule update --init --recursive
```

If the repository was already cloned:

```bash
git pull
git submodule sync --recursive
git submodule update --init --recursive
```

### 3. Create the Python environment

Run these commands from the repository root:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r CrockerGUI/requirements.txt
```

### 4. Configure and build everything

```bash
cd CrockerGUI

cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DCROCKER_BUILD_PYTHON=ON \
  -DCROCKER_BUILD_OPENGL_TEST=OFF \
  -DBUILD_TESTING=ON \
  -DPython_EXECUTABLE="$(realpath ../.venv/bin/python)"

cmake --build build --parallel
```

The build should create a file similar to this directly inside `CrockerGUI`:

```text
CycloViz.cpython-312-x86_64-linux-gnu.so
```

The number in the filename will match the selected Python version.

### 5. Run the tests

```bash
ctest --test-dir build --output-on-failure
../.venv/bin/python tests/MainArgsTest.py
```

### 6. Run the GUI

Run these commands from the `CrockerGUI` directory:

```bash
# Original in-process channel smoke simulator
../.venv/bin/python main.py -simulation -smoke

# Regular GUI with the cyclotron model acting as the ZMQ plant
../.venv/bin/python main.py -simulation -cyclotron

# Connect the GUI to external ZMQ hardware
../.venv/bin/python main.py -ZMQ
```

Linux must have an active graphical desktop session. Running the GUI over SSH
requires X11/Wayland forwarding or another display server configuration.

### 7. Optional OpenGL diagnostic

```bash
cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DCROCKER_BUILD_PYTHON=ON \
  -DCROCKER_BUILD_OPENGL_TEST=ON \
  -DBUILD_TESTING=ON \
  -DPython_EXECUTABLE="$(realpath ../.venv/bin/python)"

cmake --build build --parallel
./build/CrockerOpenGLTest
```

## Common problems

### `Cyclotron simulation is unavailable`

The active Python interpreter loaded an old or incompatible `CycloViz` file.
Delete the build directory and any stale `CycloViz` binary, then configure and
build again using the exact Python executable from the virtual environment.

Windows PowerShell:

```powershell
Get-ChildItem .\CycloViz*.pyd
& ..\.venv\Scripts\python.exe -c "import sys, CycloViz; print(sys.version); print(CycloViz.__file__)"
```

Ubuntu:

```bash
ls -l CycloViz*.so
../.venv/bin/python -c 'import sys, CycloViz; print(sys.version); print(CycloViz.__file__)'
```

### CMake cannot find `pybind11`

Install it into the same interpreter passed through `Python_EXECUTABLE`:

```text
python -m pip install pybind11
```

Then remove the stale build directory or reconfigure it with the correct
Python executable.

### CMake cannot find OpenGL

On Ubuntu, ensure `libgl1-mesa-dev` is installed. On Windows, install the
Windows SDK and the Visual Studio Desktop development with C++ workload, then
update the graphics driver.

### Git submodule files are missing

From the repository root, run:

```text
git submodule sync --recursive
git submodule update --init --recursive
```

### The GUI opens but the cyclotron plant does not connect

Port `5555` may already be in use. Close the other process or select another
endpoint. The internal cyclotron plant uses the same endpoint selected for the
GUI server.
