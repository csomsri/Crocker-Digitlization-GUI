#pragma once

#include <glad/glad.h>
#include <cstdint>
#include <iostream>

class VAO {
public:
	uint32_t ID;
	VAO();
	void Bind() const;
	void Unbind() const;
	void setAttribute(uint32_t index, uint32_t size, uint32_t type, uint32_t stride, uint32_t offset) const;
	~VAO();

};


