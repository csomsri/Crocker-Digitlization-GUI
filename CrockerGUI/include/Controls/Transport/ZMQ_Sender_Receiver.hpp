#pragma once

#include <iostream>
#include <vector>
#include <cstdlib>
#include <string>
#include <optional>


class ZMQReceiver {
    public:

    // Receiver:
    void ServerBind();


    private:
        
   // Protocol sizes
    constexpr std::size_t N_TRIM = 14;
    constexpr std::size_t N_SRC_EX_12 = 12;
    constexpr std::size_t N_SRC_EX_18 = 18;
    constexpr std::size_t N_TRANS = 10;
    constexpr std::size_t N_VAC_BM_7 = 7;      // vac1..vac5, rf_kV, beam_raw

    constexpr std::size_t REPLY_DOUBLES = N_TRIM + 1; // 14 targets + 1 bitmask
    constexpr std::size_t REPLY_BYTES = REPLY_DOUBLES * sizeof(double);

    std::array<double, REPLY_DOUBLES> reply{};

    // LabVIEW epoch (1904) → Unix epoch (1970)
    constexpr double EPOCH_OFFSET = 2082844800.0;

    // HELPERS FOR DEBUG TOGGLE
    static bool envFlagEnabled(const char* name) {
        const char* value = std::getenv(name);
        return value != nullptr && std::string(value) == "1";
    }
    
    static std::optional<std::string> envStringOrNone(const char* name) {
        const char* value = std::getenv(name);

        if (value == nullptr) {
            return std::nullopt;
        }

        std::string str = value;

        // Equivalent to Python .strip()
        const auto start = str.find_first_not_of(" \t\n\r\f\v");
        if (start == std::string::npos) {
            return std::nullopt;
        }

        const auto end = str.find_last_not_of(" \t\n\r\f\v");
        str = str.substr(start, end - start + 1);

        return str.empty() ? std::nullopt : std::optional<std::string>{str};
    }

    static float envFloatOrDefault(const char* name, float defaultValue) {
        const char* value = std::getenv(name);

        if (value == nullptr) {
            return defaultValue;
        }

        try {
            return std::stof(value);
        } catch (...) {
            return defaultValue;
        }
    }

    // ---------- Debug toggles ----------
    const bool DBG_VERBOSE = envFlagEnabled("ZMQ_VERBOSE");
    const bool DBG_RAW     = envFlagEnabled("ZMQ_RAW");

    const std::optional<std::string> DUMP_JSON_FP = envStringOrNone("ZMQ_DUMP_JSON");

    const float LOG_EVERY_S = envFloatOrDefault("ZMQ_LOG_PERIOD", 1.0f);
    
}