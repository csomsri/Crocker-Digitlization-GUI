#pragma once

#include "Engine/Viz/Charts/ChartTypes/TimeSeriesChart.hpp"

// Expected columns: Time, Setpoint, Process Value, Controller Output, Error.
class PIDChart : public TimeSeriesChart {};
