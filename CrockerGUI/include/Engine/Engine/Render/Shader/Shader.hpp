#pragma once

#include <external/glad/glad.h> // Need to fix 
#include <string>
#include <iostream>
#include <fstream>
#include <sstream>
#include <external/glm/glm.hpp>

class Shader
{

public:
	uint32_t ID; // Program ID

	Shader(const char* vertexPath, const char* fragmentPath);
	~Shader();
	
	void Use() const;
	void Unuse() const;
	
	// Uniforms Bools
	void setBool(const std::string &name, bool value) const;

	// Uniforms Floats
	void setUniform1f(const std::string &name, float value) const;
	void setUniform2f(const std::string& name, glm::vec2 value) const;
	void setUniform3f(const std::string& name, glm::vec3 value) const;

	// Uniforms Ints
	void setUniform1i(const std::string &name, int value) const;
	void setUniform2i(const std::string &name, glm::ivec2 value) const;
	void setUniform3i(const std::string &name, glm::ivec3 value) const;

	// Matrix 4x4
	void setUniformMat4(const std::string &name, glm::mat4x4) const;

	// Set Array Buffer
	// void setArrayBuffer(std::string& name, int num_components, GLuint buffer, int stride, int count = 0) const;


private:
	void checkCompileErrors(unsigned int shader, std::string type);

};

#endif // SHADER_H
