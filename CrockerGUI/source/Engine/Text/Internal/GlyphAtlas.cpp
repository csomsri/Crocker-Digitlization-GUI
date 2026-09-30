#include "GlyphAtlas.hpp"
namespace crocker::engine {
unsigned int GlyphAtlas::Texture(FontId font, FontManager& fonts) {
    auto& page = pages_[font];
    if (page.id) return page.id;
    const auto& face = fonts.Face(font);
    glCreateTextures(GL_TEXTURE_2D, 1, &page.id);
    glTextureStorage2D(page.id, 1, GL_R8, face.atlasWidth, face.atlasHeight);
    GLint alignment, rowLength, skipRows, skipPixels, unpackBuffer;
    glGetIntegerv(GL_UNPACK_ALIGNMENT, &alignment);
    glGetIntegerv(GL_UNPACK_ROW_LENGTH, &rowLength);
    glGetIntegerv(GL_UNPACK_SKIP_ROWS, &skipRows);
    glGetIntegerv(GL_UNPACK_SKIP_PIXELS, &skipPixels);
    glGetIntegerv(GL_PIXEL_UNPACK_BUFFER_BINDING, &unpackBuffer);
    glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1); glPixelStorei(GL_UNPACK_ROW_LENGTH, 0);
    glPixelStorei(GL_UNPACK_SKIP_ROWS, 0); glPixelStorei(GL_UNPACK_SKIP_PIXELS, 0);
    glTextureSubImage2D(page.id, 0, 0, 0, face.atlasWidth, face.atlasHeight, GL_RED, GL_UNSIGNED_BYTE, face.coverage.data());
    glPixelStorei(GL_UNPACK_ALIGNMENT, alignment); glPixelStorei(GL_UNPACK_ROW_LENGTH, rowLength);
    glPixelStorei(GL_UNPACK_SKIP_ROWS, skipRows); glPixelStorei(GL_UNPACK_SKIP_PIXELS, skipPixels);
    glBindBuffer(GL_PIXEL_UNPACK_BUFFER, unpackBuffer);
    glTextureParameteri(page.id, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTextureParameteri(page.id, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTextureParameteri(page.id, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTextureParameteri(page.id, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    return page.id;
}
void GlyphAtlas::Release() { for (auto& [id, page] : pages_) page.Release(); pages_.clear(); }
}
