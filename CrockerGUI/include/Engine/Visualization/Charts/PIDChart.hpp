#pragma once

#include "Engine/Visualization/Charts/TimeSeriesChart.hpp"

// Expected columns: Time, Setpoint, Process Value, Controller Output, Error.
class PIDChart : public TimeSeriesChart {};
