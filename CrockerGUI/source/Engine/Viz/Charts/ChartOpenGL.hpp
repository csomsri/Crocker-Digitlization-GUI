#pragma once

#include <glad/glad.h>

#include "Engine/Viz/Charts/ChartRect.hpp"

#include <algorithm>
#include <stdexcept>
#include <string>
#include <vector>

namespace chart_gl {

inline GLuint Compile(GLenum type, const char* source) {
    const GLuint shader = glCreateShader(type);
    glShaderSource(shader, 1, &source, nullptr);
    glCompileShader(shader);
    GLint success = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &success);
    if (success == GL_FALSE) {
        GLint length = 0;
        glGetShaderiv(shader, GL_INFO_LOG_LENGTH, &length);
        std::string log(static_cast<std::size_t>(length), '\0');
        glGetShaderInfoLog(shader, length, nullptr, log.data());
        glDeleteShader(shader);
        throw std::runtime_error("Chart shader compilation failed:\n" + log);
    }
    return shader;
}

inline GLuint CreateProgram() {
    constexpr const char* vertexSource = R"(
        #version 460 core
        layout(location = 0) in vec2 position;
        void main() { gl_Position = vec4(position, 0.0, 1.0); }
    )";
    constexpr const char* fragmentSource = R"(
        #version 460 core
        uniform vec3 chartColor;
        layout(location = 0) out vec4 color;
        void main() { color = vec4(chartColor, 1.0); }
    )";

    const GLuint vertex = Compile(GL_VERTEX_SHADER, vertexSource);
    GLuint fragment = 0;
    try {
        fragment = Compile(GL_FRAGMENT_SHADER, fragmentSource);
    } catch (...) {
        glDeleteShader(vertex);
        throw;
    }
    const GLuint program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glLinkProgram(program);
    glDeleteShader(vertex);
    glDeleteShader(fragment);
    GLint success = GL_FALSE;
    glGetProgramiv(program, GL_LINK_STATUS, &success);
    if (success == GL_FALSE) {
        glDeleteProgram(program);
        throw std::runtime_error("Unable to link chart shader program");
    }
    return program;
}

inline void CreateResources(GLuint& vao, GLuint& vbo, GLuint& program) {
    program = CreateProgram();
    glCreateVertexArrays(1, &vao);
    glCreateBuffers(1, &vbo);
    glVertexArrayVertexBuffer(vao, 0, vbo, 0, 2 * sizeof(float));
    glEnableVertexArrayAttrib(vao, 0);
    glVertexArrayAttribFormat(vao, 0, 2, GL_FLOAT, GL_FALSE, 0);
    glVertexArrayAttribBinding(vao, 0, 0);
}

inline void DestroyResources(GLuint& vao, GLuint& vbo, GLuint& program) {
    if (glDeleteVertexArrays != nullptr) glDeleteVertexArrays(1, &vao);
    if (glDeleteBuffers != nullptr) glDeleteBuffers(1, &vbo);
    if (glDeleteProgram != nullptr) glDeleteProgram(program);
    vao = vbo = program = 0;
}

inline void Validate(const DataTable& table) {
    const std::size_t columns = table.ColumnCount();
    for (const auto& row : table.rows) {
        if (row.size() != columns) {
            throw std::invalid_argument("Every DataTable row must have the same number of columns");
        }
    }
}

inline void Draw(GLuint vao, GLuint vbo, GLuint program,
                 const std::vector<float>& vertices, GLenum mode,
                 float r, float g, float b, float size = 1.0f) {
    if (vertices.empty()) return;
    const GLboolean depthWasEnabled = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean cullWasEnabled = glIsEnabled(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glNamedBufferData(vbo,
        static_cast<GLsizeiptr>(vertices.size() * sizeof(float)),
        vertices.data(), GL_DYNAMIC_DRAW);
    glUseProgram(program);
    glProgramUniform3f(program, glGetUniformLocation(program, "chartColor"), r, g, b);
    if (mode == GL_POINTS) glPointSize(size);
    else glLineWidth(size);
    glBindVertexArray(vao);
    glDrawArrays(mode, 0, static_cast<GLsizei>(vertices.size() / 2));
    if (depthWasEnabled) glEnable(GL_DEPTH_TEST);
    if (cullWasEnabled) glEnable(GL_CULL_FACE);
}

inline float ToNdcX(float pixelX, const GLint viewport[4]) {
    return 2.0f * (pixelX - viewport[0]) / std::max(viewport[2], 1) - 1.0f;
}
inline float ToNdcY(float pixelY, const GLint viewport[4]) {
    return 2.0f * (pixelY - viewport[1]) / std::max(viewport[3], 1) - 1.0f;
}

struct PlotArea {
    float left;
    float right;
    float bottom;
    float top;
};

inline PlotArea InnerArea(const ChartRect& area) {
    return {
        area.x + 42.0f,
        area.x + std::max(area.width - 14.0f, 43.0f),
        area.y + 30.0f,
        area.y + std::max(area.height - 14.0f, 31.0f)
    };
}

inline std::vector<float> Axes(const PlotArea& plot, const GLint viewport[4], float zeroY) {
    return {
        ToNdcX(plot.left, viewport), ToNdcY(plot.bottom, viewport),
        ToNdcX(plot.left, viewport), ToNdcY(plot.top, viewport),
        ToNdcX(plot.left, viewport), ToNdcY(zeroY, viewport),
        ToNdcX(plot.right, viewport), ToNdcY(zeroY, viewport)
    };
}

inline std::vector<float> Grid(const PlotArea& plot, const GLint viewport[4]) {
    std::vector<float> vertices;
    vertices.reserve(32);
    for (int i = 1; i < 5; ++i) {
        const float t = static_cast<float>(i) / 5.0f;
        const float x = plot.left + t * (plot.right - plot.left);
        const float y = plot.bottom + t * (plot.top - plot.bottom);
        vertices.insert(vertices.end(), {
            ToNdcX(x, viewport), ToNdcY(plot.bottom, viewport),
            ToNdcX(x, viewport), ToNdcY(plot.top, viewport),
            ToNdcX(plot.left, viewport), ToNdcY(y, viewport),
            ToNdcX(plot.right, viewport), ToNdcY(y, viewport)
        });
    }
    return vertices;
}

inline float Normalize(float value, float minimum, float maximum) {
    return maximum == minimum ? 0.5f : (value - minimum) / (maximum - minimum);
}

} // namespace chart_gl
