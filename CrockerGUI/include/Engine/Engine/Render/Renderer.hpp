#pragma once

#include "Buffers/VAO.h"
#include "Buffers/VBO.h"

#include "Shader/shader.h"
//#include "../Data/data_map.h"
#include "../Data/dbreader.h"
#include "../Data/csv_reader.h"
//#include "../Graphics/point_vertex.h"
#include "camera.h"

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>


#include <iostream>

class Renderer {
public:
	Renderer(const char* vertexPath, const char* fragmentPath);
	~Renderer();

	
	void Render(int width, int height);
	void Initialize(const char* pathToData);
	void Shutdown();
	
	Camera& GetCamera();

private:
	Shader shader;

	VBO vbo;
	VAO vao;


	// Data
	int vertexCount;
	void Customize();

	// Camera
	Camera camera;
};

#endif	// RENDERER_H