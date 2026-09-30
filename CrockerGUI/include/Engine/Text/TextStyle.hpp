#pragma once
#include "Engine/Core/Color.hpp"
#include "Engine/Text/FontId.hpp"
namespace crocker::engine {
enum class HorizontalAlignment { Left, Center, Right };
enum class VerticalAlignment { Baseline, Center, Top, Bottom };
struct TextStyle {
    FontId font = DefaultFont;
    float size = 16;
    Color color{};
    float alpha = 1;
    HorizontalAlignment horizontalAlignment = HorizontalAlignment::Center;
    VerticalAlignment verticalAlignment = VerticalAlignment::Center;
    float rotationDegrees = 0;
    float lineSpacing = 1.2f;
    bool shadow = true;
};
}
