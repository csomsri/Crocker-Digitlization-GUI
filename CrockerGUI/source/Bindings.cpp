#include <pybind11/pybind11.h>
#include "Engine/Engine.hpp"

namespace py = pybind11;

// Pinding to the Python UI
PYBIND11_MODULE(CycloViz, m) {
    py::class_<Engine>(m, "Engine")
        .def(py::init<>())
        .def("Init", &Engine::Init)
        .def("Update", &Engine::Update)
        .def("Render", &Engine::Render);
}