#pragma once
#include "Engine/Text/FontManager.hpp"
#include "../../Graphics/OpenGL/Objects.hpp"
#include <map>
namespace crocker::engine {
class GlyphAtlas {
public:
    unsigned int Texture(FontId font, FontManager& fonts);
    void Release();
private:
    std::map<FontId, gl::Texture2D> pages_;
};
}
