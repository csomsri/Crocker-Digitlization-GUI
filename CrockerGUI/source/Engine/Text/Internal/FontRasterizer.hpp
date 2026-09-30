#pragma once
#include "Engine/Text/FontManager.hpp"
namespace crocker::engine {
class FontRasterizer {
public:
    static FontFace Bake(const std::string& path);
};
}
