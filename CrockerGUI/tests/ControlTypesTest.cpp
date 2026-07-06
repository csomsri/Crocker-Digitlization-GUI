#include "Controls/ControlTypes.hpp"

#include <cassert>
#include <type_traits>

int main() {
    using namespace crocker::controls;

    static_assert(ChannelCount == 14);
    static_assert(std::is_default_constructible_v<TelemetrySnapshot>);
    static_assert(std::is_copy_constructible_v<TelemetrySnapshot>);

    ControlCommand command{};
    assert(command.size() == ChannelCount);
    assert(!command[0].enabled);

    SequencePoint point{};
    point.timeSeconds = 1.5;
    point.targets[2] = 42.0;
    assert(!point.targets[1].has_value());
    assert(point.targets[2].value() == 42.0);

    TelemetrySnapshot snapshot{};
    assert(snapshot.connection == ConnectionState::Disconnected);
    assert(IsValidChannel(13));
    assert(!IsValidChannel(14));
}
