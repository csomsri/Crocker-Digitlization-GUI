#include "VAO.h"

VAO::VAO() {
	glGenVertexArrays(1, &ID);
}

void VAO::Bind() const {
	glBindVertexArray(ID);
}

void VAO::Unbind() const {
	glBindVertexArray(0);
}

void VAO::setAttribute(uint32_t index, uint32_t size, uint32_t type, uint32_t stride, uint32_t offset) const {
	glVertexAttribPointer(index, size, type, GL_FALSE, stride, (void*)offset);
	glEnableVertexAttribArray(index);
}	

VAO::~VAO() {
	glDeleteVertexArrays(1, &ID);
}	