#include "StateGuard.hpp"
namespace crocker::engine::gl {
StateGuard::StateGuard() {
    glGetIntegerv(GL_CURRENT_PROGRAM, &program_); glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao_);
    glGetIntegerv(GL_ACTIVE_TEXTURE, &activeTexture_);
    glActiveTexture(GL_TEXTURE0); glGetIntegerv(GL_TEXTURE_BINDING_2D, &texture_);
    glGetIntegeri_v(GL_SAMPLER_BINDING, 0, &sampler_);
    glGetIntegerv(GL_BLEND_SRC_RGB, &srcRgb_); glGetIntegerv(GL_BLEND_DST_RGB, &dstRgb_);
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &srcAlpha_); glGetIntegerv(GL_BLEND_DST_ALPHA, &dstAlpha_);
    glGetIntegerv(GL_BLEND_EQUATION_RGB, &equationRgb_); glGetIntegerv(GL_BLEND_EQUATION_ALPHA, &equationAlpha_);
    glGetFloatv(GL_POINT_SIZE, &pointSize_);
    depth_ = glIsEnabled(GL_DEPTH_TEST); cull_ = glIsEnabled(GL_CULL_FACE); blend_ = glIsEnabled(GL_BLEND);
}
StateGuard::~StateGuard() {
    glUseProgram(program_); glBindVertexArray(vao_);
    glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, texture_);
    glBindSampler(0, sampler_); glActiveTexture(activeTexture_);
    glBlendFuncSeparate(srcRgb_, dstRgb_, srcAlpha_, dstAlpha_);
    glBlendEquationSeparate(equationRgb_, equationAlpha_);
    glPointSize(pointSize_);
    (depth_ ? glEnable : glDisable)(GL_DEPTH_TEST);
    (cull_ ? glEnable : glDisable)(GL_CULL_FACE);
    (blend_ ? glEnable : glDisable)(GL_BLEND);
}
}
