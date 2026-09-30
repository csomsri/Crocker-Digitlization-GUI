#include "Engine/Visualization/Charts/TickFormatter.hpp"
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <sstream>
namespace crocker::engine {
std::string TickFormatter::Format(float value, float span) {
    // Can be done in CUDA
    if (std::abs(value) < std::max(std::abs(span), 1.0f) * 0.0001f) value = 0;
    const auto absoluteSpan = std::abs(span);
    const int precision = absoluteSpan >= 20 ? 0 : absoluteSpan >= 2 ? 1 : 2;
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(precision) << value;
    auto label = stream.str();
    if (precision > 0) {
        while (!label.empty() && label.back() == '0') label.pop_back();
        if (!label.empty() && label.back() == '.') label.pop_back();
    }
    return label;
}
}
