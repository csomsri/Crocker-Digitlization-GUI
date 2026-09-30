#pragma once
#include "Engine/Text/FontManager.hpp"
#include "Engine/Text/TextStyle.hpp"
#include <string_view>
namespace crocker::engine {
struct PositionedGlyph { FontId font; char32_t codepoint; Rect bounds; Rect uv; };
struct TextRun {
    std::vector<PositionedGlyph> glyphs;
    Rect bounds;
    float advance = 0;
    std::size_t missingGlyphs = 0;
    TextStyle style;
};
class TextLayout {
public:
    explicit TextLayout(FontManager& fonts) : fonts_(fonts) {}
    TextRun Layout(std::string_view utf8, const TextStyle& style);
    static std::u32string DecodeUtf8(std::string_view utf8);
private:
    FontManager& fonts_;
};
}
