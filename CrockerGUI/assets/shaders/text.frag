#version 460 core
in vec2 fontUv;
in vec4 textColor;
layout(binding = 0) uniform sampler2D fontAtlas;
layout(location = 0) out vec4 color;
void main() { color = vec4(textColor.rgb, textColor.a * texture(fontAtlas, fontUv).r); }
