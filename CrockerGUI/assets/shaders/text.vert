#version 460 core
layout(location = 0) in vec2 position;
layout(location = 1) in vec2 textureCoordinate;
layout(location = 2) in vec4 vertexColor;
out vec2 fontUv;
out vec4 textColor;
void main() {
    gl_Position = vec4(position, 0.0, 1.0);
    fontUv = textureCoordinate;
    textColor = vertexColor;
}
