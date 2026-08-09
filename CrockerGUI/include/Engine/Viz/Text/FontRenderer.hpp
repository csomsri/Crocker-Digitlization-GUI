#pragma once

#include "Engine/Viz/Charts/ChartStyle.hpp"

#include <string>

namespace font_renderer {

// Draws centered UTF-8 text using a cached TrueType/OpenType texture atlas.
// The current bundled fonts and chart labels use the printable ASCII subset.
void DrawText(const std::string& text, float centerX, float centerY, float pixelHeight,
              bool vertical, const ChartColor& color, float alpha = 1.0f,
              const std::string& fontPath = {});

} // namespace font_renderer
