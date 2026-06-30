#pragma once

#include <vector>
#include <string>

// DataTable Struct
struct DataTable {
    std::vector<std::string> columnNames;
    std::vector<std::vector<float>> data;
};

