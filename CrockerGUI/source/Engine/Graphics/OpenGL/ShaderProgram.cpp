#include "ShaderProgram.hpp"
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
namespace crocker::engine::gl {
namespace {
GLuint Compile(GLenum type, const std::string& file) {
    const auto path = std::filesystem::path(CROCKER_ASSET_DIR) / "shaders" / file;
    std::ifstream stream(path);
    if (!stream) throw std::runtime_error("Shader not found: " + path.string());
    std::ostringstream contents; contents << stream.rdbuf();
    auto source = contents.str(); const auto* text = source.c_str();
    const auto shader = glCreateShader(type);
    glShaderSource(shader, 1, &text, nullptr); glCompileShader(shader);
    GLint success = 0; glGetShaderiv(shader, GL_COMPILE_STATUS, &success);
    if (!success) {
        GLint length = 0; glGetShaderiv(shader, GL_INFO_LOG_LENGTH, &length);
        std::string log(static_cast<std::size_t>(std::max(length, 1)), '\0');
        glGetShaderInfoLog(shader, length, nullptr, log.data()); glDeleteShader(shader);
        throw std::runtime_error(file + ": " + log);
    }
    return shader;
}
}
void ShaderProgram::Load(const std::string& vertexAsset, const std::string& fragmentAsset) {
    if (id) return;
    const auto vertex = Compile(GL_VERTEX_SHADER, vertexAsset);
    GLuint fragment = 0;
    try { fragment = Compile(GL_FRAGMENT_SHADER, fragmentAsset); }
    catch (...) { glDeleteShader(vertex); throw; }
    id = glCreateProgram();
    glAttachShader(id, vertex); glAttachShader(id, fragment); glLinkProgram(id);
    glDeleteShader(vertex); glDeleteShader(fragment);
    GLint success = 0; glGetProgramiv(id, GL_LINK_STATUS, &success);
    if (!success) {
        GLint length = 0; glGetProgramiv(id, GL_INFO_LOG_LENGTH, &length);
        std::string log(static_cast<std::size_t>(std::max(length, 1)), '\0');
        glGetProgramInfoLog(id, length, nullptr, log.data()); Release();
        throw std::runtime_error("Shader link failed: " + log);
    }
}
void ShaderProgram::Release() { if (id) glDeleteProgram(id); id = 0; }
}
