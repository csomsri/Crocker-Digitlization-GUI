#include "Bindings.hpp"

#include "Simulation/CyclotronModel.hpp"

#include <pybind11/pybind11.h>

namespace py = pybind11;
namespace Simulation = crocker::simulation;

void BindCyclotron(py::module_& module)
{
    py::class_<Simulation::ParticleState>(module, "ParticleState")
        .def(py::init<>())
        .def_readwrite("x_m", &Simulation::ParticleState::xMeters)
        .def_readwrite("y_m", &Simulation::ParticleState::yMeters)
        .def_readwrite("px_kg_m_s", &Simulation::ParticleState::pxKgMetersPerSecond)
        .def_readwrite("py_kg_m_s", &Simulation::ParticleState::pyKgMetersPerSecond)
        .def_readwrite("time_s", &Simulation::ParticleState::timeSeconds);

    py::class_<Simulation::CyclotronConfig>(module, "CyclotronConfig")
        .def(py::init<>())
        .def_readwrite("magnetic_field_t", &Simulation::CyclotronConfig::magneticFieldTesla)
        .def_readwrite("rf_frequency_hz", &Simulation::CyclotronConfig::rfFrequencyHz)
        .def_readwrite(
            "rf_peak_electric_field_v_m",
            &Simulation::CyclotronConfig::rfPeakElectricFieldVoltsPerMeter)
        .def_readwrite("rf_phase_rad", &Simulation::CyclotronConfig::rfPhaseRadians)
        .def_readwrite("gap_half_width_m", &Simulation::CyclotronConfig::gapHalfWidthMeters)
        .def_readwrite("chamber_radius_m", &Simulation::CyclotronConfig::chamberRadiusMeters)
        .def_readwrite("time_step_s", &Simulation::CyclotronConfig::timeStepSeconds);

    py::class_<Simulation::CyclotronDiagnostics>(module, "CyclotronDiagnostics")
        .def_readonly("kinetic_energy_ev", &Simulation::CyclotronDiagnostics::kineticEnergyElectronVolts)
        .def_readonly("speed_m_s", &Simulation::CyclotronDiagnostics::speedMetersPerSecond)
        .def_readonly("radius_m", &Simulation::CyclotronDiagnostics::radiusMeters)
        .def_readonly("rf_phase_rad", &Simulation::CyclotronDiagnostics::rfPhaseRadians)
        .def_readonly("completed_steps", &Simulation::CyclotronDiagnostics::completedSteps)
        .def_readonly("lost", &Simulation::CyclotronDiagnostics::lost);

    py::class_<Simulation::CyclotronModel>(module, "CyclotronModel")
        .def(py::init<Simulation::CyclotronConfig>(), py::arg("config") = Simulation::CyclotronConfig{})
        .def("reset", &Simulation::CyclotronModel::Reset, py::arg("state") = Simulation::ParticleState{})
        .def("step", py::overload_cast<std::size_t>(&Simulation::CyclotronModel::Step), py::arg("count") = 1)
        .def("set_magnetic_field_t", &Simulation::CyclotronModel::SetMagneticFieldTesla)
        .def("set_rf_peak_electric_field_v_m", &Simulation::CyclotronModel::SetRfPeakElectricField)
        .def_property_readonly("state", [](const Simulation::CyclotronModel& model) {
            return model.State();
        })
        .def_property_readonly("diagnostics", &Simulation::CyclotronModel::Diagnostics)
        .def("electric_field_x", &Simulation::CyclotronModel::ElectricFieldX);
}
