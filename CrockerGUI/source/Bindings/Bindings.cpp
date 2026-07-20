#include <pybind11/pybind11.h>

#include "Bindings.hpp"

PYBIND11_MODULE(CycloViz, module)
{
    BindEngine(module);
    BindTransport(module);
    BindControlService(module);
    BindCyclotron(module);
}
