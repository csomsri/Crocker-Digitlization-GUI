#pragma once
#include "Controls/Sequencer/SequenceTypes.hpp"
namespace crocker::controls {
class SequenceValidator {
public:
    static SequenceDefinition FromConfig(const SequenceRunConfig& config);
    static void Validate(const SequenceDefinition& definition);
};
}
