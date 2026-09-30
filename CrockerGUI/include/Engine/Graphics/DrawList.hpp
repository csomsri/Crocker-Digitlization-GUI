#pragma once
#include "Engine/Text/TextLayout.hpp"
namespace crocker::engine {
struct TextDraw { TextRun run; Point position; };
struct DrawList { std::vector<TextDraw> text; void Clear() { text.clear(); } };
}
