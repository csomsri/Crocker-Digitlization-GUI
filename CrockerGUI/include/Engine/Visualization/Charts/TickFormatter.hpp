#pragma once
#include <string>
namespace crocker::engine {
class TickFormatter {
public:
    static std::string Format(float value, float span);
};
}
