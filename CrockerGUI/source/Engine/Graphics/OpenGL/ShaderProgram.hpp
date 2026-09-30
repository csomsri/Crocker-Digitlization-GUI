#pragma once
#include <glad/glad.h>
#include <string>
namespace crocker::engine::gl {
struct ShaderProgram {
    GLuint id = 0;
    void Load(const std::string& vertexAsset, const std::string& fragmentAsset);
    void Release();
};
}
