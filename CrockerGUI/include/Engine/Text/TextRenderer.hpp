#pragma once
#include "Engine/Core/Viewport.hpp"
#include "Engine/Graphics/DrawList.hpp"
#include <memory>
namespace crocker::engine {
class TextRenderer {
public:
    TextRenderer();
    ~TextRenderer();
    TextRenderer(const TextRenderer&) = delete;
    TextRenderer& operator=(const TextRenderer&) = delete;
    void Draw(const DrawList& list, FontManager& fonts, const Viewport& viewport);
    void Release(); // Owning GL context must be current.
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
