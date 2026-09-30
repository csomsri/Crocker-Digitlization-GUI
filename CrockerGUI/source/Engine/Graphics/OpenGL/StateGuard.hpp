#pragma once
#include <glad/glad.h>
namespace crocker::engine::gl {
class StateGuard {
public:
    StateGuard();
    ~StateGuard();
    StateGuard(const StateGuard&) = delete;
    StateGuard& operator=(const StateGuard&) = delete;
private:
    GLint program_, vao_, texture_, activeTexture_, sampler_;
    GLint srcRgb_, dstRgb_, srcAlpha_, dstAlpha_, equationRgb_, equationAlpha_;
    GLboolean depth_, cull_, blend_;
    GLfloat pointSize_;
};
}
