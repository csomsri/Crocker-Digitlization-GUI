#pragma once

#include <glad/glad.h>
#include <cstdint>
#include <iostream>

class VBO {
public:
	uint32_t ID;
	VBO();
	void Bind() const;
	void Unbind() const;
	void SetData(GLsizeiptr size, const void* data) const;
	~VBO();

};


