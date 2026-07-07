# Crocker-Digitlization-GUI
Hello this is the GUI for Crocker Nuclear Lab

## Installs
You need to have:
- Pyside6
- A NVIDIA Driver that can run OpenGL 4.6
- GLFW 3.4 
- GLAD
- GLM
- Finally and NVIDIA GPU!!!!

## How to Install
We are using GitHub Submodules so all you need to do hopefully is 
```
git submodule update --init --recursive
```
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


## How to Run
WIP
