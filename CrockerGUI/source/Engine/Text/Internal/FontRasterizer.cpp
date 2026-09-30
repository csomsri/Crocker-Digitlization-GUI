#include "FontRasterizer.hpp"
#define NK_INCLUDE_FIXED_TYPES
#define NK_INCLUDE_STANDARD_IO
#define NK_INCLUDE_STANDARD_VARARGS
#define NK_INCLUDE_DEFAULT_ALLOCATOR
#define NK_INCLUDE_VERTEX_BUFFER_OUTPUT
#define NK_INCLUDE_FONT_BAKING
#define NK_IMPLEMENTATION
#ifdef _MSC_VER
#pragma warning(push, 0)
#pragma warning(disable: 4701)
#endif
#include <GLFW/deps/nuklear.h>
#ifdef _MSC_VER
#pragma warning(pop)
#endif
#include <fstream>
#include <stdexcept>
namespace crocker::engine {
FontFace FontRasterizer::Bake(const std::string& path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream || stream.tellg() <= 0) throw std::runtime_error("Cannot read font: " + path);
    const auto length = stream.tellg();
    std::vector<unsigned char> bytes(static_cast<std::size_t>(length));
    stream.seekg(0);
    if (!stream.read(reinterpret_cast<char*>(bytes.data()), length)) throw std::runtime_error("Incomplete font file: " + path);
    nk_tt_fontinfo fontInfo{};
    if (!nk_tt_InitFont(&fontInfo, bytes.data(), 0))
        throw std::runtime_error("Invalid TrueType/OpenType font: " + path);
    struct Baker {
        nk_font_atlas value{};
        Baker() { nk_font_atlas_init_default(&value); nk_font_atlas_begin(&value); }
        ~Baker() { nk_font_atlas_clear(&value); }
    } baker;
    FontFace result;
    result.path = path;
    // Latin, Greek, arrows and a single replacement glyph. UTF-8 decoding is
    // independent of this repertoire; unsupported codepoints use fallbacks.
    static const nk_rune ranges[] = {32, 255, 0x370, 0x3ff, 0x2190, 0x2193, 0xfffd, 0xfffd, 0};
    auto config = nk_font_config(result.bakeSize);
    config.range = ranges;
    auto* font = nk_font_atlas_add_from_memory(&baker.value, bytes.data(), bytes.size(), result.bakeSize, &config);
    if (!font) throw std::runtime_error("Cannot bake font: " + path);
    const auto* image = static_cast<const unsigned char*>(nk_font_atlas_bake(
        &baker.value, &result.atlasWidth, &result.atlasHeight, NK_FONT_ATLAS_ALPHA8));
    if (!image || result.atlasWidth <= 0 || result.atlasHeight <= 0) throw std::runtime_error("Font atlas bake failed: " + path);
    result.coverage.assign(image, image + static_cast<std::size_t>(result.atlasWidth) * result.atlasHeight);
    result.ascent = font->info.ascent;
    result.descent = font->info.descent;
    for (unsigned int i = 0; i < font->info.glyph_count; ++i) {
        const auto& g = font->glyphs[i];
        if (nk_tt_FindGlyphIndex(&fontInfo, static_cast<int>(g.codepoint)) == 0) continue;
        // Remove Nuklear's top-origin ascent offset to expose baseline metrics.
        result.glyphs[g.codepoint] = {g.xadvance,
            {g.x0, result.ascent + 0.5f - g.y1, g.x1 - g.x0, g.y1 - g.y0},
            {g.u0, g.v0, g.u1 - g.u0, g.v1 - g.v0}};
    }
    nk_font_atlas_end(&baker.value, nk_handle_id(0), nullptr);
    return result;
}
}
