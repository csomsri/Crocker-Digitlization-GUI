#include "Shader.h"


// Public 
Shader::Shader(const char* vertexPath, const char* fragmentPath) {
    std::string vertexCode;
    std::string fragmentCode;
    std::ifstream vShaderFile;
    std::ifstream fShaderFile;

	// Ensure Exceptions are thrown on failure
    vShaderFile.exceptions(std::ifstream::failbit | std::ifstream::badbit);
    fShaderFile.exceptions(std::ifstream::failbit | std::ifstream::badbit);

    try {
        // 1. Open Files
		vShaderFile.open(vertexPath);
		fShaderFile.open(fragmentPath);
        std::stringstream vShaderStream, fShaderStream;
		// 2. Read File's Buffer Contents into Streams
		vShaderStream << std::noskipws << vShaderFile.rdbuf();
		fShaderStream << std::noskipws << fShaderFile.rdbuf();
		// 3. Close File Handlers
        vShaderFile.close();
		fShaderFile.close();
		// 4. Convert Stream into String
		vertexCode = vShaderStream.str();
		fragmentCode = fShaderStream.str();
	} catch (std::ifstream::failure& e) {
		std::cout << "ERROR::SHADER::FILE_NOT_SUCCESSFULLY_READ: " << e.what() << std::endl;
		ID = 0;
		return;

	}

	const char* vShaderCode = vertexCode.c_str();
	const char* fShaderCode = fragmentCode.c_str();
	
	// 5. Compile Shaders 
	GLuint vertex, fragment;

	// Vertex Shader
	vertex = glCreateShader(GL_VERTEX_SHADER);
	glShaderSource(vertex, 1, &vShaderCode, NULL);
	glCompileShader(vertex);
	checkCompileErrors(vertex, "VERTEX");

	// Fragment Shader
	fragment = glCreateShader(GL_FRAGMENT_SHADER);
	glShaderSource(fragment, 1, &fShaderCode, NULL);
	glCompileShader(fragment);
	checkCompileErrors(fragment, "FRAGMENT");

    // Shader Program
	ID = glCreateProgram();
	glAttachShader(ID, vertex);
	glAttachShader(ID, fragment);
	glLinkProgram(ID);
	checkCompileErrors(ID, "PROGRAM");

	// Delete
	glDeleteShader(vertex);
	glDeleteShader(fragment);

}

void Shader::Use() const {
	glUseProgram(ID);
}

void Shader::Unuse() const {
	glUseProgram(0);
}

// Uniforms Bools
void Shader::setBool(const std::string &name, bool value) const {
	glUniform1i(glGetUniformLocation(ID, name.c_str()), (int)value);
}

// Uniforms Floats
void Shader::setUniform1f(const std::string &name, float value) const {
	glUniform1f(glGetUniformLocation(ID, name.c_str()), value);
}

void Shader::setUniform2f(const std::string& name, glm::vec2 value) const {
	glUniform2f(glGetUniformLocation(ID, name.c_str()), value.x, value.y);
}

void Shader::setUniform3f(const std::string& name, glm::vec3 value) const {
	glUniform3f(glGetUniformLocation(ID, name.c_str()), value.x, value.y, value.z);
}

// Uniform Ints
void Shader::setUniform1i(const std::string &name, int value) const {
	glUniform1i(glGetUniformLocation(ID, name.c_str()), value);
}

void Shader::setUniform2i(const std::string &name, glm::ivec2 value) const {
	glUniform2i(glGetUniformLocation(ID, name.c_str()), value.x, value.y);
}	

void Shader::setUniform3i(const std::string &name, glm::ivec3 value) const {
	glUniform3i(glGetUniformLocation(ID, name.c_str()), value.x, value.y, value.z);
}	

// Uniform Mat4 Floats and Ints
void Shader::setUniformMat4(const std::string &name, glm::mat4x4 value) const {
	glUniformMatrix4fv(glGetUniformLocation(ID, name.c_str()), 1, GL_FALSE, &value[0][0]);
}	

//void Shader::setArrayBuffer(std::string &name, int num_components, GLuint buffer, int stride, int count) const {
//	stride = 0;
//	count = 0;
//	GLint location = glGetAttribLocation(ID, name.c_str());
//	glBindBuffer(GL_ARRAY_BUFFER, buffer);
//	glVertexAttribPointer(location, num_components, GL_FLOAT, GL_FALSE, stride, (void*)0);
//	glEnableVertexAttribArray(location);
//	
//}

Shader::~Shader() {
	// std::cout << "Shader Deleted" << std::endl;
	glDeleteProgram(ID);
}

// Private
void Shader::checkCompileErrors(unsigned int shader, std::string type)
{
    int success;
    char infoLog[1024];
    if (type != "PROGRAM")
    {
        glGetShaderiv(shader, GL_COMPILE_STATUS, &success);
        if (!success)
        {
            glGetShaderInfoLog(shader, 1024, NULL, infoLog);
            std::cout << "ERROR::SHADER_COMPILATION_ERROR of type: " << type << "\n" << infoLog << "\n -- --------------------------------------------------- -- " << std::endl;
        }
    }
    else
    {
        glGetProgramiv(shader, GL_LINK_STATUS, &success);
        if (!success)
        {
            glGetProgramInfoLog(shader, 1024, NULL, infoLog);
            std::cout << "ERROR::PROGRAM_LINKING_ERROR of type: " << type << "\n" << infoLog << "\n -- --------------------------------------------------- -- " << std::endl;
        }
    }
}

