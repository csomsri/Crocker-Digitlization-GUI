#include <pybind11/pybind11.h>

#include "Bindings/Bindings.hpp"

PYBIND11_MODULE(CycloViz, module)
{
    BindEngine(module);
    BindTransport(module);
}
