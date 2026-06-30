#include "Engine/Engine/Render/Shader/Shader.hpp"

#include <glm/gtc/type_ptr.hpp>

#include <fstream>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace {

std::string ReadFile(const char* path) {
    std::ifstream file(path, std::ios::in | std::ios::binary);
    if (!file) {
        throw std::runtime_error(std::string("Unable to open shader: ") + path);
    }

    std::ostringstream stream;
    stream << file.rdbuf();
    return stream.str();
}

} // namespace

Shader::Shader(const char* vertexPath, const char* fragmentPath) {
    const GLuint vertex = Compile(GL_VERTEX_SHADER, ReadFile(vertexPath));
    GLuint fragment = 0;
    try {
        fragment = Compile(GL_FRAGMENT_SHADER, ReadFile(fragmentPath));
    } catch (...) {
        glDeleteShader(vertex);
        throw;
    }

    ID = glCreateProgram();
    glAttachShader(ID, vertex);
    glAttachShader(ID, fragment);
    glLinkProgram(ID);
    glDeleteShader(vertex);
    glDeleteShader(fragment);

    GLint success = GL_FALSE;
    glGetProgramiv(ID, GL_LINK_STATUS, &success);
    if (success == GL_FALSE) {
        GLint length = 0;
        glGetProgramiv(ID, GL_INFO_LOG_LENGTH, &length);
        std::string log(static_cast<std::size_t>(length), '\0');
        glGetProgramInfoLog(ID, length, nullptr, log.data());
        glDeleteProgram(ID);
        ID = 0;
        throw std::runtime_error("Shader program link failed:\n" + log);
    }
}

Shader::~Shader() {
    glDeleteProgram(ID);
}

Shader::Shader(Shader&& other) noexcept
    : ID(std::exchange(other.ID, 0)) {}

Shader& Shader::operator=(Shader&& other) noexcept {
    if (this != &other) {
        glDeleteProgram(ID);
        ID = std::exchange(other.ID, 0);
    }
    return *this;
}

void Shader::Use() const { glUseProgram(ID); }
void Shader::Unuse() { glUseProgram(0); }
void Shader::SetBool(const std::string& name, bool value) const { glProgramUniform1i(ID, GetUniformLocation(name), value); }
void Shader::SetUniform1f(const std::string& name, float value) const { glProgramUniform1f(ID, GetUniformLocation(name), value); }
void Shader::SetUniform2f(const std::string& name, const glm::vec2& value) const { glProgramUniform2fv(ID, GetUniformLocation(name), 1, glm::value_ptr(value)); }
void Shader::SetUniform3f(const std::string& name, const glm::vec3& value) const { glProgramUniform3fv(ID, GetUniformLocation(name), 1, glm::value_ptr(value)); }
void Shader::SetUniform1i(const std::string& name, int value) const { glProgramUniform1i(ID, GetUniformLocation(name), value); }
void Shader::SetUniform2i(const std::string& name, const glm::ivec2& value) const { glProgramUniform2iv(ID, GetUniformLocation(name), 1, glm::value_ptr(value)); }
void Shader::SetUniform3i(const std::string& name, const glm::ivec3& value) const { glProgramUniform3iv(ID, GetUniformLocation(name), 1, glm::value_ptr(value)); }
void Shader::SetUniformMat4(const std::string& name, const glm::mat4& value) const { glProgramUniformMatrix4fv(ID, GetUniformLocation(name), 1, GL_FALSE, glm::value_ptr(value)); }

GLuint Shader::Compile(GLenum type, const std::string& source) {
    const GLuint shader = glCreateShader(type);
    const char* code = source.c_str();
    glShaderSource(shader, 1, &code, nullptr);
    glCompileShader(shader);

    GLint success = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &success);
    if (success == GL_FALSE) {
        GLint length = 0;
        glGetShaderiv(shader, GL_INFO_LOG_LENGTH, &length);
        std::string log(static_cast<std::size_t>(length), '\0');
        glGetShaderInfoLog(shader, length, nullptr, log.data());
        glDeleteShader(shader);
        throw std::runtime_error("Shader compilation failed:\n" + log);
    }
    return shader;
}

GLint Shader::GetUniformLocation(const std::string& name) const {
    return glGetUniformLocation(ID, name.c_str());
}
