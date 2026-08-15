#include "Engine/Viz/Text/FontRenderer.hpp"

#include <glad/glad.h>

#define NK_INCLUDE_FIXED_TYPES
#define NK_INCLUDE_STANDARD_IO
#define NK_INCLUDE_STANDARD_VARARGS
#define NK_INCLUDE_DEFAULT_ALLOCATOR
#define NK_INCLUDE_VERTEX_BUFFER_OUTPUT
#define NK_INCLUDE_FONT_BAKING
#define NK_IMPLEMENTATION
#ifdef _MSC_VER
#pragma warning(disable: 4701) // False positive in bundled Nuklear's numeric edit code.
#pragma warning(push, 0)
#endif
#include <GLFW/deps/nuklear.h>
#ifdef _MSC_VER
#pragma warning(pop)
#endif

#include <algorithm>
#include <array>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace font_renderer {
namespace {
constexpr int kFirstCharacter = 32;
constexpr int kCharacterCount = 95;
constexpr float kBakeHeight = 128.0f;
#ifdef _WIN32
constexpr const char* kDefaultFont = "C:/Windows/Fonts/segoeui.ttf";
#else
constexpr const char* kDefaultFont = "assets/fonts/FuturisticArmour-1p84.ttf";
#endif

struct Character {
    float xadvance;
    float x0;
    float y0;
    float x1;
    float y1;
    float u0;
    float v0;
    float u1;
    float v1;
};

struct Atlas {
    GLuint texture = 0;
    GLuint vertexBuffer = 0;
    GLuint shader = 0;
    std::array<Character, kCharacterCount> characters {};
    std::string loadedPath;
};

Atlas& SharedAtlas()
{
    // OpenGL objects intentionally live for the process lifetime. Their owning
    // Qt context may already be gone during static destruction.
    static Atlas* atlas = new Atlas();
    return *atlas;
}

GLuint Compile(GLenum type, const char* source)
{
    const GLuint shader = glCreateShader(type);
    glShaderSource(shader, 1, &source, nullptr);
    glCompileShader(shader);
    GLint success = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &success);
    if (success == GL_FALSE) {
        glDeleteShader(shader);
        throw std::runtime_error("Font shader compilation failed");
    }
    return shader;
}

GLuint CreateProgram()
{
    constexpr const char* vertexSource = R"(
        #version 460 core
        layout(location = 0) in vec2 position;
        layout(location = 1) in vec2 textureCoordinate;
        out vec2 fontUv;
        void main() {
            gl_Position = vec4(position, 0.0, 1.0);
            fontUv = textureCoordinate;
        }
    )";
    constexpr const char* fragmentSource = R"(
        #version 460 core
        in vec2 fontUv;
        uniform sampler2D fontAtlas;
        uniform vec4 textColor;
        layout(location = 0) out vec4 color;
        void main() {
            float coverage = texture(fontAtlas, fontUv).r;
            color = vec4(textColor.rgb, textColor.a * coverage);
        }
    )";

    const GLuint vertex = Compile(GL_VERTEX_SHADER, vertexSource);
    const GLuint fragment = Compile(GL_FRAGMENT_SHADER, fragmentSource);
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
        throw std::runtime_error("Unable to link font shader program");
    }
    return program;
}

std::filesystem::path ResolveFontPath(const std::string& requested)
{
    const std::filesystem::path path = requested.empty() ? kDefaultFont : requested;
    if (std::filesystem::exists(path)) return path;
#ifdef CROCKER_ASSET_DIR
    const auto fromAssets = std::filesystem::path(CROCKER_ASSET_DIR) /
        (requested.empty() ? "fonts/FuturisticArmour-1p84.ttf" : requested);
    if (std::filesystem::exists(fromAssets)) return fromAssets;
#endif
    throw std::runtime_error("OpenGL font file not found: " + path.string());
}

std::vector<unsigned char> ReadFile(const std::filesystem::path& path)
{
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream) throw std::runtime_error("Unable to open font: " + path.string());
    const auto size = stream.tellg();
    std::vector<unsigned char> bytes(static_cast<std::size_t>(size));
    stream.seekg(0);
    stream.read(reinterpret_cast<char*>(bytes.data()), size);
    return bytes;
}

void EnsureAtlas(const std::string& requestedPath)
{
    Atlas& atlas = SharedAtlas();
    const auto path = ResolveFontPath(requestedPath);
    const std::string normalized = std::filesystem::absolute(path).lexically_normal().string();
    if (atlas.texture != 0 && atlas.loadedPath == normalized) return;

    auto fontBytes = ReadFile(path);
    nk_font_atlas baker {};
    nk_font_atlas_init_default(&baker);
    nk_font_atlas_begin(&baker);
    struct nk_font_config config = nk_font_config(kBakeHeight);
    config.range = nk_font_default_glyph_ranges();
    struct nk_font* font = nk_font_atlas_add_from_memory(
        &baker, fontBytes.data(), fontBytes.size(), kBakeHeight, &config);
    if (font == nullptr) {
        nk_font_atlas_clear(&baker);
        throw std::runtime_error("Unable to load OpenGL font: " + path.string());
    }
    int atlasWidth = 0;
    int atlasHeight = 0;
    const auto* bitmap = static_cast<const unsigned char*>(
        nk_font_atlas_bake(&baker, &atlasWidth, &atlasHeight, NK_FONT_ATLAS_ALPHA8));
    if (bitmap == nullptr || atlasWidth <= 0 || atlasHeight <= 0) {
        nk_font_atlas_clear(&baker);
        throw std::runtime_error("Unable to bake OpenGL font atlas: " + path.string());
    }
    for (int codepoint = kFirstCharacter; codepoint < kFirstCharacter + kCharacterCount; ++codepoint) {
        const struct nk_font_glyph* glyph = nk_font_find_glyph(font, static_cast<nk_rune>(codepoint));
        atlas.characters[static_cast<std::size_t>(codepoint - kFirstCharacter)] = {
            glyph->xadvance, glyph->x0, glyph->y0, glyph->x1, glyph->y1,
            glyph->u0, glyph->v0, glyph->u1, glyph->v1
        };
    }

    if (atlas.shader == 0) {
        atlas.shader = CreateProgram();
        glCreateBuffers(1, &atlas.vertexBuffer);
    }
    if (atlas.texture != 0) glDeleteTextures(1, &atlas.texture);
    glCreateTextures(GL_TEXTURE_2D, 1, &atlas.texture);
    glTextureStorage2D(atlas.texture, 1, GL_R8, atlasWidth, atlasHeight);
    GLint unpackAlignment = 4;
    glGetIntegerv(GL_UNPACK_ALIGNMENT, &unpackAlignment);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTextureSubImage2D(atlas.texture, 0, 0, 0, atlasWidth, atlasHeight,
                        GL_RED, GL_UNSIGNED_BYTE, bitmap);
    glPixelStorei(GL_UNPACK_ALIGNMENT, unpackAlignment);
    glTextureParameteri(atlas.texture, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTextureParameteri(atlas.texture, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTextureParameteri(atlas.texture, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTextureParameteri(atlas.texture, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    nk_font_atlas_end(&baker, nk_handle_id(static_cast<int>(atlas.texture)), nullptr);
    nk_font_atlas_clear(&baker);
    atlas.loadedPath = normalized;
}

struct Quad { float left; float bottom; float right; float top; float u0; float v0; float u1; float v1; };

} // namespace

void DrawText(const std::string& text, float centerX, float centerY, float pixelHeight,
              bool vertical, const ChartColor& color, float alpha, const std::string& fontPath)
{
    if (text.empty() || pixelHeight <= 0.0f) return;
    EnsureAtlas(fontPath);
    Atlas& atlas = SharedAtlas();
    const float scale = pixelHeight / kBakeHeight;

    std::vector<Quad> quads;
    quads.reserve(text.size());
    float pen = 0.0f;
    float minX = 0.0f, maxX = 0.0f, minY = 0.0f, maxY = 0.0f;
    bool hasGlyph = false;
    for (unsigned char value : text) {
        const int index = value >= kFirstCharacter && value < kFirstCharacter + kCharacterCount
            ? value - kFirstCharacter : '?' - kFirstCharacter;
        const auto& glyph = atlas.characters[static_cast<std::size_t>(index)];
        Quad quad {
            pen + glyph.x0 * scale, -glyph.y1 * scale,
            pen + glyph.x1 * scale, -glyph.y0 * scale,
            glyph.u0, glyph.v1, glyph.u1, glyph.v0,
        };
        quads.push_back(quad);
        pen += glyph.xadvance * scale;
        minX = hasGlyph ? std::min(minX, quad.left) : quad.left;
        maxX = hasGlyph ? std::max(maxX, quad.right) : quad.right;
        minY = hasGlyph ? std::min(minY, quad.bottom) : quad.bottom;
        maxY = hasGlyph ? std::max(maxY, quad.top) : quad.top;
        hasGlyph = true;
    }

    GLint viewport[4];
    glGetIntegerv(GL_VIEWPORT, viewport);
    // Center against the full typographic advance, not the varying ink bounds.
    // This keeps strings of different lengths aligned to the same center line.
    const float offsetX = pen * 0.5f;
    const float offsetY = (minY + maxY) * 0.5f;
    std::vector<float> vertices;
    vertices.reserve(quads.size() * 24);
    const auto add = [&](float x, float y, float u, float v) {
        x -= offsetX;
        y -= offsetY;
        const float px = centerX + (vertical ? -y : x);
        const float py = centerY + (vertical ? x : y);
        vertices.insert(vertices.end(), {
            2.0f * (px - viewport[0]) / std::max(viewport[2], 1) - 1.0f,
            2.0f * (py - viewport[1]) / std::max(viewport[3], 1) - 1.0f, u, v
        });
    };
    for (const auto& q : quads) {
        add(q.left, q.bottom, q.u0, q.v0); add(q.right, q.bottom, q.u1, q.v0);
        add(q.right, q.top, q.u1, q.v1); add(q.left, q.bottom, q.u0, q.v0);
        add(q.right, q.top, q.u1, q.v1); add(q.left, q.top, q.u0, q.v1);
    }

    // VAOs are not shared between the separate QOpenGLWidget contexts used by
    // the speedometer and line chart. Configure a context-local VAO per draw;
    // the atlas texture, shader, and buffer remain shared by Qt's share group.
    GLuint vertexArray = 0;
    glCreateVertexArrays(1, &vertexArray);
    glVertexArrayVertexBuffer(vertexArray, 0, atlas.vertexBuffer, 0, 4 * sizeof(float));
    glEnableVertexArrayAttrib(vertexArray, 0);
    glEnableVertexArrayAttrib(vertexArray, 1);
    glVertexArrayAttribFormat(vertexArray, 0, 2, GL_FLOAT, GL_FALSE, 0);
    glVertexArrayAttribFormat(vertexArray, 1, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float));
    glVertexArrayAttribBinding(vertexArray, 0, 0);
    glVertexArrayAttribBinding(vertexArray, 1, 0);
    glBindVertexArray(vertexArray);

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glUseProgram(atlas.shader);
    glBindTextureUnit(0, atlas.texture);
    glProgramUniform1i(atlas.shader, glGetUniformLocation(atlas.shader, "fontAtlas"), 0);

    const auto drawVertices = [&](const std::vector<float>& textVertices,
                                  float r, float g, float b, float a) {
        glNamedBufferData(atlas.vertexBuffer,
                          static_cast<GLsizeiptr>(textVertices.size() * sizeof(float)),
                          textVertices.data(), GL_DYNAMIC_DRAW);
        glProgramUniform4f(atlas.shader, glGetUniformLocation(atlas.shader, "textColor"),
                           r, g, b, std::clamp(a, 0.0f, 1.0f));
        glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(textVertices.size() / 4));
    };

    std::vector<float> shadowVertices = vertices;
    const float shadowX = 2.0f * 1.35f / std::max(viewport[2], 1);
    const float shadowY = -2.0f * 1.35f / std::max(viewport[3], 1);
    for (std::size_t index = 0; index + 1 < shadowVertices.size(); index += 4) {
        shadowVertices[index] += shadowX;
        shadowVertices[index + 1] += shadowY;
    }
    drawVertices(shadowVertices, 2.0f / 255.0f, 6.0f / 255.0f, 23.0f / 255.0f, 0.72f * alpha);
    drawVertices(vertices, color.r, color.g, color.b, alpha);
    glDeleteVertexArrays(1, &vertexArray);
}

} // namespace font_renderer
