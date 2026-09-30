#pragma once
#include "Engine/Core/Rect.hpp"
#include "Engine/Text/FontId.hpp"
#include <memory>
#include <string>
#include <vector>
#include <unordered_map>
namespace crocker::engine {
struct GlyphMetrics {
    float advance = 0;
    Rect bounds; // Relative to baseline, at bake size.
    Rect uv;     // Top-left texture origin.
};
struct FontFace {
    float bakeSize = 64, ascent = 0, descent = 0;
    int atlasWidth = 0, atlasHeight = 0;
    std::vector<unsigned char> coverage;
    std::unordered_map<char32_t, GlyphMetrics> glyphs;
    std::string path;
};
struct ResolvedGlyph { FontId font; GlyphMetrics metrics; bool replaced; };
// CPU-only. No OpenGL/Qt state and no process-wide mutable font atlas.
class FontManager {
public:
    FontId Load(const std::string& path = {});
    void SetFallbacks(std::vector<FontId> fonts);
    const FontFace& Face(FontId id);
    ResolvedGlyph Resolve(FontId id, char32_t codepoint);
private:
    std::vector<std::shared_ptr<const FontFace>> faces_;
    std::vector<FontId> fallbacks_;
    std::unordered_map<std::string, FontId> loadedPaths_;
};
}
