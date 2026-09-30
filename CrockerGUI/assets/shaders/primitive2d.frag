#version 460 core
uniform vec4 primitiveColor;
layout(location = 0) out vec4 color;
void main() { color = primitiveColor; }
