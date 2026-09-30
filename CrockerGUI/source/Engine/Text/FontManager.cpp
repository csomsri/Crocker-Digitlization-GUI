#include "Engine/Text/FontManager.hpp"
#include "Internal/FontRasterizer.hpp"
#include <filesystem>
#include <stdexcept>
namespace crocker::engine {
namespace {
std::string ResolvePath(const std::string& requested) {
    std::filesystem::path path = requested;
    if (path.empty()) {
#ifdef _WIN32
        path = "C:/Windows/Fonts/segoeui.ttf";
#endif
        if (path.empty() || !std::filesystem::exists(path))
            path = std::filesystem::path(CROCKER_ASSET_DIR) / "fonts/FuturisticArmour-1p84.ttf";
    }
    if (!std::filesystem::exists(path)) path = std::filesystem::path(CROCKER_ASSET_DIR) / requested;
    if (!std::filesystem::is_regular_file(path)) throw std::runtime_error("Font file not found: " + path.string());
    return std::filesystem::weakly_canonical(path).string();
}
}
FontId FontManager::Load(const std::string& path) {
    if (const auto found = loadedPaths_.find(path); found != loadedPaths_.end()) return found->second;
    const auto resolved = ResolvePath(path);
    for (std::size_t i = 0; i < faces_.size(); ++i)
        if (faces_[i]->path == resolved) return loadedPaths_[path] = static_cast<FontId>(i + 1);
    faces_.push_back(std::make_shared<FontFace>(FontRasterizer::Bake(resolved)));
    return loadedPaths_[path] = static_cast<FontId>(faces_.size());
}
const FontFace& FontManager::Face(FontId id) {
    if (id == DefaultFont) id = Load();
    if (id > faces_.size()) throw std::out_of_range("Unknown font id");
    return *faces_[id - 1];
}
void FontManager::SetFallbacks(std::vector<FontId> fonts) {
    for (auto& id : fonts) { if (!id) id = Load(); (void)Face(id); }
    fallbacks_ = std::move(fonts);
}
ResolvedGlyph FontManager::Resolve(FontId id, char32_t codepoint) {
    if (!id) id = Load();
    const auto lookup = [&](FontId candidate) -> const GlyphMetrics* {
        const auto& face = Face(candidate);
        auto found = face.glyphs.find(codepoint);
        return found == face.glyphs.end() ? nullptr : &found->second;
    };
    if (const auto* glyph = lookup(id)) return {id, *glyph, false};
    for (const auto fallback : fallbacks_)
        if (const auto* glyph = lookup(fallback)) return {fallback, *glyph, false};
    const auto& face = Face(id);
    for (char32_t replacement : {U'\ufffd', U'?'}) {
        auto found = face.glyphs.find(replacement);
        if (found != face.glyphs.end()) return {id, found->second, true};
    }
    throw std::runtime_error("Font has no replacement glyph");
}
}
