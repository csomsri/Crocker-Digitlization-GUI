#include "VBO.h"

VBO::VBO() {
	glGenBuffers(1, &ID);
}

void VBO::Bind() const {
	glBindBuffer(GL_ARRAY_BUFFER, ID);
}

void VBO::Unbind() const {
	glBindBuffer(GL_ARRAY_BUFFER, 0);
}	

void VBO::SetData(GLsizeiptr size, const void* data) const {
	glBufferData(GL_ARRAY_BUFFER, size, data, GL_STATIC_DRAW);
}

VBO::~VBO() {
	glDeleteBuffers(1, &ID);
}