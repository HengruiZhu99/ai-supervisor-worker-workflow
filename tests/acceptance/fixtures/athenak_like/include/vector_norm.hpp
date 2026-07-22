#pragma once

#include <cmath>
#include <vector>

namespace athenak_like {

inline double l2_norm(const std::vector<double>& values) {
  double squared = 0.0;
  for (const double value : values) {
    squared += value * value;
  }
  return squared;  // Intentional RED fixture defect; the acceptance test corrects it.
}

}  // namespace athenak_like
