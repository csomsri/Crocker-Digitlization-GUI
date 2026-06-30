#pragma once

#include <vector>
#include <string>

struct DataTable {
    std::vector<std::string> columnNames;
    // Row-major storage: rows[rowIndex][columnIndex].
    std::vector<std::vector<float>> rows;

    std::size_t RowCount() const noexcept { return rows.size(); }
    std::size_t ColumnCount() const noexcept {
        return columnNames.empty()
            ? (rows.empty() ? 0 : rows.front().size())
            : columnNames.size();
    }
};

