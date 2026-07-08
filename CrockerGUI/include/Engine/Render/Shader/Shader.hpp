#pragma once

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <string>

class Shader {
public:
    Shader(const char* vertexPath, const char* fragmentPath);
    ~Shader();

    Shader(const Shader&) = delete;
    Shader& operator=(const Shader&) = delete;
    Shader(Shader&& other) noexcept;
    Shader& operator=(Shader&& other) noexcept;

    void Use() const;
    static void Unuse();

    void SetBool(const std::string& name, bool value) const;
    void SetUniform1f(const std::string& name, float value) const;
    void SetUniform2f(const std::string& name, const glm::vec2& value) const;
    void SetUniform3f(const std::string& name, const glm::vec3& value) const;
    void SetUniform1i(const std::string& name, int value) const;
    void SetUniform2i(const std::string& name, const glm::ivec2& value) const;
    void SetUniform3i(const std::string& name, const glm::ivec3& value) const;
    void SetUniformMat4(const std::string& name, const glm::mat4& value) const;

private:
    static GLuint Compile(GLenum type, const std::string& source);
    GLint GetUniformLocation(const std::string& name) const;

    GLuint ID = 0;
};
