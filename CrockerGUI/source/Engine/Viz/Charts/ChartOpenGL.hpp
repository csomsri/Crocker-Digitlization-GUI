#pragma once

#include <glad/glad.h>

#include "Engine/Viz/Charts/ChartRect.hpp"
#include "Engine/Viz/Charts/ChartStyle.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstdint>
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
        uniform vec4 chartColor;
        layout(location = 0) out vec4 color;
        void main() { color = chartColor; }
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
                 float r, float g, float b, float size = 1.0f, float alpha = 1.0f) {
    if (vertices.empty()) return;

    const GLboolean depthWasEnabled = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean cullWasEnabled = glIsEnabled(GL_CULL_FACE);
    const GLboolean blendWasEnabled = glIsEnabled(GL_BLEND);

    GLint blendSourceRgb = GL_ONE;
    GLint blendDestinationRgb = GL_ZERO;
    GLint blendSourceAlpha = GL_ONE;
    GLint blendDestinationAlpha = GL_ZERO;

    if (blendWasEnabled) {
        glGetIntegerv(GL_BLEND_SRC_RGB, &blendSourceRgb);
        glGetIntegerv(GL_BLEND_DST_RGB, &blendDestinationRgb);
        glGetIntegerv(GL_BLEND_SRC_ALPHA, &blendSourceAlpha);
        glGetIntegerv(GL_BLEND_DST_ALPHA, &blendDestinationAlpha);
    }

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    
    glNamedBufferData(vbo,
        static_cast<GLsizeiptr>(vertices.size() * sizeof(float)),
        vertices.data(), GL_DYNAMIC_DRAW);

    glUseProgram(program);
    glProgramUniform4f(program, glGetUniformLocation(program, "chartColor"), r, g, b, alpha);
    if (alpha < 1.0f) {
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    }

    const float validSize = std::isfinite(size) && size > 0.0f ? size : 1.0f;
    if (mode == GL_POINTS) {
        glPointSize(validSize);
    }

    // Native OpenGL line widths are disabled because some core-profile GPU
    // drivers (including the laptop used for this test) reject widths greater
    // than 1.0 with GL_INVALID_VALUE. To try driver-controlled line thickness,
    // restore the following block. The chart style's lineWidth, axisWidth, or
    // gridWidth is passed to this function as `validSize`.
    //
    // if (mode == GL_LINES || mode == GL_LINE_STRIP || mode == GL_LINE_LOOP) {
    //     GLfloat lineWidthRange[2] = {1.0f, 1.0f};
    //     glGetFloatv(GL_ALIASED_LINE_WIDTH_RANGE, lineWidthRange);
    //     glLineWidth(std::clamp(validSize, lineWidthRange[0], lineWidthRange[1]));
    // }

    glBindVertexArray(vao);
    glDrawArrays(mode, 0, static_cast<GLsizei>(vertices.size() / 2));
    
    if (depthWasEnabled) glEnable(GL_DEPTH_TEST);
    if (cullWasEnabled) glEnable(GL_CULL_FACE);
    
    if (blendWasEnabled) {
        glBlendFuncSeparate(blendSourceRgb, blendDestinationRgb, blendSourceAlpha, blendDestinationAlpha);
    } else {
        glDisable(GL_BLEND);
    }
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

inline PlotArea InnerArea(const ChartRect& area, const ChartStyle& style, bool hasTitle) {
    const float topMargin = hasTitle && style.showTitle ? style.titleMargin : style.plotPadding;
    return {
        area.x + style.leftMargin,
        area.x + std::max(area.width - style.plotPadding, style.leftMargin + 1.0f),
        area.y + style.bottomMargin,
        area.y + std::max(area.height - topMargin, style.bottomMargin + 1.0f)
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

inline std::vector<float> Grid(const PlotArea& plot, const GLint viewport[4], int divisions) {
    std::vector<float> vertices;
    divisions = std::max(divisions, 1);
    vertices.reserve(static_cast<std::size_t>(divisions - 1) * 8);
    for (int i = 1; i < divisions; ++i) {
        const float t = static_cast<float>(i) / static_cast<float>(divisions);
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

inline std::array<std::uint8_t, 7> Glyph(char value) {
    switch (static_cast<char>(std::toupper(static_cast<unsigned char>(value)))) {
        case 'A': return {14, 17, 17, 31, 17, 17, 17};
        case 'B': return {30, 17, 17, 30, 17, 17, 30};
        case 'C': return {14, 17, 16, 16, 16, 17, 14};
        case 'D': return {30, 17, 17, 17, 17, 17, 30};
        case 'E': return {31, 16, 16, 30, 16, 16, 31};
        case 'F': return {31, 16, 16, 30, 16, 16, 16};
        case 'G': return {14, 17, 16, 23, 17, 17, 15};
        case 'H': return {17, 17, 17, 31, 17, 17, 17};
        case 'I': return {14, 4, 4, 4, 4, 4, 14};
        case 'J': return {7, 2, 2, 2, 18, 18, 12};
        case 'K': return {17, 18, 20, 24, 20, 18, 17};
        case 'L': return {16, 16, 16, 16, 16, 16, 31};
        case 'M': return {17, 27, 21, 21, 17, 17, 17};
        case 'N': return {17, 25, 21, 19, 17, 17, 17};
        case 'O': return {14, 17, 17, 17, 17, 17, 14};
        case 'P': return {30, 17, 17, 30, 16, 16, 16};
        case 'Q': return {14, 17, 17, 17, 21, 18, 13};
        case 'R': return {30, 17, 17, 30, 20, 18, 17};
        case 'S': return {15, 16, 16, 14, 1, 1, 30};
        case 'T': return {31, 4, 4, 4, 4, 4, 4};
        case 'U': return {17, 17, 17, 17, 17, 17, 14};
        case 'V': return {17, 17, 17, 17, 17, 10, 4};
        case 'W': return {17, 17, 17, 21, 21, 21, 10};
        case 'X': return {17, 17, 10, 4, 10, 17, 17};
        case 'Y': return {17, 17, 10, 4, 4, 4, 4};
        case 'Z': return {31, 1, 2, 4, 8, 16, 31};
        case '0': return {14, 17, 19, 21, 25, 17, 14};
        case '1': return {4, 12, 4, 4, 4, 4, 14};
        case '2': return {14, 17, 1, 2, 4, 8, 31};
        case '3': return {30, 1, 1, 14, 1, 1, 30};
        case '4': return {2, 6, 10, 18, 31, 2, 2};
        case '5': return {31, 16, 16, 30, 1, 1, 30};
        case '6': return {14, 16, 16, 30, 17, 17, 14};
        case '7': return {31, 1, 2, 4, 8, 8, 8};
        case '8': return {14, 17, 17, 14, 17, 17, 14};
        case '9': return {14, 17, 17, 15, 1, 1, 14};
        case '+': return {0, 4, 4, 31, 4, 4, 0};
        case '-': return {0, 0, 0, 31, 0, 0, 0};
        case '.': return {0, 0, 0, 0, 0, 12, 12};
        case '/': return {1, 1, 2, 4, 8, 16, 16};
        case ':': return {0, 12, 12, 0, 12, 12, 0};
        case '(': return {2, 4, 8, 8, 8, 4, 2};
        case ')': return {8, 4, 2, 2, 2, 4, 8};
        case ' ': return {0, 0, 0, 0, 0, 0, 0};
        default: return {31, 17, 2, 4, 4, 0, 4};
    }
}

inline std::vector<float> Text(
    const std::string& text,
    float centerX,
    float centerY,
    float scale,
    bool vertical,
    const GLint viewport[4]) {
    std::vector<float> vertices;
    vertices.reserve(text.size() * 5 * 7 * 12);
    const float length = std::max(
        static_cast<float>(text.size()) * 6.0f - 1.0f,
        0.0f) * scale;
    const float originX = vertical
        ? centerX + 3.5f * scale
        : centerX - length * 0.5f;
    const float originY = vertical
        ? centerY - length * 0.5f
        : centerY - 3.5f * scale;

    for (std::size_t character = 0; character < text.size(); ++character) {
        const auto glyph = Glyph(text[character]);
        for (int row = 0; row < 7; ++row) {
            for (int column = 0; column < 5; ++column) {
                if ((glyph[row] & (1U << (4 - column))) == 0) continue;
                const float along = (
                    static_cast<float>(character) * 6.0f
                    + static_cast<float>(column)) * scale;
                const float across = static_cast<float>(6 - row) * scale;
                const float x0 = vertical
                    ? originX - across
                    : originX + along;
                const float y0 = vertical ? originY + along : originY + across;
                const float x1 = x0 + scale;
                const float y1 = y0 + scale;
                const float nx0 = ToNdcX(x0, viewport);
                const float nx1 = ToNdcX(x1, viewport);
                const float ny0 = ToNdcY(y0, viewport);
                const float ny1 = ToNdcY(y1, viewport);
                vertices.insert(vertices.end(), {
                    nx0, ny0, nx1, ny0, nx1, ny1,
                    nx0, ny0, nx1, ny1, nx0, ny1,
                });
            }
        }
    }
    return vertices;
}

inline void DrawLabels(GLuint vao, GLuint vbo, GLuint program, const ChartRect& area,
                       const PlotArea& plot, const GLint viewport[4], const ChartStyle& style,
                       const std::string& title, const std::string& xTitle, const std::string& yTitle) {
    const auto color = style.textColor;
    if (style.showTitle && !title.empty()) {
        const auto vertices = Text(title, (plot.left + plot.right) * 0.5f,
            area.y + area.height - style.titleMargin * 0.5f, style.titleSize, false, viewport);
        Draw(vao, vbo, program, vertices, GL_TRIANGLES, color.r, color.g, color.b);
    }
    if (style.showAxisTitles && !xTitle.empty()) {
        const auto vertices = Text(xTitle, (plot.left + plot.right) * 0.5f,
            area.y + style.bottomMargin * 0.35f, style.axisTitleSize, false, viewport);
        Draw(vao, vbo, program, vertices, GL_TRIANGLES, color.r, color.g, color.b);
    }
    if (style.showAxisTitles && !yTitle.empty()) {
        const auto vertices = Text(yTitle, area.x + style.leftMargin * 0.25f,
            (plot.bottom + plot.top) * 0.5f, style.axisTitleSize, true, viewport);
        Draw(vao, vbo, program, vertices, GL_TRIANGLES, color.r, color.g, color.b);
    }
}

inline float Normalize(float value, float minimum, float maximum) {
    return maximum == minimum ? 0.5f : (value - minimum) / (maximum - minimum);
}

} // namespace chart_gl
