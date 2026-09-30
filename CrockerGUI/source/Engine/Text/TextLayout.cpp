#include "Engine/Text/TextLayout.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>
namespace crocker::engine {
std::u32string TextLayout::DecodeUtf8(std::string_view value) {
    std::u32string result;
    for (std::size_t i = 0; i < value.size();) {
        const auto first = static_cast<unsigned char>(value[i]);
        if (first < 0x80) { result.push_back(first); ++i; continue; }
        const int count = first >= 0xc2 && first <= 0xdf ? 2 : first >= 0xe0 && first <= 0xef ? 3 : first >= 0xf0 && first <= 0xf4 ? 4 : 0;
        char32_t code = count ? first & ((1 << (7 - count)) - 1) : 0;
        bool valid = count && i + count <= value.size();
        for (int j = 1; valid && j < count; ++j) {
            auto next = static_cast<unsigned char>(value[i + j]);
            valid = (next & 0xc0) == 0x80;
            code = (code << 6) | (next & 0x3f);
        }
        valid = valid && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff) &&
            (count != 3 || code >= 0x800) && (count != 4 || code >= 0x10000);
        result.push_back(valid ? code : U'\ufffd');
        i += valid ? count : 1;
    }
    return result;
}
TextRun TextLayout::Layout(std::string_view text, const TextStyle& style) {
    if (!std::isfinite(style.size) || style.size <= 0 || !std::isfinite(style.lineSpacing) || style.lineSpacing <= 0 || !std::isfinite(style.rotationDegrees))
        throw std::invalid_argument("Text size, line spacing and rotation must be finite; size and spacing must be positive.");
    TextRun run; run.style = style;
    if (text.empty()) return run;
    const auto& face = fonts_.Face(style.font);
    const float scale = style.size / face.bakeSize;
    std::vector<float> widths{0};
    std::vector<std::size_t> lines;
    std::size_t line = 0;
    for (auto cp : DecodeUtf8(text)) {
        if (cp == U'\r') continue;
        if (cp == U'\n') { widths.push_back(0); ++line; continue; }
        if (cp == U'\t') {
            const auto space = fonts_.Resolve(style.font, U' ');
            const auto tab = 4 * space.metrics.advance * style.size / fonts_.Face(space.font).bakeSize;
            widths[line] = (std::floor(widths[line] / std::max(tab, 1.0f)) + 1) * tab;
            continue;
        }
        const auto glyph = fonts_.Resolve(style.font, cp);
        const float glyphScale = style.size / fonts_.Face(glyph.font).bakeSize;
        const auto& b = glyph.metrics.bounds;
        run.glyphs.push_back({glyph.font, cp,
            {widths[line] + b.x * glyphScale, b.y * glyphScale - static_cast<float>(line) * style.size * style.lineSpacing,
             b.width * glyphScale, b.height * glyphScale}, glyph.metrics.uv});
        lines.push_back(line);
        widths[line] += glyph.metrics.advance * glyphScale;
        run.missingGlyphs += glyph.replaced ? 1 : 0;
    }
    run.advance = *std::max_element(widths.begin(), widths.end());
    const float bottom = face.descent * scale - static_cast<float>(line) * style.size * style.lineSpacing;
    const float top = face.ascent * scale;
    const float verticalOffset = style.verticalAlignment == VerticalAlignment::Center ? -(top + bottom) / 2 :
        style.verticalAlignment == VerticalAlignment::Top ? -top : style.verticalAlignment == VerticalAlignment::Bottom ? -bottom : 0;
    const auto horizontalOffset = [&](float width) { return style.horizontalAlignment == HorizontalAlignment::Center ? -width / 2 :
        style.horizontalAlignment == HorizontalAlignment::Right ? -width : 0; };
    for (std::size_t i = 0; i < run.glyphs.size(); ++i) {
        run.glyphs[i].bounds.x += horizontalOffset(widths[lines[i]]);
        run.glyphs[i].bounds.y += verticalOffset;
    }
    run.bounds = {horizontalOffset(run.advance), bottom + verticalOffset, run.advance, top - bottom};
    return run;
}
}
