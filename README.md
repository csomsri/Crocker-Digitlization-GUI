# Crocker-Digitlization-GUI
Hello this is the GUI for Crocker Nuclear Lab

## How To Run
You need to have:
- Windows Operating System (Linux / Ubuntuu Should Work too but not Guranteed)
- NVIDIA GPU
- Modern C++ (20 I think?)


## Installs
We are using GitHub Submodules so all you need to do hopefully is 

```
git clone --recursive "git.shh"
```

```
git submodule update --init --recursive
```

*If you are using the GIT GUI make sure to click the checkmark for submodules


If any point there are any issues the C++ Libraries we are using are:

GLFW,GLAD,GLM,ZMQ
## External Dependencies
### GLFW
GLFW is a multi-platform library used for creating windows
but for our sake we are using this for debugging as we are 
using Python for the UI

*Place screenshot here 
https://www.glfw.org/

### GLAD
Generates Loaders for OpenGL especially for C++

*Place screenshot here
https://glad.dav1d.de/
*Core and 4.6

### GLM
Transformation / Matrix Multiplaction Library for OpenGL
https://github.com/g-truc/glm


### Python Dependencies
We should have all the requirements to build inside requirements.txt
```python 
pip install -r requirements.txt
```
If at any point there are any issues, a solution can be going through the list and manually installing each python library

## Credits



## How to Run

From the `CrockerGUI` directory, choose one launch mode:

```powershell
python main.py -simulation -smoke
python main.py -simulation -cyclotron
python main.py -ZMQ
```

The cyclotron mode requires a freshly built `CycloViz` extension containing
the cyclotron model bindings. It runs the regular GUI and uses that model as
the ZMQ plant behind the existing controls; it does not open a separate orbit
simulation application.
